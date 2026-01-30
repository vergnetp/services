"""Project store - returns typed Project entities."""

from typing import List, Optional
from .base import BaseStore
from ..models import Project


class ProjectStore(BaseStore[Project]):
    table_name = "projects"
    entity_class = Project
    
    @classmethod
    async def get_by_name(cls, db, workspace_id: str, name: str) -> Optional[Project]:
        results = await cls.find(
            db,
            where_clause="workspace_id = ? AND name = ? AND deleted_at IS NULL",
            params=(workspace_id, name),
            limit=1,
        )
        return results[0] if results else None
    
    @classmethod
    async def list_for_workspace(cls, db, workspace_id: str) -> List[Project]:
        return await cls.find(
            db,
            where_clause="workspace_id = ? AND deleted_at IS NULL",
            params=(workspace_id,),
        )
    
    # Alias
    list_for_user = list_for_workspace


# Module-level functions
get = ProjectStore.get
create = ProjectStore.create
update = ProjectStore.update
delete = ProjectStore.delete
soft_delete = ProjectStore.soft_delete
get_by_name = ProjectStore.get_by_name
list_for_workspace = ProjectStore.list_for_workspace
list_for_user = ProjectStore.list_for_user
