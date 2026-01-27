"""
Snapshot store - cached snapshot registry.
"""

from typing import Any, Dict, List, Optional
from .base import WorkspaceScopedStore


class SnapshotStore(WorkspaceScopedStore):
    """Store for snapshot entities."""
    
    table = "snapshots"
    soft_delete = False
    
    async def get_by_do_id(
        self,
        db: Any,
        do_snapshot_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Get snapshot by DigitalOcean ID."""
        return await self.find_one(
            db,
            "[do_snapshot_id] = ?",
            (do_snapshot_id,),
        )
    
    async def get_by_name(
        self,
        db: Any,
        workspace_id: str,
        name: str,
    ) -> Optional[Dict[str, Any]]:
        """Get snapshot by name within workspace."""
        return await self.find_one(
            db,
            "[workspace_id] = ? AND [name] = ?",
            (workspace_id, name),
        )
    
    async def list_for_region(
        self,
        db: Any,
        workspace_id: str,
        region: str,
    ) -> List[Dict[str, Any]]:
        """List snapshots available in a region."""
        return await self.list(
            db,
            where_clause="[region] = ?",
            params=(region,),
            workspace_id=workspace_id,
            order_by="[created_at] DESC",
        )
    
    async def get_base_snapshot(
        self,
        db: Any,
        workspace_id: str,
        region: str,
    ) -> Optional[Dict[str, Any]]:
        """Get the base snapshot for a region."""
        return await self.find_one(
            db,
            "[workspace_id] = ? AND [region] = ? AND [is_base] = ?",
            (workspace_id, region, True),
        )
    
    async def get_latest_for_region(
        self,
        db: Any,
        workspace_id: str,
        region: str,
    ) -> Optional[Dict[str, Any]]:
        """Get the most recent snapshot for a region."""
        results = await self.list(
            db,
            where_clause="[region] = ?",
            params=(region,),
            workspace_id=workspace_id,
            order_by="[created_at] DESC",
            limit=1,
        )
        return results[0] if results else None
    
    async def mark_as_base(
        self,
        db: Any,
        snapshot_id: str,
        workspace_id: str,
        region: str,
    ) -> Optional[Dict[str, Any]]:
        """Mark snapshot as base, clearing any existing base for the region."""
        # Clear existing base for this region
        existing_bases = await self.list(
            db,
            where_clause="[region] = ? AND [is_base] = ?",
            params=(region, True),
            workspace_id=workspace_id,
        )
        for existing in existing_bases:
            await self.update(db, existing["id"], {"is_base": False})
        
        # Set new base
        return await self.update(db, snapshot_id, {"is_base": True})
