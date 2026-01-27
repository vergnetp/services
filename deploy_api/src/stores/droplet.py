"""
Droplet store - server inventory with health monitoring.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from .base import WorkspaceScopedStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DropletStore(WorkspaceScopedStore):
    """Store for droplet entities with health monitoring."""
    
    table = "droplets"
    soft_delete = True
    
    # =========================================================================
    # Lookup helpers
    # =========================================================================
    
    async def get_by_do_id(
        self,
        db: Any,
        do_droplet_id: int,
    ) -> Optional[Dict[str, Any]]:
        """Get droplet by DigitalOcean ID."""
        return await self.find_one(
            db,
            "[do_droplet_id] = ? AND [deleted_at] IS NULL",
            (do_droplet_id,),
        )
    
    async def list_by_region(
        self,
        db: Any,
        workspace_id: str,
        region: str,
    ) -> List[Dict[str, Any]]:
        """List droplets in a specific region."""
        return await self.list(
            db,
            where_clause="[region] = ? AND [deleted_at] IS NULL",
            params=(region,),
            workspace_id=workspace_id,
        )
    
    async def list_active(
        self,
        db: Any,
        workspace_id: str,
    ) -> List[Dict[str, Any]]:
        """List active (non-deleted) droplets."""
        return await self.list(
            db,
            where_clause="[status] = ? AND [deleted_at] IS NULL",
            params=("active",),
            workspace_id=workspace_id,
        )
    
    # =========================================================================
    # Health monitoring
    # =========================================================================
    
    async def list_for_health_check(
        self,
        db: Any,
    ) -> List[Dict[str, Any]]:
        """List all active droplets needing health checks (all workspaces)."""
        return await self.list(
            db,
            where_clause="[status] = ? AND [deleted_at] IS NULL",
            params=("active",),
            limit=10000,  # All droplets
        )
    
    async def list_problematic(
        self,
        db: Any,
        workspace_id: str = None,
    ) -> List[Dict[str, Any]]:
        """List droplets flagged as problematic."""
        return await self.list(
            db,
            where_clause="[problematic_reason] IS NOT NULL AND [deleted_at] IS NULL",
            workspace_id=workspace_id,
        )
    
    async def mark_healthy(
        self,
        db: Any,
        droplet_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Mark droplet as healthy, reset failure count."""
        return await self.update(db, droplet_id, {
            "health_status": "healthy",
            "failure_count": 0,
            "last_checked": _now(),
        })
    
    async def record_failure(
        self,
        db: Any,
        droplet_id: str,
        reason: str,
    ) -> Optional[Dict[str, Any]]:
        """Record a health check failure."""
        droplet = await self.get(db, droplet_id)
        if not droplet:
            return None
        
        new_count = (droplet.get("failure_count") or 0) + 1
        
        return await self.update(db, droplet_id, {
            "health_status": "unhealthy",
            "failure_count": new_count,
            "last_checked": _now(),
            "last_failure_at": _now(),
            "last_failure_reason": reason,
        })
    
    async def flag_problematic(
        self,
        db: Any,
        droplet_id: str,
        reason: str,
    ) -> Optional[Dict[str, Any]]:
        """Flag droplet as problematic (needs manual intervention)."""
        return await self.update(db, droplet_id, {
            "health_status": "problematic",
            "problematic_reason": reason,
            "flagged_at": _now(),
        })
    
    async def clear_problematic(
        self,
        db: Any,
        droplet_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Clear problematic flag after manual intervention."""
        return await self.update(db, droplet_id, {
            "health_status": "healthy",
            "problematic_reason": None,
            "flagged_at": None,
            "failure_count": 0,
        })
    
    async def record_reboot(
        self,
        db: Any,
        droplet_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Record that droplet was rebooted."""
        return await self.update(db, droplet_id, {
            "last_reboot_at": _now(),
        })
    
    async def update_health(
        self,
        db: Any,
        droplet_id: str,
        status: str,
    ) -> Optional[Dict[str, Any]]:
        """Update health status."""
        return await self.update(db, droplet_id, {
            "health_status": status,
            "last_checked": _now(),
        })
    
    async def list_all(
        self,
        db: Any,
        workspace_id: str = None,
    ) -> List[Dict[str, Any]]:
        """List all droplets (including deleted if no workspace filter)."""
        if workspace_id:
            return await self.list(
                db,
                where_clause="[deleted_at] IS NULL",
                workspace_id=workspace_id,
            )
        return await self.list(db, limit=10000)
