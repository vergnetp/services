"""
Deployment history routes.

This provides a REST API for querying deployment history.
The actual deployment is triggered via /api/v1/infra/deploy endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Optional

try:
    from shared_libs.backend.app_kernel.auth import get_current_user, UserIdentity
except ImportError:
    UserIdentity = dict
    def get_current_user(): pass

from ..deps import get_deployment_store, get_project_store
from ..stores import DeploymentStore, ProjectStore


router = APIRouter(prefix="/deployments", tags=["Deployment History"])


@router.get("")
async def list_deployments(
    project: Optional[str] = Query(None, description="Filter by project name"),
    service: Optional[str] = Query(None, description="Filter by service name"),
    env: Optional[str] = Query(None, description="Filter by environment"),
    limit: int = Query(50, ge=1, le=200),
    user: UserIdentity = Depends(get_current_user),
    deployment_store: DeploymentStore = Depends(get_deployment_store),
):
    """List deployment history."""
    deployments = await deployment_store.get_deployments(
        workspace_id=str(user.id),
        project=project,
        environment=env,
        service_name=service,
        limit=limit,
        enrich=True,
    )
    
    return {
        "deployments": [d.to_dict() for d in deployments],
        "total": len(deployments),
    }


@router.get("/{deployment_id}")
async def get_deployment(
    deployment_id: str,
    user: UserIdentity = Depends(get_current_user),
    deployment_store: DeploymentStore = Depends(get_deployment_store),
):
    """Get deployment details."""
    deployment = await deployment_store.get_deployment(deployment_id, enrich=True)
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")
    
    # Verify ownership
    if deployment.workspace_id != str(user.id):
        raise HTTPException(status_code=404, detail="Deployment not found")
    
    return deployment.to_dict()


@router.get("/project/{project}")
async def list_project_deployments(
    project: str,
    env: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    user: UserIdentity = Depends(get_current_user),
    deployment_store: DeploymentStore = Depends(get_deployment_store),
):
    """List deployments for a specific project."""
    deployments = await deployment_store.get_deployments(
        workspace_id=str(user.id),
        project=project,
        environment=env,
        limit=limit,
        enrich=True,
    )
    
    return {
        "project": project,
        "deployments": [d.to_dict() for d in deployments],
        "total": len(deployments),
    }


@router.get("/project/{project}/service/{service}")
async def list_service_deployments(
    project: str,
    service: str,
    env: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    user: UserIdentity = Depends(get_current_user),
    deployment_store: DeploymentStore = Depends(get_deployment_store),
):
    """List deployments for a specific service."""
    deployments = await deployment_store.get_deployments(
        workspace_id=str(user.id),
        project=project,
        environment=env,
        service_name=service,
        limit=limit,
        enrich=True,
    )
    
    return {
        "project": project,
        "service": service,
        "deployments": [d.to_dict() for d in deployments],
        "total": len(deployments),
    }


@router.get("/project/{project}/service/{service}/{env}/v/{version}")
async def get_deployment_by_version(
    project: str,
    service: str,
    env: str,
    version: int,
    user: UserIdentity = Depends(get_current_user),
    deployment_store: DeploymentStore = Depends(get_deployment_store),
):
    """
    Get deployment by version number.
    
    Example: GET /deployments/project/ai/service/ai-agents/prod/v/5
    """
    deployment = await deployment_store.get_by_version(
        workspace_id=str(user.id),
        project=project,
        service_name=service,
        env=env,
        version=version,
    )
    
    if not deployment:
        raise HTTPException(
            status_code=404, 
            detail=f"Version {version} not found for {project}/{service}/{env}"
        )
    
    return deployment.to_dict()


@router.get("/project/{project}/service/{service}/{env}/latest")
async def get_latest_deployment(
    project: str,
    service: str,
    env: str,
    user: UserIdentity = Depends(get_current_user),
    deployment_store: DeploymentStore = Depends(get_deployment_store),
):
    """
    Get the latest successful deployment (current live version).
    
    Example: GET /deployments/project/ai/service/ai-agents/prod/latest
    """
    latest_version = await deployment_store.get_latest_version(
        workspace_id=str(user.id),
        project=project,
        service_name=service,
        env=env,
    )
    
    if not latest_version:
        raise HTTPException(
            status_code=404, 
            detail=f"No successful deployments found for {project}/{service}/{env}"
        )
    
    deployment = await deployment_store.get_by_version(
        workspace_id=str(user.id),
        project=project,
        service_name=service,
        env=env,
        version=latest_version,
    )
    
    return deployment.to_dict()


@router.get("/project/{project}/service/{service}/{env}/versions")
async def list_versions(
    project: str,
    service: str,
    env: str,
    limit: int = Query(20, ge=1, le=100),
    user: UserIdentity = Depends(get_current_user),
    deployment_store: DeploymentStore = Depends(get_deployment_store),
):
    """
    List all versions for a coordinate.
    
    Example: GET /deployments/project/ai/service/ai-agents/prod/versions
    Returns only successful deployments (which have version numbers).
    """
    deployments = await deployment_store.get_deployments(
        workspace_id=str(user.id),
        project=project,
        environment=env,
        service_name=service,
        status="success",
        limit=limit,
        enrich=True,
    )
    
    return {
        "project": project,
        "service": service,
        "env": env,
        "versions": [
            {
                "version": d.version,
                "id": d.id,
                "deployed_at": d.started_at,
                "deployed_by": d.deployed_by_name or d.deployed_by,
                "is_rollback": d.is_rollback,
                "image_name": d.image_name,
                "git_commit": d.git_commit,
                "comment": d.comment,
            }
            for d in deployments if d.version
        ],
        "latest_version": deployments[0].version if deployments and deployments[0].version else None,
    }


@router.get("/project/{project}/service/{service}/{env}/previous")
async def get_previous_deployment(
    project: str,
    service: str,
    env: str,
    user: UserIdentity = Depends(get_current_user),
    deployment_store: DeploymentStore = Depends(get_deployment_store),
):
    """Get the previous successful deployment (for rollback)."""
    deployment = await deployment_store.get_previous(
        workspace_id=str(user.id),
        project=project,
        environment=env,
        service_name=service,
    )
    
    if not deployment:
        raise HTTPException(
            status_code=404, 
            detail=f"No previous successful deployment found for {project}/{service}/{env}"
        )
    
    return deployment.to_dict()
