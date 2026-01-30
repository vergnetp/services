"""Droplet store - returns typed Droplet entities."""

from typing import List, Optional
from .base import BaseStore
from ..models import Droplet


class DropletStore(BaseStore[Droplet]):
    table_name = "droplets"
    entity_class = Droplet
    
    @classmethod
    async def list_active(cls, db) -> List[Droplet]:
        return await cls.find(db, where_clause="deleted_at IS NULL")
    
    @classmethod
    async def list_for_workspace(cls, db, workspace_id: str) -> List[Droplet]:
        return await cls.find(
            db,
            where_clause="workspace_id = ? AND deleted_at IS NULL",
            params=(workspace_id,),
        )
    
    @classmethod
    async def get_by_do_id(cls, db, do_droplet_id: int) -> Optional[Droplet]:
        """Get droplet by DigitalOcean ID."""
        results = await cls.find(
            db,
            where_clause="do_droplet_id = ?",
            params=(do_droplet_id,),
            limit=1,
        )
        return results[0] if results else None
    
    # Alias
    list_for_user = list_for_workspace


# Module-level functions
get = DropletStore.get
create = DropletStore.create
update = DropletStore.update
delete = DropletStore.delete
soft_delete = DropletStore.soft_delete
list_active = DropletStore.list_active
list_for_workspace = DropletStore.list_for_workspace
list_for_user = DropletStore.list_for_user
get_by_do_id = DropletStore.get_by_do_id
