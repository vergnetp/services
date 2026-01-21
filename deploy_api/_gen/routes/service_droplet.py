"""
ServiceDroplet CRUD routes - AUTO-GENERATED from manifest.yaml
DO NOT EDIT - changes will be overwritten on regenerate

For custom logic, create src/routes/service_droplet.py
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional

from ..schemas import ServiceDropletCreate, ServiceDropletUpdate, ServiceDropletResponse
from ..crud import EntityCRUD

# Import db dependency from src (allows customization)
from ...src.deps import db_connection

router = APIRouter(prefix="/service_droplets", tags=["service_droplets"])
crud = EntityCRUD("service_droplets", soft_delete=False)


@router.get("", response_model=list[ServiceDropletResponse])
async def list_service_droplets(
    db=Depends(db_connection),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    workspace_id: Optional[str] = None,
):
    """List service_droplets."""
    return await crud.list(db, skip=skip, limit=limit, workspace_id=workspace_id)


@router.post("", response_model=ServiceDropletResponse, status_code=201)
async def create_service_droplet(data: ServiceDropletCreate, db=Depends(db_connection)):
    """Create service_droplet."""
    return await crud.create(db, data)


@router.get("/{id}", response_model=ServiceDropletResponse)
async def get_service_droplet(id: str, db=Depends(db_connection)):
    """Get service_droplet by ID."""
    entity = await crud.get(db, id)
    if not entity:
        raise HTTPException(404, "ServiceDroplet not found")
    return entity


@router.patch("/{id}", response_model=ServiceDropletResponse)
async def update_service_droplet(id: str, data: ServiceDropletUpdate, db=Depends(db_connection)):
    """Update service_droplet."""
    entity = await crud.update(db, id, data)
    if not entity:
        raise HTTPException(404, "ServiceDroplet not found")
    return entity


@router.delete("/{id}", status_code=204)
async def delete_service_droplet(id: str, db=Depends(db_connection)):
    """Delete service_droplet."""
    await crud.delete(db, id)
