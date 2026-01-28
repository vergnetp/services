# =============================================================================
# routes.py
# =============================================================================
"""FastAPI routes for deploy_api3."""

import os
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Optional

from shared_libs.backend.app_kernel import get_current_user, UserIdentity, db_connection

from ...src import snapshot, service, scale, droplet, project
from ..stores import snapshots, services, projects, droplets, deployments


router = APIRouter( tags=["deployer"])


# =============================================================================
# Config
# =============================================================================

def get_do_token() -> str:
    token = os.environ.get("DO_TOKEN")
    if not token:
        raise HTTPException(500, "DO_TOKEN not configured")
    return token


def get_cf_token() -> str:
    token = os.environ.get("CF_TOKEN")
    if not token:
        raise HTTPException(500, "CF_TOKEN not configured")
    return token


# =============================================================================
# Pydantic Models
# =============================================================================

class GitRepo(BaseModel):
    url: str
    branch: str = 'main'
    token: str = None


class CreateBaseSnapshotRequest(BaseModel):
    region: str = 'lon1'
    size: str = 's-1vcpu-1gb'
    images: List[str] = None


class CreateCustomSnapshotRequest(BaseModel):
    git_repos: List[GitRepo] = None
    dockerfile_content: str = None
    snapshot_name: str = None
    region: str = 'lon1'
    size: str = 's-1vcpu-1gb'
    base_snapshot_id: str = None
    test_env_variables: List[str] = None


class DeployServiceRequest(BaseModel):
    project_name: str
    service_name: str
    service_description: str = None
    service_type: str = 'webservice'
    env_variables: List[str] = None
    env: str = 'prod'
    # Source:
    image_name: str = None
    git_repos: List[GitRepo] = None
    dockerfile_content: str = None
    # Droplets:
    existing_droplet_ids: List[str] = None
    new_droplets_nb: int = 0
    new_droplets_region: str = 'lon1'
    new_droplets_size: str = 's-1vcpu-1gb'
    new_droplets_snapshot_id: str = None


class RollbackRequest(BaseModel):
    target_version: int = None
    env: str = 'prod'


class ScaleRequest(BaseModel):
    env: str = 'prod'
    target_count: int
    region: str = 'lon1'
    size: str = 's-1vcpu-1gb'
    snapshot_id: str = None


class CreateDropletRequest(BaseModel):
    snapshot_id: str
    region: str = 'lon1'
    size: str = 's-1vcpu-1gb'


# =============================================================================
# SSE Helper
# =============================================================================

async def sse_stream(async_generator):
    """Wrap async generator for SSE streaming."""
    async for event in async_generator:
        yield event


# =============================================================================
# Snapshot Routes
# =============================================================================

@router.post("/snapshots/base", summary="Create base snapshot")
async def create_base_snapshot(
    req: CreateBaseSnapshotRequest,
    user: UserIdentity = Depends(get_current_user),
    db=Depends(db_connection),
):
    """Create base snapshot with Docker, nginx, agent, and common images."""
    do_token = get_do_token()
    
    return StreamingResponse(
        sse_stream(snapshot.create_base_snapshot(
            db, user.id, req.region, do_token,
            images=req.images, size=req.size
        )),
        media_type="text/event-stream"
    )


@router.post("/snapshots/custom", summary="Create custom snapshot")
async def create_custom_snapshot(
    req: CreateCustomSnapshotRequest,
    user: UserIdentity = Depends(get_current_user),
    db=Depends(db_connection),
):
    """Create custom snapshot with app baked in."""
    do_token = get_do_token()
    git_repos = [r.dict() for r in req.git_repos] if req.git_repos else None
    
    return StreamingResponse(
        sse_stream(snapshot.create_custom_snapshot(
            db, user.id, do_token,
            git_repos=git_repos,
            dockerfile_content=req.dockerfile_content,
            snapshot_name=req.snapshot_name,
            region=req.region,
            size=req.size,
            base_snapshot_id=req.base_snapshot_id,
            test_env_variables=req.test_env_variables,
        )),
        media_type="text/event-stream"
    )


@router.delete("/snapshots/{snapshot_id}", summary="Delete snapshot")
async def delete_snapshot_route(
    snapshot_id: str,
    user: UserIdentity = Depends(get_current_user),
    db=Depends(db_connection),
):
    """Delete a snapshot."""
    do_token = get_do_token()
    return await snapshot.delete_snapshot(db, snapshot_id, do_token)


@router.get("/snapshots", summary="List snapshots")
async def list_snapshots(
    user: UserIdentity = Depends(get_current_user),
    db=Depends(db_connection),
):
    """List all snapshots for user."""
    return await snapshots.list_for_user(db, user.id)


@router.get("/snapshots/images", summary="List base images")
async def list_base_images():
    """List available base images (redis, postgres, etc.)."""
    return await snapshot.list_base_images()


# =============================================================================
# Deploy Routes
# =============================================================================

@router.post("/deploy", summary="Deploy service")
async def deploy_service_route(
    req: DeployServiceRequest,
    user: UserIdentity = Depends(get_current_user),
    db=Depends(db_connection),
):
    """Deploy a service from git repos or existing image."""
    do_token = get_do_token()
    cf_token = get_cf_token()
    git_repos = [r.dict() for r in req.git_repos] if req.git_repos else None
    
    return StreamingResponse(
        sse_stream(service.deploy_service(
            db, user.id, req.project_name, req.service_name, req.service_description,
            req.service_type, req.env_variables or [], req.env,
            do_token, cf_token,
            image_name=req.image_name,
            git_repos=git_repos,
            dockerfile_content=req.dockerfile_content,
            existing_droplet_ids=req.existing_droplet_ids,
            new_droplets_nb=req.new_droplets_nb,
            new_droplets_region=req.new_droplets_region,
            new_droplets_size=req.new_droplets_size,
            new_droplets_snapshot_id=req.new_droplets_snapshot_id,
        )),
        media_type="text/event-stream"
    )


