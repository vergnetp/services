"""
Agent & Operations Routes - Node agent, containers, deployments, configs.

Thin wrappers around infra.node_agent, infra.fleet services.
Uses server ID (not IP) for VPC-aware routing.
"""

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from typing import List, Optional, Dict, Any

from shared_libs.backend.app_kernel.auth import get_current_user, UserIdentity
from shared_libs.backend.app_kernel.db import db_connection

from ..deps import get_deployment_store, get_deploy_config_store

router = APIRouter(prefix="/infra", tags=["Agent & Operations"])


def _get_do_token(do_token: str = None) -> str:
    if do_token:
        return do_token
    raise HTTPException(400, "DigitalOcean token required")


async def _get_agent_client(
    server_id: str,
    do_token: str,
):
    """
    Get NodeAgentClient for a server with automatic VPC-aware routing.
    
    Args:
        server_id: DigitalOcean droplet ID
        do_token: DigitalOcean API token
    
    Routing priority:
    1. Same droplet → 127.0.0.1 (instant, <1ms)
    2. In VPC + target has private IP → private IP (low latency)
    3. Otherwise → public IP
    
    Detection uses DO Metadata API (works inside Docker containers).
    """
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    from shared_libs.backend.infra.providers import AsyncDOClient, get_best_ip_for_target
    
    # Get droplet info directly from DO API
    client = AsyncDOClient(do_token)
    try:
        droplet = await client.get_droplet(int(server_id))
        if not droplet:
            raise HTTPException(404, f"Server {server_id} not found")
        
        # Smart routing: localhost > VPC > public
        agent_ip = get_best_ip_for_target(
            public_ip=droplet.ip,
            private_ip=droplet.private_ip,
            target_droplet_id=droplet.id,
        )
        if not agent_ip:
            raise HTTPException(400, f"Server {server_id} has no IP address")
        
        return NodeAgentClient(agent_ip, do_token)
    finally:
        await client.close()


# =============================================================================
# Agent Routes (direct node agent calls) - Using server ID
# =============================================================================

@router.get("/agent/{server_id}/health")
async def get_agent_health(
    server_id: str,
    do_token: str = Query(...),
    user: UserIdentity = Depends(get_current_user),
):
    """Get agent health on a server."""
    client = await _get_agent_client(server_id, _get_do_token(do_token))
    result = await client.health_check()
    return result.data if result.success else {"error": result.error}


@router.get("/agent/{server_id}/containers")
async def list_containers(
    server_id: str,
    do_token: str = Query(...),
    user: UserIdentity = Depends(get_current_user),
):
    """List containers on a server."""
    client = await _get_agent_client(server_id, _get_do_token(do_token))
    result = await client.list_containers()
    return {
        "containers": result.data.get("containers", []) if result.success else [],
        "error": result.error if not result.success else None,
    }


@router.post("/agent/{server_id}/containers/{container_name}/restart")
async def restart_container(
    server_id: str,
    container_name: str,
    do_token: str = Query(...),
    user: UserIdentity = Depends(get_current_user),
):
    """Restart a container."""
    client = await _get_agent_client(server_id, _get_do_token(do_token))
    result = await client.restart_container(container_name)
    return {"success": result.success, "error": result.error}


@router.post("/agent/{server_id}/containers/{container_name}/stop")
async def stop_container(
    server_id: str,
    container_name: str,
    do_token: str = Query(...),
    user: UserIdentity = Depends(get_current_user),
):
    """Stop a container."""
    client = await _get_agent_client(server_id, _get_do_token(do_token))
    result = await client.stop_container(container_name)
    return {"success": result.success, "error": result.error}


