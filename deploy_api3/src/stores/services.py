"""Service store - returns typed Service entities."""

from typing import List, Optional
from .base import BaseStore
from _gen.entities import Service


class ServiceStore(BaseStore[Service]):
    table_name = "services"  # Note: plural to match schema
    entity_class = Service
    
    @classmethod
    async def get_by_name(cls, db, project_id: str, name: str) -> Optional[Service]:
        row = await db.fetchone(
            f"SELECT * FROM {cls.table_name} WHERE project_id = ? AND name = ? AND deleted_at IS NULL",
            (project_id, name)
        )
        return cls._to_entity(row)
    
    @classmethod
    async def list_for_project(cls, db, project_id: str) -> List[Service]:
        rows = await db.fetchall(
            f"SELECT * FROM {cls.table_name} WHERE project_id = ? AND deleted_at IS NULL",
            (project_id,)
        )
        return cls._to_entities(rows)


# Module-level functions
get = ServiceStore.get
create = ServiceStore.create
update = ServiceStore.update
delete = ServiceStore.delete
soft_delete = ServiceStore.soft_delete
get_by_name = ServiceStore.get_by_name
list_for_project = ServiceStore.list_for_project
