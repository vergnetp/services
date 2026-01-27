"""Deployment store."""

from typing import Dict, Any, List, Optional
from .base import BaseStore

class DeploymentStore(BaseStore):
    table_name = "deployment"
    
    @classmethod
    async def get_latest(cls, db, service_id: str, env: str, status: str = None) -> Optional[Dict[str, Any]]:
        sql = f"SELECT * FROM {cls.table_name} WHERE service_id = ? AND env = ?"
        params = [service_id, env]
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY version DESC LIMIT 1"
        row = await db.fetchone(sql, tuple(params))
        return dict(row) if row else None
    
    @classmethod
    async def get_previous(cls, db, service_id: str, env: str, before_version: int, status: str = None) -> Optional[Dict[str, Any]]:
        sql = f"SELECT * FROM {cls.table_name} WHERE service_id = ? AND env = ? AND version < ?"
        params = [service_id, env, before_version]
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY version DESC LIMIT 1"
        row = await db.fetchone(sql, tuple(params))
        return dict(row) if row else None
    
    @classmethod
    async def get_by_version(cls, db, service_id: str, env: str, version: int) -> Optional[Dict[str, Any]]:
        row = await db.fetchone(
            f"SELECT * FROM {cls.table_name} WHERE service_id = ? AND env = ? AND version = ?",
            (service_id, env, version))
        return dict(row) if row else None
    
    @classmethod
    async def list_for_service(cls, db, service_id: str, env: str = None, limit: int = 100) -> List[Dict[str, Any]]:
        if env:
            rows = await db.fetchall(
                f"SELECT * FROM {cls.table_name} WHERE service_id = ? AND env = ? ORDER BY version DESC LIMIT ?",
                (service_id, env, limit))
        else:
            rows = await db.fetchall(
                f"SELECT * FROM {cls.table_name} WHERE service_id = ? ORDER BY version DESC LIMIT ?",
                (service_id, limit))
        return [dict(r) for r in rows]
    
    @classmethod
    async def delete_by_service(cls, db, service_id: str, env: str = None):
        if env:
            await db.execute(f"DELETE FROM {cls.table_name} WHERE service_id = ? AND env = ?", (service_id, env))
        else:
            await db.execute(f"DELETE FROM {cls.table_name} WHERE service_id = ?", (service_id,))

get = DeploymentStore.get
create = DeploymentStore.create
update = DeploymentStore.update
delete = DeploymentStore.delete
get_latest = DeploymentStore.get_latest
get_previous = DeploymentStore.get_previous
get_by_version = DeploymentStore.get_by_version
list_for_service = DeploymentStore.list_for_service
delete_by_service = DeploymentStore.delete_by_service
