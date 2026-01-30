"""
Project store - custom queries + entity re-exports.

Basic CRUD: Project.get(), Project.save(), Project.update(), Project.delete()
"""

from typing import List, Optional
from ...schemas import Project


# Re-export entity methods for backward compatibility
get = Project.get
create = Project.save
save = Project.save
update = Project.update
delete = Project.delete
soft_delete = Project.soft_delete


async def get_by_name(db, workspace_id: str, name: str) -> Optional[Project]:
    """Get project by workspace and name."""
    results = await Project.find(
        db,
        where="workspace_id = ? AND name = ? AND deleted_at IS NULL",
        params=(workspace_id, name),
        limit=1,
    )
    return results[0] if results else None


async def list_for_workspace(db, workspace_id: str) -> List[Project]:
    """List all projects in a workspace."""
    return await Project.find(
        db,
        where="workspace_id = ? AND deleted_at IS NULL",
        params=(workspace_id,),
    )


# Alias
list_for_user = list_for_workspace
