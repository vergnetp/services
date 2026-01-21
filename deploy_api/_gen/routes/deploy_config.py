"""
DeployConfig CRUD routes - AUTO-GENERATED from manifest.yaml
DO NOT EDIT - changes will be overwritten on regenerate

For custom logic, create src/routes/deploy_config.py
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional

from ..schemas import DeployConfigCreate, DeployConfigUpdate, DeployConfigResponse
from ..crud import EntityCRUD

# Import db dependency from src (allows customization)
from ...src.deps import db_connection

router = APIRouter(prefix="/deploy_configs", tags=["deploy_configs"])
crud = EntityCRUD("deploy_configs", soft_delete=False)


@router.get("", response_model=list[DeployConfigResponse])
async def list_deploy_configs(
    db=Depends(db_connection),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    workspace_id: Optional[str] = None,
):
    """List deploy_configs."""
    return await crud.list(db, skip=skip, limit=limit, workspace_id=workspace_id)


@router.post("", response_model=DeployConfigResponse, status_code=201)
async def create_deploy_config(data: DeployConfigCreate, db=Depends(db_connection)):
    """Create deploy_config."""
    return await crud.create(db, data)


@router.get("/{id}", response_model=DeployConfigResponse)
async def get_deploy_config(id: str, db=Depends(db_connection)):
    """Get deploy_config by ID."""
    entity = await crud.get(db, id)
    if not entity:
        raise HTTPException(404, "DeployConfig not found")
    return entity


@router.patch("/{id}", response_model=DeployConfigResponse)
async def update_deploy_config(id: str, data: DeployConfigUpdate, db=Depends(db_connection)):
    """Update deploy_config."""
    entity = await crud.update(db, id, data)
    if not entity:
        raise HTTPException(404, "DeployConfig not found")
    return entity


@router.delete("/{id}", status_code=204)
async def delete_deploy_config(id: str, db=Depends(db_connection)):
    """Delete deploy_config."""
    await crud.delete(db, id)
