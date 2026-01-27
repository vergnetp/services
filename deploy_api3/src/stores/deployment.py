"""
Deployment store - deployment history and versioning.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from .base import BaseStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DeploymentStore(BaseStore):
    """Store for deployment history."""
    
    table = "deployments"
    soft_delete = False
    
    # =========================================================================
    # Version management
    # =========================================================================
    
    async def get_next_version(
        self,
        db: Any,
        service_id: str,
        env: str,
    ) -> int:
        """Get next version number for service/env combination."""
        latest = await self.find_one(
            db,
            "[service_id] = ? AND [env] = ?",
            (service_id, env),
        )
        # Note: find_one uses ORDER BY created_at DESC by default in list()
        # Let's be explicit with a custom query
        results = await self.list(
            db,
            where_clause="[service_id] = ? AND [env] = ?",
            params=(service_id, env),
            order_by="[version] DESC",
            limit=1,
        )
        if results:
            return results[0].get("version", 0) + 1
        return 1
    
    async def get_latest(
        self,
        db: Any,
        service_id: str,
        env: str,
        status: str = "success",
    ) -> Optional[Dict[str, Any]]:
        """Get latest successful deployment for service/env."""
        results = await self.list(
            db,
            where_clause="[service_id] = ? AND [env] = ? AND [status] = ?",
            params=(service_id, env, status),
            order_by="[version] DESC",
            limit=1,
        )
        return results[0] if results else None
    
    async def get_by_version(
        self,
        db: Any,
        service_id: str,
        env: str,
        version: int,
    ) -> Optional[Dict[str, Any]]:
        """Get specific deployment by version number."""
        return await self.find_one(
            db,
            "[service_id] = ? AND [env] = ? AND [version] = ?",
            (service_id, env, version),
        )
    
    async def get_latest_before_version(
        self,
        db: Any,
        service_id: str,
        env: str,
        before_version: int,
        status: str = "success",
    ) -> Optional[Dict[str, Any]]:
        """Get latest successful deployment before a specific version."""
        results = await self.list(
            db,
            where_clause="[service_id] = ? AND [env] = ? AND [version] < ? AND [status] = ?",
            params=(service_id, env, before_version, status),
            order_by="[version] DESC",
            limit=1,
        )
        return results[0] if results else None
    
    # =========================================================================
    # History queries
    # =========================================================================
    
    async def list_for_service(
        self,
        db: Any,
        service_id: str,
        env: str = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """List deployment history for a service."""
        if env:
            where = "[service_id] = ? AND [env] = ?"
            params = (service_id, env)
        else:
            where = "[service_id] = ?"
            params = (service_id,)
        
        return await self.list(
            db,
            where_clause=where,
            params=params,
            order_by="[version] DESC",
            limit=limit,
        )
    
    async def list_recent(
        self,
        db: Any,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List recent deployments across all services."""
        return await self.list(
            db,
            order_by="[created_at] DESC",
            limit=limit,
        )
    
    # =========================================================================
    # Status updates
    # =========================================================================
    
    async def mark_in_progress(
        self,
        db: Any,
        deployment_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Mark deployment as in progress."""
        return await self.update(db, deployment_id, {
            "status": "in_progress",
        })
    
    async def mark_success(
        self,
        db: Any,
        deployment_id: str,
        log: str = None,
    ) -> Optional[Dict[str, Any]]:
        """Mark deployment as successful."""
        data = {"status": "success"}
        if log:
            data["log"] = log
        return await self.update(db, deployment_id, data)
    
    async def mark_failed(
        self,
        db: Any,
        deployment_id: str,
        error: str,
        log: str = None,
    ) -> Optional[Dict[str, Any]]:
        """Mark deployment as failed."""
        data = {
            "status": "failed",
            "error": error,
        }
        if log:
            data["log"] = log
        return await self.update(db, deployment_id, data)
    
    async def append_log(
        self,
        db: Any,
        deployment_id: str,
        message: str,
    ) -> Optional[Dict[str, Any]]:
        """Append to deployment log."""
        deployment = await self.get(db, deployment_id)
        if not deployment:
            return None
        
        current_log = deployment.get("log") or ""
        timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        new_log = f"{current_log}[{timestamp}] {message}\n"
        
        return await self.update(db, deployment_id, {"log": new_log})
    
    # =========================================================================
    # Additional methods for deploy/rollback
    # =========================================================================
    
    async def get_previous(
        self,
        db: Any,
        service_id: str,
        env: str,
        current_version: int,
        status: str = "success",
    ) -> Optional[Dict[str, Any]]:
        """Get previous successful deployment (for rollback)."""
        results = await self.list(
            db,
            where_clause="[service_id] = ? AND [env] = ? AND [version] < ? AND [status] = ?",
            params=(service_id, env, current_version, status),
            order_by="[version] DESC",
            limit=1,
        )
        return results[0] if results else None
    
    async def delete_by_service(
        self,
        db: Any,
        service_id: str,
        env: str = None,
    ) -> int:
        """Delete all deployments for a service (optionally filtered by env)."""
        service_deployments = await self.list_for_service(db, service_id, env=env, limit=10000)
        count = 0
        for dep in service_deployments:
            await self.delete(db, dep["id"])
            count += 1
        return count
