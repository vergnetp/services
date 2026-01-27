"""
Service store - deployable units within projects.
"""

from typing import Any, Dict, List, Optional
from .base import BaseStore


class ServiceStore(BaseStore):
    """Store for service entities."""
    
    table = "services"
    soft_delete = True
    
    async def list_for_project(
        self,
        db: Any,
        project_id: str,
        include_deleted: bool = False,
    ) -> List[Dict[str, Any]]:
        """List all services for a project."""
        where = "[project_id] = ?"
        if not include_deleted:
            where += " AND [deleted_at] IS NULL"
        return await self.list(
            db,
            where_clause=where,
            params=(project_id,),
            order_by="[name] ASC",
        )
    
    async def get_by_name(
        self,
        db: Any,
        project_id: str,
        name: str,
    ) -> Optional[Dict[str, Any]]:
        """Get service by name within project."""
        return await self.find_one(
            db,
            "[project_id] = ? AND [name] = ? AND [deleted_at] IS NULL",
            (project_id, name),
        )
    
    async def list_by_type(
        self,
        db: Any,
        project_id: str,
        service_type: str,
    ) -> List[Dict[str, Any]]:
        """List services of a specific type within project."""
        return await self.list(
            db,
            where_clause="[project_id] = ? AND [service_type] = ? AND [deleted_at] IS NULL",
            params=(project_id, service_type),
        )
    
    async def list_stateful_services(
        self,
        db: Any,
        project_id: str,
    ) -> List[Dict[str, Any]]:
        """List stateful services (redis, postgres, etc.) for env injection."""
        return await self.list(
            db,
            where_clause="[project_id] = ? AND [service_type] IN (?, ?, ?, ?) AND [deleted_at] IS NULL",
            params=(project_id, "redis", "postgres", "mysql", "mongodb"),
        )
