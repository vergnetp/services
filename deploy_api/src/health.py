"""
Health monitoring logic.

Centralized health checks for droplets and containers.
"""

import asyncio
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from .stores import droplets, containers, services
from .node_agent import NodeAgentClient
from config import settings


# =============================================================================
# Health Overview
# =============================================================================

async def get_health_overview(db, workspace_id: str) -> Dict[str, Any]:
    """
    Get overall health status for workspace.
    
    Returns summary of droplets and containers health.
    """
    # Get all droplets
    all_droplets = await droplets.list_active(db, workspace_id)
    
    # Count by status
    droplet_stats = {
        "total": len(all_droplets),
        "healthy": 0,
        "unhealthy": 0,
        "unknown": 0,
    }
    
    for d in all_droplets:
        status = d.get("health_status", "unknown")
        if status == "healthy":
            droplet_stats["healthy"] += 1
        elif status == "unhealthy":
            droplet_stats["unhealthy"] += 1
        else:
            droplet_stats["unknown"] += 1
    
    # Get all containers
    all_containers = await containers.list_all(db, workspace_id)
    
    container_stats = {
        "total": len(all_containers),
        "running": 0,
        "stopped": 0,
        "healthy": 0,
        "unhealthy": 0,
    }
    
    for c in all_containers:
        if c.get("status") == "running":
            container_stats["running"] += 1
        else:
            container_stats["stopped"] += 1
        
        health = c.get("health_status", "unknown")
        if health == "healthy":
            container_stats["healthy"] += 1
        elif health == "unhealthy":
            container_stats["unhealthy"] += 1
    
    return {
        "droplets": droplet_stats,
        "containers": container_stats,
        "overall": "healthy" if droplet_stats["unhealthy"] == 0 and container_stats["unhealthy"] == 0 else "degraded",
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


# =============================================================================
# Droplet Health Checks
# =============================================================================

async def check_droplet_health(
    db,
    droplet_id: str,
    do_token: str,
) -> Dict[str, Any]:
    """
    Check health of a single droplet via node agent ping.
    """
    droplet = await droplets.get(db, droplet_id)
    if not droplet:
        return {"error": "Droplet not found"}
    
    ip = droplet.get("ip")
    if not ip:
        return {"error": "Droplet has no IP"}
    
    agent = NodeAgentClient(
        host=ip,
        port=settings.node_agent_port,
        do_token=do_token,
    )
    
    try:
        result = await asyncio.wait_for(agent.ping(), timeout=10.0)
        
        # Update droplet health status
        status = result.get("status", "unknown")
        await droplets.update_health(db, droplet_id, status)
        
        return {
            "droplet_id": droplet_id,
            "name": droplet.get("name"),
            "ip": ip,
            "status": status,
            "agent_version": result.get("version"),
            "docker": result.get("docker", False),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        
    except asyncio.TimeoutError:
        await droplets.update_health(db, droplet_id, "unhealthy")
        return {
            "droplet_id": droplet_id,
            "name": droplet.get("name"),
            "ip": ip,
            "status": "unhealthy",
            "error": "Timeout connecting to node agent",
        }
        
    except Exception as e:
        await droplets.update_health(db, droplet_id, "unhealthy")
        return {
            "droplet_id": droplet_id,
            "name": droplet.get("name"),
            "ip": ip,
            "status": "unhealthy",
            "error": str(e),
        }
        
    finally:
        await agent.close()


async def check_all_droplets(
    db,
    workspace_id: str,
    do_token: str,
) -> List[Dict[str, Any]]:
    """
    Check health of all droplets in workspace.
    """
    all_droplets = await droplets.list_active(db, workspace_id)
    
    # Check all in parallel
    tasks = [
        check_droplet_health(db, d["id"], do_token)
        for d in all_droplets
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Convert exceptions to error dicts
    checked = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            checked.append({
                "droplet_id": all_droplets[i]["id"],
                "name": all_droplets[i].get("name"),
                "status": "error",
                "error": str(result),
            })
        else:
            checked.append(result)
    
    return checked


# =============================================================================
# Container Health Checks
# =============================================================================

async def check_container_health(
    db,
    container_id: str,
    do_token: str,
) -> Dict[str, Any]:
    """
    Check health of a single container via node agent.
    """
    container = await containers.get(db, container_id)
    if not container:
        return {"error": "Container not found"}
    
    droplet = await droplets.get(db, container["droplet_id"])
    if not droplet or not droplet.get("ip"):
        return {"error": "Droplet not found or has no IP"}
    
    agent = NodeAgentClient(
        host=droplet["ip"],
        port=settings.node_agent_port,
        do_token=do_token,
    )
    
    try:
        result = await agent.get_container_health(container["container_name"])
        
        health_status = result.get("health_status", "unknown")
        await containers.update_health(db, container_id, health_status)
        
        return {
            "container_id": container_id,
            "container_name": container["container_name"],
            "droplet_name": droplet.get("name"),
            "status": container.get("status"),
            "health_status": health_status,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        
    except Exception as e:
        await containers.update_health(db, container_id, "unknown")
        return {
            "container_id": container_id,
            "container_name": container["container_name"],
            "status": "error",
            "error": str(e),
        }
        
    finally:
        await agent.close()


async def check_all_containers(
    db,
    workspace_id: str,
    do_token: str,
) -> List[Dict[str, Any]]:
    """
    Check health of all containers in workspace.
    """
    # Get all containers via droplets
    all_droplets = await droplets.list_active(db, workspace_id)
    
    results = []
    for droplet in all_droplets:
        droplet_containers = await containers.list_for_droplet(db, droplet["id"])
        
        for container in droplet_containers:
            result = await check_container_health(db, container["id"], do_token)
            results.append(result)
    
    return results


# =============================================================================
# Restart Operations
# =============================================================================

async def restart_droplet(
    db,
    droplet_id: str,
    do_token: str,
) -> Dict[str, Any]:
    """
    Restart a droplet via DigitalOcean API.
    """
    from backend.cloud import AsyncDOClient
    
    droplet = await droplets.get(db, droplet_id)
    if not droplet:
        return {"error": "Droplet not found"}
    
    do_droplet_id = droplet.get("do_droplet_id")
    if not do_droplet_id:
        return {"error": "Droplet has no DigitalOcean ID"}
    
    async with AsyncDOClient(api_token=do_token) as client:
        try:
            # Reboot via DO API
            await client.reboot_droplet(int(do_droplet_id))
            
            # Update status
            await droplets.update_health(db, droplet_id, "rebooting")
            
            return {
                "droplet_id": droplet_id,
                "name": droplet.get("name"),
                "action": "reboot",
                "status": "initiated",
            }
            
        except Exception as e:
            return {
                "droplet_id": droplet_id,
                "error": str(e),
            }


async def restart_container(
    db,
    container_id: str,
    do_token: str,
) -> Dict[str, Any]:
    """
    Restart a container via node agent.
    """
    container = await containers.get(db, container_id)
    if not container:
        return {"error": "Container not found"}
    
    droplet = await droplets.get(db, container["droplet_id"])
    if not droplet or not droplet.get("ip"):
        return {"error": "Droplet not found or has no IP"}
    
    agent = NodeAgentClient(
        host=droplet["ip"],
        port=settings.node_agent_port,
        do_token=do_token,
    )
    
    try:
        await agent.restart_container(container["container_name"])
        
        # Update status
        await containers.mark_running(db, container_id)
        
        return {
            "container_id": container_id,
            "container_name": container["container_name"],
            "action": "restart",
            "status": "success",
        }
        
    except Exception as e:
        return {
            "container_id": container_id,
            "error": str(e),
        }
        
    finally:
        await agent.close()


# =============================================================================
# Scheduled Health Monitoring
# =============================================================================

async def run_health_check_cycle(
    db,
    workspace_id: str,
    do_token: str,
    auto_restart: bool = False,
) -> Dict[str, Any]:
    """
    Run a full health check cycle.
    
    Optionally auto-restarts unhealthy containers.
    """
    results = {
        "droplets": [],
        "containers": [],
        "actions": [],
    }
    
    # Check all droplets
    droplet_results = await check_all_droplets(db, workspace_id, do_token)
    results["droplets"] = droplet_results
    
    # Check all containers
    container_results = await check_all_containers(db, workspace_id, do_token)
    results["containers"] = container_results
    
    # Auto-restart unhealthy containers if enabled
    if auto_restart:
        for container in container_results:
            if container.get("health_status") == "unhealthy":
                action = await restart_container(
                    db, 
                    container["container_id"], 
                    do_token
                )
                results["actions"].append({
                    "type": "container_restart",
                    "target": container["container_name"],
                    "result": action,
                })
    
    results["completed_at"] = datetime.now(timezone.utc).isoformat()
    return results
