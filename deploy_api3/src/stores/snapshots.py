"""Snapshot store - returns typed Snapshot entities."""

from typing import List, Optional
from .base import BaseStore
from ..models import Snapshot


class SnapshotStore(BaseStore[Snapshot]):
    table_name = "snapshots"
    entity_class = Snapshot
    
    @classmethod
    async def list_for_workspace(cls, db, workspace_id: str) -> List[Snapshot]:
        """List all snapshots for a workspace."""
        return await cls.find(
            db,
            where_clause="workspace_id = ?",
            params=(workspace_id,),
            order_by="created_at DESC",
        )
    
    @classmethod
    async def get_by_do_id(cls, db, do_snapshot_id: str) -> Optional[Snapshot]:
        """Get snapshot by DigitalOcean ID."""
        results = await cls.find(
            db,
            where_clause="do_snapshot_id = ?",
            params=(do_snapshot_id,),
            limit=1,
        )
        return results[0] if results else None
    
    @classmethod
    async def get_base(cls, db, workspace_id: str) -> Optional[Snapshot]:
        """Get the base snapshot for a workspace."""
        results = await cls.find(
            db,
            where_clause="workspace_id = ? AND is_base = 1",
            params=(workspace_id,),
            limit=1,
        )
        return results[0] if results else None
    
    @classmethod
    async def set_base(cls, db, snapshot_id: str, workspace_id: str) -> Optional[Snapshot]:
        """Set a snapshot as the base snapshot (unsets others)."""
        # Unset current base
        await db.execute(
            f"UPDATE {cls.table_name} SET is_base = 0 WHERE workspace_id = ? AND is_base = 1",
            (workspace_id,)
        )
        # Set new base
        return await cls.update(db, snapshot_id, {'is_base': True})
    
    # Aliases
    list_for_user = list_for_workspace


# Module-level functions
get = SnapshotStore.get
create = SnapshotStore.create
update = SnapshotStore.update
delete = SnapshotStore.delete
list_for_workspace = SnapshotStore.list_for_workspace
list_for_user = SnapshotStore.list_for_user
get_by_do_id = SnapshotStore.get_by_do_id
get_base = SnapshotStore.get_base
set_base = SnapshotStore.set_base

# Backward-compat aliases
save = create
