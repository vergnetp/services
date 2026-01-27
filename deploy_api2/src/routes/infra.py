"""
Infrastructure routes - servers, snapshots, provisioning.

Thin wrappers around cloud clients and stores.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List

from ..deps import db_connection, get_current_user, require_do_token, get_cf_token

router = APIRouter(prefix="/infra", tags=["infrastructure"])


# =============================================================================
# Request/Response Models
# =============================================================================

class ProvisionServerRequest(BaseModel):
    """Request to provision a new server."""
    name: str
    region: str = "lon1"
    size: str = "s-1vcpu-1gb"
    snapshot_id: Optional[str] = None  # If None, uses base snapshot for region


class CreateSnapshotRequest(BaseModel):
    """Request to create a snapshot from a droplet."""
    droplet_id: str
    name: str
    set_as_base: bool = False


class ServerResponse(BaseModel):
    """Server/droplet response."""
    id: str
    do_droplet_id: int
    name: str
    region: str
    size: str
    ip: Optional[str]
    private_ip: Optional[str]
    status: str
    health_status: str


# =============================================================================
# Server Routes
# =============================================================================

@router.get("/servers")
async def list_servers(
    region: Optional[str] = None,
    status: Optional[str] = None,
    db=Depends(db_connection),
    user=Depends(get_current_user),
    do_token: str = Depends(require_do_token),
):
    """List all servers for the current workspace."""
    from ..stores import droplets
    
    if region:
        results = await droplets.list_by_region(db, user.id, region)
    else:
        results = await droplets.list_for_workspace(db, user.id)
    
    # Filter by status if provided
    if status:
        results = [d for d in results if d.get("status") == status]
    
    return {"servers": results}


@router.post("/servers/provision")
async def provision_server(
    request: ProvisionServerRequest,
    db=Depends(db_connection),
    user=Depends(get_current_user),
    do_token: str = Depends(require_do_token),
):
    """
    Provision a new server from snapshot.
    
    If snapshot_id is not provided, uses the base snapshot for the region.
    """
    from ..stores import droplets, snapshots
    from backend.cloud import AsyncDOClient
    
    # Get snapshot to use
    if request.snapshot_id:
        snapshot = await snapshots.get(db, request.snapshot_id)
        if not snapshot:
            raise HTTPException(404, "Snapshot not found")
        do_snapshot_id = snapshot["do_snapshot_id"]
    else:
        # Get base snapshot for region
        snapshot = await snapshots.get_base_snapshot(db, user.id, request.region)
        if not snapshot:
            raise HTTPException(400, f"No base snapshot available for region {request.region}")
        do_snapshot_id = snapshot["do_snapshot_id"]
    
    # Create droplet via DO API
    async with AsyncDOClient(api_token=do_token) as client:
        droplet_data = await client.create_droplet(
            name=request.name,
            region=request.region,
            size=request.size,
            image=str(do_snapshot_id),
            wait=True,
        )
    
    # Save to our database
    droplet = await droplets.create(db, {
        "workspace_id": user.id,
        "do_droplet_id": droplet_data.id,
        "name": droplet_data.name,
        "region": droplet_data.region,
        "size": droplet_data.size,
        "snapshot_id": request.snapshot_id or snapshot["id"],
        "ip": droplet_data.ip,
        "private_ip": droplet_data.private_ip,
        "vpc_uuid": droplet_data.vpc_uuid,
        "status": "active",
        "health_status": "unknown",
    })
    
    return droplet


@router.delete("/servers/{server_id}")
async def delete_server(
    server_id: str,
    force: bool = False,
    db=Depends(db_connection),
    user=Depends(get_current_user),
    do_token: str = Depends(require_do_token),
):
    """Delete a server."""
    from ..stores import droplets
    from backend.cloud import AsyncDOClient
    
    droplet = await droplets.get_for_workspace(db, server_id, user.id)
    if not droplet:
        raise HTTPException(404, "Server not found")
    
    # Delete from DO
    async with AsyncDOClient(api_token=do_token) as client:
        await client.delete_droplet(droplet["do_droplet_id"], force=force)
    
    # Soft delete from our database
    await droplets.delete(db, server_id)
    
    return {"status": "deleted", "id": server_id}


@router.get("/servers/{server_id}")
async def get_server(
    server_id: str,
    db=Depends(db_connection),
    user=Depends(get_current_user),
    do_token: str = Depends(require_do_token),
):
    """Get server details."""
    from ..stores import droplets
    
    droplet = await droplets.get_for_workspace(db, server_id, user.id)
    if not droplet:
        raise HTTPException(404, "Server not found")
    
    return droplet


@router.get("/servers/{server_id}/containers")
async def get_server_containers(
    server_id: str,
    db=Depends(db_connection),
    user=Depends(get_current_user),
    do_token: str = Depends(require_do_token),
):
    """Get containers running on a server."""
    from ..stores import droplets, containers
    
    droplet = await droplets.get_for_workspace(db, server_id, user.id)
    if not droplet:
        raise HTTPException(404, "Server not found")
    
    container_list = await containers.list_for_droplet(db, server_id)
    return {"containers": container_list}


# =============================================================================
# Snapshot Routes
# =============================================================================

@router.get("/snapshots")
async def list_snapshots(
    region: Optional[str] = None,
    db=Depends(db_connection),
    user=Depends(get_current_user),
    do_token: str = Depends(require_do_token),
):
    """List all snapshots for the current workspace."""
    from ..stores import snapshots
    
    if region:
        results = await snapshots.list_for_region(db, user.id, region)
    else:
        results = await snapshots.list_for_workspace(db, user.id)
    
    return {"snapshots": results}


@router.post("/snapshots")
async def create_snapshot(
    request: CreateSnapshotRequest,
    db=Depends(db_connection),
    user=Depends(get_current_user),
    do_token: str = Depends(require_do_token),
):
    """Create a snapshot from an existing droplet."""
    from ..stores import droplets, snapshots
    from backend.cloud import AsyncDOClient
    
    # Verify droplet ownership
    droplet = await droplets.get_for_workspace(db, request.droplet_id, user.id)
    if not droplet:
        raise HTTPException(404, "Server not found")
    
    # Create snapshot via DO API
    async with AsyncDOClient(api_token=do_token) as client:
        snapshot_data = await client.create_snapshot_from_droplet(
            droplet_id=droplet["do_droplet_id"],
            name=request.name,
            wait=True,
        )
    
    # Save to our database
    snapshot = await snapshots.create(db, {
        "workspace_id": user.id,
        "do_snapshot_id": snapshot_data["id"],
        "name": request.name,
        "region": droplet["region"],
        "size_gigabytes": snapshot_data.get("size_gigabytes"),
        "agent_version": None,  # TODO: detect from droplet
        "is_base": False,
    })
    
    # Set as base if requested
    if request.set_as_base:
        await snapshots.mark_as_base(db, snapshot["id"], user.id, droplet["region"])
        snapshot["is_base"] = True
    
    return snapshot


@router.post("/snapshots/{snapshot_id}/set-base")
async def set_base_snapshot(
    snapshot_id: str,
    db=Depends(db_connection),
    user=Depends(get_current_user),
):
    """Mark a snapshot as the base snapshot for its region."""
    from ..stores import snapshots
    
    snapshot = await snapshots.get(db, snapshot_id)
    if not snapshot:
        raise HTTPException(404, "Snapshot not found")
    
    if snapshot.get("workspace_id") != user.id:
        raise HTTPException(403, "Not your snapshot")
    
    await snapshots.mark_as_base(db, snapshot_id, user.id, snapshot["region"])
    
    return {"status": "ok", "snapshot_id": snapshot_id, "region": snapshot["region"]}


@router.delete("/snapshots/{snapshot_id}")
async def delete_snapshot(
    snapshot_id: str,
    db=Depends(db_connection),
    user=Depends(get_current_user),
    do_token: str = Depends(require_do_token),
):
    """Delete a snapshot."""
    from ..stores import snapshots
    from backend.cloud import AsyncDOClient
    
    snapshot = await snapshots.get(db, snapshot_id)
    if not snapshot:
        raise HTTPException(404, "Snapshot not found")
    
    if snapshot.get("workspace_id") != user.id:
        raise HTTPException(403, "Not your snapshot")
    
    # Delete from DO
    async with AsyncDOClient(api_token=do_token) as client:
        await client.delete_snapshot(str(snapshot["do_snapshot_id"]))
    
    # Delete from our database
    await snapshots.delete(db, snapshot_id)
    
    return {"status": "deleted", "id": snapshot_id}


# =============================================================================
# Region/Size Info Routes
# =============================================================================

@router.get("/regions")
async def list_regions(
    do_token: str = Depends(require_do_token),
):
    """List available DO regions."""
    from backend.cloud import AsyncDOClient
    
    async with AsyncDOClient(api_token=do_token) as client:
        regions = await client.list_regions()
    
    return {"regions": regions}


@router.get("/sizes")
async def list_sizes(
    do_token: str = Depends(require_do_token),
):
    """List available DO droplet sizes."""
    from backend.cloud import AsyncDOClient
    
    async with AsyncDOClient(api_token=do_token) as client:
        sizes = await client.list_sizes()
    
    return {"sizes": sizes}
