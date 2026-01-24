"""
Business logic stores for deploy_api.

Normalized Schema:
- Project: container for services
- Service: deployable unit (FK project_id)
- Droplet: server inventory
- ServiceDroplet: junction - which services on which droplets
- Deployment: deployment history (FK service_id, droplet_ids)
- DeployConfig: saved settings (FK service_id)
- Credential: encrypted secrets (FK project_id)
"""

import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from shared_libs.backend.app_kernel.observability import get_logger
from .._gen.crud import EntityCRUD


logger = get_logger()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# =============================================================================
# User Lookup Helper
# =============================================================================

class UserLookup:
    """Resolve user IDs to display names from auth_users table."""
    
    _cache: Dict[str, str] = {}
    
    @classmethod
    async def get_display_name(cls, db, user_id: str) -> Optional[str]:
        if not user_id:
            return None
        if user_id in cls._cache:
            return cls._cache[user_id]
        try:
            # Use entity-based API (same as other stores)
            result = await db.get_entity("auth_users", user_id)
            if result:
                # Prefer name, fall back to email
                display = result.get("name") or result.get("email") or user_id
                cls._cache[user_id] = display
                return display
        except Exception:
            pass
        return None
    
    @classmethod
    async def enrich_deployments(cls, db, records: List["Deployment"]) -> List["Deployment"]:
        for record in records:
            if record.triggered_by and not record._data.get("_triggered_by_name"):
                email = await cls.get_display_name(db, record.triggered_by)
                if email:
                    record._data["_triggered_by_name"] = email
        return records


# =============================================================================
# Project Store
# =============================================================================

class ProjectStore:
    """Project CRUD."""
    
    def __init__(self, db):
        self.db = db
        self._crud = EntityCRUD("projects")
    
    async def create(
        self,
        workspace_id: str,
        name: str,
        description: str = None,
        docker_hub_user: str = None,
        created_by: str = None,
    ) -> Dict[str, Any]:
        return await self._crud.create(self.db, {
            "workspace_id": workspace_id,
            "name": name,
            "description": description,
            "docker_hub_user": docker_hub_user,
            "created_by": created_by,
        })
    
    async def get(self, project_id: str) -> Optional[Dict[str, Any]]:
        return await self._crud.get(self.db, project_id)
    
    async def get_by_name(self, workspace_id: str, name: str) -> Optional[Dict[str, Any]]:
        return await self._crud.find_one(
            self.db,
            "[workspace_id] = ? AND [name] = ?",
            (workspace_id, name),
        )
    
    async def get_or_create(
        self,
        workspace_id: str,
        name: str,
        created_by: str = None,
    ) -> Dict[str, Any]:
        existing = await self.get_by_name(workspace_id, name)
        if existing:
            return existing
        return await self.create(workspace_id, name, created_by=created_by)
    
    async def list(self, workspace_id: str) -> List[Dict[str, Any]]:
        return await self._crud.list(
            self.db,
            workspace_id=workspace_id,
            order_by="[name] ASC",
        )
    
    async def update(self, project_id: str, **updates) -> Optional[Dict[str, Any]]:
        return await self._crud.update(self.db, project_id, updates)
    
    async def delete(self, project_id: str) -> bool:
        return await self._crud.delete(self.db, project_id, permanent=True)


# =============================================================================
# Service Store
# =============================================================================

class ServiceStore:
    """Service CRUD - deployable units within projects."""
    
    def __init__(self, db):
        self.db = db
        self._crud = EntityCRUD("services")
    
    async def create(
        self,
        workspace_id: str,
        project_id: str,
        name: str,
        port: int = 8000,
        health_endpoint: str = "/health",
        description: str = None,
        is_stateful: bool = False,
        service_type: str = None,
    ) -> Dict[str, Any]:
        return await self._crud.create(self.db, {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "name": name,
            "port": port,
            "health_endpoint": health_endpoint,
            "description": description,
            "is_stateful": is_stateful,
            "service_type": service_type or ("stateful" if is_stateful else "app"),
        })
    
    async def get(self, service_id: str) -> Optional[Dict[str, Any]]:
        return await self._crud.get(self.db, service_id)
    
    async def get_by_name(self, project_id: str, name: str) -> Optional[Dict[str, Any]]:
        return await self._crud.find_one(
            self.db,
            "[project_id] = ? AND [name] = ?",
            (project_id, name),
        )
    
    async def get_or_create(
        self,
        workspace_id: str,
        project_id: str,
        name: str,
        port: int = 8000,
        is_stateful: bool = False,
        service_type: str = None,
    ) -> Dict[str, Any]:
        existing = await self.get_by_name(project_id, name)
        if existing:
            # Update stateful fields if changed
            if is_stateful and not existing.get("is_stateful"):
                await self.update(existing["id"], is_stateful=True, service_type=service_type)
                existing["is_stateful"] = True
                existing["service_type"] = service_type
            return existing
        return await self.create(workspace_id, project_id, name, port, is_stateful=is_stateful, service_type=service_type)
    
    async def list_for_project(self, project_id: str) -> List[Dict[str, Any]]:
        return await self._crud.list(
            self.db,
            where_clause="[project_id] = ?",
            params=(project_id,),
            order_by="[name] ASC",
        )
    
    async def list_stateful_for_project(self, project_id: str) -> List[Dict[str, Any]]:
        """List all stateful services (redis, postgres, etc.) for a project."""
        return await self._crud.list(
            self.db,
            where_clause="[project_id] = ? AND [is_stateful] = 1",
            params=(project_id,),
            order_by="[name] ASC",
        )
    
    async def list(self, workspace_id: str) -> List[Dict[str, Any]]:
        return await self._crud.list(
            self.db,
            workspace_id=workspace_id,
            order_by="[name] ASC",
        )
    
    async def update(self, service_id: str, **updates) -> Optional[Dict[str, Any]]:
        return await self._crud.update(self.db, service_id, updates)
    
    async def delete(self, service_id: str) -> bool:
        return await self._crud.delete(self.db, service_id, permanent=True)


# =============================================================================
# Droplet Store
# =============================================================================

