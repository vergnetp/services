"""Container store - returns typed Container entities."""

from typing import List, Optional
from .base import BaseStore
from ..models import Container


class ContainerStore(BaseStore[Container]):
    table_name = "containers"
    entity_class = Container
    
    @classmethod
    async def upsert(cls, db, data: dict) -> Container:
        """Upsert by container_name + droplet_id."""
        existing = await cls.get_by_name_and_droplet(
            db, data.get('container_name'), data.get('droplet_id')
        )
        if existing:
            return await cls.update(db, existing.id, data)
        return await cls.create(db, data)
    
    @classmethod
    async def get_by_name_and_droplet(
        cls, db, container_name: str, droplet_id: str
    ) -> Optional[Container]:
        """Get container by name and droplet."""
        results = await cls.find(
            db,
            where_clause="container_name = ? AND droplet_id = ?",
            params=(container_name, droplet_id),
            limit=1,
        )
        return results[0] if results else None
    
    @classmethod
    async def list_for_droplet(cls, db, droplet_id: str) -> List[Container]:
        """List all containers on a droplet."""
        return await cls.find(
            db,
            where_clause="droplet_id = ?",
            params=(droplet_id,),
        )
    
    @classmethod
    async def list_for_deployment(cls, db, deployment_id: str) -> List[Container]:
        """List all containers for a deployment."""
        return await cls.find(
            db,
            where_clause="deployment_id = ?",
            params=(deployment_id,),
        )
    
    @classmethod
    async def list_active(cls, db) -> List[Container]:
        """List all non-deleted containers."""
        return await cls.find(
            db,
            where_clause="status != 'deleted'",
        )
    
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
    
    @classmethod
    async def delete_by_service(cls, db, service_id: str, env: str = None) -> None:
        """Delete all containers for a service's deployments."""
        from . import deployments
        deps = await deployments.list_for_service(db, service_id, env=env)
        for dep in deps:
            await db.execute(
                f"DELETE FROM {cls.table_name} WHERE deployment_id = ?",
                (dep.id,)
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
delete_by_service = ContainerStore.delete_by_service