@router.post("/agent/{server_id}/containers/{container_name}/remove")
async def remove_container(
    server_id: str,
    container_name: str,
    do_token: str = Query(...),
    cf_token: Optional[str] = Query(None, description="Cloudflare token for DNS cleanup"),
    domain: Optional[str] = Query(None, description="Domain for nginx/DNS cleanup"),
    cleanup_nginx: bool = Query(True, description="Remove nginx config"),
    cleanup_dns: bool = Query(False, description="Update DNS (remove IP from A records)"),
    user: UserIdentity = Depends(get_current_user),
):
    """
    Remove a container with optional cleanup.
    
    Cleanup options:
    - cleanup_nginx (default True): Remove nginx reverse proxy config
    - cleanup_dns (default False): Remove this server's IP from DNS records
    
    For DNS cleanup, provide cf_token and domain.
    """
    from shared_libs.backend.infra.deploy import AsyncUndeployService
    from shared_libs.backend.infra.providers import AsyncDOClient
    
    do_token_val = _get_do_token(do_token)
    
    # Get droplet IP for undeploy service
    do_client = AsyncDOClient(do_token_val)
    try:
        droplet = await do_client.get_droplet(int(server_id))
        if not droplet:
            raise HTTPException(404, f"Server {server_id} not found")
        droplet_ip = droplet.ip
    finally:
        await do_client.close()
    
    # Use undeploy service for full cleanup
    undeploy = AsyncUndeployService(
        do_token=do_token_val,
        cf_token=cf_token,
    )
    
    result = await undeploy.remove_container_from_droplet(
        container_name=container_name,
        droplet_ip=droplet_ip,
        domain=domain,
        cleanup_nginx=cleanup_nginx,
        cleanup_dns=cleanup_dns and cf_token is not None,
    )
    
    return {
        "success": result.success,
        "container_removed": result.container_removed,
        "nginx_removed": result.nginx_removed,
        "dns_updated": result.dns_updated,
        "errors": result.errors if result.errors else None,
    }


@router.get("/agent/{server_id}/containers/{container_name}/logs")
async def get_container_logs(
    server_id: str,
    container_name: str,
    lines: int = Query(100),
    do_token: str = Query(...),
    user: UserIdentity = Depends(get_current_user),
):
    """Get container logs."""
    client = await _get_agent_client(server_id, _get_do_token(do_token))
    result = await client.container_logs(container_name, lines=lines)
    return {
        "logs": result.data.get("logs", "") if result.success else None,
        "error": result.error if not result.success else None,
    }


@router.get("/agent/{server_id}/metrics")
async def get_server_metrics(
    server_id: str,
    do_token: str = Query(...),
    user: UserIdentity = Depends(get_current_user),
):
    """Get server metrics."""
    client = await _get_agent_client(server_id, _get_do_token(do_token))
    result = await client.get_metrics()
    return result.data if result.success else {"error": result.error}


# =============================================================================
# Services State & Cleanup
# =============================================================================

@router.get("/services/state")
async def get_services_state(
    project: str = Query(...),
    service: str = Query(None),
    service_name: str = Query(None),  # Alias for frontend compatibility
    environment: str = Query(...),
    do_token: str = Query(...),
    user: UserIdentity = Depends(get_current_user),
):
    """Get current state of a service across servers."""
    from shared_libs.backend.infra.fleet import AsyncFleetService
    
    # Accept either service or service_name
    svc = service or service_name
    if not svc:
        raise HTTPException(400, "Either 'service' or 'service_name' is required")
    
    fleet = AsyncFleetService(_get_do_token(do_token), str(user.id))
    results = await fleet.get_service_state(project, svc, environment)
    return {"servers": results}


@router.post("/services/check-servers")
async def check_servers(
    do_token: str = Query(...),
    server_ips: str = Query(...),
    user: UserIdentity = Depends(get_current_user),
):
    """Check health of specified servers."""
    from shared_libs.backend.infra.fleet import AsyncFleetService
    fleet = AsyncFleetService(_get_do_token(do_token), str(user.id))
    ips = [ip.strip() for ip in server_ips.split(",")]
    results = await fleet.check_servers_health(ips)
    return {"results": results}


class ServiceCleanupRequest(BaseModel):
    project: str
    service: str
    environment: str
    server_ips: List[str]
    do_token: Optional[str] = None


@router.post("/services/cleanup")
async def cleanup_services(
    req: ServiceCleanupRequest,
    do_token: str = Query(None),
    user: UserIdentity = Depends(get_current_user),
):
    """Clean up old containers for a service."""
    from shared_libs.backend.infra.fleet import AsyncFleetService
    fleet = AsyncFleetService(_get_do_token(req.do_token or do_token), str(user.id))
    results = await fleet.cleanup_service_containers(
        project=req.project,
        service=req.service,
        environment=req.environment,
        server_ips=req.server_ips,
    )
    return {"results": results}


# =============================================================================
# Deploy Configs (stored in DB)
# =============================================================================

@router.get("/deploy-configs")
async def list_deploy_configs(
    user: UserIdentity = Depends(get_current_user),
    store = Depends(get_deploy_config_store),
):
    """List all saved deploy configs."""
    configs = await store.list_configs(user_id=str(user.id))
    return {"configs": configs}


