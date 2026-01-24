"""
Backup CRUD routes - AUTO-GENERATED from manifest.yaml
DO NOT EDIT - changes will be overwritten on regenerate

For custom logic, create src/routes/backup.py
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional

from ..schemas import BackupCreate, BackupUpdate, BackupResponse
from ..crud import EntityCRUD

# Import db dependency from src (allows customization)
from ...src.deps import db_connection

router = APIRouter(prefix="/backups", tags=["backups"])
crud = EntityCRUD("backups", soft_delete=False)


@router.get("", response_model=list[BackupResponse])
async def list_backups(
    db=Depends(db_connection),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    workspace_id: Optional[str] = None,
):
    """List backups."""
    return await crud.list(db, skip=skip, limit=limit, workspace_id=workspace_id)


@router.post("", response_model=BackupResponse, status_code=201)
async def create_backup(data: BackupCreate, db=Depends(db_connection)):
    """Create backup."""
    return await crud.create(db, data)


@router.get("/{id}", response_model=BackupResponse)
async def get_backup(id: str, db=Depends(db_connection)):
    """Get backup by ID."""
    entity = await crud.get(db, id)
    if not entity:
        raise HTTPException(404, "Backup not found")
    return entity


@router.patch("/{id}", response_model=BackupResponse)
async def update_backup(id: str, data: BackupUpdate, db=Depends(db_connection)):
    """Update backup."""
    entity = await crud.update(db, id, data)
    if not entity:
        raise HTTPException(404, "Backup not found")
    return entity


@router.delete("/{id}", status_code=204)
async def delete_backup(id: str, db=Depends(db_connection)):
    """Delete backup."""
    await crud.delete(db, id)
