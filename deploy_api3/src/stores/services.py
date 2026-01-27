"""Service store."""

from typing import Dict, Any, List, Optional
from .base import BaseStore

class ServiceStore(BaseStore):
    table_name = "service"
    
    @classmethod
    async def get_by_name(cls, db, project_id: str, name: str) -> Optional[Dict[str, Any]]:
        row = await db.fetchone(
            f"SELECT * FROM {cls.table_name} WHERE project_id = ? AND name = ? AND deleted_at IS NULL", (project_id, name))
        return dict(row) if row else None
    
    @classmethod
    async def list_for_project(cls, db, project_id: str) -> List[Dict[str, Any]]:
        rows = await db.fetchall(f"SELECT * FROM {cls.table_name} WHERE project_id = ? AND deleted_at IS NULL", (project_id,))
        return [dict(r) for r in rows]

get = ServiceStore.get
create = ServiceStore.create
update = ServiceStore.update
delete = ServiceStore.delete
get_by_name = ServiceStore.get_by_name
list_for_project = ServiceStore.list_for_project
