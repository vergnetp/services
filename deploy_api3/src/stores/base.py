"""
Base store using app_kernel's schemaless entity framework.

Uses db.save_entity() and db.find_entities() which auto-add columns.
"""

import json
import uuid
from typing import Dict, Any, List, Optional, TypeVar, Type, Generic
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_id() -> str:
    return str(uuid.uuid4())


T = TypeVar('T')


class BaseStore(Generic[T]):
    """
    Base store using app_kernel's schemaless entity framework.
    
    Uses save_entity/find_entities which auto-add missing columns.
    
    Usage:
        class ProjectStore(BaseStore[Project]):
            table_name = "projects"
            entity_class = Project
    """
    table_name: str = ""
    entity_class: Type[T] = None
    
    @classmethod
    def _to_entity(cls, row) -> Optional[T]:
        """Convert dict to typed entity."""
        if row is None:
            return None
        data = dict(row) if not isinstance(row, dict) else row
        if cls.entity_class and hasattr(cls.entity_class, 'from_dict'):
            return cls.entity_class.from_dict(data)
        return data
    
    @classmethod
    def _to_entities(cls, rows) -> List[T]:
        """Convert rows to typed entities."""
        return [cls._to_entity(r) for r in rows]
    
    @classmethod
    def _serialize(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Serialize complex types to JSON strings."""
        serialized = {}
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                serialized[k] = json.dumps(v)
            elif isinstance(v, bool):
                serialized[k] = 1 if v else 0
            else:
                serialized[k] = v
        return serialized
    
    @classmethod
    async def get(cls, db, id: str) -> Optional[T]:
        """Get entity by ID."""
        results = await db.find_entities(
            cls.table_name,
            where_clause="id = ?",
            params=(id,),
            limit=1,
        )
        return cls._to_entity(results[0]) if results else None
    
    @classmethod
    async def create(cls, db, data: Dict[str, Any]) -> T:
        """Create new entity (schemaless - auto-adds columns)."""
        data['id'] = data.get('id') or _generate_id()
        data['created_at'] = data.get('created_at') or _now_iso()
        data['updated_at'] = _now_iso()
        
        serialized = cls._serialize(data)
        await db.save_entity(cls.table_name, serialized)
        
        return cls._to_entity(data)
    
    @classmethod
    async def update(cls, db, id: str, data: Dict[str, Any]) -> T:
        """Update entity (schemaless - auto-adds columns)."""
        # Get existing
        existing = await cls.get(db, id)
        if not existing:
            return None
        
        # Merge with existing
        if hasattr(existing, '__dict__'):
            merged = {**existing.__dict__, **data}
        else:
            merged = {**existing, **data}
        
        merged['updated_at'] = _now_iso()
        
        serialized = cls._serialize(merged)
        await db.save_entity(cls.table_name, serialized)
        
        return await cls.get(db, id)
    
    @classmethod
    async def delete(cls, db, id: str) -> bool:
        """Hard delete entity."""
        await db.execute(f"DELETE FROM {cls.table_name} WHERE id = ?", (id,))
        return True
    
    @classmethod
    async def soft_delete(cls, db, id: str) -> bool:
        """Soft delete (set deleted_at)."""
        return await cls.update(db, id, {'deleted_at': _now_iso()}) is not None
    
    @classmethod
    async def find(cls, db, where_clause: str = None, params: tuple = None, 
                   limit: int = None, order_by: str = None) -> List[T]:
        """Find entities with optional filtering."""
        results = await db.find_entities(
            cls.table_name,
            where_clause=where_clause,
            params=params,
            limit=limit,
            order_by=order_by,
        )
        return cls._to_entities(results)
