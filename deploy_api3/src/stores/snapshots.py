"""
Snapshot store - custom queries + entity re-exports.

Basic CRUD: Snapshot.get(), Snapshot.save(), Snapshot.update(), Snapshot.delete()
"""

from typing import List, Optional
from ...schemas import Snapshot


# Re-export entity methods for backward compatibility
get = Snapshot.get
create = Snapshot.save
save = Snapshot.save
update = Snapshot.update
delete = Snapshot.delete


async def list_for_workspace(db, workspace_id: str) -> List[Snapshot]:
    """List all snapshots for a workspace."""
    return await Snapshot.find(
        db,
        where="workspace_id = ?",
        params=(workspace_id,),
        order_by="created_at DESC",
    )


async def get_by_do_id(db, do_snapshot_id: str) -> Optional[Snapshot]:
    """Get snapshot by DigitalOcean ID."""
    results = await Snapshot.find(
        db,
        where="do_snapshot_id = ?",
        params=(do_snapshot_id,),
        limit=1,
    )
    return results[0] if results else None


async def get_base(db, workspace_id: str) -> Optional[Snapshot]:
    """Get the base snapshot for a workspace."""
    results = await Snapshot.find(
        db,
        where="workspace_id = ? AND is_base = 1",
        params=(workspace_id,),
        limit=1,
    )
    return results[0] if results else None


async def set_base(db, snapshot_id: str, workspace_id: str) -> Optional[Snapshot]:
    """Set a snapshot as the base snapshot (unsets others)."""
    # Unset current base
    await db.execute(
        "UPDATE snapshots SET is_base = 0 WHERE workspace_id = ? AND is_base = 1",
        (workspace_id,)
    )
    # Set new base
    return await Snapshot.update(db, snapshot_id, {'is_base': True})


# Alias
list_for_user = list_for_workspace
