"""
Project and Service management routes.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime

try:
    from shared_libs.backend.app_kernel.auth import get_current_user, UserIdentity
except ImportError:
    UserIdentity = dict
    def get_current_user(): pass

from ..deps import (
    get_project_store, 
    get_service_store, 
    get_credentials_store,
)
from ..stores import ProjectStore, ServiceStore, CredentialsStore


router = APIRouter(prefix="/projects", tags=["Projects & Services"])


# =============================================================================
# Request/Response Models
# =============================================================================

class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None
    docker_hub_user: Optional[str] = None


class ProjectUpdate(BaseModel):
    description: Optional[str] = None
    docker_hub_user: Optional[str] = None


class ServiceCreate(BaseModel):
    name: str
    port: int = 8000
    health_endpoint: str = "/health"
    description: Optional[str] = None


class ServiceUpdate(BaseModel):
    port: Optional[int] = None
    health_endpoint: Optional[str] = None
    description: Optional[str] = None


class CredentialsSet(BaseModel):
    digitalocean_token: str
    docker_hub_user: Optional[str] = None
    docker_hub_password: Optional[str] = None


# =============================================================================
# Projects CRUD
# =============================================================================

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_project(
    data: ProjectCreate,
    user: UserIdentity = Depends(get_current_user),
    project_store: ProjectStore = Depends(get_project_store),
):
    """Create a new project."""
    workspace_id = str(user.id)
    
    # Check if exists
    existing = await project_store.get_by_name(workspace_id, data.name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Project '{data.name}' already exists",
        )
    
    project = await project_store.create(
        workspace_id=workspace_id,
        name=data.name,
        description=data.description,
        docker_hub_user=data.docker_hub_user,
        created_by=str(user.id),
    )
    
    return project


@router.get("")
async def list_projects(
    user: UserIdentity = Depends(get_current_user),
    project_store: ProjectStore = Depends(get_project_store),
):
    """List all projects."""
    projects = await project_store.list(str(user.id))
    return {"projects": projects}


@router.get("/{project_name}")
async def get_project(
    project_name: str,
    user: UserIdentity = Depends(get_current_user),
    project_store: ProjectStore = Depends(get_project_store),
    service_store: ServiceStore = Depends(get_service_store),
):
    """Get project with its services."""
    workspace_id = str(user.id)
    
    project = await project_store.get_by_name(workspace_id, project_name)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Get services
    services = await service_store.list_for_project(project["id"])
    
    return {
        **project,
        "services": services,
    }


@router.patch("/{project_name}")
async def update_project(
    project_name: str,
    data: ProjectUpdate,
    user: UserIdentity = Depends(get_current_user),
    project_store: ProjectStore = Depends(get_project_store),
):
    """Update project."""
    workspace_id = str(user.id)
    
    project = await project_store.get_by_name(workspace_id, project_name)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if updates:
        project = await project_store.update(project["id"], **updates)
    
    return project


@router.delete("/{project_name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_name: str,
    user: UserIdentity = Depends(get_current_user),
    project_store: ProjectStore = Depends(get_project_store),
):
    """Delete a project."""
    workspace_id = str(user.id)
    
    project = await project_store.get_by_name(workspace_id, project_name)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    await project_store.delete(project["id"])


# =============================================================================
# Services CRUD
# =============================================================================

@router.post("/{project_name}/services", status_code=status.HTTP_201_CREATED)
async def create_service(
    project_name: str,
    data: ServiceCreate,
    user: UserIdentity = Depends(get_current_user),
    project_store: ProjectStore = Depends(get_project_store),
    service_store: ServiceStore = Depends(get_service_store),
):
    """Create a service in a project."""
    workspace_id = str(user.id)
    
    project = await project_store.get_by_name(workspace_id, project_name)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Check if service exists
    existing = await service_store.get_by_name(project["id"], data.name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Service '{data.name}' already exists in project '{project_name}'",
        )
    
    service = await service_store.create(
        workspace_id=workspace_id,
        project_id=project["id"],
        name=data.name,
        port=data.port,
        health_endpoint=data.health_endpoint,
        description=data.description,
    )
    
    return service


@router.get("/{project_name}/services")
async def list_services(
    project_name: str,
    user: UserIdentity = Depends(get_current_user),
    project_store: ProjectStore = Depends(get_project_store),
    service_store: ServiceStore = Depends(get_service_store),
):
    """List services in a project."""
    workspace_id = str(user.id)
    
    project = await project_store.get_by_name(workspace_id, project_name)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    services = await service_store.list_for_project(project["id"])
    return {"services": services}


@router.get("/{project_name}/services/{service_name}")
async def get_service(
    project_name: str,
    service_name: str,
    user: UserIdentity = Depends(get_current_user),
    project_store: ProjectStore = Depends(get_project_store),
    service_store: ServiceStore = Depends(get_service_store),
):
    """Get a specific service."""
    workspace_id = str(user.id)
    
    project = await project_store.get_by_name(workspace_id, project_name)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    service = await service_store.get_by_name(project["id"], service_name)
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    
    return service


@router.patch("/{project_name}/services/{service_name}")
async def update_service(
    project_name: str,
    service_name: str,
    data: ServiceUpdate,
    user: UserIdentity = Depends(get_current_user),
    project_store: ProjectStore = Depends(get_project_store),
    service_store: ServiceStore = Depends(get_service_store),
):
    """Update a service."""
    workspace_id = str(user.id)
    
    project = await project_store.get_by_name(workspace_id, project_name)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    service = await service_store.get_by_name(project["id"], service_name)
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if updates:
        service = await service_store.update(service["id"], **updates)
    
    return service


@router.delete("/{project_name}/services/{service_name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_service(
    project_name: str,
    service_name: str,
    user: UserIdentity = Depends(get_current_user),
    project_store: ProjectStore = Depends(get_project_store),
    service_store: ServiceStore = Depends(get_service_store),
):
    """Delete a service."""
    workspace_id = str(user.id)
    
    project = await project_store.get_by_name(workspace_id, project_name)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    service = await service_store.get_by_name(project["id"], service_name)
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    
    await service_store.delete(service["id"])


# =============================================================================
# Credentials
# =============================================================================

@router.put("/{project_name}/credentials/{env}")
async def set_credentials(
    project_name: str,
    env: str,
    data: CredentialsSet,
    user: UserIdentity = Depends(get_current_user),
    project_store: ProjectStore = Depends(get_project_store),
    credentials_store: CredentialsStore = Depends(get_credentials_store),
):
    """Set credentials for a project environment."""
    workspace_id = str(user.id)
    
    project = await project_store.get_by_name(workspace_id, project_name)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    creds = {
        "digitalocean_token": data.digitalocean_token,
    }
    if data.docker_hub_user:
        creds["docker_hub_user"] = data.docker_hub_user
    if data.docker_hub_password:
        creds["docker_hub_password"] = data.docker_hub_password
    
    await credentials_store.set(workspace_id, project["id"], env, creds)
    
    return {
        "project": project_name,
        "env": env,
        "has_digitalocean": True,
        "has_docker_hub": bool(data.docker_hub_user),
    }


@router.get("/{project_name}/credentials/{env}")
async def get_credentials_status(
    project_name: str,
    env: str,
    user: UserIdentity = Depends(get_current_user),
    project_store: ProjectStore = Depends(get_project_store),
    credentials_store: CredentialsStore = Depends(get_credentials_store),
):
    """Check if credentials are set (doesn't return actual secrets)."""
    workspace_id = str(user.id)
    
    project = await project_store.get_by_name(workspace_id, project_name)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    creds = await credentials_store.get(project["id"], env)
    if not creds:
        raise HTTPException(status_code=404, detail="Credentials not set")
    
    return {
        "project": project_name,
        "env": env,
        "has_digitalocean": bool(creds.get("digitalocean_token")),
        "has_docker_hub": bool(creds.get("docker_hub_user")),
    }


@router.delete("/{project_name}/credentials/{env}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credentials(
    project_name: str,
    env: str,
    user: UserIdentity = Depends(get_current_user),
    project_store: ProjectStore = Depends(get_project_store),
    credentials_store: CredentialsStore = Depends(get_credentials_store),
):
    """Delete credentials for a project environment."""
    workspace_id = str(user.id)
    
    project = await project_store.get_by_name(workspace_id, project_name)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    await credentials_store.delete(project["id"], env)