# =============================================================================
# Service Routes
# =============================================================================

@router.post("/services/{service_id}/rollback", summary="Rollback service")
async def rollback_service(
    service_id: str,
    req: RollbackRequest,
    user: UserIdentity = Depends(get_current_user),
    db=Depends(db_connection),
):
    """Rollback to a previous version."""
    do_token = get_do_token()
    cf_token = get_cf_token()
    
    return StreamingResponse(
        sse_stream(service.rollback_service(
            db, user.id, service_id, req.target_version, req.env,
            do_token, cf_token
        )),
        media_type="text/event-stream"
    )


@router.delete("/services/{service_id}", summary="Delete service")
async def delete_service_route(
    service_id: str,
    env: str = None,
    user: UserIdentity = Depends(get_current_user),
    db=Depends(db_connection),
):
    """Delete a service (all envs or specific env)."""
    do_token = get_do_token()
    cf_token = get_cf_token()
    
    return StreamingResponse(
        sse_stream(service.delete_service(
            db, user.id, service_id, env, do_token, cf_token
        )),
        media_type="text/event-stream"
    )


@router.get("/services", summary="List services")
async def list_services(
    project_id: str = None,
    user: UserIdentity = Depends(get_current_user),
    db=Depends(db_connection),
):
    """List services."""
    if project_id:
        return await services.list_for_project(db, project_id)
    return await services.list_for_user(db, user.id)


@router.get("/services/{service_id}", summary="Get service")
async def get_service(
    service_id: str,
    user: UserIdentity = Depends(get_current_user),
    db=Depends(db_connection),
):
    """Get service details."""
    svc = await services.get(db, service_id)
    if not svc:
        raise HTTPException(404, "Service not found")
    return svc


# =============================================================================
# Scale Routes
# =============================================================================

@router.post("/services/{service_id}/scale", summary="Scale service")
async def scale_service(
    service_id: str,
    req: ScaleRequest,
    user: UserIdentity = Depends(get_current_user),
    db=Depends(db_connection),
):
    """Scale service to target count."""
    do_token = get_do_token()
    cf_token = get_cf_token()
    
    return StreamingResponse(
        sse_stream(scale.scale(
            db, user.id, service_id, req.env, req.target_count,
            do_token, cf_token, req.region, req.size, req.snapshot_id
        )),
        media_type="text/event-stream"
    )


# =============================================================================
# Project Routes
# =============================================================================

@router.get("/projects", summary="List projects")
async def list_projects(
    user: UserIdentity = Depends(get_current_user),
    db=Depends(db_connection),
):
    """List all projects."""
    return await projects.list_for_user(db, user.id)


@router.delete("/projects/{project_id}", summary="Delete project")
async def delete_project_route(
    project_id: str,
    user: UserIdentity = Depends(get_current_user),
    db=Depends(db_connection),
):
    """Delete project and all its services."""
    do_token = get_do_token()
    cf_token = get_cf_token()
    
    return StreamingResponse(
        sse_stream(project.delete_project(
            db, user.id, project_id, do_token, cf_token
        )),
        media_type="text/event-stream"
    )


# =============================================================================
# Droplet Routes
# =============================================================================

@router.post("/droplets", summary="Create droplet")
async def create_droplet_route(
    req: CreateDropletRequest,
    user: UserIdentity = Depends(get_current_user),
    db=Depends(db_connection),
):
    """Create a new droplet from snapshot."""
    do_token = get_do_token()
    return await droplet.create_droplet(
        db, user.id, req.snapshot_id, req.region, req.size, do_token
    )


@router.delete("/droplets/{droplet_id}", summary="Delete droplet")
async def delete_droplet_route(
    droplet_id: str,
    user: UserIdentity = Depends(get_current_user),
    db=Depends(db_connection),
):
    """Delete a droplet."""
    do_token = get_do_token()
    cf_token = get_cf_token()
    
    return StreamingResponse(
        sse_stream(droplet.delete_droplet(
            db, user.id, droplet_id, do_token, cf_token
        )),
        media_type="text/event-stream"
    )


@router.get("/droplets", summary="List droplets")
async def list_droplets(
    user: UserIdentity = Depends(get_current_user),
    db=Depends(db_connection),
):
    """List all droplets."""
    return await droplets.list_for_user(db, user.id)


# =============================================================================
# Deployment Routes
# =============================================================================

@router.get("/deployments", summary="List deployments")
async def list_deployments(
    service_id: str,
    env: str = None,
    user: UserIdentity = Depends(get_current_user),
    db=Depends(db_connection),
):
    """List deployments for a service."""
    return await deployments.list_for_service(db, service_id, env)


@router.get("/deployments/{deployment_id}", summary="Get deployment")
async def get_deployment(
    deployment_id: str,
    user: UserIdentity = Depends(get_current_user),
    db=Depends(db_connection),
):
    """Get deployment details."""
    dep = await deployments.get(db, deployment_id)
    if not dep:
        raise HTTPException(404, "Deployment not found")
    return dep