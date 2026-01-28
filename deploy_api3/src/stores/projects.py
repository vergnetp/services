"""Project store - returns typed Project entities."""

from typing import List, Optional
from .base import BaseStore
from _gen.entities import Project


class ProjectStore(BaseStore[Project]):
    table_name = "projects"  # Note: plural to match schema
    entity_class = Project
    
    @classmethod
    async def get_by_name(cls, db, workspace_id: str, name: str) -> Optional[Project]:
        row = await db.fetchone(
            f"SELECT * FROM {cls.table_name} WHERE workspace_id = ? AND name = ? AND deleted_at IS NULL",
            (workspace_id, name)
        )
        return cls._to_entity(row)
    
    @classmethod
    async def list_for_workspace(cls, db, workspace_id: str) -> List[Project]:
        rows = await db.fetchall(
            f"SELECT * FROM {cls.table_name} WHERE workspace_id = ? AND deleted_at IS NULL",
            (workspace_id,)
        )
        return cls._to_entities(rows)


# Module-level functions for convenience
get = ProjectStore.get
create = ProjectStore.create
update = ProjectStore.update
delete = ProjectStore.delete
soft_delete = ProjectStore.soft_delete
get_by_name = ProjectStore.get_by_name
list_for_workspace = ProjectStore.list_for_workspace
