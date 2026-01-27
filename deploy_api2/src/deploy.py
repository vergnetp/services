"""
Deployment orchestration logic.

Handles deploy and rollback operations with SSE streaming.
"""

import json
import asyncio
from typing import Optional, List, Dict, Any, AsyncIterator
from datetime import datetime, timezone

from .stores import services, deployments, droplets, containers
from .node_agent import NodeAgentClient
from config import settings


# =============================================================================
# SSE Event Helpers
# =============================================================================

def sse_event(event: str, data: dict) -> str:
    """Format an SSE event."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def sse_log(message: str, level: str = "info") -> str:
    """Format a log SSE event."""
    return sse_event("log", {"message": message, "level": level, "timestamp": _now_iso()})


def sse_progress(percent: int, step: str) -> str:
    """Format a progress SSE event."""
    return sse_event("progress", {"percent": percent, "step": step})


def sse_complete(success: bool, deployment_id: str, error: Optional[str] = None) -> str:
    """Format a complete SSE event."""
    return sse_event("complete", {
        "success": success,
        "deployment_id": deployment_id,
        "error": error,
    })


def sse_error(message: str) -> str:
    """Format an error SSE event."""
    return sse_event("error", {"message": message})


def _now_iso() -> str:
    """Get current time as ISO string."""
    return datetime.now(timezone.utc).isoformat()


# =============================================================================
# Deployment Creation
# =============================================================================

async def create_deployment(
    db,
    user,
    do_token: str,
    cf_token: str,
    project_id: str,
    service_name: str,
    env: str,
    image_name: str,
    env_variables: Optional[dict] = None,
    droplet_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Create a new deployment record.
    
    Does not execute - call stream_deployment() to run.
    """
    # Get or create service
    service = await services.get_by_name(db, project_id, service_name)
    if not service:
        # Auto-create service
        service = await services.create(db, {
            "project_id": project_id,
            "name": service_name,
            "service_type": "web",  # Default
        })
    
    # Get next version
    version = await deployments.get_next_version(db, service["id"], env)
    
    # Resolve target droplets
    if droplet_ids:
        target_droplets = droplet_ids
    else:
        # Get all active droplets for workspace
        # TODO: Filter by project/service tags
        workspace_droplets = await droplets.list_active(db, user.id)
        target_droplets = [d["id"] for d in workspace_droplets]
    
    if not target_droplets:
        raise ValueError("No target droplets specified or available")
    
    # Create deployment record
    deployment = await deployments.create(db, {
        "service_id": service["id"],
        "version": version,
        "env": env,
        "image_name": image_name,
        "env_variables": env_variables or {},
        "droplet_ids": target_droplets,
        "is_rollback": False,
        "status": "pending",
        "triggered_by": user.email,
        "triggered_at": _now_iso(),
    })
    
    return deployment


async def create_rollback(
    db,
    user,
    do_token: str,
    cf_token: str,
    source_deployment_id: str,
) -> Dict[str, Any]:
    """
    Create a rollback deployment from a previous deployment.
    
    Uses the exact tagged image from the source deployment.
    """
    # Get source deployment
    source = await deployments.get(db, source_deployment_id)
    if not source:
        raise ValueError("Source deployment not found")
    
    # Get next version
    version = await deployments.get_next_version(db, source["service_id"], source["env"])
    
    # Create rollback deployment
    deployment = await deployments.create(db, {
        "service_id": source["service_id"],
        "version": version,
        "env": source["env"],
        "image_name": source["image_name"],  # Same image
        "env_variables": source.get("env_variables", {}),
        "droplet_ids": source.get("droplet_ids", []),
        "is_rollback": True,
        "status": "pending",
        "triggered_by": user.email,
        "triggered_at": _now_iso(),
    })
    
    return deployment


# =============================================================================
# Deployment Execution (Streaming)
# =============================================================================

async def stream_deployment(
    db,
    deployment_id: str,
    do_token: str,
) -> AsyncIterator[str]:
    """
    Execute deployment with SSE progress streaming.
    
    Yields SSE events as the deployment progresses.
    """
    deployment = await deployments.get(db, deployment_id)
    if not deployment:
        yield sse_error("Deployment not found")
        return
    
    try:
        # Mark as in progress
        await deployments.mark_in_progress(db, deployment_id)
        yield sse_log("Starting deployment...")
        yield sse_progress(5, "initializing")
        
        # Get target droplets
        target_ids = deployment.get("droplet_ids", [])
        if isinstance(target_ids, str):
            target_ids = json.loads(target_ids)
        
        if not target_ids:
            raise ValueError("No target droplets")
        
        yield sse_log(f"Deploying to {len(target_ids)} server(s)")
        
        # Get droplet details
        target_droplets = []
        for droplet_id in target_ids:
            droplet = await droplets.get(db, droplet_id)
            if droplet and droplet.get("ip"):
                target_droplets.append(droplet)
            else:
                yield sse_log(f"Warning: Droplet {droplet_id} not found or has no IP", "warning")
        
        if not target_droplets:
            raise ValueError("No reachable droplets")
        
        # Deploy to each droplet
        image_name = deployment["image_name"]
        env_vars = deployment.get("env_variables", {})
        if isinstance(env_vars, str):
            env_vars = json.loads(env_vars)
        
        total = len(target_droplets)
        success_count = 0
        
        for i, droplet in enumerate(target_droplets):
            progress = 10 + int((i / total) * 80)
            yield sse_progress(progress, f"deploying to {droplet['name']}")
            yield sse_log(f"Deploying to {droplet['name']} ({droplet['ip']})")
            
            try:
                await deploy_to_droplet(
                    db=db,
                    deployment=deployment,
                    droplet=droplet,
                    image_name=image_name,
                    env_vars=env_vars,
                    do_token=do_token,
                )
                success_count += 1
                yield sse_log(f"✓ {droplet['name']} deployed successfully")
                
            except Exception as e:
                yield sse_log(f"✗ {droplet['name']} failed: {e}", "error")
                await deployments.append_log(db, deployment_id, f"Failed on {droplet['name']}: {e}")
        
        # Final status
        if success_count == total:
            await deployments.mark_success(db, deployment_id)
            yield sse_progress(100, "complete")
            yield sse_log(f"Deployment complete: {success_count}/{total} servers")
            yield sse_complete(True, deployment_id)
        elif success_count > 0:
            await deployments.mark_success(db, deployment_id)  # Partial success
            yield sse_progress(100, "partial")
            yield sse_log(f"Partial deployment: {success_count}/{total} servers", "warning")
            yield sse_complete(True, deployment_id)
        else:
            raise ValueError("All deployments failed")
            
    except Exception as e:
        await deployments.mark_failed(db, deployment_id, str(e))
        yield sse_log(f"Deployment failed: {e}", "error")
        yield sse_complete(False, deployment_id, str(e))


