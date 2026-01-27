"""
Container CRUD routes - AUTO-GENERATED from manifest.yaml
DO NOT EDIT - changes will be overwritten on regenerate

For custom logic, create src/routes/container.py
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional

from ..schemas import ContainerCreate, ContainerUpdate, ContainerResponse
from ..crud import EntityCRUD

# Import db dependency from src (allows customization)
from ...src.deps import db_connection

router = APIRouter(prefix="/containers", tags=["containers"])
crud = EntityCRUD("containers", soft_delete=False)


@router.get("", response_model=list[ContainerResponse])
async def list_containers(
    db=Depends(db_connection),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    
):
    """List containers."""
    return await crud.list(db, skip=skip, limit=limit)


@router.post("", response_model=ContainerResponse, status_code=201)
async def create_container(data: ContainerCreate, db=Depends(db_connection)):
    """Create container."""
    return await crud.create(db, data)


@router.get("/{id}", response_model=ContainerResponse)
async def get_container(id: str, db=Depends(db_connection)):
    """Get container by ID."""
    entity = await crud.get(db, id)
    if not entity:
        raise HTTPException(404, "Container not found")
    return entity


@router.patch("/{id}", response_model=ContainerResponse)
async def update_container(id: str, data: ContainerUpdate, db=Depends(db_connection)):
    """Update container."""
    entity = await crud.update(db, id, data)
    if not entity:
        raise HTTPException(404, "Container not found")
    return entity


@router.delete("/{id}", status_code=204)
async def delete_container(id: str, db=Depends(db_connection)):
    """Delete container."""
    await crud.delete(db, id)
