"""Container store - returns typed Container entities."""

from typing import List, Optional
from .base import BaseStore, _now_iso, _generate_id
from _gen.entities import Container
import json


class ContainerStore(BaseStore[Container]):
    table_name = "containers"  # Note: plural to match schema
    entity_class = Container
    
    @classmethod
    async def upsert(cls, db, data: dict) -> Container:
        """Upsert by container_name + droplet_id."""
        existing = await db.fetchone(
            f"SELECT * FROM {cls.table_name} WHERE container_name = ? AND droplet_id = ?",
            (data.get('container_name'), data.get('droplet_id'))
        )
        if existing:
            return await cls.update(db, existing['id'], data)
        return await cls.create(db, data)
    
    @classmethod
    async def get_by_name_and_droplet(
        cls, db, container_name: str, droplet_id: str
    ) -> Optional[Container]:
        """Get container by name and droplet."""
        row = await db.fetchone(
            f"SELECT * FROM {cls.table_name} WHERE container_name = ? AND droplet_id = ?",
            (container_name, droplet_id)
        )
        return cls._to_entity(row)
    
    @classmethod
    async def list_for_droplet(cls, db, droplet_id: str) -> List[Container]:
        """List all containers on a droplet."""
        rows = await db.fetchall(
            f"SELECT * FROM {cls.table_name} WHERE droplet_id = ?",
            (droplet_id,)
        )
        return cls._to_entities(rows)
    
    @classmethod
    async def list_for_deployment(cls, db, deployment_id: str) -> List[Container]:
        """List all containers for a deployment."""
        rows = await db.fetchall(
            f"SELECT * FROM {cls.table_name} WHERE deployment_id = ?",
            (deployment_id,)
        )
        return cls._to_entities(rows)
    
    @classmethod
    async def list_active(cls, db) -> List[Container]:
        """List all non-deleted containers."""
        rows = await db.fetchall(
            f"SELECT * FROM {cls.table_name} WHERE status != 'deleted'"
        )
        return cls._to_entities(rows)
    
    @classmethod
    async def delete_by_droplet(cls, db, droplet_id: str) -> None:
        """Delete all containers on a droplet."""
        await db.execute(
            f"DELETE FROM {cls.table_name} WHERE droplet_id = ?",
            (droplet_id,)
        )
    
    @classmethod
    async def delete_by_droplet_and_name(
        cls, db, droplet_id: str, container_name: str
    ) -> None:
        """Delete specific container by droplet and name."""
        await db.execute(
            f"DELETE FROM {cls.table_name} WHERE droplet_id = ? AND container_name = ?",
            (droplet_id, container_name)
        )


# Module-level functions
get = ContainerStore.get
create = ContainerStore.create
update = ContainerStore.update
delete = ContainerStore.delete
upsert = ContainerStore.upsert
get_by_name_and_droplet = ContainerStore.get_by_name_and_droplet
list_for_droplet = ContainerStore.list_for_droplet
list_for_deployment = ContainerStore.list_for_deployment
list_active = ContainerStore.list_active
delete_by_droplet = ContainerStore.delete_by_droplet
delete_by_droplet_and_name = ContainerStore.delete_by_droplet_and_name
