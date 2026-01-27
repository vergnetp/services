"""
Generic CRUD operations - AUTO-GENERATED from manifest.yaml
DO NOT EDIT - changes will be overwritten on regenerate

Usage in stores:
    from .._gen.crud import EntityCRUD
    
    class MyStore:
        def __init__(self, db):
            self.db = db
            self._crud = EntityCRUD("my_table")
        
        async def create(self, data: dict) -> dict:
            return await self._crud.create(self.db, data)
"""

from typing import Any, Optional, List
from datetime import datetime, timezone
import uuid


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


def _to_dict(data: Any) -> dict:
    """Convert pydantic model or dict to dict."""
    if hasattr(data, "model_dump"):
        return data.model_dump(exclude_unset=True)
    return dict(data)


class EntityCRUD:
    """
    Generic CRUD for any entity table.
    
    Uses the databases library entity methods:
    - db.find_entities() for list/search
    - db.get_entity() for get by id
    - db.save_entity() for create/update
    - db.delete_entity() for delete
    """
    
    def __init__(self, table: str, soft_delete: bool = False):
        self.table = table
        self.soft_delete = soft_delete
    
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
    ) -> List[dict]:
        """List entities with optional filtering."""
        conditions = []
        all_params = []
        
        if workspace_id:
            conditions.append("[workspace_id] = ?")
            all_params.append(workspace_id)
        
        if where_clause:
            conditions.append(f"({where_clause})")
            if params:
                all_params.extend(params)
        
        final_where = " AND ".join(conditions) if conditions else None
        final_params = tuple(all_params) if all_params else None
        
        return await db.find_entities(
            self.table,
            where_clause=final_where,
            params=final_params,
            order_by=order_by or "[created_at] DESC",
            limit=limit,
            offset=offset,
            include_deleted=include_deleted if self.soft_delete else True,
        )
    
    async def get(self, db: Any, entity_id: str) -> Optional[dict]:
        """Get entity by ID."""
        return await db.get_entity(self.table, entity_id)
    
    async def create(self, db: Any, data: Any, entity_id: str = None) -> dict:
        """Create new entity from dict or pydantic model."""
        values = _to_dict(data)
        values["id"] = entity_id or _uuid()
        values["created_at"] = _now()
        values["updated_at"] = _now()
        
        return await db.save_entity(self.table, values)
    
    async def update(self, db: Any, entity_id: str, data: Any) -> Optional[dict]:
        """Update entity. Merges with existing."""
        existing = await self.get(db, entity_id)
        if not existing:
            return None
        
        updates = _to_dict(data)
        if not updates:
            return existing
        
        # Merge
        for k, v in updates.items():
            existing[k] = v
        existing["updated_at"] = _now()
        
        return await db.save_entity(self.table, existing)
    
    async def save(self, db: Any, entity: dict) -> dict:
        """Save entity (upsert). Entity must have 'id'."""
        entity["updated_at"] = _now()
        if "created_at" not in entity:
            entity["created_at"] = _now()
        return await db.save_entity(self.table, entity)
    
    async def delete(self, db: Any, entity_id: str, permanent: bool = None) -> bool:
        """Delete entity. Uses soft_delete setting unless permanent specified."""
        is_permanent = permanent if permanent is not None else not self.soft_delete
        return await db.delete_entity(self.table, entity_id, permanent=is_permanent)
    
    async def find_one(
        self,
        db: Any,
        where_clause: str,
        params: tuple = None,
    ) -> Optional[dict]:
        """Find single entity matching criteria."""
        results = await db.find_entities(
            self.table,
            where_clause=where_clause,
            params=params,
            limit=1,
        )
        return results[0] if results else None
    
    async def count(
        self,
        db: Any,
        where_clause: str = None,
        params: tuple = None,
        workspace_id: str = None,
    ) -> int:
        """Count entities matching criteria."""
        conditions = []
        all_params = []
        
        if workspace_id:
            conditions.append("[workspace_id] = ?")
            all_params.append(workspace_id)
        
        if where_clause:
            conditions.append(f"({where_clause})")
            if params:
                all_params.extend(params)
        
        final_where = " AND ".join(conditions) if conditions else None
        final_params = tuple(all_params) if all_params else None
        
        return await db.count_entities(
            self.table,
            where_clause=final_where,
            params=final_params,
        )
