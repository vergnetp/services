"""Deployment store - returns typed Deployment entities."""

from typing import List, Optional
from .base import BaseStore
from _gen.entities import Deployment


class DeploymentStore(BaseStore[Deployment]):
    table_name = "deployments"  # Note: plural to match schema
    entity_class = Deployment
    
    @classmethod
    async def get_latest(
        cls, db, service_id: str, env: str, status: str = None
    ) -> Optional[Deployment]:
        """Get most recent deployment for service/env."""
        sql = f"SELECT * FROM {cls.table_name} WHERE service_id = ? AND env = ?"
        params = [service_id, env]
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY version DESC LIMIT 1"
        row = await db.fetchone(sql, tuple(params))
        return cls._to_entity(row)
    
    @classmethod
    async def get_previous(
        cls, db, service_id: str, env: str, before_version: int, status: str = None
    ) -> Optional[Deployment]:
        """Get deployment before a specific version (for rollback)."""
        sql = f"SELECT * FROM {cls.table_name} WHERE service_id = ? AND env = ? AND version < ?"
        params = [service_id, env, before_version]
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY version DESC LIMIT 1"
        row = await db.fetchone(sql, tuple(params))
        return cls._to_entity(row)
    
    @classmethod
    async def get_by_version(
        cls, db, service_id: str, env: str, version: int
    ) -> Optional[Deployment]:
        """Get specific version of deployment."""
        row = await db.fetchone(
            f"SELECT * FROM {cls.table_name} WHERE service_id = ? AND env = ? AND version = ?",
            (service_id, env, version)
        )
        return cls._to_entity(row)
    
    @classmethod
    async def list_for_service(
        cls, db, service_id: str, env: str = None, limit: int = 100
    ) -> List[Deployment]:
        """List deployments for a service."""
        if env:
            rows = await db.fetchall(
                f"SELECT * FROM {cls.table_name} WHERE service_id = ? AND env = ? ORDER BY version DESC LIMIT ?",
                (service_id, env, limit)
            )
        else:
            rows = await db.fetchall(
                f"SELECT * FROM {cls.table_name} WHERE service_id = ? ORDER BY version DESC LIMIT ?",
                (service_id, limit)
            )
        return cls._to_entities(rows)
    
    @classmethod
    async def delete_by_service(cls, db, service_id: str, env: str = None) -> None:
        """Delete all deployments for a service."""
        if env:
            await db.execute(
                f"DELETE FROM {cls.table_name} WHERE service_id = ? AND env = ?",
                (service_id, env)
            )
        else:
            await db.execute(
                f"DELETE FROM {cls.table_name} WHERE service_id = ?",
                (service_id,)
            )


# Module-level functions
get = DeploymentStore.get
create = DeploymentStore.create
update = DeploymentStore.update
delete = DeploymentStore.delete
get_latest = DeploymentStore.get_latest
get_previous = DeploymentStore.get_previous
get_by_version = DeploymentStore.get_by_version
list_for_service = DeploymentStore.list_for_service
delete_by_service = DeploymentStore.delete_by_service
