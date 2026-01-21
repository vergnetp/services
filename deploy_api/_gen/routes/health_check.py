"""
HealthCheck CRUD routes - AUTO-GENERATED from manifest.yaml
DO NOT EDIT - changes will be overwritten on regenerate

For custom logic, create src/routes/health_check.py
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional

from ..schemas import HealthCheckCreate, HealthCheckUpdate, HealthCheckResponse
from ..crud import EntityCRUD

# Import db dependency from src (allows customization)
from ...src.deps import db_connection

router = APIRouter(prefix="/health_checks", tags=["health_checks"])
crud = EntityCRUD("health_checks", soft_delete=False)


@router.get("", response_model=list[HealthCheckResponse])
async def list_health_checks(
    db=Depends(db_connection),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    workspace_id: Optional[str] = None,
):
    """List health_checks."""
    return await crud.list(db, skip=skip, limit=limit, workspace_id=workspace_id)


@router.post("", response_model=HealthCheckResponse, status_code=201)
async def create_health_check(data: HealthCheckCreate, db=Depends(db_connection)):
    """Create health_check."""
    return await crud.create(db, data)


@router.get("/{id}", response_model=HealthCheckResponse)
async def get_health_check(id: str, db=Depends(db_connection)):
    """Get health_check by ID."""
    entity = await crud.get(db, id)
    if not entity:
        raise HTTPException(404, "HealthCheck not found")
    return entity


@router.patch("/{id}", response_model=HealthCheckResponse)
async def update_health_check(id: str, data: HealthCheckUpdate, db=Depends(db_connection)):
    """Update health_check."""
    entity = await crud.update(db, id, data)
    if not entity:
        raise HTTPException(404, "HealthCheck not found")
    return entity


@router.delete("/{id}", status_code=204)
async def delete_health_check(id: str, db=Depends(db_connection)):
    """Delete health_check."""
    await crud.delete(db, id)
