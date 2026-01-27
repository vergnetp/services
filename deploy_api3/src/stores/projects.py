"""Project store."""

from typing import Dict, Any, List, Optional
from .base import BaseStore

class ProjectStore(BaseStore):
    table_name = "project"
    
    @classmethod
    async def get_by_name(cls, db, workspace_id: str, name: str) -> Optional[Dict[str, Any]]:
        row = await db.fetchone(
            f"SELECT * FROM {cls.table_name} WHERE workspace_id = ? AND name = ? AND deleted_at IS NULL", (workspace_id, name))
        return dict(row) if row else None
    
    @classmethod
    async def list_for_workspace(cls, db, workspace_id: str) -> List[Dict[str, Any]]:
        rows = await db.fetchall(f"SELECT * FROM {cls.table_name} WHERE workspace_id = ? AND deleted_at IS NULL", (workspace_id,))
        return [dict(r) for r in rows]

get = ProjectStore.get
create = ProjectStore.create
update = ProjectStore.update
delete = ProjectStore.delete
get_by_name = ProjectStore.get_by_name
list_for_workspace = ProjectStore.list_for_workspace
