"""
Health monitoring with auto-healing.
Supports configurable health paths per service.
"""

import asyncio
import logging
from typing import Dict, Any, List
from datetime import datetime, timezone

from .stores import droplets, containers, services, deployments
from .node_agent import NodeAgentClient
from .naming import get_container_port
from config import settings


logger = logging.getLogger(__name__)

MAX_CONTAINER_RESTARTS = 3
MAX_DROPLET_REBOOTS = 2


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# =============================================================================
# Health Check Loop
# =============================================================================

async def check_health_all(db, do_token: str):
    """Check health of all active droplets and containers."""
    all_droplets = await droplets.list_active(db)
    
    for droplet in all_droplets:
        try:
            await check_droplet_health(db, droplet, do_token)
        except Exception as e:
            logger.error(f"Error checking droplet {droplet.get('name')}: {e}")


async def check_droplet_health(db, droplet: Dict[str, Any], do_token: str):
    """Check droplet agent and its containers."""
    droplet_id = droplet['id']
    droplet_ip = droplet.get('ip')
    
    if not droplet_ip:
        return
    
    agent = NodeAgentClient(host=droplet_ip, port=settings.node_agent_port, do_token=do_token)
    
    try:
        # Ping agent
        resp = await asyncio.wait_for(agent.ping(), timeout=10.0)
        
        if resp.get('status') != 'ok':
            await handle_droplet_unreachable(db, droplet, do_token)
            return
        
        # Reset failure count on success
        if droplet.get('failure_count', 0) > 0:
            await droplets.update(db, droplet_id, {
                'health_status': 'healthy',
                'failure_count': 0,
                'last_checked': _now_iso(),
            })
        
        # Check containers on this droplet
        droplet_containers = await containers.list_for_droplet(db, droplet_id)
        
        for container in droplet_containers:
            await check_container_health(db, droplet, container, do_token)
            
    except asyncio.TimeoutError:
        logger.warning(f"Droplet {droplet.get('name')} agent timeout")
        await handle_droplet_unreachable(db, droplet, do_token)
    except Exception as e:
        logger.error(f"Error checking droplet {droplet.get('name')}: {e}")
        await handle_droplet_unreachable(db, droplet, do_token)
    finally:
        await agent.close()


async def check_container_health(db, droplet: Dict[str, Any], container: Dict[str, Any], do_token: str):
    """Check container health: TCP ping first, then optional HTTP for webservices."""
    container_name = container.get('container_name')
    droplet_ip = droplet.get('ip')
    
    # Get service info for http_health_path and container_port
    http_health_path = None
    container_port = 8000  # default
    
    if container.get('deployment_id'):
        dep = await deployments.get(db, container['deployment_id'])
        if dep:
            svc = await services.get(db, dep['service_id'])
            if svc:
                container_port = get_container_port(svc.get('service_type', 'webservice'))
                # HTTP health check only for webservices with configured endpoint
                if svc.get('service_type') == 'webservice':
                    http_health_path = svc.get('http_health_path')  # May be None = TCP only
    
    agent = NodeAgentClient(host=droplet_ip, port=settings.node_agent_port, do_token=do_token)
    
    try:
        # TCP ping first, optional HTTP for webservices
        status = await agent.health(container_name, container_port, http_path=http_health_path)
        
        if status.get('error') == 'not_found':
            await mark_container_unhealthy(db, container, 'not_found')
            return
        
        if status.get('status') == 'healthy':
            # Healthy - reset failure count
            if container.get('failure_count', 0) > 0:
                await containers.update(db, container['id'], {
                    'health_status': 'healthy',
                    'failure_count': 0,
                    'last_checked': _now_iso(),
                })
        else:
            reason = status.get('reason', 'unhealthy')
            await mark_container_unhealthy(db, container, reason)
            await heal_container(db, droplet, container, do_token)
            
    except Exception as e:
        logger.warning(f"Failed to check health for {container_name}: {e}")
    finally:
        await agent.close()


# =============================================================================
# Marking & Healing
# =============================================================================

async def mark_container_unhealthy(db, container: Dict[str, Any], reason: str):
    """Mark container as unhealthy and increment failure count."""
    failure_count = container.get('failure_count', 0) + 1
    
    await containers.update(db, container['id'], {
        'health_status': 'unhealthy',
        'failure_count': failure_count,
        'last_failure_at': _now_iso(),
        'last_failure_reason': reason,
    })
    
    logger.warning(f"Container {container.get('container_name')} unhealthy: {reason} (failures: {failure_count})")


