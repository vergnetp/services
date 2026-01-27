"""
Base store class with common patterns.

All stores inherit from this to get:
- Async/sync database access
- Standard CRUD via EntityCRUD from _gen
- Workspace scoping helpers
"""

from typing import Any, Dict, List, Optional
from .._gen.crud import EntityCRUD


class BaseStore:
    """
    Base class for entity stores.
    
    Provides common patterns for database operations.
    Subclasses set `table` and `soft_delete` class attributes.
    """
    
    table: str = ""
    soft_delete: bool = False
    
    def __init__(self):
        if not self.table:
            raise ValueError(f"{self.__class__.__name__} must define 'table' attribute")
        self._crud = EntityCRUD(self.table, soft_delete=self.soft_delete)
    
    # =========================================================================
    # Standard CRUD - delegates to EntityCRUD
    # =========================================================================
    
    async def get(self, db: Any, entity_id: str) -> Optional[Dict[str, Any]]:
        """Get entity by ID."""
        return await self._crud.get(db, entity_id)
    
    async def create(self, db: Any, data: Any, entity_id: str = None) -> Dict[str, Any]:
        """Create new entity."""
        return await self._crud.create(db, data, entity_id=entity_id)
    
    async def update(self, db: Any, entity_id: str, data: Any) -> Optional[Dict[str, Any]]:
        """Update entity by ID."""
        return await self._crud.update(db, entity_id, data)
    
    async def save(self, db: Any, entity: Dict[str, Any]) -> Dict[str, Any]:
        """Save entity (upsert). Entity must have 'id'."""
        return await self._crud.save(db, entity)
    
    async def delete(self, db: Any, entity_id: str, permanent: bool = None) -> bool:
        """Delete entity."""
        return await self._crud.delete(db, entity_id, permanent=permanent)
    
    async def list(
        self,
        db: Any,
        where_clause: str = None,
        params: tuple = None,
        order_by: str = None,
        limit: int = 100,
        offset: int = 0,
        workspace_id: str = None,
        include_deleted: bool = False,
    ) -> List[Dict[str, Any]]:
        """List entities with optional filtering."""
        return await self._crud.list(
            db,
            where_clause=where_clause,
            params=params,
            order_by=order_by,
            limit=limit,
            offset=offset,
            workspace_id=workspace_id,
            include_deleted=include_deleted,
        )
    
    async def find_one(
        self,
        db: Any,
        where_clause: str,
        params: tuple = None,
    ) -> Optional[Dict[str, Any]]:
        """Find single entity matching criteria."""
        return await self._crud.find_one(db, where_clause, params)
    
    async def count(
        self,
        db: Any,
        where_clause: str = None,
        params: tuple = None,
        workspace_id: str = None,
    ) -> int:
        """Count entities matching criteria."""
        return await self._crud.count(db, where_clause, params, workspace_id)


class WorkspaceScopedStore(BaseStore):
    """
    Store for workspace-scoped entities.
    
    Adds workspace_id helpers for common patterns.
    """
    
    async def list_for_workspace(
        self,
        db: Any,
        workspace_id: str,
        order_by: str = None,
        limit: int = 100,
        offset: int = 0,
        include_deleted: bool = False,
    ) -> List[Dict[str, Any]]:
        """List all entities for a workspace."""
        return await self.list(
            db,
            workspace_id=workspace_id,
            order_by=order_by,
            limit=limit,
            offset=offset,
            include_deleted=include_deleted,
        )
    
    async def get_for_workspace(
        self,
        db: Any,
        entity_id: str,
        workspace_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Get entity by ID, verifying workspace ownership."""
        entity = await self.get(db, entity_id)
        if entity and entity.get("workspace_id") == workspace_id:
            return entity
        return None
