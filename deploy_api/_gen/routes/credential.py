"""
Credential CRUD routes - AUTO-GENERATED from manifest.yaml
DO NOT EDIT - changes will be overwritten on regenerate

For custom logic, create src/routes/credential.py
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional

from ..schemas import CredentialCreate, CredentialUpdate, CredentialResponse
from ..crud import EntityCRUD

# Import db dependency from src (allows customization)
from ...src.deps import db_connection

router = APIRouter(prefix="/credentials", tags=["credentials"])
crud = EntityCRUD("credentials", soft_delete=False)


@router.get("", response_model=list[CredentialResponse])
async def list_credentials(
    db=Depends(db_connection),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    workspace_id: Optional[str] = None,
):
    """List credentials."""
    return await crud.list(db, skip=skip, limit=limit, workspace_id=workspace_id)


@router.post("", response_model=CredentialResponse, status_code=201)
async def create_credential(data: CredentialCreate, db=Depends(db_connection)):
    """Create credential."""
    return await crud.create(db, data)


@router.get("/{id}", response_model=CredentialResponse)
async def get_credential(id: str, db=Depends(db_connection)):
    """Get credential by ID."""
    entity = await crud.get(db, id)
    if not entity:
        raise HTTPException(404, "Credential not found")
    return entity


@router.patch("/{id}", response_model=CredentialResponse)
async def update_credential(id: str, data: CredentialUpdate, db=Depends(db_connection)):
    """Update credential."""
    entity = await crud.update(db, id, data)
    if not entity:
        raise HTTPException(404, "Credential not found")
    return entity


@router.delete("/{id}", status_code=204)
async def delete_credential(id: str, db=Depends(db_connection)):
    """Delete credential."""
    await crud.delete(db, id)
