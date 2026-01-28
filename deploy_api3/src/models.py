"""
Entity models for deploy_api.

These dataclasses define the schema and provide:
- Validation (constructor checks required fields)
- Defaults (built into the class)
- Documentation (AI/humans read the class)
- IDE autocomplete

Usage:
    # Validate and use
    project = Project(**data)
    print(project.name)
    
    # Convert to dict for database
    from dataclasses import asdict
    await db.save_entity("projects", asdict(project))
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any
import json


# =============================================================================
# Base functionality
# =============================================================================

def from_dict(cls, data: Dict[str, Any]):
    """Create entity from dict, handling only known fields."""
    if data is None:
        return None
    known_fields = {f.name for f in cls.__dataclass_fields__.values()}
    filtered = {k: v for k, v in data.items() if k in known_fields}
    return cls(**filtered)


# =============================================================================
# Entities
# =============================================================================

@dataclass
class Project:
    """A project groups related services."""
    name: str
    workspace_id: Optional[str] = None
    id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[str] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Project":
        return from_dict(cls, data)


@dataclass
class Service:
    """A deployable service within a project."""
    name: str
    project_id: str
    description: Optional[str] = None
    service_type: Optional[str] = None
    id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[str] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Service":
        return from_dict(cls, data)


@dataclass
class Deployment:
    """A deployment of a service to infrastructure."""
    service_id: str
    env: str = "prod"
    version: Optional[int] = None
    image_name: Optional[str] = None
    container_name: Optional[str] = None
    env_variables: Optional[str] = None  # JSON string
    droplet_ids: Optional[str] = None    # JSON string
    is_rollback: bool = False
    status: str = "pending"
    error: Optional[str] = None
    log: Optional[str] = None
    triggered_by: Optional[str] = None
    triggered_at: Optional[str] = None
    id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Deployment":
        return from_dict(cls, data)
    
    @property
    def env_vars_dict(self) -> Dict[str, str]:
        """Parse env_variables JSON to dict."""
        if not self.env_variables:
            return {}
        try:
            return json.loads(self.env_variables)
        except:
            return {}
    
    @property
    def droplet_ids_list(self) -> List[str]:
        """Parse droplet_ids JSON to list."""
        if not self.droplet_ids:
            return []
        try:
            return json.loads(self.droplet_ids)
        except:
            return []


@dataclass
class Droplet:
    """A DigitalOcean droplet (server)."""
    name: str
    workspace_id: Optional[str] = None
    do_droplet_id: Optional[int] = None
    ip: Optional[str] = None
    private_ip: Optional[str] = None
    region: Optional[str] = None
    size: Optional[str] = None
    vpc_uuid: Optional[str] = None
    snapshot_id: Optional[str] = None
    status: str = "active"
    health_status: str = "healthy"
    failure_count: int = 0
    last_checked: Optional[str] = None
    last_failure_at: Optional[str] = None
    last_failure_reason: Optional[str] = None
    problematic_reason: Optional[str] = None
    flagged_at: Optional[str] = None
    last_reboot_at: Optional[str] = None
    id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_at: Optional[str] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Droplet":
        return from_dict(cls, data)


@dataclass
class Container:
    """A Docker container running on a droplet."""
    container_name: str
    droplet_id: str
    deployment_id: Optional[str] = None
    status: str = "pending"
    health_status: str = "unknown"
    failure_count: int = 0
    last_failure_at: Optional[str] = None
    last_failure_reason: Optional[str] = None
    last_healthy_at: Optional[str] = None
    last_restart_at: Optional[str] = None
    last_checked: Optional[str] = None
    error: Optional[str] = None
    id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Container":
        return from_dict(cls, data)


@dataclass
class Snapshot:
    """A DigitalOcean snapshot (droplet image)."""
    name: str
    workspace_id: Optional[str] = None
    do_snapshot_id: Optional[str] = None
    region: Optional[str] = None
    size_gigabytes: Optional[float] = None
    agent_version: Optional[str] = None
    is_base: bool = False
    id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Snapshot":
        return from_dict(cls, data)


__all__ = [
    "Project",
    "Service", 
    "Deployment",
    "Droplet",
    "Container",
    "Snapshot",
]
