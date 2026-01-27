"""Snapshot store."""

from typing import Dict, Any, List, Optional
from .base import BaseStore

class SnapshotStore(BaseStore):
    table_name = "snapshot"
    
    @classmethod
    async def list_for_workspace(cls, db, workspace_id: str, region: str = None) -> List[Dict[str, Any]]:
        if region:
            rows = await db.fetchall(
                f"SELECT * FROM {cls.table_name} WHERE workspace_id = ? AND region = ?",
                (workspace_id, region))
        else:
            rows = await db.fetchall(
                f"SELECT * FROM {cls.table_name} WHERE workspace_id = ?",
                (workspace_id,))
        return [dict(r) for r in rows]
    
    @classmethod
    async def get_base(cls, db, workspace_id: str) -> Optional[Dict[str, Any]]:
        row = await db.fetchone(
            f"SELECT * FROM {cls.table_name} WHERE workspace_id = ? AND is_base = 1",
            (workspace_id,))
        return dict(row) if row else None

get = SnapshotStore.get
create = SnapshotStore.create
update = SnapshotStore.update
delete = SnapshotStore.delete
list_for_workspace = SnapshotStore.list_for_workspace
get_base = SnapshotStore.get_base