class DropletStore:
    """Server inventory - tracks DO droplets."""
    
    def __init__(self, db):
        self.db = db
        self._crud = EntityCRUD("droplets")
    
    async def create(
        self,
        workspace_id: str,
        do_droplet_id: str,
        name: str = None,
        ip: str = None,
        region: str = None,
        size: str = None,
        snapshot_id: str = None,
        created_by: str = None,
    ) -> Dict[str, Any]:
        return await self._crud.create(self.db, {
            "workspace_id": workspace_id,
            "do_droplet_id": do_droplet_id,
            "name": name,
            "ip": ip,
            "region": region,
            "size": size,
            "status": "active",
            "snapshot_id": snapshot_id,
            "created_by": created_by,
        })
    
    async def get(self, droplet_id: str) -> Optional[Dict[str, Any]]:
        return await self._crud.get(self.db, droplet_id)
    
    async def get_by_do_id(self, workspace_id: str, do_droplet_id: str) -> Optional[Dict[str, Any]]:
        return await self._crud.find_one(
            self.db,
            "[workspace_id] = ? AND [do_droplet_id] = ?",
            (workspace_id, do_droplet_id),
        )
    
    async def get_by_ip(self, workspace_id: str, ip: str) -> Optional[Dict[str, Any]]:
        return await self._crud.find_one(
            self.db,
            "[workspace_id] = ? AND [ip] = ?",
            (workspace_id, ip),
        )
    
    async def get_or_create_by_ip(
        self,
        workspace_id: str,
        ip: str,
        do_droplet_id: str = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Get by IP or create new droplet record."""
        existing = await self.get_by_ip(workspace_id, ip)
        if existing:
            return existing
        return await self.create(
            workspace_id=workspace_id,
            do_droplet_id=do_droplet_id or f"ip-{ip.replace('.', '-')}",
            ip=ip,
            **kwargs,
        )
    
    async def get_many(self, droplet_ids: List[str]) -> List[Dict[str, Any]]:
        if not droplet_ids:
            return []
        placeholders = ",".join(["?" for _ in droplet_ids])
        return await self._crud.list(
            self.db,
            where_clause=f"[id] IN ({placeholders})",
            params=tuple(droplet_ids),
        )
    
    async def get_ips_for_ids(self, droplet_ids: List[str]) -> List[str]:
        """Convert droplet IDs to IPs."""
        droplets = await self.get_many(droplet_ids)
        return [d["ip"] for d in droplets if d.get("ip")]
    
    async def get_ids_for_ips(self, workspace_id: str, ips: List[str]) -> List[str]:
        """Convert IPs to droplet IDs, creating records if needed."""
        ids = []
        for ip in ips:
            droplet = await self.get_or_create_by_ip(workspace_id, ip)
            ids.append(droplet["id"])
        return ids
    
    async def get_droplets_for_ips(self, workspace_id: str, ips: List[str]) -> List[Dict[str, Any]]:
        """Get droplet info (including names) for a list of IPs."""
        droplets = []
        for ip in ips:
            droplet = await self.get_by_ip(workspace_id, ip)
            if droplet:
                droplets.append(droplet)
        return droplets
    
    async def list(self, workspace_id: str, status: str = None) -> List[Dict[str, Any]]:
        if status:
            return await self._crud.list(
                self.db,
                workspace_id=workspace_id,
                where_clause="[status] = ?",
                params=(status,),
                order_by="[name] ASC",
            )
        return await self._crud.list(
            self.db,
            workspace_id=workspace_id,
            order_by="[name] ASC",
        )
    
    async def list_for_workspace(self, workspace_id: str) -> List[Dict[str, Any]]:
        """List all droplets for a workspace. Required by DropletStoreProtocol."""
        return await self.list(workspace_id)
    
    async def upsert_from_do(self, workspace_id: str, do_droplet: Dict[str, Any]) -> Dict[str, Any]:
        """Upsert a droplet from DO API data. Required by DropletStoreProtocol."""
        do_id = do_droplet.get("do_droplet_id")
        if not do_id:
            raise ValueError("do_droplet must contain 'do_droplet_id'")
        
        existing = await self.get_by_do_id(workspace_id, do_id)
        if existing:
            # Update existing record
            update_data = {
                "name": do_droplet.get("name"),
                "ip": do_droplet.get("public_ip") or do_droplet.get("ip"),
                "private_ip": do_droplet.get("private_ip"),
                "region": do_droplet.get("region"),
                "size": do_droplet.get("size"),
                "status": do_droplet.get("status", "active"),
                "vpc_uuid": do_droplet.get("vpc_uuid"),
            }
            # Remove None values
            update_data = {k: v for k, v in update_data.items() if v is not None}
            return await self._crud.update(self.db, existing["id"], update_data)
        else:
            # Create new record
            return await self.create(
                workspace_id=workspace_id,
                do_droplet_id=do_id,
                name=do_droplet.get("name"),
                ip=do_droplet.get("public_ip") or do_droplet.get("ip"),
                region=do_droplet.get("region"),
                size=do_droplet.get("size"),
            )
    
    async def delete_by_do_id(self, workspace_id: str, do_droplet_id: str) -> bool:
        """Delete a droplet by its DO ID. Required by DropletStoreProtocol."""
        existing = await self.get_by_do_id(workspace_id, do_droplet_id)
        if existing:
            return await self._crud.delete(self.db, existing["id"], permanent=True)
        return False
    
    async def update(self, droplet_id: str, **updates) -> Optional[Dict[str, Any]]:
        return await self._crud.update(self.db, droplet_id, updates)
    
    async def set_status(self, droplet_id: str, status: str) -> bool:
        result = await self.update(droplet_id, status=status)
        return result is not None
    
    async def delete(self, droplet_id: str) -> bool:
        return await self._crud.delete(self.db, droplet_id, permanent=True)


# =============================================================================
# ServiceDroplet Store (Junction)
# =============================================================================

class ServiceDropletStore:
    """Junction table: which services run on which droplets (per env).
    
    Also stores service mesh routing info (ports, IPs) for nginx stream proxy.
    """
    
    def __init__(self, db):
        self.db = db
        self._crud = EntityCRUD("service_droplets")
    
    async def link(
        self,
        workspace_id: str,
        service_id: str,
        droplet_id: str,
        env: str,
        container_name: str = None,
        # Service mesh fields
        host_port: int = None,
        container_port: int = None,
        internal_port: int = None,
        private_ip: str = None,
    ) -> Dict[str, Any]:
        """Link a service to a droplet, with optional service mesh routing info."""
        existing = await self._crud.find_one(
            self.db,
            "[service_id] = ? AND [droplet_id] = ? AND [env] = ?",
            (service_id, droplet_id, env),
        )
        if existing:
            # Update existing link
            if container_name:
                existing["container_name"] = container_name
            if host_port is not None:
                existing["host_port"] = host_port
            if container_port is not None:
                existing["container_port"] = container_port
            if internal_port is not None:
                existing["internal_port"] = internal_port
            if private_ip is not None:
                existing["private_ip"] = private_ip
            existing["is_healthy"] = 1
            existing["last_healthy_at"] = _now()
            await self._crud.save(self.db, existing)
            return existing
        
        return await self._crud.create(self.db, {
            "workspace_id": workspace_id,
            "service_id": service_id,
            "droplet_id": droplet_id,
            "env": env,
            "container_name": container_name,
            "is_healthy": 1,
            "last_healthy_at": _now(),
            # Service mesh fields
            "host_port": host_port,
            "container_port": container_port,
            "internal_port": internal_port,
            "private_ip": private_ip,
        })
    
    async def unlink(self, service_id: str, droplet_id: str, env: str) -> bool:
        existing = await self._crud.find_one(
            self.db,
            "[service_id] = ? AND [droplet_id] = ? AND [env] = ?",
            (service_id, droplet_id, env),
        )
        if existing:
            return await self._crud.delete(self.db, existing["id"], permanent=True)
        return False
    
    async def get_droplets_for_service(
        self,
        service_id: str,
        env: str,
        healthy_only: bool = False,
    ) -> List[Dict[str, Any]]:
        if healthy_only:
            return await self._crud.list(
                self.db,
                where_clause="[service_id] = ? AND [env] = ? AND [is_healthy] = 1",
                params=(service_id, env),
            )
        return await self._crud.list(
            self.db,
            where_clause="[service_id] = ? AND [env] = ?",
            params=(service_id, env),
        )
    
    async def get_services_on_droplet(self, droplet_id: str) -> List[Dict[str, Any]]:
        return await self._crud.list(
            self.db,
            where_clause="[droplet_id] = ?",
            params=(droplet_id,),
        )
    
    async def update_health(
        self,
        service_id: str,
        droplet_id: str,
        env: str,
        is_healthy: bool,
    ) -> bool:
        existing = await self._crud.find_one(
            self.db,
            "[service_id] = ? AND [droplet_id] = ? AND [env] = ?",
            (service_id, droplet_id, env),
        )
        if existing:
            existing["is_healthy"] = 1 if is_healthy else 0
            if is_healthy:
                existing["last_healthy_at"] = _now()
            await self._crud.save(self.db, existing)
            return True
        return False
    
    async def get_peer_ips(
        self,
        service_id: str,
        env: str,
        droplet_store: DropletStore,
    ) -> List[str]:
        """Get sorted list of peer IPs for leader election."""
        links = await self.get_droplets_for_service(service_id, env, healthy_only=True)
        droplet_ids = [l["droplet_id"] for l in links]
        droplets = await droplet_store.get_many(droplet_ids)
        return sorted([d["ip"] for d in droplets if d.get("ip")])
    
    # =========================================================================
    # Service Mesh Methods
    # =========================================================================
    
    async def get_project_server_ips(
        self,
        workspace_id: str,
        project_id: str,
        env: str,
        droplet_store: DropletStore,
    ) -> List[str]:
        """
        Get all droplet IPs for a project/env.
        
        Used by service mesh to update nginx on ALL servers when deploying
        a service, so other services can reach it.
        """
        # Get all service_droplets for this workspace/env
        all_links = await self._crud.list(
            self.db,
            where_clause="[workspace_id] = ? AND [env] = ?",
            params=(workspace_id, env),
        )
        
        # Get unique droplet IDs
        droplet_ids = list(set(l["droplet_id"] for l in all_links))
        if not droplet_ids:
            return []
        
        # Get droplet IPs
        droplets = await droplet_store.get_many(droplet_ids)
        return [d["ip"] for d in droplets if d.get("ip")]
    
    async def find_service_locations(
        self,
        workspace_id: str,
        service_name: str,
        env: str,
        service_store: "ServiceStore",
        droplet_store: DropletStore,
    ) -> List[Dict[str, Any]]:
        """
        Find where a service is deployed.
        
        Returns list of locations with droplet IP and service mesh info.
        Used to route traffic to a dependency service.
        """
        # Find service by name
        services = await service_store.list(workspace_id)
        service = next((s for s in services if s["name"] == service_name), None)
        if not service:
            return []
        
        # Get links for this service
        links = await self.get_droplets_for_service(service["id"], env)
        if not links:
            return []
        
        # Enrich with droplet IPs
        droplet_ids = [l["droplet_id"] for l in links]
        droplets = await droplet_store.get_many(droplet_ids)
        droplet_map = {d["id"]: d for d in droplets}
        
        locations = []
        for link in links:
            droplet = droplet_map.get(link["droplet_id"])
            if droplet:
                locations.append({
                    "server_ip": droplet.get("ip"),
                    "private_ip": link.get("private_ip") or droplet.get("private_ip"),
                    "host_port": link.get("host_port"),
                    "container_port": link.get("container_port"),
                    "internal_port": link.get("internal_port"),
                    "container_name": link.get("container_name"),
                })
        
        return locations
    
    async def get_stateful_services_for_project(
        self,
        project_id: str,
        env: str,
        service_store: ServiceStore,
        droplet_store: DropletStore,
    ) -> List[Dict[str, Any]]:
        """
        Get all stateful services (redis, postgres, etc.) for a project/env with their locations.
        
        Used to auto-inject URLs when deploying any service to the same project/env.
        
        Returns:
            List of dicts with {service_type, host, port, service_name, connection_info}
        """
        logger.info(
            f"📋 ServiceDropletStore.get_stateful_services_for_project",
            project_id=project_id,
            env=env,
        )
        
        # Get all stateful services for project
        stateful_services = await service_store.list_stateful_for_project(project_id)
        
        logger.info(
            f"🗄️ Found {len(stateful_services)} stateful service(s) in services table",
            services=[{
                "name": s.get("name"),
                "id": s.get("id"),
                "service_type": s.get("service_type"),
                "is_stateful": s.get("is_stateful"),
            } for s in stateful_services],
        )
        
        result = []
        for svc in stateful_services:
            svc_name = svc.get("name")
            svc_id = svc.get("id")
            
            # Get deployment location for this env
            links = await self.get_droplets_for_service(svc_id, env, healthy_only=True)
            
            logger.info(
                f"🔗 Service '{svc_name}': found {len(links)} service_droplet link(s) for env={env}",
                service_id=svc_id,
                links=[{
                    "droplet_id": l.get("droplet_id"),
                    "host_port": l.get("host_port"),
                    "internal_port": l.get("internal_port"),
                } for l in links],
            )
            
            if not links:
                logger.warning(f"⚠️ Service '{svc_name}' not deployed to env={env} (no service_droplet links)")
                continue  # Not deployed to this env
            
            # Get droplet IP
            droplet_ids = [l["droplet_id"] for l in links]
            droplets = await droplet_store.get_many(droplet_ids)
            
            logger.info(
                f"đŸ–¥ï¸ Service '{svc_name}': retrieved {len([d for d in droplets if d])} droplet(s)",
                droplets=[{
                    "id": d.get("id") if d else None,
                    "ip": d.get("ip") if d else None,
                } for d in droplets],
            )
            
            for link, droplet in zip(links, droplets):
                if not droplet:
                    logger.warning(f"⚠️ Service '{svc_name}': droplet not found in database")
                    continue
                    
                host = droplet.get("ip")
                port = link.get("host_port") or link.get("internal_port")
                
                if host and port:
                    discovered = {
                        "service_type": svc.get("service_type") or svc.get("name"),
                        "service_name": svc.get("name"),
                        "host": host,
                        "port": port,
                        "service_id": svc["id"],
                    }
                    logger.info(
                        f"Service '{svc_name}' ready for auto-injection",
                        discovered=discovered,
                    )
                    result.append(discovered)
                    break  # One location per service is enough for URL
                else:
                    logger.warning(
                        f"⚠️ Service '{svc_name}': missing host or port",
                        host=host,
                        port=port,
                    )
        
        logger.info(
            f"đŸŽ¯ Final result: {len(result)} stateful service(s) available for injection",
        )
        
        return result


# =============================================================================
# Deployment
# =============================================================================

class Deployment:
    """Deployment record wrapper with backward-compatible properties."""
    
    def __init__(self, data: dict, service_info: dict = None, project_info: dict = None):
        self._data = data
        self._service = service_info or {}
        self._project = project_info or {}
    
    @property
    def id(self) -> str:
        return self._data.get("id", "")
    
    @property
    def workspace_id(self) -> str:
        return self._data.get("workspace_id", "")
    
    @property
    def service_id(self) -> str:
        return self._data.get("service_id", "")
    
    # Backward-compatible accessors
    @property
    def service_name(self) -> str:
        return self._service.get("name", "")
    
    @property
    def project_name(self) -> str:
        return self._project.get("name", "")
    
    @property
    def environment(self) -> str:
        return self._data.get("env", "prod")
    
    @property
    def env(self) -> str:
        return self._data.get("env", "prod")
    
    @property
    def source_type(self) -> str:
        return self._data.get("source_type", "image")
    
    @property
    def image_name(self) -> Optional[str]:
        return self._data.get("image_name")
    
    @property
    def image_digest(self) -> Optional[str]:
        return self._data.get("image_digest")
    
    @property
    def git_url(self) -> Optional[str]:
        return self._data.get("git_url")
    
    @property
    def git_branch(self) -> Optional[str]:
        return self._data.get("git_branch")
    
    @property
    def git_commit(self) -> Optional[str]:
        return self._data.get("git_commit")
    
    @property
    def droplet_ids(self) -> List[str]:
        val = self._data.get("droplet_ids")
        if isinstance(val, str):
            return json.loads(val) if val else []
        return val or []
    
    # Backward compat: server_ips populated by store enrichment
    @property
    def server_ips(self) -> List[str]:
        return self._data.get("_server_ips", [])
    
    @property
    def port(self) -> Optional[int]:
        return self._data.get("port")
    
    @property
    def env_vars(self) -> Dict[str, str]:
        val = self._data.get("env_vars")
        if isinstance(val, str):
            return json.loads(val) if val else {}
        return val or {}
    
    @property
    def user_env_vars(self) -> Dict[str, str]:
        """User-provided env vars only (excludes auto-injected stateful service URLs)."""
        val = self._data.get("user_env_vars")
        if isinstance(val, str):
            return json.loads(val) if val else {}
        return val or {}
    
    @property
    def status(self) -> str:
        return self._data.get("status", "pending")
    
    @property
    def triggered_by(self) -> Optional[str]:
        return self._data.get("triggered_by")
    
    @property
    def deployed_by(self) -> Optional[str]:
        """Alias for triggered_by."""
        return self.triggered_by
    
    @property
    def triggered_by_name(self) -> Optional[str]:
        return self._data.get("_triggered_by_name")
    
    @property
    def deployed_by_name(self) -> Optional[str]:
        """Alias for triggered_by_name."""
        return self.triggered_by_name
    
    @property
    def comment(self) -> Optional[str]:
        return self._data.get("comment")
    
    @property
    def is_rollback(self) -> bool:
        return bool(self._data.get("is_rollback"))
    
    @property
    def rollback_from_id(self) -> Optional[str]:
        return self._data.get("rollback_from_id")
    
    @property
    def version(self) -> Optional[int]:
        """Version number for this coordinate (only set on successful deployments)."""
        return self._data.get("version")
    
    @property
    def config_snapshot(self) -> Optional[Dict[str, Any]]:
        val = self._data.get("config_snapshot")
        if isinstance(val, str):
            return json.loads(val) if val else None
        return val
    
    @property
    def started_at(self) -> Optional[str]:
        return self._data.get("started_at")
    
    @property
    def created_at(self) -> Optional[str]:
        return self._data.get("created_at")
    
    @property
    def completed_at(self) -> Optional[str]:
        return self._data.get("completed_at")
    
    @property
    def duration_seconds(self) -> Optional[float]:
        return self._data.get("duration_seconds")
    
    @property
    def result(self) -> Optional[Dict[str, Any]]:
        val = self._data.get("result_json")
        if isinstance(val, str):
            return json.loads(val) if val else None
        return val
    
    @property
    def error(self) -> Optional[str]:
        return self._data.get("error")
    
    @property
    def logs(self) -> Optional[List[Dict[str, Any]]]:
        val = self._data.get("logs_json")
        if isinstance(val, str):
            return json.loads(val) if val else None
        return val
    
    @property
    def has_logs(self) -> bool:
        return bool(self._data.get("logs_json"))
    
    def to_dict(self) -> dict:
        """Return dict with both normalized and backward-compat fields."""
        return {
            "id": self.id,
            "service_id": self.service_id,
            "service_name": self.service_name,
            "service": self.service_name,  # Alias
            "project_name": self.project_name,
            "project": self.project_name,  # Alias
            "env": self.env,
            "environment": self.environment,
            "version": self.version,
            "source_type": self.source_type,
            "image_name": self.image_name,
            "image_digest": self.image_digest,
            "git_url": self.git_url,
            "git_branch": self.git_branch,
            "git_commit": self.git_commit,
            "droplet_ids": self.droplet_ids,
            "server_ips": self.server_ips,
            "port": self.port,
            "env_vars": self.env_vars,
            "status": self.status,
            "triggered_by": self.triggered_by,
            "deployed_by": self.deployed_by_name or self.deployed_by,  # Prefer name over ID
            "triggered_by_name": self.triggered_by_name,
            "deployed_by_name": self.deployed_by_name,
            "user": self.deployed_by_name or self.deployed_by,  # Alias
            "comment": self.comment,
            "is_rollback": self.is_rollback,
            "rollback_from_id": self.rollback_from_id,
            "config_snapshot": self.config_snapshot,
            "started_at": self.started_at,
            "created_at": self.created_at,
            "deployed_at": self.started_at,  # Alias
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "result": self.result,
            "error": self.error,
            "has_logs": self.has_logs,
            # Computed field for rollback eligibility
            "can_rollback": self.status == "success",
        }


class DeploymentStore:
    """Deployment history management."""
    
    def __init__(self, db):
        self.db = db
        self._crud = EntityCRUD("deployments")
    
    async def _enrich_deployment(
        self, 
        entity: dict, 
        include_service: bool = True,
        include_ips: bool = True,
        include_user: bool = True,
    ) -> Deployment:
        """Enrich deployment with service/project info, server IPs, and user names."""
        service_info = {}
        project_info = {}
        
        if include_service and entity.get("service_id"):
            service_store = ServiceStore(self.db)
            service = await service_store.get(entity["service_id"])
            if service:
                service_info = service
                if service.get("project_id"):
                    project_store = ProjectStore(self.db)
                    project = await project_store.get(service["project_id"])
                    if project:
                        project_info = project
        
        # Convert droplet_ids to IPs
        if include_ips:
            droplet_ids = entity.get("droplet_ids")
            if isinstance(droplet_ids, str):
                droplet_ids = json.loads(droplet_ids) if droplet_ids else []
            if droplet_ids:
                droplet_store = DropletStore(self.db)
                ips = await droplet_store.get_ips_for_ids(droplet_ids)
                entity["_server_ips"] = ips
        
        # Resolve user ID to name/email
        if include_user and entity.get("triggered_by"):
            display_name = await UserLookup.get_display_name(self.db, entity["triggered_by"])
            if display_name:
                entity["_triggered_by_name"] = display_name
        
        return Deployment(entity, service_info, project_info)
    
    async def record_deployment(
        self,
        workspace_id: str,
        project: str,
        environment: str,
        service_name: str,
        source_type: str = "image",
        image_name: str = None,
        image_digest: str = None,
        git_url: str = None,
        git_branch: str = None,
        git_commit: str = None,
        server_ips: list = None,
        port: int = None,
        env_vars: dict = None,
        user_env_vars: dict = None,  # User-provided env vars (excludes auto-injected)
        deployed_by: str = None,
        comment: str = None,
        is_rollback: bool = False,
        rollback_from_id: str = None,
        source_version: int = None,  # For rollbacks: version being rolled back TO
        config_snapshot: dict = None,
    ) -> Deployment:
        """
        Record a new deployment.
        Accepts project/service names, normalizes to IDs internally.
        """
        # Get or create project
        project_store = ProjectStore(self.db)
        project_entity = await project_store.get_or_create(
            workspace_id, project, created_by=deployed_by
        )
        
        # Get or create service
        service_store = ServiceStore(self.db)
        service_entity = await service_store.get_or_create(
            workspace_id, project_entity["id"], service_name, port or 8000
        )
        
        # Convert IPs to droplet IDs
        droplet_ids = []
        if server_ips:
            droplet_store = DropletStore(self.db)
            droplet_ids = await droplet_store.get_ids_for_ips(workspace_id, server_ips)
        
        entity = await self._crud.create(self.db, {
            "workspace_id": workspace_id,
            "service_id": service_entity["id"],
            "env": environment,
            "source_type": source_type,
            "image_name": image_name,
            "image_digest": image_digest,
            "git_url": git_url,
            "git_branch": git_branch,
            "git_commit": git_commit,
            "droplet_ids": json.dumps(droplet_ids) if droplet_ids else None,
            "port": port,
            "env_vars": json.dumps(env_vars) if env_vars else None,
            "user_env_vars": json.dumps(user_env_vars) if user_env_vars else None,
            "status": "pending",
            "started_at": _now(),
            "triggered_by": deployed_by,
            "comment": comment,
            "is_rollback": 1 if is_rollback else 0,
            "rollback_from_id": rollback_from_id,
            "source_version": source_version,  # For rollbacks: the version we're rolling back TO
            "config_snapshot": json.dumps(config_snapshot) if config_snapshot else None,
        })
        
        entity["_server_ips"] = server_ips or []
        return Deployment(entity, service_entity, project_entity)
    
    async def update_deployment(
        self,
        deployment_id: str,
        status: str = None,
        started_at: str = None,
        completed_at: str = None,
        duration_seconds: float = None,
        result: dict = None,
        logs: list = None,
        error: str = None,
        image_name: str = None,
        image_digest: str = None,
        git_commit: str = None,
        server_ips: list = None,
    ) -> dict:
        """
        Update deployment status/result. Assigns version number on success.
        Returns dict with 'success' and optionally 'version' if newly assigned.
        """
        entity = await self._crud.get(self.db, deployment_id)
        if not entity:
            return {"success": False}
        
        assigned_version = None
        
        # If transitioning to success, assign version number
        if status == "success" and entity.get("status") != "success":
            # For rollbacks, use source_version (the version we rolled back TO)
            if entity.get("is_rollback") and entity.get("source_version"):
                entity["version"] = entity["source_version"]
                assigned_version = entity["source_version"]
            else:
                # For regular deploys, auto-increment version
                next_version = await self._get_next_version(
                    entity["service_id"], 
                    entity["env"]
                )
                entity["version"] = next_version
                assigned_version = next_version
        
        if status:
            entity["status"] = status
        if completed_at:
            entity["completed_at"] = completed_at
        if duration_seconds is not None:
            entity["duration_seconds"] = duration_seconds
        if result:
            entity["result_json"] = json.dumps(result)
        if logs is not None:
            entity["logs_json"] = json.dumps(logs)
        if error:
            entity["error"] = error
        if image_name:
            entity["image_name"] = image_name
        if image_digest:
            entity["image_digest"] = image_digest
        if git_commit:
            entity["git_commit"] = git_commit
        
        # Convert server_ips to droplet_ids
        if server_ips is not None:
            droplet_store = DropletStore(self.db)
            droplet_ids = await droplet_store.get_ids_for_ips(
                entity["workspace_id"], server_ips
            )
            entity["droplet_ids"] = json.dumps(droplet_ids)
        
        await self._crud.save(self.db, entity)
        
        return {
            "success": True,
            "version": assigned_version,
            "service_id": entity.get("service_id"),
            "env": entity.get("env"),
        }
    
    async def _get_next_version(self, service_id: str, env: str) -> int:
        """Get next version number for a coordinate (service_id + env)."""
        # Use raw execute for efficient MAX query
        result = await self.db.execute(
            "SELECT MAX(version) FROM deployments WHERE service_id = ? AND env = ?",
            (service_id, env)
        )
        # result is List[Tuple] like [(5,)] or [(None,)]
        current_max = result[0][0] if result and result[0][0] else 0
        return current_max + 1
    
    async def get_by_version(
        self,
        workspace_id: str,
        project: str,
        service_name: str,
        env: str,
        version: int,
        enrich: bool = True,
    ) -> Optional[Deployment]:
        """Get a deployment by version number."""
        # Resolve project/service to service_id
        project_store = ProjectStore(self.db)
        project_entity = await project_store.get_by_name(workspace_id, project)
        if not project_entity:
            return None
        
        service_store = ServiceStore(self.db)
        service_entity = await service_store.get_by_name(project_entity["id"], service_name)
        if not service_entity:
            return None
        
        entity = await self._crud.find_one(
            self.db,
            "[service_id] = ? AND [env] = ? AND [version] = ?",
            (service_entity["id"], env, version),
        )
        
        if not entity:
            return None
        if enrich:
            return await self._enrich_deployment(entity)
        return Deployment(entity, service_entity, project_entity)
    
    async def get_latest_version(
        self,
        workspace_id: str,
        project: str,
        service_name: str,
        env: str,
    ) -> Optional[int]:
        """Get latest version number for a coordinate."""
        project_store = ProjectStore(self.db)
        project_entity = await project_store.get_by_name(workspace_id, project)
        if not project_entity:
            return None
        
        service_store = ServiceStore(self.db)
        service_entity = await service_store.get_by_name(project_entity["id"], service_name)
        if not service_entity:
            return None
        
        result = await self.db.execute(
            "SELECT MAX(version) FROM deployments WHERE service_id = ? AND env = ?",
            (service_entity["id"], env)
        )
        return result[0][0] if result and result[0][0] else None
    
    async def get_deployment(
        self,
        deployment_id: str,
        enrich: bool = True,
    ) -> Optional[Deployment]:
        entity = await self._crud.get(self.db, deployment_id)
        if not entity:
            return None
        if enrich:
            return await self._enrich_deployment(entity)
        return Deployment(entity)
    
    async def get_deployments(
        self,
        workspace_id: str,
        project: str = None,
        environment: str = None,
        service_name: str = None,
        status: str = None,
        limit: int = 50,
        enrich: bool = True,
    ) -> List[Deployment]:
        """
        List deployments with optional filters.
        Accepts project/service names for filtering.
        """
        # Build service_id filter if project/service specified
        service_id = None
        if project:
            project_store = ProjectStore(self.db)
            project_entity = await project_store.get_by_name(workspace_id, project)
            if not project_entity:
                return []
            
            if service_name:
                service_store = ServiceStore(self.db)
                service_entity = await service_store.get_by_name(
                    project_entity["id"], service_name
                )
                if not service_entity:
                    return []
                service_id = service_entity["id"]
        
        # Build query
        conditions = ["[workspace_id] = ?"]
        params = [workspace_id]
        
        if service_id:
            conditions.append("[service_id] = ?")
            params.append(service_id)
        if environment:
            conditions.append("[env] = ?")
            params.append(environment)
        if status:
            conditions.append("[status] = ?")
            params.append(status)
        
        entities = await self._crud.list(
            self.db,
            where_clause=" AND ".join(conditions),
            params=tuple(params),
            order_by="[created_at] DESC",
            limit=limit,
        )
        
        if enrich:
            return [await self._enrich_deployment(e) for e in entities]
        return [Deployment(e) for e in entities]
    
    async def get_previous(
        self,
        workspace_id: str,
        project: str,
        environment: str,
        service_name: str,
    ) -> Optional[Deployment]:
        """Get last successful deployment for rollback."""
        project_store = ProjectStore(self.db)
        project_entity = await project_store.get_by_name(workspace_id, project)
        if not project_entity:
            return None
        
        service_store = ServiceStore(self.db)
        service_entity = await service_store.get_by_name(
            project_entity["id"], service_name
        )
        if not service_entity:
            return None
        
        entity = await self._crud.find_one(
            self.db,
            "[service_id] = ? AND [env] = ? AND [status] = 'success'",
            (service_entity["id"], environment),
        )
        if entity:
            return await self._enrich_deployment(entity)
        return None
    
    async def get_current_deployment(
        self,
        workspace_id: str,
        project: str,
        environment: str,
        service_name: str,
    ) -> Optional[Deployment]:
        """Get the current active (most recent successful) deployment for a service."""
        return await self.get_previous(workspace_id, project, environment, service_name)
    
    async def get_current_servers(
        self,
        workspace_id: str,
        project: str,
        environment: str,
        service_name: str,
    ) -> List[Dict[str, Any]]:
        """
        Get info about servers currently running a service.
        Returns list of {ip, name, status} for each server.
        """
        deployment = await self.get_current_deployment(
            workspace_id, project, environment, service_name
        )
        if not deployment or not deployment.server_ips:
            return []
        
        droplet_store = DropletStore(self.db)
        droplets = await droplet_store.get_droplets_for_ips(
            workspace_id, deployment.server_ips
        )
        
        return [
            {
                "ip": d.get("ip"),
                "name": d.get("name") or d.get("ip"),
                "status": d.get("status", "unknown"),
            }
            for d in droplets
        ]


# =============================================================================
# Credentials Store
# =============================================================================

def _get_encryption_key() -> bytes:
    import os, hashlib, base64
    key = os.environ.get("ENCRYPTION_KEY")
    if key:
        return base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest())
    jwt_secret = os.environ.get("JWT_SECRET", "dev-secret-change-in-production")
    return base64.urlsafe_b64encode(hashlib.sha256(jwt_secret.encode()).digest())


def _encrypt(data: str) -> str:
    try:
        from cryptography.fernet import Fernet
        return Fernet(_get_encryption_key()).encrypt(data.encode()).decode()
    except ImportError:
        return f"UNENCRYPTED:{data}"


def _decrypt(data: str) -> str:
    if data.startswith("UNENCRYPTED:"):
        return data[12:]
    try:
        from cryptography.fernet import Fernet
        return Fernet(_get_encryption_key()).decrypt(data.encode()).decode()
    except ImportError:
        raise RuntimeError("cryptography package required")
    except Exception:
        return data


class CredentialsStore:
    """Encrypted credentials storage."""
    
    def __init__(self, db):
        self.db = db
        self._crud = EntityCRUD("credentials")
    
    async def set(
        self,
        workspace_id: str,
        project_id: str,
        env: str,
        credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        existing = await self._crud.find_one(
            self.db,
            "[project_id] = ? AND [env] = ?",
            (project_id, env),
        )
        
        data = {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "env": env,
            "encrypted_blob": _encrypt(json.dumps(credentials)),
        }
        
        if existing:
            data["id"] = existing["id"]
            data["created_at"] = existing.get("created_at")
            return await self._crud.save(self.db, data)
        
        return await self._crud.create(self.db, data)
    
    async def get(self, project_id: str, env: str) -> Optional[Dict[str, Any]]:
        cred = await self._crud.find_one(
            self.db,
            "[project_id] = ? AND [env] = ?",
            (project_id, env),
        )
        if not cred or not cred.get("encrypted_blob"):
            return None
        try:
            return json.loads(_decrypt(cred["encrypted_blob"]))
        except Exception:
            return None
    
    async def delete(self, project_id: str, env: str) -> bool:
        cred = await self._crud.find_one(
            self.db,
            "[project_id] = ? AND [env] = ?",
            (project_id, env),
        )
        if cred:
            return await self._crud.delete(self.db, cred["id"], permanent=True)
        return False


# =============================================================================
# Deploy Config Store
# =============================================================================

DEFAULT_EXCLUDE_PATTERNS = [
    "node_modules/",
    "__pycache__/",
    "*.pyc",
    ".git/",
    ".venv/",
    "venv/",
    ".env",
    ".DS_Store",
    ".idea/",
    ".vscode/",
    "*.egg-info/",
    ".pytest_cache/",
    ".mypy_cache/",
]


class DeployConfig:
    """Deployment configuration wrapper."""
    
    def __init__(self, entity: dict, service_info: dict = None, project_info: dict = None):
        self._entity = entity
        self._service = service_info or {}
        self._project = project_info or {}
    
    @property
    def id(self) -> str:
        return self._entity.get("id", "")
    
    @property
    def service_id(self) -> str:
        return self._entity.get("service_id", "")
    
    @property
    def service_name(self) -> str:
        return self._service.get("name", "")
    
    @property
    def project_name(self) -> str:
        return self._project.get("name", "")
    
    @property
    def env(self) -> str:
        return self._entity.get("env", "prod")
    
    @property
    def source_type(self) -> str:
        return self._entity.get("source_type", "git")
    
    @property
    def git_url(self) -> Optional[str]:
        return self._entity.get("git_url")
    
    @property
    def git_branch(self) -> str:
        return self._entity.get("git_branch", "main")
    
    @property
    def git_folders(self) -> List[dict]:
        val = self._entity.get("git_folders")
        if isinstance(val, str):
            return json.loads(val) if val else []
        return val or []
    
    @property
    def main_folder_path(self) -> Optional[str]:
        return self._entity.get("main_folder_path")
    
    @property
    def dependency_folder_paths(self) -> List[str]:
        val = self._entity.get("dependency_folder_paths")
        if isinstance(val, str):
            return json.loads(val) if val else []
        return val or []
    
    @property
    def exclude_patterns(self) -> List[str]:
        val = self._entity.get("exclude_patterns")
        if isinstance(val, str):
            return json.loads(val) if val else DEFAULT_EXCLUDE_PATTERNS
        return val or DEFAULT_EXCLUDE_PATTERNS
    
    @property
    def port(self) -> int:
        return self._entity.get("port", 8000)
    
    @property
    def env_vars(self) -> dict:
        val = self._entity.get("env_vars")
        if isinstance(val, str):
            return json.loads(val) if val else {}
        return val or {}
    
    @property
    def dockerfile_path(self) -> str:
        return self._entity.get("dockerfile_path", "Dockerfile")
    
    @property
    def snapshot_id(self) -> Optional[str]:
        return self._entity.get("snapshot_id")
    
    @property
    def region(self) -> Optional[str]:
        return self._entity.get("region")
    
    @property
    def size(self) -> str:
        return self._entity.get("size", "s-1vcpu-1gb")
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "service_id": self.service_id,
            "service_name": self.service_name,
            "project_name": self.project_name,
            "env": self.env,
            "source_type": self.source_type,
            "git_url": self.git_url,
            "git_branch": self.git_branch,
            "git_folders": self.git_folders,
            "main_folder_path": self.main_folder_path,
            "dependency_folder_paths": self.dependency_folder_paths,
            "exclude_patterns": self.exclude_patterns,
            "port": self.port,
            "env_vars": self.env_vars,
            "dockerfile_path": self.dockerfile_path,
            "snapshot_id": self.snapshot_id,
            "region": self.region,
            "size": self.size,
        }


class DeployConfigStore:
    """Saved deployment configurations."""
    
    def __init__(self, db):
        self.db = db
        self._crud = EntityCRUD("deploy_configs")
    
    async def _get_service_id(
        self,
        workspace_id: str,
        project_name: str,
        service_name: str,
    ) -> Optional[str]:
        """Resolve project/service names to service_id."""
        project_store = ProjectStore(self.db)
        project = await project_store.get_by_name(workspace_id, project_name)
        if not project:
            return None
        
        service_store = ServiceStore(self.db)
        service = await service_store.get_by_name(project["id"], service_name)
        return service["id"] if service else None
    
    async def _enrich_config(self, entity: dict) -> DeployConfig:
        """Add service/project info to config."""
        service_info = {}
        project_info = {}
        
        if entity.get("service_id"):
            service_store = ServiceStore(self.db)
            service = await service_store.get(entity["service_id"])
            if service:
                service_info = service
                if service.get("project_id"):
                    project_store = ProjectStore(self.db)
                    project = await project_store.get(service["project_id"])
                    if project:
                        project_info = project
        
        return DeployConfig(entity, service_info, project_info)
    
    async def save(
        self,
        workspace_id: str,
        project_name: str,
        service_name: str,
        env: str,
        config: dict,
    ) -> Optional[DeployConfig]:
        """Save or update deployment config."""
        # Get or create project and service
        project_store = ProjectStore(self.db)
        project = await project_store.get_or_create(workspace_id, project_name)
        
        service_store = ServiceStore(self.db)
        service = await service_store.get_or_create(
            workspace_id, project["id"], service_name, config.get("port", 8000)
        )
        
        existing = await self._crud.find_one(
            self.db,
            "[service_id] = ? AND [env] = ?",
            (service["id"], env),
        )
        
        data = {
            "workspace_id": workspace_id,
            "service_id": service["id"],
            "env": env,
            "source_type": config.get("source_type", "git"),
            "git_url": config.get("git_url"),
            "git_branch": config.get("git_branch", "main"),
            "git_folders": json.dumps(config.get("git_folders", [])),
            "main_folder_path": config.get("main_folder_path"),
            "dependency_folder_paths": json.dumps(config.get("dependency_folder_paths", [])),
            "exclude_patterns": json.dumps(config.get("exclude_patterns", DEFAULT_EXCLUDE_PATTERNS)),
            "port": config.get("port", 8000),
            "env_vars": json.dumps(config.get("env_vars", {})),
            "dockerfile_path": config.get("dockerfile_path", "Dockerfile"),
            "snapshot_id": config.get("snapshot_id"),
            "region": config.get("region"),
            "size": config.get("size", "s-1vcpu-1gb"),
        }
        
        if existing:
            data["id"] = existing["id"]
            data["created_at"] = existing.get("created_at")
            entity = await self._crud.save(self.db, data)
        else:
            entity = await self._crud.create(self.db, data)
        
        return DeployConfig(entity, service, project)
    
    async def get(
        self,
        workspace_id: str,
        project_name: str,
        service_name: str,
        env: str,
    ) -> Optional[DeployConfig]:
        """Get deployment config by project/service/env."""
        service_id = await self._get_service_id(workspace_id, project_name, service_name)
        if not service_id:
            return None
        
        entity = await self._crud.find_one(
            self.db,
            "[service_id] = ? AND [env] = ?",
            (service_id, env),
        )
        if entity:
            return await self._enrich_config(entity)
        return None
    
    async def list_for_project(
        self,
        workspace_id: str,
        project_name: str,
    ) -> List[DeployConfig]:
        """List all configs for a project."""
        project_store = ProjectStore(self.db)
        project = await project_store.get_by_name(workspace_id, project_name)
        if not project:
            return []
        
        service_store = ServiceStore(self.db)
        services = await service_store.list_for_project(project["id"])
        service_ids = [s["id"] for s in services]
        
        if not service_ids:
            return []
        
        placeholders = ",".join(["?" for _ in service_ids])
        entities = await self._crud.list(
            self.db,
            where_clause=f"[service_id] IN ({placeholders})",
            params=tuple(service_ids),
        )
        
        return [await self._enrich_config(e) for e in entities]
    
    async def list_all(self, workspace_id: str) -> List[DeployConfig]:
        """List all configs for workspace."""
        entities = await self._crud.list(self.db, workspace_id=workspace_id)
        return [await self._enrich_config(e) for e in entities]
    
    async def delete(
        self,
        workspace_id: str,
        project_name: str,
        service_name: str,
        env: str,
    ) -> bool:
        """Delete a config."""
        service_id = await self._get_service_id(workspace_id, project_name, service_name)
        if not service_id:
            return False
        
        existing = await self._crud.find_one(
            self.db,
            "[service_id] = ? AND [env] = ?",
            (service_id, env),
        )
        if existing:
            return await self._crud.delete(self.db, existing["id"], permanent=True)
        return False


# =============================================================================
# Health Check Store
# =============================================================================

class HealthCheckStore:
    """Store for health check records."""
    
    def __init__(self, db):
        self.db = db
        self._crud = EntityCRUD("health_checks", soft_delete=False)
    
    async def record(
        self,
        workspace_id: str,
        droplet_id: str,
        status: str,  # healthy, degraded, unhealthy, unreachable
        container_name: str = None,
        response_time_ms: int = None,
        error_message: str = None,
        action_taken: str = None,
        attempt_count: int = 0,
    ) -> dict:
        """Record a health check result."""
        from datetime import datetime, timezone
        
        data = {
            "workspace_id": workspace_id,
            "droplet_id": droplet_id,
            "container_name": container_name,
            "status": status,
            "response_time_ms": response_time_ms,
            "error_message": error_message,
            "action_taken": action_taken,
            "attempt_count": attempt_count,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        return await self._crud.create(self.db, data)
    
    async def get_latest_for_droplet(
        self,
        droplet_id: str,
        container_name: str = None,
    ) -> Optional[dict]:
        """Get the most recent health check for a droplet/container."""
        if container_name:
            where = "[droplet_id] = ? AND [container_name] = ?"
            params = (droplet_id, container_name)
        else:
            where = "[droplet_id] = ? AND [container_name] IS NULL"
            params = (droplet_id,)
        
        results = await self._crud.list(
            self.db,
            where_clause=where,
            params=params,
            order_by="[checked_at] DESC",
            limit=1,
        )
        return results[0] if results else None
    
    async def get_recent_failures(
        self,
        droplet_id: str,
        container_name: str = None,
        limit: int = 10,
    ) -> List[dict]:
        """Get recent failed health checks (unhealthy or unreachable)."""
        if container_name:
            where = "[droplet_id] = ? AND [container_name] = ? AND [status] IN ('unhealthy', 'unreachable')"
            params = (droplet_id, container_name)
        else:
            where = "[droplet_id] = ? AND [container_name] IS NULL AND [status] IN ('unhealthy', 'unreachable')"
            params = (droplet_id,)
        
        return await self._crud.list(
            self.db,
            where_clause=where,
            params=params,
            order_by="[checked_at] DESC",
            limit=limit,
        )
    
    async def count_consecutive_failures(
        self,
        droplet_id: str,
        container_name: str = None,
    ) -> int:
        """Count consecutive failures from the most recent check backward.
        
        Returns the number of consecutive unhealthy/unreachable checks.
        Stops counting when a healthy check is found.
        """
        if container_name:
            where = "[droplet_id] = ? AND [container_name] = ?"
            params = (droplet_id, container_name)
        else:
            where = "[droplet_id] = ? AND [container_name] IS NULL"
            params = (droplet_id,)
        
        # Get recent checks in order
        recent = await self._crud.list(
            self.db,
            where_clause=where,
            params=params,
            order_by="[checked_at] DESC",
            limit=20,  # Look back up to 20 checks
        )
        
        count = 0
        for check in recent:
            if check["status"] in ("unhealthy", "unreachable"):
                count += 1
            else:
                break  # Stop at first healthy check
        
        return count
    
    async def list_for_droplet(
        self,
        droplet_id: str,
        limit: int = 50,
    ) -> List[dict]:
        """List recent health checks for a droplet (all containers)."""
        return await self._crud.list(
            self.db,
            where_clause="[droplet_id] = ?",
            params=(droplet_id,),
            order_by="[checked_at] DESC",
            limit=limit,
        )
    
    async def list_for_workspace(
        self,
        workspace_id: str,
        limit: int = 100,
    ) -> List[dict]:
        """List recent health checks for a workspace."""
        return await self._crud.list(
            self.db,
            workspace_id=workspace_id,
            order_by="[checked_at] DESC",
            limit=limit,
        )
    
    async def cleanup_old(
        self,
        days: int = 7,
    ) -> int:
        """Delete health checks older than N days. Returns count deleted."""
        from datetime import datetime, timezone, timedelta
        
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        
        # Find old records
        old_records = await self.db.find_entities(
            "health_checks",
            where_clause="[checked_at] < ?",
            params=(cutoff,),
            limit=10000,
        )
        
        count = 0
        for record in old_records:
            await self._crud.delete(self.db, record["id"], permanent=True)
            count += 1
        
        return count


# =============================================================================
# Backup Store
# =============================================================================

class BackupStore:
    """Backup history CRUD for stateful services."""
    
    def __init__(self, db):
        self.db = db
        self._crud = EntityCRUD("backups", soft_delete=False)
    
    async def create(
        self,
        workspace_id: str,
        service_id: str,
        service_type: str,
        filename: str,
        storage_path: str,
        size_bytes: int = None,
        storage_type: str = "local",
        status: str = "in_progress",
        error_message: str = None,
        triggered_by: str = "scheduled",
    ) -> Dict[str, Any]:
        """Create a backup record."""
        return await self._crud.create(self.db, {
            "workspace_id": workspace_id,
            "service_id": service_id,
            "service_type": service_type,
            "filename": filename,
            "size_bytes": size_bytes,
            "storage_type": storage_type,
            "storage_path": storage_path,
            "status": status,
            "error_message": error_message,
            "triggered_by": triggered_by,
            "completed_at": _now() if status == "completed" else None,
        })
    
    async def get(self, backup_id: str) -> Optional[Dict[str, Any]]:
        """Get backup by ID."""
        return await self._crud.get(self.db, backup_id)
    
    async def update_status(
        self,
        backup_id: str,
        status: str,
        error_message: str = None,
        size_bytes: int = None,
    ) -> Optional[Dict[str, Any]]:
        """Update backup status."""
        updates = {"status": status}
        if error_message:
            updates["error_message"] = error_message
        if size_bytes is not None:
            updates["size_bytes"] = size_bytes
        if status == "completed":
            updates["completed_at"] = _now()
        return await self._crud.update(self.db, backup_id, updates)
    
    async def list_for_service(
        self,
        workspace_id: str,
        service_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List backups for a service."""
        return await self._crud.list(
            self.db,
            where_clause="[service_id] = ?",
            params=(service_id,),
            workspace_id=workspace_id,
            order_by="[created_at] DESC",
            limit=limit,
        )
    
    async def list_for_workspace(
        self,
        workspace_id: str,
        service_type: str = None,
        status: str = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """List backups for a workspace with optional filters."""
        conditions = []
        params = []
        
        if service_type:
            conditions.append("[service_type] = ?")
            params.append(service_type)
        if status:
            conditions.append("[status] = ?")
            params.append(status)
        
        where_clause = " AND ".join(conditions) if conditions else None
        
        return await self._crud.list(
            self.db,
            where_clause=where_clause,
            params=tuple(params) if params else None,
            workspace_id=workspace_id,
            order_by="[created_at] DESC",
            limit=limit,
        )
    
    async def get_latest_for_service(
        self,
        workspace_id: str,
        service_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Get the most recent successful backup for a service."""
        results = await self._crud.list(
            self.db,
            where_clause="[service_id] = ? AND [status] = ?",
            params=(service_id, "completed"),
            workspace_id=workspace_id,
            order_by="[created_at] DESC",
            limit=1,
        )
        return results[0] if results else None
    
    async def delete(self, backup_id: str) -> bool:
        """Delete a backup record."""
        return await self._crud.delete(self.db, backup_id, permanent=True)
    
    async def count_for_service(
        self,
        workspace_id: str,
        service_id: str,
        status: str = "completed",
    ) -> int:
        """Count backups for a service."""
        return await self._crud.count(
            self.db,
            where_clause="[service_id] = ? AND [status] = ?",
            params=(service_id, status),
            workspace_id=workspace_id,
        )
    
    async def get_oldest_completed(
        self,
        workspace_id: str,
        service_id: str,
        keep_count: int = 7,
    ) -> List[Dict[str, Any]]:
        """Get oldest backups beyond retention limit (for cleanup)."""
        return await self._crud.list(
            self.db,
            where_clause="[service_id] = ? AND [status] = ?",
            params=(service_id, "completed"),
            workspace_id=workspace_id,
            order_by="[created_at] ASC",
            offset=keep_count,
            limit=100,
        )
