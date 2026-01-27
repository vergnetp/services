"""
Project store - workspace-level grouping.
"""

from typing import Any, Dict, List, Optional
from .base import WorkspaceScopedStore


class ProjectStore(WorkspaceScopedStore):
    """Store for project entities."""
    
    table = "projects"
    soft_delete = True
    
    async def get_by_name(
        self,
        db: Any,
        workspace_id: str,
        name: str,
    ) -> Optional[Dict[str, Any]]:
        """Get project by name within workspace."""
        return await self.find_one(
            db,
            "[workspace_id] = ? AND [name] = ? AND [deleted_at] IS NULL",
            (workspace_id, name),
        )
    
    async def exists(
        self,
        db: Any,
        workspace_id: str,
        name: str,
    ) -> bool:
        """Check if project name exists in workspace."""
        project = await self.get_by_name(db, workspace_id, name)
        return project is not None