async def heal_container(db, droplet: Dict[str, Any], container: Dict[str, Any], do_token: str):
    """Attempt to heal container by restarting."""
    failure_count = container.get('failure_count', 0)
    
    if failure_count >= MAX_CONTAINER_RESTARTS:
        logger.error(f"Container {container.get('container_name')} exceeded max restarts, flagging droplet")
        await flag_droplet_problematic(db, droplet, f"Container {container.get('container_name')} restart limit exceeded")
        return
    
    # Restart container
    agent = NodeAgentClient(host=droplet.get('ip'), port=settings.node_agent_port, do_token=do_token)
    
    try:
        await agent.restart_container(container.get('container_name'))
        logger.info(f"Restarted container {container.get('container_name')}")
    except Exception as e:
        logger.error(f"Failed to restart container: {e}")
    finally:
        await agent.close()


async def handle_droplet_unreachable(db, droplet: Dict[str, Any], do_token: str):
    """Handle unreachable droplet."""
    failure_count = droplet.get('failure_count', 0) + 1
    
    await droplets.update(db, droplet['id'], {
        'health_status': 'unreachable',
        'failure_count': failure_count,
        'last_failure_at': _now_iso(),
    })
    
    if failure_count > MAX_DROPLET_REBOOTS:
        await flag_droplet_problematic(db, droplet, "Max reboots exceeded")
    else:
        await heal_droplet(db, droplet, do_token)


async def heal_droplet(db, droplet: Dict[str, Any], do_token: str):
    """Attempt to heal droplet by rebooting."""
    from backend.cloud import AsyncDOClient
    
    logger.info(f"Rebooting droplet {droplet.get('name')}")
    
    try:
        async with AsyncDOClient(api_token=do_token) as client:
            await client.reboot_droplet(droplet['do_droplet_id'])
    except Exception as e:
        logger.error(f"Failed to reboot droplet: {e}")
        await flag_droplet_problematic(db, droplet, f"Reboot failed: {e}")


async def flag_droplet_problematic(db, droplet: Dict[str, Any], reason: str):
    """Flag droplet as problematic for manual intervention."""
    await droplets.update(db, droplet['id'], {
        'health_status': 'problematic',
        'problematic_reason': reason,
        'flagged_at': _now_iso(),
    })
    logger.error(f"Droplet {droplet.get('name')} flagged as problematic: {reason}")


# =============================================================================
# Dashboard Functions
# =============================================================================

async def get_health_overview(db) -> Dict[str, Any]:
    """Get health overview for dashboard."""
    all_droplets = await droplets.list_active(db)
    all_containers = await containers.list_active(db)
    
    droplet_stats = {'healthy': 0, 'unhealthy': 0, 'unreachable': 0, 'problematic': 0}
    container_stats = {'healthy': 0, 'unhealthy': 0, 'unknown': 0}
    
    for d in all_droplets:
        status = d.get('health_status', 'unknown')
        if status in droplet_stats:
            droplet_stats[status] += 1
        else:
            droplet_stats['unhealthy'] += 1
    
    for c in all_containers:
        status = c.get('health_status', 'unknown')
        if status in container_stats:
            container_stats[status] += 1
        else:
            container_stats['unknown'] += 1
    
    problematic_droplets = [d for d in all_droplets if d.get('health_status') == 'problematic']
    unhealthy_containers = [c for c in all_containers if c.get('health_status') == 'unhealthy']
    
    return {
        'droplets': droplet_stats,
        'containers': container_stats,
        'problematic_droplets': problematic_droplets,
        'unhealthy_containers': unhealthy_containers,
    }


async def restart_droplet(db, droplet_id: str, do_token: str) -> Dict[str, Any]:
    """Manual droplet restart."""
    droplet = await droplets.get(db, droplet_id)
    if not droplet:
        return {'error': 'Droplet not found'}
    
    await heal_droplet(db, droplet, do_token)
    return {'status': 'reboot_initiated', 'droplet': droplet['name']}


async def restart_container(db, container_id: str, do_token: str) -> Dict[str, Any]:
    """Manual container restart."""
    container = await containers.get(db, container_id)
    if not container:
        return {'error': 'Container not found'}
    
    droplet = await droplets.get(db, container['droplet_id'])
    if not droplet:
        return {'error': 'Droplet not found'}
    
    agent = NodeAgentClient(host=droplet.get('ip'), port=settings.node_agent_port, do_token=do_token)
    
    try:
        await agent.restart_container(container['container_name'])
        return {'status': 'restarted', 'container': container['container_name']}
    finally:
        await agent.close()


async def clear_problematic_flag(db, droplet_id: str) -> Dict[str, Any]:
    """Clear problematic flag after manual intervention."""
    droplet = await droplets.get(db, droplet_id)
    if not droplet:
        return {'error': 'Droplet not found'}
    
    await droplets.update(db, droplet_id, {
        'health_status': 'healthy',
        'failure_count': 0,
        'problematic_reason': None,
        'flagged_at': None,
    })
    
    return {'status': 'cleared', 'droplet': droplet['name']}
