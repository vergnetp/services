"""
Service store - custom queries + entity re-exports.

Basic CRUD: Service.get(), Service.save(), Service.update(), Service.delete()
"""

from typing import List, Optional
from ...schemas import Service


# Re-export entity methods for backward compatibility
get = Service.get
create = Service.save
save = Service.save
update = Service.update
delete = Service.delete
soft_delete = Service.soft_delete


async def get_by_name(db, project_id: str, name: str) -> Optional[Service]:
    """Get service by project and name."""
    results = await Service.find(
        db,
        where="project_id = ? AND name = ? AND deleted_at IS NULL",
        params=(project_id, name),
        limit=1,
    )
    return results[0] if results else None


async def list_for_project(db, project_id: str) -> List[Service]:
    """List all services in a project."""
    return await Service.find(
        db,
        where="project_id = ? AND deleted_at IS NULL",
        params=(project_id,),
    )


async def list_for_user(db, workspace_id: str) -> List[Service]:
    """List all services for user (across all their projects)."""
    from . import projects
    user_projects = await projects.list_for_workspace(db, workspace_id)
    if not user_projects:
        return []
    
    project_ids = [p.id for p in user_projects]
    placeholders = ",".join(["?"] * len(project_ids))
    return await Service.find(
        db,
        where=f"project_id IN ({placeholders}) AND deleted_at IS NULL",
        params=tuple(project_ids),
    )
