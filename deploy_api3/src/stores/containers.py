"""Container store."""

from typing import Dict, Any, List, Optional
from .base import BaseStore, _now_iso, _generate_id
import json

class ContainerStore(BaseStore):
    table_name = "container"
    
    @classmethod
    async def upsert(cls, db, data: Dict[str, Any]) -> Dict[str, Any]:
        """Upsert by container_name + droplet_id."""
        existing = await db.fetchone(
            f"SELECT * FROM {cls.table_name} WHERE container_name = ? AND droplet_id = ?",
            (data.get('container_name'), data.get('droplet_id')))
        if existing:
            return await cls.update(db, existing['id'], data)
        return await cls.create(db, data)
    
    @classmethod
    async def list_for_droplet(cls, db, droplet_id: str) -> List[Dict[str, Any]]:
        rows = await db.fetchall(f"SELECT * FROM {cls.table_name} WHERE droplet_id = ?", (droplet_id,))
        return [dict(r) for r in rows]
    
    @classmethod
    async def list_active(cls, db) -> List[Dict[str, Any]]:
        rows = await db.fetchall(f"SELECT * FROM {cls.table_name} WHERE status != 'deleted'")
        return [dict(r) for r in rows]
    
    @classmethod
    async def delete_by_droplet(cls, db, droplet_id: str):
        await db.execute(f"DELETE FROM {cls.table_name} WHERE droplet_id = ?", (droplet_id,))
    
    @classmethod
    async def delete_by_droplet_and_name(cls, db, droplet_id: str, container_name: str):
        await db.execute(f"DELETE FROM {cls.table_name} WHERE droplet_id = ? AND container_name = ?", (droplet_id, container_name))
    
    @classmethod
    async def delete_by_service(cls, db, service_id: str, env: str = None):
        # Containers don't have service_id directly, need to go through deployments
        pass

get = ContainerStore.get
create = ContainerStore.create
update = ContainerStore.update
delete = ContainerStore.delete
upsert = ContainerStore.upsert
list_for_droplet = ContainerStore.list_for_droplet
list_active = ContainerStore.list_active
delete_by_droplet = ContainerStore.delete_by_droplet
delete_by_droplet_and_name = ContainerStore.delete_by_droplet_and_name
delete_by_service = ContainerStore.delete_by_service
