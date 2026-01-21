"""
Service CRUD routes - AUTO-GENERATED from manifest.yaml
DO NOT EDIT - changes will be overwritten on regenerate

For custom logic, create src/routes/service.py
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional

from ..schemas import ServiceCreate, ServiceUpdate, ServiceResponse
from ..crud import EntityCRUD

# Import db dependency from src (allows customization)
from ...src.deps import db_connection

router = APIRouter(prefix="/services", tags=["services"])
crud = EntityCRUD("services", soft_delete=False)


@router.get("", response_model=list[ServiceResponse])
async def list_services(
    db=Depends(db_connection),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    workspace_id: Optional[str] = None,
):
    """List services."""
    return await crud.list(db, skip=skip, limit=limit, workspace_id=workspace_id)


@router.post("", response_model=ServiceResponse, status_code=201)
async def create_service(data: ServiceCreate, db=Depends(db_connection)):
    """Create service."""
    return await crud.create(db, data)


@router.get("/{id}", response_model=ServiceResponse)
async def get_service(id: str, db=Depends(db_connection)):
    """Get service by ID."""
    entity = await crud.get(db, id)
    if not entity:
        raise HTTPException(404, "Service not found")
    return entity


@router.patch("/{id}", response_model=ServiceResponse)
async def update_service(id: str, data: ServiceUpdate, db=Depends(db_connection)):
    """Update service."""
    entity = await crud.update(db, id, data)
    if not entity:
        raise HTTPException(404, "Service not found")
    return entity


@router.delete("/{id}", status_code=204)
async def delete_service(id: str, db=Depends(db_connection)):
    """Delete service."""
    await crud.delete(db, id)
