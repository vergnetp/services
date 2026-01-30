"""
Droplet store - custom queries + entity re-exports.

Basic CRUD: Droplet.get(), Droplet.save(), Droplet.update(), Droplet.delete()
"""

from typing import List, Optional
from ...schemas import Droplet


# Re-export entity methods for backward compatibility
get = Droplet.get
create = Droplet.save
save = Droplet.save
update = Droplet.update
delete = Droplet.delete
soft_delete = Droplet.soft_delete


async def list_active(db) -> List[Droplet]:
    """List all active (non-deleted) droplets."""
    return await Droplet.find(db, where="deleted_at IS NULL")


async def list_for_workspace(db, workspace_id: str) -> List[Droplet]:
    """List droplets for a workspace."""
    return await Droplet.find(
        db,
        where="workspace_id = ? AND deleted_at IS NULL",
        params=(workspace_id,),
    )


async def get_by_do_id(db, do_droplet_id: int) -> Optional[Droplet]:
    """Get droplet by DigitalOcean ID."""
    results = await Droplet.find(
        db,
        where="do_droplet_id = ?",
        params=(do_droplet_id,),
        limit=1,
    )
    return results[0] if results else None


# Alias
list_for_user = list_for_workspace
