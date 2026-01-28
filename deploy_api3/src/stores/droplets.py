"""Droplet store - returns typed Droplet entities."""

from typing import List, Optional
from .base import BaseStore
from _gen.entities import Droplet


class DropletStore(BaseStore[Droplet]):
    table_name = "droplets"  # Note: plural to match schema
    entity_class = Droplet
    
    @classmethod
    async def list_active(cls, db) -> List[Droplet]:
        rows = await db.fetchall(
            f"SELECT * FROM {cls.table_name} WHERE deleted_at IS NULL"
        )
        return cls._to_entities(rows)
    
    @classmethod
    async def list_for_workspace(cls, db, workspace_id: str) -> List[Droplet]:
        rows = await db.fetchall(
            f"SELECT * FROM {cls.table_name} WHERE workspace_id = ? AND deleted_at IS NULL",
            (workspace_id,)
        )
        return cls._to_entities(rows)
    
    @classmethod
    async def get_by_do_id(cls, db, do_droplet_id: int) -> Optional[Droplet]:
        """Get droplet by DigitalOcean ID."""
        row = await db.fetchone(
            f"SELECT * FROM {cls.table_name} WHERE do_droplet_id = ?",
            (do_droplet_id,)
        )
        return cls._to_entity(row)


# Module-level functions
get = DropletStore.get
create = DropletStore.create
update = DropletStore.update
delete = DropletStore.delete
soft_delete = DropletStore.soft_delete
list_active = DropletStore.list_active
list_for_workspace = DropletStore.list_for_workspace
get_by_do_id = DropletStore.get_by_do_id
