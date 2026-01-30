"""
Entity schemas for deploy_api using schema-first approach.

These @entity decorators define the database schema explicitly:
- Single source of truth for table structure
- Auto-migration on startup
- Indexes for performance
- Constraints for data integrity

Import this module in main.py to register schemas.
"""

from dataclasses import dataclass
from typing import Optional
from databases import entity, entity_field


@entity(table="projects")
@dataclass
class Project:
    """A project groups related services."""
    name: str = entity_field(nullable=False)
    workspace_id: str = entity_field(index=True, nullable=True)
    
    # System fields (auto-managed by entity framework)
    id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[str] = None


@entity(table="services")
@dataclass
class Service:
    """A deployable service within a project."""
    name: str = entity_field(nullable=False)
    project_id: str = entity_field(index=True, nullable=False)
    description: str = entity_field(nullable=True)
    service_type: str = entity_field(nullable=True)
    
    # System fields
    id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[str] = None


@entity(table="deployments")
@dataclass
class Deployment:
    """A deployment of a service to infrastructure."""
    service_id: str = entity_field(index=True, nullable=False)
    env: str = entity_field(default="prod")
    version: int = entity_field(nullable=True)
    image_name: str = entity_field(nullable=True)
    container_name: str = entity_field(nullable=True)
    env_variables: str = entity_field(nullable=True)  # JSON string
    droplet_ids: str = entity_field(nullable=True)    # JSON string
    is_rollback: bool = entity_field(default=False)
    status: str = entity_field(
        default="pending",
        check="[status] IN ('pending', 'running', 'completed', 'failed', 'cancelled')"
    )
    error: str = entity_field(nullable=True)
    log: str = entity_field(nullable=True)
    triggered_by: str = entity_field(nullable=True)
    triggered_at: str = entity_field(nullable=True)
    
    # System fields
    id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None


@entity(table="droplets")
@dataclass
class Droplet:
    """A DigitalOcean droplet (server)."""
    name: str = entity_field(nullable=False)
    workspace_id: str = entity_field(index=True, nullable=True)
    do_droplet_id: int = entity_field(index=True, unique=True, nullable=True)
    ip: str = entity_field(nullable=True)
    private_ip: str = entity_field(nullable=True)
    region: str = entity_field(nullable=True)
    size: str = entity_field(nullable=True)
    vpc_uuid: str = entity_field(nullable=True)
    snapshot_id: str = entity_field(index=True, nullable=True)
    status: str = entity_field(
        default="active",
        check="[status] IN ('active', 'inactive', 'provisioning', 'error')"
    )
    health_status: str = entity_field(
        default="healthy",
        check="[health_status] IN ('healthy', 'unhealthy', 'unknown')"
    )
    failure_count: int = entity_field(default=0)
    last_checked: str = entity_field(nullable=True)
    last_failure_at: str = entity_field(nullable=True)
    last_failure_reason: str = entity_field(nullable=True)
    problematic_reason: str = entity_field(nullable=True)
    flagged_at: str = entity_field(nullable=True)
    last_reboot_at: str = entity_field(nullable=True)
    
    # System fields
    id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[str] = None


@entity(table="containers")
@dataclass
class Container:
    """A Docker container running on a droplet."""
    container_name: str = entity_field(nullable=False)
    droplet_id: str = entity_field(index=True, nullable=False)
    deployment_id: str = entity_field(index=True, nullable=True)
    status: str = entity_field(
        default="pending",
        check="[status] IN ('pending', 'running', 'stopped', 'error')"
    )
    health_status: str = entity_field(
        default="unknown",
        check="[health_status] IN ('healthy', 'unhealthy', 'unknown')"
    )
    failure_count: int = entity_field(default=0)
    last_failure_at: str = entity_field(nullable=True)
    last_failure_reason: str = entity_field(nullable=True)
    last_healthy_at: str = entity_field(nullable=True)
    last_restart_at: str = entity_field(nullable=True)
    last_checked: str = entity_field(nullable=True)
    error: str = entity_field(nullable=True)
    
    # System fields
    id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None


@entity(table="snapshots")
@dataclass
class Snapshot:
    """A DigitalOcean snapshot (droplet image)."""
    name: str = entity_field(nullable=False)
    workspace_id: str = entity_field(index=True, nullable=True)
    do_snapshot_id: str = entity_field(index=True, unique=True, nullable=True)
    region: str = entity_field(nullable=True)
    size_gigabytes: float = entity_field(nullable=True)
    agent_version: str = entity_field(nullable=True)
    is_base: bool = entity_field(default=False)
    is_managed: bool = entity_field(default=False)
    
    # System fields
    id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None


__all__ = [
    "Project",
    "Service",
    "Deployment",
    "Droplet",
    "Container",
    "Snapshot",
]
