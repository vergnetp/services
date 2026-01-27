"""
Snapshot CRUD routes - AUTO-GENERATED from manifest.yaml
DO NOT EDIT - changes will be overwritten on regenerate

For custom logic, create src/routes/snapshot.py
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional

from ..schemas import SnapshotCreate, SnapshotUpdate, SnapshotResponse
from ..crud import EntityCRUD

# Import db dependency from src (allows customization)
from ...src.deps import db_connection

router = APIRouter(prefix="/snapshots", tags=["snapshots"])
crud = EntityCRUD("snapshots", soft_delete=False)


@router.get("", response_model=list[SnapshotResponse])
async def list_snapshots(
    db=Depends(db_connection),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    workspace_id: Optional[str] = None,
):
    """List snapshots."""
    return await crud.list(db, skip=skip, limit=limit, workspace_id=workspace_id)


@router.post("", response_model=SnapshotResponse, status_code=201)
async def create_snapshot(data: SnapshotCreate, db=Depends(db_connection)):
    """Create snapshot."""
    return await crud.create(db, data)


@router.get("/{id}", response_model=SnapshotResponse)
async def get_snapshot(id: str, db=Depends(db_connection)):
    """Get snapshot by ID."""
    entity = await crud.get(db, id)
    if not entity:
        raise HTTPException(404, "Snapshot not found")
    return entity


@router.patch("/{id}", response_model=SnapshotResponse)
async def update_snapshot(id: str, data: SnapshotUpdate, db=Depends(db_connection)):
    """Update snapshot."""
    entity = await crud.update(db, id, data)
    if not entity:
        raise HTTPException(404, "Snapshot not found")
    return entity


@router.delete("/{id}", status_code=204)
async def delete_snapshot(id: str, db=Depends(db_connection)):
    """Delete snapshot."""
    await crud.delete(db, id)
