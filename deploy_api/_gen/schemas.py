"""
Pydantic schemas - AUTO-GENERATED from manifest.yaml
DO NOT EDIT - changes will be overwritten on regenerate
"""

from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel


class ProjectBase(BaseModel):
    name: str
    description: Optional[str] = None
    docker_hub_user: Optional[str] = None
    created_by: Optional[str] = None

class ProjectCreate(ProjectBase):
    workspace_id: Optional[str] = None

class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    docker_hub_user: Optional[str] = None
    created_by: Optional[str] = None

class ProjectResponse(ProjectBase):
    id: str
    workspace_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ServiceBase(BaseModel):
    project_id: str
    name: str
    port: Optional[int] = 8000
    health_endpoint: Optional[str] = '/health'
    description: Optional[str] = None
    is_stateful: Optional[bool] = False
    service_type: Optional[str] = None

class ServiceCreate(ServiceBase):
    workspace_id: Optional[str] = None

class ServiceUpdate(BaseModel):
    project_id: Optional[str] = None
    name: Optional[str] = None
    port: Optional[int] = None
    health_endpoint: Optional[str] = None
    description: Optional[str] = None
    is_stateful: Optional[bool] = None
    service_type: Optional[str] = None

class ServiceResponse(ServiceBase):
    id: str
    workspace_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DropletBase(BaseModel):
    do_droplet_id: str
    name: Optional[str] = None
    ip: Optional[str] = None
    region: Optional[str] = None
    size: Optional[str] = None
    status: Optional[str] = 'active'
    snapshot_id: Optional[str] = None
    created_by: Optional[str] = None

class DropletCreate(DropletBase):
    workspace_id: Optional[str] = None

class DropletUpdate(BaseModel):
    do_droplet_id: Optional[str] = None
    name: Optional[str] = None
    ip: Optional[str] = None
    region: Optional[str] = None
    size: Optional[str] = None
    status: Optional[str] = None
    snapshot_id: Optional[str] = None
    created_by: Optional[str] = None

class DropletResponse(DropletBase):
    id: str
    workspace_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ServiceDropletBase(BaseModel):
    service_id: str
    droplet_id: str
    env: str
    container_name: Optional[str] = None
    is_healthy: Optional[bool] = True
    last_healthy_at: Optional[datetime] = None
    host_port: Optional[int] = None
    container_port: Optional[int] = None
    internal_port: Optional[int] = None
    private_ip: Optional[str] = None

class ServiceDropletCreate(ServiceDropletBase):
    workspace_id: Optional[str] = None

class ServiceDropletUpdate(BaseModel):
    service_id: Optional[str] = None
    droplet_id: Optional[str] = None
    env: Optional[str] = None
    container_name: Optional[str] = None
    is_healthy: Optional[bool] = None
    last_healthy_at: Optional[datetime] = None
    host_port: Optional[int] = None
    container_port: Optional[int] = None
    internal_port: Optional[int] = None
    private_ip: Optional[str] = None

class ServiceDropletResponse(ServiceDropletBase):
    id: str
    workspace_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DeploymentBase(BaseModel):
    service_id: str
    env: str
    source_type: Optional[str] = 'image'
    image_name: Optional[str] = None
    image_digest: Optional[str] = None
    git_url: Optional[str] = None
    git_branch: Optional[str] = None
    git_commit: Optional[str] = None
    droplet_ids: Optional[Dict[str, Any]] = None
    port: Optional[int] = None
    env_vars: Optional[Dict[str, Any]] = None
    user_env_vars: Optional[Dict[str, Any]] = None
    status: Optional[str] = 'pending'
    triggered_by: str
    comment: Optional[str] = None
    is_rollback: Optional[bool] = False
    rollback_from_id: Optional[str] = None
    config_snapshot: Optional[Dict[str, Any]] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    result_json: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class DeploymentCreate(DeploymentBase):
    workspace_id: Optional[str] = None

