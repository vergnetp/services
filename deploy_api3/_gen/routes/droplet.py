"""
Droplet CRUD routes - AUTO-GENERATED from manifest.yaml
DO NOT EDIT - changes will be overwritten on regenerate

For custom logic, create src/routes/droplet.py
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional

from ..schemas import DropletCreate, DropletUpdate, DropletResponse
from ..crud import EntityCRUD

# Import db dependency from src (allows customization)
from ...src.deps import db_connection

router = APIRouter(prefix="/droplets", tags=["droplets"])
crud = EntityCRUD("droplets", soft_delete=True)


@router.get("", response_model=list[DropletResponse])
async def list_droplets(
    db=Depends(db_connection),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    workspace_id: Optional[str] = None,
):
    """List droplets."""
    return await crud.list(db, skip=skip, limit=limit, workspace_id=workspace_id)


@router.post("", response_model=DropletResponse, status_code=201)
async def create_droplet(data: DropletCreate, db=Depends(db_connection)):
    """Create droplet."""
    return await crud.create(db, data)


@router.get("/{id}", response_model=DropletResponse)
async def get_droplet(id: str, db=Depends(db_connection)):
    """Get droplet by ID."""
    entity = await crud.get(db, id)
    if not entity:
        raise HTTPException(404, "Droplet not found")
    return entity


@router.patch("/{id}", response_model=DropletResponse)
async def update_droplet(id: str, data: DropletUpdate, db=Depends(db_connection)):
    """Update droplet."""
    entity = await crud.update(db, id, data)
    if not entity:
        raise HTTPException(404, "Droplet not found")
    return entity


@router.delete("/{id}", status_code=204)
async def delete_droplet(id: str, db=Depends(db_connection)):
    """Delete droplet."""
    await crud.delete(db, id)
