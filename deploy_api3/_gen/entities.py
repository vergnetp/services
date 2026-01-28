"""
Typed entity dataclasses - AUTO-GENERATED from manifest.yaml
DO NOT EDIT - changes will be overwritten on regenerate

These provide type-safe entity access for internal code.
Use Pydantic schemas (schemas.py) for API validation.
"""

from dataclasses import dataclass, fields, asdict
from typing import Any, Dict, List, Optional


@dataclass
class Project:
    """Typed entity for project."""

    # System fields
    id: Optional[str] = None
    workspace_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[str] = None

    # Required fields
    name: str = None  # required

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Project':
        """Create from dict, filtering to known fields."""
        if data is None:
            return None
        field_names = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in field_names}
        return cls(**filtered)


@dataclass
class Service:
    """Typed entity for service."""

    # System fields
    id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[str] = None

    # Required fields
    project_id: str = None  # required
    name: str = None  # required

    # Optional fields
    description: Optional[str] = ""
    service_type: Optional[str] = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Service':
        """Create from dict, filtering to known fields."""
        if data is None:
            return None
        field_names = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in field_names}
        return cls(**filtered)


@dataclass
class Deployment:
    """Typed entity for deployment."""

    # System fields
    id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None

    # Required fields
    service_id: str = None  # required
    env: str = None  # required
    version: int = None  # required

    # Optional fields
    image_name: Optional[str] = ""
    container_name: Optional[str] = ""
    env_variables: Optional[Dict[str, Any]] = None
    droplet_ids: Optional[Dict[str, Any]] = None
    is_rollback: Optional[bool] = False
    status: Optional[str] = "pending"
    error: Optional[str] = ""
    log: Optional[str] = ""
    triggered_by: Optional[str] = ""
    triggered_at: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Deployment':
        """Create from dict, filtering to known fields."""
        if data is None:
            return None
        field_names = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in field_names}
        return cls(**filtered)


@dataclass
class Droplet:
    """Typed entity for droplet."""

    # System fields
    id: Optional[str] = None
    workspace_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[str] = None

    # Optional fields
    do_droplet_id: Optional[str] = ""
    name: Optional[str] = ""
    ip: Optional[str] = ""
    private_ip: Optional[str] = ""
    region: Optional[str] = ""
    size: Optional[str] = ""
    vpc_uuid: Optional[str] = ""
    snapshot_id: Optional[str] = ""
    status: Optional[str] = "active"
    health_status: Optional[str] = "healthy"
    failure_count: Optional[int] = 0
    last_checked: Optional[str] = None
    last_failure_at: Optional[str] = None
    last_failure_reason: Optional[str] = ""
    problematic_reason: Optional[str] = ""
    flagged_at: Optional[str] = None
    last_reboot_at: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Droplet':
        """Create from dict, filtering to known fields."""
        if data is None:
            return None
        field_names = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in field_names}
        return cls(**filtered)


@dataclass
class Container:
    """Typed entity for container."""

    # System fields
    id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None

    # Optional fields
    container_name: Optional[str] = ""
    droplet_id: Optional[str] = ""
    deployment_id: Optional[str] = ""
    status: Optional[str] = "pending"
    health_status: Optional[str] = "unknown"
    failure_count: Optional[int] = 0
    last_failure_at: Optional[str] = None
    last_failure_reason: Optional[str] = ""
    last_healthy_at: Optional[str] = None
    last_restart_at: Optional[str] = None
    last_checked: Optional[str] = None
    error: Optional[str] = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Container':
        """Create from dict, filtering to known fields."""
        if data is None:
            return None
        field_names = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in field_names}
        return cls(**filtered)


@dataclass
class Snapshot:
    """Typed entity for snapshot."""

    # System fields
    id: Optional[str] = None
    workspace_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None

    # Optional fields
    do_snapshot_id: Optional[str] = ""
    name: Optional[str] = ""
    region: Optional[str] = ""
    size_gigabytes: Optional[float] = 0
    agent_version: Optional[str] = ""
    is_base: Optional[bool] = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Snapshot':
        """Create from dict, filtering to known fields."""
        if data is None:
            return None
        field_names = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in field_names}
        return cls(**filtered)


__all__ = [
    "Project",
    "Service",
    "Deployment",
    "Droplet",
    "Container",
    "Snapshot",
]