"""
Pydantic schemas - AUTO-GENERATED from manifest.yaml
DO NOT EDIT - changes will be overwritten on regenerate
"""

from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel


class ProjectBase(BaseModel):
    name: str

class ProjectCreate(ProjectBase):
    workspace_id: Optional[str] = None

class ProjectUpdate(BaseModel):
    name: Optional[str] = None

class ProjectResponse(ProjectBase):
    id: str
    workspace_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ServiceBase(BaseModel):
    project_id: str
    name: str
    description: Optional[str] = None
    service_type: str

class ServiceCreate(ServiceBase):
    pass

class ServiceUpdate(BaseModel):
    project_id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    service_type: Optional[str] = None

class ServiceResponse(ServiceBase):
    id: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DropletBase(BaseModel):
    do_droplet_id: int
    name: str
    region: str
    size: str
    snapshot_id: Optional[str] = None
    ip: Optional[str] = None
    private_ip: Optional[str] = None
    vpc_uuid: Optional[str] = None
    status: Optional[str] = 'active'
    health_status: Optional[str] = 'healthy'
    failure_count: Optional[int] = 0
    last_checked: Optional[datetime] = None
    last_failure_at: Optional[datetime] = None
    last_failure_reason: Optional[str] = None
    problematic_reason: Optional[str] = None
    flagged_at: Optional[datetime] = None
    last_reboot_at: Optional[datetime] = None

class DropletCreate(DropletBase):
    workspace_id: Optional[str] = None

class DropletUpdate(BaseModel):
    do_droplet_id: Optional[int] = None
    name: Optional[str] = None
    region: Optional[str] = None
    size: Optional[str] = None
    snapshot_id: Optional[str] = None
    ip: Optional[str] = None
    private_ip: Optional[str] = None
    vpc_uuid: Optional[str] = None
    status: Optional[str] = None
    health_status: Optional[str] = None
    failure_count: Optional[int] = None
    last_checked: Optional[datetime] = None
    last_failure_at: Optional[datetime] = None
    last_failure_reason: Optional[str] = None
    problematic_reason: Optional[str] = None
    flagged_at: Optional[datetime] = None
    last_reboot_at: Optional[datetime] = None

class DropletResponse(DropletBase):
    id: str
    workspace_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DeploymentBase(BaseModel):
    service_id: str
    version: int
    env: str
    image_name: str
    env_variables: Optional[Dict[str, Any]] = None
    droplet_ids: Dict[str, Any]
    is_rollback: Optional[bool] = False
    status: Optional[str] = 'pending'
    error: Optional[str] = None
    log: Optional[str] = None
    triggered_by: str
    triggered_at: datetime

class DeploymentCreate(DeploymentBase):
    pass

class DeploymentUpdate(BaseModel):
    service_id: Optional[str] = None
    version: Optional[int] = None
    env: Optional[str] = None
    image_name: Optional[str] = None
    env_variables: Optional[Dict[str, Any]] = None
    droplet_ids: Optional[Dict[str, Any]] = None
    is_rollback: Optional[bool] = None
    status: Optional[str] = None
    error: Optional[str] = None
    log: Optional[str] = None
    triggered_by: Optional[str] = None
    triggered_at: Optional[datetime] = None

class DeploymentResponse(DeploymentBase):
    id: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ContainerBase(BaseModel):
    container_name: str
    droplet_id: str
    deployment_id: str
    status: Optional[str] = 'pending'
    health_status: Optional[str] = 'unknown'
    failure_count: Optional[int] = 0
    last_failure_at: Optional[datetime] = None
    last_failure_reason: Optional[str] = None
    last_healthy_at: Optional[datetime] = None
    last_restart_at: Optional[datetime] = None
    last_checked: Optional[datetime] = None
    error: Optional[str] = None

class ContainerCreate(ContainerBase):
    pass

class ContainerUpdate(BaseModel):
    container_name: Optional[str] = None
    droplet_id: Optional[str] = None
    deployment_id: Optional[str] = None
    status: Optional[str] = None
    health_status: Optional[str] = None
    failure_count: Optional[int] = None
    last_failure_at: Optional[datetime] = None
    last_failure_reason: Optional[str] = None
    last_healthy_at: Optional[datetime] = None
    last_restart_at: Optional[datetime] = None
    last_checked: Optional[datetime] = None
    error: Optional[str] = None

class ContainerResponse(ContainerBase):
    id: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SnapshotBase(BaseModel):
    do_snapshot_id: str
    name: str
    region: str
    size_gigabytes: Optional[float] = None
    agent_version: Optional[str] = None
    is_base: Optional[bool] = False

class SnapshotCreate(SnapshotBase):
    workspace_id: Optional[str] = None

class SnapshotUpdate(BaseModel):
    do_snapshot_id: Optional[str] = None
    name: Optional[str] = None
    region: Optional[str] = None
    size_gigabytes: Optional[float] = None
    agent_version: Optional[str] = None
    is_base: Optional[bool] = None

class SnapshotResponse(SnapshotBase):
    id: str
    workspace_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

