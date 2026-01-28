"""Snapshot store - returns typed Snapshot entities."""

from typing import List, Optional
from .base import BaseStore
from _gen.entities import Snapshot


class SnapshotStore(BaseStore[Snapshot]):
    table_name = "snapshots"
    entity_class = Snapshot
    
    @classmethod
    async def list_for_workspace(cls, db, workspace_id: str) -> List[Snapshot]:
        """List all snapshots for a workspace."""
        rows = await db.fetchall(
            f"SELECT * FROM {cls.table_name} WHERE workspace_id = ? ORDER BY created_at DESC",
            (workspace_id,)
        )
        return cls._to_entities(rows)
    
    @classmethod
    async def get_by_do_id(cls, db, do_snapshot_id: str) -> Optional[Snapshot]:
        """Get snapshot by DigitalOcean ID."""
        row = await db.fetchone(
            f"SELECT * FROM {cls.table_name} WHERE do_snapshot_id = ?",
            (do_snapshot_id,)
        )
        return cls._to_entity(row)
    
    @classmethod
    async def get_base(cls, db, workspace_id: str) -> Optional[Snapshot]:
        """Get the base snapshot for a workspace."""
        row = await db.fetchone(
            f"SELECT * FROM {cls.table_name} WHERE workspace_id = ? AND is_base = 1",
            (workspace_id,)
        )
        return cls._to_entity(row)
    
    @classmethod
    async def set_base(cls, db, snapshot_id: str, workspace_id: str) -> Optional[Snapshot]:
        """Set a snapshot as the base snapshot (unsets others)."""
        # Unset current base
        await db.execute(
            f"UPDATE {cls.table_name} SET is_base = 0 WHERE workspace_id = ? AND is_base = 1",
            (workspace_id,)
        )
        # Set new base
        await db.execute(
            f"UPDATE {cls.table_name} SET is_base = 1 WHERE id = ?",
            (snapshot_id,)
        )
        return await cls.get(db, snapshot_id)


# Module-level functions
get = SnapshotStore.get
create = SnapshotStore.create
update = SnapshotStore.update
delete = SnapshotStore.delete
list_for_workspace = SnapshotStore.list_for_workspace
get_by_do_id = SnapshotStore.get_by_do_id
get_base = SnapshotStore.get_base
set_base = SnapshotStore.set_base

# Backward-compat aliases
list_for_user = list_for_workspace
save = create
