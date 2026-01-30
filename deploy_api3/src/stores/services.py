"""Service store - returns typed Service entities."""

from typing import List, Optional
from .base import BaseStore
from ..models import Service


class ServiceStore(BaseStore[Service]):
    table_name = "services"
    entity_class = Service
    
    @classmethod
    async def get_by_name(cls, db, project_id: str, name: str) -> Optional[Service]:
        results = await cls.find(
            db,
            where_clause="project_id = ? AND name = ? AND deleted_at IS NULL",
            params=(project_id, name),
            limit=1,
        )
        return results[0] if results else None
    
    @classmethod
    async def list_for_project(cls, db, project_id: str) -> List[Service]:
        return await cls.find(
            db,
            where_clause="project_id = ? AND deleted_at IS NULL",
            params=(project_id,),
        )
    
    @classmethod
    async def list_for_user(cls, db, workspace_id: str) -> List[Service]:
        """List all services for user (across all their projects)."""
        # Get via join with projects
        from . import projects
        user_projects = await projects.list_for_workspace(db, workspace_id)
        if not user_projects:
            return []
        
        project_ids = [p.id for p in user_projects]
        placeholders = ",".join(["?"] * len(project_ids))
        return await cls.find(
            db,
            where_clause=f"project_id IN ({placeholders}) AND deleted_at IS NULL",
            params=tuple(project_ids),
        )


# Module-level functions
get = ServiceStore.get
create = ServiceStore.create
update = ServiceStore.update
delete = ServiceStore.delete
soft_delete = ServiceStore.soft_delete
get_by_name = ServiceStore.get_by_name
list_for_project = ServiceStore.list_for_project
list_for_user = ServiceStore.list_for_user
