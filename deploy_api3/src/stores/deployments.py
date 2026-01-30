"""Deployment store - returns typed Deployment entities."""

from typing import List, Optional
from .base import BaseStore
from ..models import Deployment


class DeploymentStore(BaseStore[Deployment]):
    table_name = "deployments"
    entity_class = Deployment
    
    @classmethod
    async def get_latest(
        cls, db, service_id: str, env: str, status: str = None
    ) -> Optional[Deployment]:
        """Get most recent deployment for service/env."""
        where = "service_id = ? AND env = ?"
        params = [service_id, env]
        if status:
            where += " AND status = ?"
            params.append(status)
        
        results = await cls.find(
            db,
            where_clause=where,
            params=tuple(params),
            order_by="version DESC",
            limit=1,
        )
        return results[0] if results else None
    
    @classmethod
    async def get_previous(
        cls, db, service_id: str, env: str, before_version: int, status: str = None
    ) -> Optional[Deployment]:
        """Get deployment before a specific version (for rollback)."""
        where = "service_id = ? AND env = ? AND version < ?"
        params = [service_id, env, before_version]
        if status:
            where += " AND status = ?"
            params.append(status)
        
        results = await cls.find(
            db,
            where_clause=where,
            params=tuple(params),
            order_by="version DESC",
            limit=1,
        )
        return results[0] if results else None
    
    @classmethod
    async def get_by_version(
        cls, db, service_id: str, env: str, version: int
    ) -> Optional[Deployment]:
        """Get specific version of deployment."""
        results = await cls.find(
            db,
            where_clause="service_id = ? AND env = ? AND version = ?",
            params=(service_id, env, version),
            limit=1,
        )
        return results[0] if results else None
    
    @classmethod
    async def list_for_service(
        cls, db, service_id: str, env: str = None, limit: int = 100
    ) -> List[Deployment]:
        """List deployments for a service."""
        if env:
            return await cls.find(
                db,
                where_clause="service_id = ? AND env = ?",
                params=(service_id, env),
                order_by="version DESC",
                limit=limit,
            )
        else:
            return await cls.find(
                db,
                where_clause="service_id = ?",
                params=(service_id,),
                order_by="version DESC",
                limit=limit,
            )
    
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
