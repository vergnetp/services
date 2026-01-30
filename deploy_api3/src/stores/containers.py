"""
Container store - custom queries + entity re-exports.

Basic CRUD: Container.get(), Container.save(), Container.update(), Container.delete()
"""

from typing import List, Optional
from ...schemas import Container


# Re-export entity methods for backward compatibility
get = Container.get
create = Container.save
save = Container.save
update = Container.update
delete = Container.delete


async def upsert(db, data: dict) -> Container:
    """Upsert by container_name + droplet_id."""
    existing = await get_by_name_and_droplet(
        db, data.get('container_name'), data.get('droplet_id')
    )
    if existing:
        return await Container.update(db, existing.id, data)
    return await Container.save(db, data)


async def get_by_name_and_droplet(db, container_name: str, droplet_id: str) -> Optional[Container]:
    """Get container by name and droplet."""
    results = await Container.find(
        db,
        where="container_name = ? AND droplet_id = ?",
        params=(container_name, droplet_id),
        limit=1,
    )
    return results[0] if results else None


async def list_for_droplet(db, droplet_id: str) -> List[Container]:
    """List all containers on a droplet."""
    return await Container.find(
        db,
        where="droplet_id = ?",
        params=(droplet_id,),
    )


async def list_for_deployment(db, deployment_id: str) -> List[Container]:
    """List all containers for a deployment."""
    return await Container.find(
        db,
        where="deployment_id = ?",
        params=(deployment_id,),
    )


async def list_active(db) -> List[Container]:
    """List all non-deleted containers."""
    return await Container.find(
        db,
        where="status != 'deleted'",
    )


async def delete_by_droplet(db, droplet_id: str) -> None:
    """Delete all containers on a droplet."""
    await db.execute(
        "DELETE FROM containers WHERE droplet_id = ?",
        (droplet_id,)
    )


async def delete_by_droplet_and_name(db, droplet_id: str, container_name: str) -> None:
    """Delete specific container by droplet and name."""
    await db.execute(
        "DELETE FROM containers WHERE droplet_id = ? AND container_name = ?",
        (droplet_id, container_name)
    )


async def delete_by_service(db, service_id: str, env: str = None) -> None:
    """Delete all containers for a service's deployments."""
    from . import deployments
    deps = await deployments.list_for_service(db, service_id, env=env)
    for dep in deps:
        await db.execute(
            "DELETE FROM containers WHERE deployment_id = ?",
            (dep.id,)
        )