@router.get("/deploy-configs/{project}/{service}/{env}")
async def get_deploy_config(
    project: str,
    service: str,
    env: str,
    user: UserIdentity = Depends(get_current_user),
    store = Depends(get_deploy_config_store),
):
    """Get a specific deploy config."""
    config = await store.get(
        workspace_id=str(user.id),
        project_name=project,
        service_name=service,
        env=env,
    )
    if not config:
        raise HTTPException(404, "Config not found")
    return config


class DeployConfigSaveRequest(BaseModel):
    project: str
    service: str
    environment: str
    config: Dict[str, Any]


@router.post("/deploy-configs")
async def save_deploy_config(
    req: DeployConfigSaveRequest,
    user: UserIdentity = Depends(get_current_user),
    store = Depends(get_deploy_config_store),
):
    """Save a deploy config."""
    await store.save(
        workspace_id=str(user.id),
        project_name=req.project,
        service_name=req.service,
        env=req.environment,
        config=req.config,
    )
    return {"success": True}


@router.delete("/deploy-configs/{project}/{service}/{env}")
async def delete_deploy_config(
    project: str,
    service: str,
    env: str,
    user: UserIdentity = Depends(get_current_user),
    store = Depends(get_deploy_config_store),
):
    """Delete a deploy config."""
    await store.delete(
        workspace_id=str(user.id),
        project_name=project,
        service_name=service,
        env=env,
    )
    return {"success": True}


# =============================================================================
# Deployments History
# =============================================================================

@router.get("/deployments")
async def list_deployments_route(
    project: str = Query(None),
    service: str = Query(None),
    environment: str = Query(None),
    limit: int = Query(50),
    user: UserIdentity = Depends(get_current_user),
    store = Depends(get_deployment_store),
):
    """List deployment history."""
    deployments = await store.get_deployments(
        workspace_id=str(user.id),
        project=project,
        service_name=service,
        environment=environment,
        limit=limit,
    )
    return {"deployments": [d.to_dict() if hasattr(d, 'to_dict') else d for d in deployments]}


@router.get("/deployments/history")
async def get_deployments_history(
    project: str = Query(None),
    service: str = Query(None),
    environment: str = Query(None),
    limit: int = Query(50),
    user: UserIdentity = Depends(get_current_user),
    store = Depends(get_deployment_store),
):
    """Get deployment history (alias)."""
    deployments = await store.get_deployments(
        workspace_id=str(user.id),
        project=project,
        service_name=service,
        environment=environment,
        limit=limit,
    )
    return {"deployments": [d.to_dict() if hasattr(d, 'to_dict') else d for d in deployments]}


@router.get("/deployments/history/{deployment_id}")
async def get_deployment(
    deployment_id: str,
    user: UserIdentity = Depends(get_current_user),
    store = Depends(get_deployment_store),
):
    """Get a specific deployment."""
    deployment = await store.get_deployment(deployment_id)
    if not deployment:
        raise HTTPException(404, "Deployment not found")
    return deployment


@router.get("/deployments/history/{deployment_id}/logs")
async def get_deployment_logs(
    deployment_id: str,
    user: UserIdentity = Depends(get_current_user),
    store = Depends(get_deployment_store),
):
    """Get logs for a deployment."""
    deployment = await store.get_deployment(deployment_id)
    if not deployment:
        raise HTTPException(404, "Deployment not found")
    return {"logs": deployment.logs or []}


@router.get("/deployments/rollback/preview")
async def preview_rollback(
    deployment_id: str = Query(...),
    user: UserIdentity = Depends(get_current_user),
    store = Depends(get_deployment_store),
):
    """Preview what a rollback would do."""
    deployment = await store.get_deployment(deployment_id)
    if not deployment:
        raise HTTPException(404, "Deployment not found")
    
    return {
        "deployment_id": deployment_id,
        "project": deployment.get("project"),
        "service": deployment.get("service"),
        "environment": deployment.get("environment"),
        "image": deployment.get("image"),
        "created_at": deployment.get("created_at"),
        "can_rollback": True,
    }


# =============================================================================
# Scheduler/Tasks (TODO)
# =============================================================================

@router.get("/scheduler/tasks")
async def list_scheduler_tasks(
    user: UserIdentity = Depends(get_current_user),
):
    """List scheduled tasks."""
    return {"tasks": []}


@router.delete("/scheduler/tasks/{task_id}")
async def delete_scheduler_task(
    task_id: str,
    user: UserIdentity = Depends(get_current_user),
):
    """Delete a scheduled task."""
    return {"success": True, "deleted": task_id}
