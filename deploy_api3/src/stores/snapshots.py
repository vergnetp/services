# src/stores/snapshots.py
"""Snapshot store operations."""

from typing import List, Optional


async def list_for_user(db, user_id: str) -> List[dict]:
    """List all snapshots for a user."""
    return await db.find_entities(
        "snapshots",
        where_clause="[workspace_id] = ?",
        params=(user_id,),
        order_by="[created_at] DESC",
    )


async def get(db, snapshot_id: str) -> Optional[dict]:
    """Get snapshot by ID."""
    return await db.get_entity("snapshots", snapshot_id)


async def get_by_do_id(db, do_snapshot_id: str) -> Optional[dict]:
    """Get snapshot by DigitalOcean ID."""
    results = await db.find_entities(
        "snapshots",
        where_clause="[do_snapshot_id] = ?",
        params=(do_snapshot_id,),
        limit=1,
    )
    return results[0] if results else None


async def get_base(db, user_id: str) -> Optional[dict]:
    """Get the base snapshot for a user."""
    results = await db.find_entities(
        "snapshots",
        where_clause="[workspace_id] = ? AND [is_base] = 1",
        params=(user_id,),
        limit=1,
    )
    return results[0] if results else None


async def save(db, snapshot: dict) -> dict:
    """Save a snapshot."""
    return await db.save_entity("snapshots", snapshot)


async def delete(db, snapshot_id: str) -> bool:
    """Delete a snapshot."""
    return await db.delete_entity("snapshots", snapshot_id, permanent=True)