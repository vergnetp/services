"""Base store with common CRUD operations."""

import json
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_id() -> str:
    return str(uuid.uuid4())


class BaseStore:
    table_name: str = ""
    
    @classmethod
    async def get(cls, db, id: str) -> Optional[Dict[str, Any]]:
        row = await db.fetchone(f"SELECT * FROM {cls.table_name} WHERE id = ?", (id,))
        return dict(row) if row else None
    
    @classmethod
    async def create(cls, db, data: Dict[str, Any]) -> Dict[str, Any]:
        data['id'] = data.get('id') or _generate_id()
        data['created_at'] = data.get('created_at') or _now_iso()
        data['updated_at'] = _now_iso()
        
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                data[k] = json.dumps(v)
        
        cols = ', '.join(data.keys())
        placeholders = ', '.join(['?' for _ in data])
        await db.execute(f"INSERT INTO {cls.table_name} ({cols}) VALUES ({placeholders})", tuple(data.values()))
        return data
    
    @classmethod
    async def update(cls, db, id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        data['updated_at'] = _now_iso()
        
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                data[k] = json.dumps(v)
        
        sets = ', '.join([f"{k} = ?" for k in data.keys()])
        await db.execute(f"UPDATE {cls.table_name} SET {sets} WHERE id = ?", (*data.values(), id))
        return await cls.get(db, id)
    
    @classmethod
    async def delete(cls, db, id: str) -> bool:
        await db.execute(f"DELETE FROM {cls.table_name} WHERE id = ?", (id,))
        return True
