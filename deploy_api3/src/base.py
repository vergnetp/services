"""Base store with common CRUD operations - returns typed entities."""

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
    Base store with typed entity returns.
    
    Usage:
        class ProjectStore(BaseStore[Project]):
            table_name = "project"
            entity_class = Project
    """
    table_name: str = ""
    entity_class: Type[T] = None
    
    @classmethod
    def _to_entity(cls, row) -> Optional[T]:
        """Convert row to typed entity."""
        if row is None:
            return None
        data = dict(row)
        if cls.entity_class and hasattr(cls.entity_class, 'from_dict'):
            return cls.entity_class.from_dict(data)
        return data
    
    @classmethod
    def _to_entities(cls, rows) -> List[T]:
        """Convert rows to typed entities."""
        return [cls._to_entity(r) for r in rows]
    
    @classmethod
    async def get(cls, db, id: str) -> Optional[T]:
        row = await db.fetchone(f"SELECT * FROM {cls.table_name} WHERE id = ?", (id,))
        return cls._to_entity(row)
    
    @classmethod
    async def create(cls, db, data: Dict[str, Any]) -> T:
        data['id'] = data.get('id') or _generate_id()
        data['created_at'] = data.get('created_at') or _now_iso()
        data['updated_at'] = _now_iso()
        
        # Serialize complex types
        serialized = {}
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                serialized[k] = json.dumps(v)
            else:
                serialized[k] = v
        
        cols = ', '.join(serialized.keys())
        placeholders = ', '.join(['?' for _ in serialized])
        await db.execute(
            f"INSERT INTO {cls.table_name} ({cols}) VALUES ({placeholders})",
            tuple(serialized.values())
        )
        
        # Return typed entity
        return cls._to_entity(data)
    
    @classmethod
    async def update(cls, db, id: str, data: Dict[str, Any]) -> T:
        data['updated_at'] = _now_iso()
        
        # Serialize complex types
        serialized = {}
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                serialized[k] = json.dumps(v)
            else:
                serialized[k] = v
        
        sets = ', '.join([f"{k} = ?" for k in serialized.keys()])
        await db.execute(
            f"UPDATE {cls.table_name} SET {sets} WHERE id = ?",
            (*serialized.values(), id)
        )
        return await cls.get(db, id)
    
    @classmethod
    async def delete(cls, db, id: str) -> bool:
        await db.execute(f"DELETE FROM {cls.table_name} WHERE id = ?", (id,))
        return True
    
    @classmethod
    async def soft_delete(cls, db, id: str) -> bool:
        await db.execute(
            f"UPDATE {cls.table_name} SET deleted_at = ? WHERE id = ?",
            (_now_iso(), id)
        )
        return True
