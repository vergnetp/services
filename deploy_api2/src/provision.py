"""
Server provisioning logic.

Handles creating droplets from snapshots, managing snapshots, etc.
"""

import asyncio
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from .stores import droplets, snapshots
from config import settings


# =============================================================================
# Droplet Provisioning
# =============================================================================

async def provision_droplets(
    db,
    workspace_id: str,
    do_token: str,
    count: int = 1,
    region: str = "lon1",
    size: str = "s-1vcpu-1gb",
    snapshot_id: Optional[str] = None,
    name_prefix: str = "app",
    tags: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Provision new droplets from base snapshot.
    
    Returns list of created droplet records.
    """
    from backend.cloud import AsyncDOClient
    
    # Get snapshot to use
    if snapshot_id:
        snapshot = await snapshots.get(db, snapshot_id)
    else:
        # Get base snapshot for region
        snapshot = await snapshots.get_base_for_region(db, region)
    
    if not snapshot:
        raise ValueError(f"No snapshot available for region {region}")
    
    do_snapshot_id = snapshot.get("do_snapshot_id")
    if not do_snapshot_id:
        raise ValueError("Snapshot has no DigitalOcean ID")
    
    async with AsyncDOClient(api_token=do_token) as client:
        created = []
        
        for i in range(count):
            # Generate unique name
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            name = f"{name_prefix}-{region}-{timestamp}-{i+1}"
            
            # Build tags
            droplet_tags = ["deployed-via-api"]
            if tags:
                droplet_tags.extend(tags)
            
            try:
                # Create droplet via DO API
                do_droplet = await client.create_droplet(
                    name=name,
                    region=region,
                    size=size,
                    image=do_snapshot_id,
                    tags=droplet_tags,
                    wait=True,  # Wait for droplet to be active
                )
                
                # Extract IPs
                public_ip = None
                private_ip = None
                
                networks = do_droplet.get("networks", {})
                for net in networks.get("v4", []):
                    if net.get("type") == "public":
                        public_ip = net.get("ip_address")
                    elif net.get("type") == "private":
                        private_ip = net.get("ip_address")
                
                # Create local record
                droplet = await droplets.create(db, {
                    "workspace_id": workspace_id,
                    "name": name,
                    "do_droplet_id": str(do_droplet["id"]),
                    "region": region,
                    "size": size,
                    "ip": public_ip,
                    "private_ip": private_ip,
                    "status": "active",
                    "health_status": "unknown",
                    "snapshot_id": snapshot["id"],
                })
                
                created.append(droplet)
                
            except Exception as e:
                # Log error but continue with other droplets
                created.append({
                    "error": str(e),
                    "name": name,
                })
        
        return created


async def delete_droplet(
    db,
    droplet_id: str,
    do_token: str,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Delete a droplet.
    
    Removes from both DigitalOcean and local database.
    """
    from backend.cloud import AsyncDOClient
    
    droplet = await droplets.get(db, droplet_id)
    if not droplet:
        return {"error": "Droplet not found"}
    
    do_droplet_id = droplet.get("do_droplet_id")
    
    async with AsyncDOClient(api_token=do_token) as client:
        try:
            if do_droplet_id:
                # Delete from DigitalOcean
                await client.delete_droplet(int(do_droplet_id), force=force)
            
            # Delete local record
            await droplets.delete(db, droplet_id)
            
            return {
                "droplet_id": droplet_id,
                "name": droplet.get("name"),
                "status": "deleted",
            }
            
        except Exception as e:
            return {
                "droplet_id": droplet_id,
                "error": str(e),
            }


async def list_droplets(
    db,
    workspace_id: str,
    region: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    List droplets for workspace.
    """
    if region:
        return await droplets.list_by_region(db, workspace_id, region)
    return await droplets.list_active(db, workspace_id)


# =============================================================================
# Snapshot Management
# =============================================================================

async def create_snapshot_from_droplet(
    db,
    workspace_id: str,
    do_token: str,
    droplet_id: str,
    name: str,
    set_as_base: bool = False,
) -> Dict[str, Any]:
    """
    Create a snapshot from an existing droplet.
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
            # Create snapshot via DO API
            result = await client.create_snapshot_from_droplet(
                droplet_id=int(do_droplet_id),
                name=name,
                wait=True,
            )
            
            # Create local record
            snapshot = await snapshots.create(db, {
                "workspace_id": workspace_id,
                "name": name,
                "do_snapshot_id": str(result["id"]),
                "region": droplet.get("region"),
                "is_base": set_as_base,
                "source_droplet_id": droplet_id,
            })
            
            # If setting as base, unset other base snapshots for this region
            if set_as_base:
                await snapshots.set_base(db, snapshot["id"], droplet.get("region"))
            
            return snapshot
            
        except Exception as e:
            return {"error": str(e)}


async def list_snapshots(
    db,
    workspace_id: str,
    region: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    List snapshots for workspace.
    """
    if region:
        return await snapshots.list_by_region(db, workspace_id, region)
    return await snapshots.list_all(db, workspace_id)


async def set_base_snapshot(
    db,
    snapshot_id: str,
) -> Dict[str, Any]:
    """
    Set a snapshot as the base for its region.
    """
    snapshot = await snapshots.get(db, snapshot_id)
    if not snapshot:
        return {"error": "Snapshot not found"}
    
    await snapshots.set_base(db, snapshot_id, snapshot.get("region"))
    
    return {
        "snapshot_id": snapshot_id,
        "name": snapshot.get("name"),
        "region": snapshot.get("region"),
        "is_base": True,
    }


async def delete_snapshot(
    db,
    snapshot_id: str,
    do_token: str,
) -> Dict[str, Any]:
    """
    Delete a snapshot.
    """
    from backend.cloud import AsyncDOClient
    
    snapshot = await snapshots.get(db, snapshot_id)
    if not snapshot:
        return {"error": "Snapshot not found"}
    
    do_snapshot_id = snapshot.get("do_snapshot_id")
    
    async with AsyncDOClient(api_token=do_token) as client:
        try:
            if do_snapshot_id:
                await client.delete_snapshot(do_snapshot_id)
            
            await snapshots.delete(db, snapshot_id)
            
            return {
                "snapshot_id": snapshot_id,
                "name": snapshot.get("name"),
                "status": "deleted",
            }
            
        except Exception as e:
            return {"error": str(e)}


# =============================================================================
# Region & Size Info
# =============================================================================

async def list_regions(do_token: str) -> List[Dict[str, Any]]:
    """
    List available DigitalOcean regions.
    """
    from backend.cloud import AsyncDOClient
    
    async with AsyncDOClient(api_token=do_token) as client:
        return await client.list_regions()


async def list_sizes(do_token: str) -> List[Dict[str, Any]]:
    """
    List available droplet sizes.
    """
    from backend.cloud import AsyncDOClient
    
    async with AsyncDOClient(api_token=do_token) as client:
        return await client.list_sizes()


# =============================================================================
# Sync Droplet State
# =============================================================================

async def sync_droplet_state(
    db,
    workspace_id: str,
    do_token: str,
) -> Dict[str, Any]:
    """
    Sync local droplet records with DigitalOcean state.
    
    Updates IPs, status, etc. from DO API.
    """
    from backend.cloud import AsyncDOClient
    
    local_droplets = await droplets.list_all(db, workspace_id)
    
    async with AsyncDOClient(api_token=do_token) as client:
        # Get all DO droplets with our tag
        do_droplets = await client.list_droplets()
        
        # Index by ID
        do_by_id = {str(d.id): d for d in do_droplets}
        
        updated = []
        missing = []
        
        for local in local_droplets:
            do_id = local.get("do_droplet_id")
            
            if do_id and do_id in do_by_id:
                do_droplet = do_by_id[do_id]
                
                # Update local record
                await droplets.update(db, local["id"], {
                    "ip": do_droplet.ip,
                    "private_ip": do_droplet.private_ip,
                    "status": do_droplet.status,
                })
                
                updated.append(local["id"])
            else:
                # Droplet no longer exists in DO
                missing.append(local["id"])
        
        return {
            "updated": len(updated),
            "missing": len(missing),
            "missing_ids": missing,
        }
