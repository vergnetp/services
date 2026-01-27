"""Droplet store."""

from typing import Dict, Any, List, Optional
from .base import BaseStore

class DropletStore(BaseStore):
    table_name = "droplet"
    
    @classmethod
    async def list_active(cls, db) -> List[Dict[str, Any]]:
        rows = await db.fetchall(f"SELECT * FROM {cls.table_name} WHERE deleted_at IS NULL")
        return [dict(r) for r in rows]
    
    @classmethod
    async def list_for_workspace(cls, db, workspace_id: str) -> List[Dict[str, Any]]:
        rows = await db.fetchall(
            f"SELECT * FROM {cls.table_name} WHERE workspace_id = ? AND deleted_at IS NULL",
            (workspace_id,))
        return [dict(r) for r in rows]

get = DropletStore.get
create = DropletStore.create
update = DropletStore.update
delete = DropletStore.delete
list_active = DropletStore.list_active
list_for_workspace = DropletStore.list_for_workspace
