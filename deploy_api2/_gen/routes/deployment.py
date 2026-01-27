"""
Deployment CRUD routes - AUTO-GENERATED from manifest.yaml
DO NOT EDIT - changes will be overwritten on regenerate

For custom logic, create src/routes/deployment.py
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional

from ..schemas import DeploymentCreate, DeploymentUpdate, DeploymentResponse
from ..crud import EntityCRUD

# Import db dependency from src (allows customization)
from ...src.deps import db_connection

router = APIRouter(prefix="/deployments", tags=["deployments"])
crud = EntityCRUD("deployments", soft_delete=False)


@router.get("", response_model=list[DeploymentResponse])
async def list_deployments(
    db=Depends(db_connection),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    
):
    """List deployments."""
    return await crud.list(db, skip=skip, limit=limit)


@router.post("", response_model=DeploymentResponse, status_code=201)
async def create_deployment(data: DeploymentCreate, db=Depends(db_connection)):
    """Create deployment."""
    return await crud.create(db, data)


@router.get("/{id}", response_model=DeploymentResponse)
async def get_deployment(id: str, db=Depends(db_connection)):
    """Get deployment by ID."""
    entity = await crud.get(db, id)
    if not entity:
        raise HTTPException(404, "Deployment not found")
    return entity


@router.patch("/{id}", response_model=DeploymentResponse)
async def update_deployment(id: str, data: DeploymentUpdate, db=Depends(db_connection)):
    """Update deployment."""
    entity = await crud.update(db, id, data)
    if not entity:
        raise HTTPException(404, "Deployment not found")
    return entity


@router.delete("/{id}", status_code=204)
async def delete_deployment(id: str, db=Depends(db_connection)):
    """Delete deployment."""
    await crud.delete(db, id)