async def deploy_to_droplet(
    db,
    deployment: dict,
    droplet: dict,
    image_name: str,
    env_vars: dict,
    do_token: str,
) -> None:
    """
    Deploy a container to a single droplet via node agent.
    """
    # Get service info for container naming
    service = await services.get(db, deployment["service_id"])
    service_name = service["name"] if service else "app"
    container_name = f"{service_name}-{deployment['env']}"
    
    # Build environment list
    env_list = [f"{k}={v}" for k, v in env_vars.items()]
    
    # Connect to node agent
    agent = NodeAgentClient(
        host=droplet["ip"],
        port=settings.node_agent_port,
        do_token=do_token,
    )
    
    try:
        # Pull image
        await agent.pull_image(image_name)
        
        # Stop existing container (if any)
        try:
            await agent.stop_container(container_name)
            await agent.remove_container(container_name)
        except Exception:
            pass  # Container may not exist
        
        # Tag image for rollback
        deploy_tag = f"{image_name.split(':')[0]}:deploy_{deployment['id'][:8]}"
        await agent.tag_image(image_name, deploy_tag)
        
        # Run new container
        result = await agent.run_container(
            name=container_name,
            image=image_name,
            ports=["8000:8000"],  # TODO: Get from service config
            environment=env_list,
            restart_policy="unless-stopped",
        )
        
        # Update container record
        existing = await containers.get_by_name(db, droplet["id"], container_name)
        if existing:
            await containers.mark_running(db, existing["id"])
        else:
            await containers.create(db, {
                "container_name": container_name,
                "droplet_id": droplet["id"],
                "deployment_id": deployment["id"],
                "status": "running",
                "health_status": "unknown",
            })
            
    finally:
        await agent.close()


# =============================================================================
# Stateful Service Injection
# =============================================================================

async def get_injected_env_vars(
    db,
    project_id: str,
    droplet: dict,
) -> Dict[str, str]:
    """
    Get environment variables to inject from stateful services.
    
    Auto-discovers Redis, Postgres, etc. in the same project
    and returns connection URLs.
    """
    injected = {}
    
    # Find stateful services in same project
    stateful = await services.list_stateful_services(db, project_id)
    
    for svc in stateful:
        svc_type = svc.get("service_type", "").lower()
        svc_name = svc.get("name", "")
        
        # Get container for this stateful service on same droplet
        container = await containers.get_by_name(
            db, 
            droplet["id"], 
            f"{svc_name}-{svc.get('env', 'prod')}"
        )
        
        if not container or container.get("status") != "running":
            continue
        
        # Build connection URL based on type
        host = droplet.get("private_ip") or droplet.get("ip") or "localhost"
        
        if svc_type == "redis":
            # redis -> REDIS_URL, redis-cache -> REDIS_CACHE_URL
            env_key = _get_env_var_name(svc_name, "REDIS", "URL")
            injected[env_key] = f"redis://{host}:6379/0"
            
        elif svc_type == "postgres":
            # postgres -> DATABASE_URL, postgres-analytics -> DATABASE_ANALYTICS_URL
            env_key = _get_env_var_name(svc_name, "DATABASE", "URL")
            # TODO: Get actual credentials from service config
            injected[env_key] = f"postgresql://postgres:postgres@{host}:5432/{svc_name}"
            
        elif svc_type == "mysql":
            env_key = _get_env_var_name(svc_name, "MYSQL", "URL")
            injected[env_key] = f"mysql://root:root@{host}:3306/{svc_name}"
    
    return injected


def _get_env_var_name(service_name: str, prefix: str, suffix: str) -> str:
    """
    Convert service name to environment variable name.
    
    redis -> REDIS_URL
    redis-cache -> REDIS_CACHE_URL
    postgres -> DATABASE_URL
    postgres-analytics -> DATABASE_ANALYTICS_URL
    """
    # Default names use standard env vars
    defaults = {
        "redis": f"{prefix}_{suffix}",
        "postgres": f"DATABASE_{suffix}",
        "mysql": f"MYSQL_{suffix}",
    }
    
    if service_name in defaults:
        return defaults[service_name]
    
    # Custom names: redis-xxx -> REDIS_XXX_URL
    parts = service_name.split("-", 1)
    if len(parts) == 2:
        base, custom = parts
        return f"{prefix}_{custom.upper().replace('-', '_')}_{suffix}"
    
    return f"{prefix}_{suffix}"
