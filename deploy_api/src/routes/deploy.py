"""
Deployment routes - deploy, rollback with SSE streaming.

Thin wrappers around src/deploy.py logic.
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from ..deps import db_connection, get_current_user, require_do_token, require_cf_token

router = APIRouter(prefix="/deploy", tags=["deploy"])


# =============================================================================
# Request/Response Models
# =============================================================================

class DeployRequest(BaseModel):
    """Request to deploy a service."""
    project_id: str
    service_name: str
    env: str = "prod"
    image_name: str
    env_variables: Optional[dict] = None
    droplet_ids: Optional[List[str]] = None  # If None, uses existing or provisions new
    domain: Optional[str] = None
    

class RollbackRequest(BaseModel):
    """Request to rollback a deployment."""
    deployment_id: str


class DeploymentStatusResponse(BaseModel):
    """Deployment status response."""
    id: str
    service_id: str
    version: int
    env: str
    status: str
    image_name: str
    droplet_ids: list
    is_rollback: bool
    error: Optional[str] = None
    triggered_by: str
    triggered_at: datetime
    created_at: datetime


# =============================================================================
# Routes
# =============================================================================

@router.post("")
async def deploy(
    request: DeployRequest,
    db=Depends(db_connection),
    user=Depends(get_current_user),
    do_token: str = Depends(require_do_token),
    cf_token: str = Depends(require_cf_token),
):
    """
    Deploy a service. Returns SSE stream with progress updates.
    
    Events:
    - status: Deployment status updates
    - log: Log messages
    - error: Error messages
    - complete: Deployment finished
    """
    from ..deploy import create_deployment_stream
    
    async def event_generator():
        async for event in create_deployment_stream(
            db=db,
            workspace_id=user.id,
            project_id=request.project_id,
            service_name=request.service_name,
            env=request.env,
            image_name=request.image_name,
            env_variables=request.env_variables,
            droplet_ids=request.droplet_ids,
            domain=request.domain,
            do_token=do_token,
            cf_token=cf_token,
            triggered_by=user.email,
        ):
            yield event
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.post("/rollback")
async def rollback(
    request: RollbackRequest,
    db=Depends(db_connection),
    user=Depends(get_current_user),
    do_token: str = Depends(require_do_token),
    cf_token: str = Depends(require_cf_token),
):
    """
    Rollback to a previous deployment. Returns SSE stream.
    """
    from ..deploy import create_rollback_stream
    
    async def event_generator():
        async for event in create_rollback_stream(
            db=db,
            deployment_id=request.deployment_id,
            do_token=do_token,
            cf_token=cf_token,
            triggered_by=user.email,
        ):
            yield event
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.get("/history/{service_id}")
async def get_deployment_history(
    service_id: str,
    env: Optional[str] = None,
    limit: int = 20,
    db=Depends(db_connection),
    user=Depends(get_current_user),
):
    """Get deployment history for a service."""
    from ..stores import deployments
    
    results = await deployments.list_for_service(
        db, 
        service_id=service_id, 
        env=env, 
        limit=limit
    )
    return {"deployments": results}


@router.get("/status/{deployment_id}")
async def get_deployment_status(
    deployment_id: str,
    db=Depends(db_connection),
    user=Depends(get_current_user),
):
    """Get status of a specific deployment."""
    from ..stores import deployments
    
    deployment = await deployments.get(db, deployment_id)
    if not deployment:
        raise HTTPException(404, "Deployment not found")
    
    return deployment


@router.get("/latest/{service_id}")
async def get_latest_deployment(
    service_id: str,
    env: str = "prod",
    db=Depends(db_connection),
    user=Depends(get_current_user),
):
    """Get the latest successful deployment for a service."""
    from ..stores import deployments
    
    deployment = await deployments.get_latest(
        db, 
        service_id=service_id, 
        env=env, 
        status="success"
    )
    if not deployment:
        raise HTTPException(404, "No successful deployment found")
    
    return deployment
