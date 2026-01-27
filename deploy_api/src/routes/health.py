"""
Health monitoring routes.

Endpoints for checking and managing server/container health.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List

from ..deps import db_connection, get_current_user, require_do_token
from config import settings

router = APIRouter(prefix="/health", tags=["health"])


# =============================================================================
# Request/Response Models
# =============================================================================

class HealthCheckResponse(BaseModel):
    """Overall health status response."""
    total_servers: int
    healthy_servers: int
    unhealthy_servers: int
    problematic_servers: int
    total_containers: int
    healthy_containers: int
    unhealthy_containers: int


class ServerHealthResponse(BaseModel):
    """Single server health response."""
    id: str
    name: str
    ip: str
    status: str
    health_status: str
    failure_count: int
    last_checked: Optional[str]
    last_failure_reason: Optional[str]
    problematic_reason: Optional[str]


class RebootRequest(BaseModel):
    """Request to reboot a server."""
    server_id: str


class RestartContainerRequest(BaseModel):
    """Request to restart a container."""
    container_id: str


# =============================================================================
# Health Overview Routes
# =============================================================================

@router.get("/overview")
async def get_health_overview(
    db=Depends(db_connection),
    user=Depends(get_current_user),
):
    """Get overall health status for the workspace."""
    from ..stores import droplets, containers
    
    # Get server stats
    all_servers = await droplets.list_active(db, user.id)
    healthy_servers = [s for s in all_servers if s.get("health_status") == "healthy"]
    unhealthy_servers = [s for s in all_servers if s.get("health_status") == "unhealthy"]
    problematic = await droplets.list_problematic(db, user.id)
    
    # Get container stats
    all_containers = await containers.list_running(db)
    # Filter to containers on user's servers
    server_ids = {s["id"] for s in all_servers}
    user_containers = [c for c in all_containers if c.get("droplet_id") in server_ids]
    healthy_containers = [c for c in user_containers if c.get("health_status") == "healthy"]
    unhealthy_containers = await containers.list_unhealthy(db)
    unhealthy_containers = [c for c in unhealthy_containers if c.get("droplet_id") in server_ids]
    
    return {
        "total_servers": len(all_servers),
        "healthy_servers": len(healthy_servers),
        "unhealthy_servers": len(unhealthy_servers),
        "problematic_servers": len(problematic),
        "total_containers": len(user_containers),
        "healthy_containers": len(healthy_containers),
        "unhealthy_containers": len(unhealthy_containers),
    }


@router.get("/servers")
async def get_unhealthy_servers(
    db=Depends(db_connection),
    user=Depends(get_current_user),
):
    """Get list of unhealthy or problematic servers."""
    from ..stores import droplets
    
    # Get all servers needing attention
    all_servers = await droplets.list_active(db, user.id)
    unhealthy = [s for s in all_servers if s.get("health_status") != "healthy"]
    problematic = await droplets.list_problematic(db, user.id)
    
    return {
        "unhealthy": unhealthy,
        "problematic": problematic,
    }


@router.get("/containers")
async def get_unhealthy_containers(
    db=Depends(db_connection),
    user=Depends(get_current_user),
):
    """Get list of unhealthy containers."""
    from ..stores import droplets, containers
    
    # Get user's server IDs
    all_servers = await droplets.list_active(db, user.id)
    server_ids = {s["id"] for s in all_servers}
    
    # Get unhealthy containers on those servers
    unhealthy = await containers.list_unhealthy(db)
    user_unhealthy = [c for c in unhealthy if c.get("droplet_id") in server_ids]
    
    return {"unhealthy_containers": user_unhealthy}


# =============================================================================
# Server Health Actions
# =============================================================================

@router.post("/servers/{server_id}/check")
async def check_server_health(
    server_id: str,
    db=Depends(db_connection),
    user=Depends(get_current_user),
    do_token: str = Depends(require_do_token),
):
    """Manually trigger health check for a server."""
    from ..stores import droplets
    from ..health import check_droplet_health
    
    droplet = await droplets.get_for_workspace(db, server_id, user.id)
    if not droplet:
        raise HTTPException(404, "Server not found")
    
    result = await check_droplet_health(db, droplet, do_token)
    
    return {
        "server_id": server_id,
        "health_status": result["health_status"],
        "details": result.get("details"),
    }


@router.post("/servers/{server_id}/reboot")
async def reboot_server(
    server_id: str,
    db=Depends(db_connection),
    user=Depends(get_current_user),
    do_token: str = Depends(require_do_token),
):
    """Reboot a server."""
    from ..stores import droplets
    from ..health import reboot_droplet
    
    droplet = await droplets.get_for_workspace(db, server_id, user.id)
    if not droplet:
        raise HTTPException(404, "Server not found")
    
    result = await reboot_droplet(db, droplet, do_token)
    
    return {
        "server_id": server_id,
        "status": "rebooting",
        "details": result,
    }


@router.post("/servers/{server_id}/clear-problematic")
async def clear_problematic_flag(
    server_id: str,
    db=Depends(db_connection),
    user=Depends(get_current_user),
):
    """Clear the problematic flag for a server."""
    from ..stores import droplets
    
    droplet = await droplets.get_for_workspace(db, server_id, user.id)
    if not droplet:
        raise HTTPException(404, "Server not found")
    
    await droplets.clear_problematic(db, server_id)
    
    return {"server_id": server_id, "status": "cleared"}


# =============================================================================
# Container Health Actions
# =============================================================================

@router.post("/containers/{container_id}/restart")
async def restart_container(
    container_id: str,
    db=Depends(db_connection),
    user=Depends(get_current_user),
    do_token: str = Depends(require_do_token),
):
    """Restart a container."""
    from ..stores import droplets, containers
    from ..health import restart_container as do_restart
    
    container = await containers.get(db, container_id)
    if not container:
        raise HTTPException(404, "Container not found")
    
    # Verify ownership via droplet
    droplet = await droplets.get_for_workspace(db, container["droplet_id"], user.id)
    if not droplet:
        raise HTTPException(403, "Not your container")
    
    result = await do_restart(db, container, droplet, do_token)
    
    return {
        "container_id": container_id,
        "status": "restarted",
        "details": result,
    }


@router.get("/containers/{container_id}/logs")
async def get_container_logs(
    container_id: str,
    tail: int = 100,
    db=Depends(db_connection),
    user=Depends(get_current_user),
    do_token: str = Depends(require_do_token),
):
    """Get logs from a container."""
    from ..stores import droplets, containers
    from ..health import get_container_logs as fetch_logs
    
    container = await containers.get(db, container_id)
    if not container:
        raise HTTPException(404, "Container not found")
    
    # Verify ownership via droplet
    droplet = await droplets.get_for_workspace(db, container["droplet_id"], user.id)
    if not droplet:
        raise HTTPException(403, "Not your container")
    
    logs = await fetch_logs(container, droplet, do_token, tail=tail)
    
    return {
        "container_id": container_id,
        "container_name": container["container_name"],
        "logs": logs,
    }


# =============================================================================
# Admin Routes (for scheduled health checks)
# =============================================================================

@router.post("/run-checks")
async def run_health_checks(
    db=Depends(db_connection),
    user=Depends(get_current_user),
    do_token: str = Depends(require_do_token),
):
    """
    Run health checks on all servers (admin only).
    
    In production, this would be called by a scheduled job.
    """
    if not settings.is_admin(user.email):
        raise HTTPException(403, "Admin only")
    
    from ..health import run_all_health_checks
    
    result = await run_all_health_checks(db, user.id, do_token)
    
    return result
