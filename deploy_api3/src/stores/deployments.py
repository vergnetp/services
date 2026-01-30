"""
Deployment store - custom queries + entity re-exports.

Basic CRUD: Deployment.get(), Deployment.save(), Deployment.update(), Deployment.delete()
"""

from typing import List, Optional
from ...schemas import Deployment


# Re-export entity methods for backward compatibility
get = Deployment.get
create = Deployment.save
save = Deployment.save
update = Deployment.update
delete = Deployment.delete


async def get_latest(db, service_id: str, env: str, status: str = None) -> Optional[Deployment]:
    """Get most recent deployment for service/env."""
    where = "service_id = ? AND env = ?"
    params = [service_id, env]
    if status:
        where += " AND status = ?"
        params.append(status)
    
    results = await Deployment.find(
        db,
        where=where,
        params=tuple(params),
        order_by="version DESC",
        limit=1,
    )
    return results[0] if results else None


async def get_previous(db, service_id: str, env: str, before_version: int, status: str = None) -> Optional[Deployment]:
    """Get deployment before a specific version (for rollback)."""
    where = "service_id = ? AND env = ? AND version < ?"
    params = [service_id, env, before_version]
    if status:
        where += " AND status = ?"
        params.append(status)
    
    results = await Deployment.find(
        db,
        where=where,
        params=tuple(params),
        order_by="version DESC",
        limit=1,
    )
    return results[0] if results else None


async def get_by_version(db, service_id: str, env: str, version: int) -> Optional[Deployment]:
    """Get specific version of deployment."""
    results = await Deployment.find(
        db,
        where="service_id = ? AND env = ? AND version = ?",
        params=(service_id, env, version),
        limit=1,
    )
    return results[0] if results else None


async def list_for_service(db, service_id: str, env: str = None, limit: int = 100) -> List[Deployment]:
    """List deployments for a service."""
    if env:
        where = "service_id = ? AND env = ?"
        params = (service_id, env)
    else:
        where = "service_id = ?"
        params = (service_id,)
    
    return await Deployment.find(
        db,
        where=where,
        params=params,
        order_by="version DESC",
        limit=limit,
    )


async def delete_by_service(db, service_id: str, env: str = None) -> None:
    """Delete all deployments for a service."""
    if env:
        await db.execute(
            "DELETE FROM deployments WHERE service_id = ? AND env = ?",
            (service_id, env)
        )
    else:
        await db.execute(
            "DELETE FROM deployments WHERE service_id = ?",
            (service_id,)
        )