class DeploymentUpdate(BaseModel):
    service_id: Optional[str] = None
    env: Optional[str] = None
    source_type: Optional[str] = None
    image_name: Optional[str] = None
    image_digest: Optional[str] = None
    git_url: Optional[str] = None
    git_branch: Optional[str] = None
    git_commit: Optional[str] = None
    droplet_ids: Optional[Dict[str, Any]] = None
    port: Optional[int] = None
    env_vars: Optional[Dict[str, Any]] = None
    user_env_vars: Optional[Dict[str, Any]] = None
    status: Optional[str] = None
    triggered_by: Optional[str] = None
    comment: Optional[str] = None
    is_rollback: Optional[bool] = None
    rollback_from_id: Optional[str] = None
    config_snapshot: Optional[Dict[str, Any]] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    result_json: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class DeploymentResponse(DeploymentBase):
    id: str
    workspace_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DeployConfigBase(BaseModel):
    service_id: str
    env: str
    source_type: Optional[str] = 'git'
    git_url: Optional[str] = None
    git_branch: Optional[str] = 'main'
    git_folders: Optional[Dict[str, Any]] = None
    main_folder_path: Optional[str] = None
    dependency_folder_paths: Optional[Dict[str, Any]] = None
    exclude_patterns: Optional[Dict[str, Any]] = None
    port: Optional[int] = 8000
    env_vars: Optional[Dict[str, Any]] = None
    dockerfile_path: Optional[str] = 'Dockerfile'
    snapshot_id: Optional[str] = None
    region: Optional[str] = None
    size: Optional[str] = 's-1vcpu-1gb'

class DeployConfigCreate(DeployConfigBase):
    workspace_id: Optional[str] = None

class DeployConfigUpdate(BaseModel):
    service_id: Optional[str] = None
    env: Optional[str] = None
    source_type: Optional[str] = None
    git_url: Optional[str] = None
    git_branch: Optional[str] = None
    git_folders: Optional[Dict[str, Any]] = None
    main_folder_path: Optional[str] = None
    dependency_folder_paths: Optional[Dict[str, Any]] = None
    exclude_patterns: Optional[Dict[str, Any]] = None
    port: Optional[int] = None
    env_vars: Optional[Dict[str, Any]] = None
    dockerfile_path: Optional[str] = None
    snapshot_id: Optional[str] = None
    region: Optional[str] = None
    size: Optional[str] = None

class DeployConfigResponse(DeployConfigBase):
    id: str
    workspace_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CredentialBase(BaseModel):
    project_id: str
    env: str
    encrypted_blob: Optional[str] = None

class CredentialCreate(CredentialBase):
    workspace_id: Optional[str] = None

class CredentialUpdate(BaseModel):
    project_id: Optional[str] = None
    env: Optional[str] = None
    encrypted_blob: Optional[str] = None

class CredentialResponse(CredentialBase):
    id: str
    workspace_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class HealthCheckBase(BaseModel):
    droplet_id: str
    container_name: Optional[str] = None
    status: str
    response_time_ms: Optional[int] = None
    error_message: Optional[str] = None
    action_taken: Optional[str] = None
    attempt_count: Optional[int] = 0
    checked_at: datetime

class HealthCheckCreate(HealthCheckBase):
    workspace_id: Optional[str] = None

class HealthCheckUpdate(BaseModel):
    droplet_id: Optional[str] = None
    container_name: Optional[str] = None
    status: Optional[str] = None
    response_time_ms: Optional[int] = None
    error_message: Optional[str] = None
    action_taken: Optional[str] = None
    attempt_count: Optional[int] = None
    checked_at: Optional[datetime] = None

class HealthCheckResponse(HealthCheckBase):
    id: str
    workspace_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class BackupBase(BaseModel):
    service_id: str
    service_type: str
    filename: str
    size_bytes: Optional[int] = None
    storage_type: Optional[str] = 'local'
    storage_path: str
    status: Optional[str] = 'completed'
    error_message: Optional[str] = None
    triggered_by: Optional[str] = 'scheduled'
    completed_at: Optional[datetime] = None

class BackupCreate(BackupBase):
    workspace_id: Optional[str] = None

class BackupUpdate(BaseModel):
    service_id: Optional[str] = None
    service_type: Optional[str] = None
    filename: Optional[str] = None
    size_bytes: Optional[int] = None
    storage_type: Optional[str] = None
    storage_path: Optional[str] = None
    status: Optional[str] = None
    error_message: Optional[str] = None
    triggered_by: Optional[str] = None
    completed_at: Optional[datetime] = None

class BackupResponse(BackupBase):
    id: str
    workspace_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

