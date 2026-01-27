"""
Container store - running containers with health monitoring.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from .base import BaseStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ContainerStore(BaseStore):
    """Store for container entities with health monitoring."""
    
    table = "containers"
    soft_delete = False
    
    # =========================================================================
    # Lookup helpers
    # =========================================================================
    
    async def get_by_name(
        self,
        db: Any,
        droplet_id: str,
        container_name: str,
    ) -> Optional[Dict[str, Any]]:
        """Get container by name on a specific droplet."""
        return await self.find_one(
            db,
            "[droplet_id] = ? AND [container_name] = ?",
            (droplet_id, container_name),
        )
    
    async def delete_by_droplet(
        self,
        db: Any,
        droplet_id: str,
    ) -> int:
        """Delete all containers for a droplet."""
        containers = await self.list_for_droplet(db, droplet_id)
        count = 0
        for c in containers:
            await self.delete(db, c["id"])
            count += 1
        return count
    
    async def delete_by_droplet_and_name(
        self,
        db: Any,
        droplet_id: str,
        container_name: str,
    ) -> bool:
        """Delete container by droplet and name."""
        container = await self.get_by_name(db, droplet_id, container_name)
        if container:
            await self.delete(db, container["id"])
            return True
        return False
    
    async def list_for_droplet(
        self,
        db: Any,
        droplet_id: str,
    ) -> List[Dict[str, Any]]:
        """List all containers on a droplet."""
        return await self.list(
            db,
            where_clause="[droplet_id] = ?",
            params=(droplet_id,),
            order_by="[created_at] DESC",
        )
    
    async def list_for_deployment(
        self,
        db: Any,
        deployment_id: str,
    ) -> List[Dict[str, Any]]:
        """List all containers for a deployment."""
        return await self.list(
            db,
            where_clause="[deployment_id] = ?",
            params=(deployment_id,),
        )
    
    async def list_running(
        self,
        db: Any,
        droplet_id: str = None,
    ) -> List[Dict[str, Any]]:
        """List running containers, optionally filtered by droplet."""
        if droplet_id:
            where = "[status] = ? AND [droplet_id] = ?"
            params = ("running", droplet_id)
        else:
            where = "[status] = ?"
            params = ("running",)
        
        return await self.list(
            db,
            where_clause=where,
            params=params,
        )
    
    # =========================================================================
    # Health monitoring
    # =========================================================================
    
    async def list_for_health_check(
        self,
        db: Any,
    ) -> List[Dict[str, Any]]:
        """List all running containers needing health checks."""
        return await self.list(
            db,
            where_clause="[status] = ?",
            params=("running",),
            limit=10000,
        )
    
    async def list_unhealthy(
        self,
        db: Any,
        droplet_id: str = None,
    ) -> List[Dict[str, Any]]:
        """List unhealthy containers."""
        if droplet_id:
            where = "[health_status] = ? AND [droplet_id] = ?"
            params = ("unhealthy", droplet_id)
        else:
            where = "[health_status] = ?"
            params = ("unhealthy",)
        
        return await self.list(db, where_clause=where, params=params)
    
    async def mark_healthy(
        self,
        db: Any,
        container_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Mark container as healthy, reset failure count."""
        return await self.update(db, container_id, {
            "health_status": "healthy",
            "failure_count": 0,
            "last_healthy_at": _now(),
            "last_checked": _now(),
        })
    
    async def record_failure(
        self,
        db: Any,
        container_id: str,
        reason: str,
    ) -> Optional[Dict[str, Any]]:
        """Record a health check failure."""
        container = await self.get(db, container_id)
        if not container:
            return None
        
        new_count = (container.get("failure_count") or 0) + 1
        
        return await self.update(db, container_id, {
            "health_status": "unhealthy",
            "failure_count": new_count,
            "last_checked": _now(),
            "last_failure_at": _now(),
            "last_failure_reason": reason,
        })
    
    async def record_restart(
        self,
        db: Any,
        container_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Record that container was restarted."""
        return await self.update(db, container_id, {
            "last_restart_at": _now(),
        })
    
    # =========================================================================
    # Status updates
    # =========================================================================
    
    async def mark_running(
        self,
        db: Any,
        container_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Mark container as running."""
        return await self.update(db, container_id, {
            "status": "running",
            "health_status": "unknown",
        })
    
    async def mark_stopped(
        self,
        db: Any,
        container_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Mark container as stopped."""
        return await self.update(db, container_id, {
            "status": "stopped",
        })
    
    async def mark_failed(
        self,
        db: Any,
        container_id: str,
        error: str,
    ) -> Optional[Dict[str, Any]]:
        """Mark container as failed with error."""
        return await self.update(db, container_id, {
            "status": "failed",
            "error": error,
        })
    
    async def update_health(
        self,
        db: Any,
        container_id: str,
        status: str,
    ) -> Optional[Dict[str, Any]]:
        """Update health status."""
        return await self.update(db, container_id, {
            "health_status": status,
            "last_checked": _now(),
        })
    
    async def list_all(
        self,
        db: Any,
        workspace_id: str = None,
    ) -> List[Dict[str, Any]]:
        """List all containers, optionally filtered by workspace via droplets."""
        # Note: containers don't have workspace_id directly, 
        # filtering by workspace requires join logic handled at caller
        return await self.list(db, limit=10000)
    
    # =========================================================================
    # Upsert and bulk delete
    # =========================================================================
    
    async def upsert(
        self,
        db: Any,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Create or update container by droplet_id + container_name.
        """
        droplet_id = data.get("droplet_id")
        container_name = data.get("container_name")
        
        if not droplet_id or not container_name:
            raise ValueError("droplet_id and container_name are required")
        
        existing = await self.get_by_name(db, droplet_id, container_name)
        
        if existing:
            return await self.update(db, existing["id"], data)
        else:
            return await self.create(db, data)
    
    async def delete_by_service(
        self,
        db: Any,
        service_id: str,
        env: str = None,
    ) -> int:
        """
        Delete all containers for a service (via deployment_id).
        Optionally filter by environment.
        """
        # Get all deployments for this service
        from .deployment import DeploymentStore
        deployment_store = DeploymentStore()
        
        service_deployments = await deployment_store.list_for_service(
            db, service_id, env=env, limit=10000
        )
        
        count = 0
        for dep in service_deployments:
            containers = await self.list_for_deployment(db, dep["id"])
            for c in containers:
                await self.delete(db, c["id"])
                count += 1
        
        return count
