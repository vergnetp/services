"""
Project CRUD routes - AUTO-GENERATED from manifest.yaml
DO NOT EDIT - changes will be overwritten on regenerate

For custom logic, create src/routes/project.py
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional

from ..schemas import ProjectCreate, ProjectUpdate, ProjectResponse
from ..crud import EntityCRUD

# Import db dependency from src (allows customization)
from ...src.deps import db_connection

router = APIRouter(prefix="/projects", tags=["projects"])
crud = EntityCRUD("projects", soft_delete=False)


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    db=Depends(db_connection),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    workspace_id: Optional[str] = None,
):
    """List projects."""
    return await crud.list(db, skip=skip, limit=limit, workspace_id=workspace_id)


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(data: ProjectCreate, db=Depends(db_connection)):
    """Create project."""
    return await crud.create(db, data)


@router.get("/{id}", response_model=ProjectResponse)
async def get_project(id: str, db=Depends(db_connection)):
    """Get project by ID."""
    entity = await crud.get(db, id)
    if not entity:
        raise HTTPException(404, "Project not found")
    return entity


@router.patch("/{id}", response_model=ProjectResponse)
async def update_project(id: str, data: ProjectUpdate, db=Depends(db_connection)):
    """Update project."""
    entity = await crud.update(db, id, data)
    if not entity:
        raise HTTPException(404, "Project not found")
    return entity


@router.delete("/{id}", status_code=204)
async def delete_project(id: str, db=Depends(db_connection)):
    """Delete project."""
    await crud.delete(db, id)
