"""
Backup and restore routes for stateful services.

Provides endpoints to:
- List backups (workspace-wide or per-service)
- Trigger manual backups
- Restore from backups
- Delete backups
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
    get_backup_store,
    get_service_store,
    get_service_droplet_store,
    get_droplet_store,
    get_project_store,
    get_credentials_store,
)
from ..stores import (
    BackupStore,
    ServiceStore,
    ServiceDropletStore,
    DropletStore,
    ProjectStore,
    CredentialsStore,
)


router = APIRouter(prefix="/backups", tags=["Backups"])


# =============================================================================
# Request/Response Models
# =============================================================================

class BackupTriggerRequest(BaseModel):
    """Request to trigger a manual backup."""
    env: str = "prod"
    config: Optional[Dict[str, Any]] = None  # database, user, password overrides


class BackupRestoreRequest(BaseModel):
    """Request to restore from a backup."""
    env: str = "prod"
    config: Optional[Dict[str, Any]] = None  # database, user, password overrides


class BackupResponse(BaseModel):
    """Backup record response."""
    id: str
    service_id: str
    service_type: str
    filename: str
    size_bytes: Optional[int] = None
    storage_type: str
    storage_path: str
    status: str
    error_message: Optional[str] = None
    triggered_by: str
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class BackupResultResponse(BaseModel):
    """Result of backup operation."""
    success: bool
    backup_id: Optional[str] = None
    filename: Optional[str] = None
    size_bytes: Optional[int] = None
    error: Optional[str] = None
    duration_ms: Optional[int] = None


class RestoreResultResponse(BaseModel):
    """Result of restore operation."""
    success: bool
    backup_id: str
    service_id: str
    error: Optional[str] = None
    duration_ms: Optional[int] = None


# =============================================================================
# Helper Functions
# =============================================================================

async def _get_service_with_validation(
    service_id: str,
    workspace_id: str,
    service_store: ServiceStore,
) -> dict:
    """Get service and validate it's stateful and belongs to workspace."""
    service = await service_store.get(service_id)
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    
    if service.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=404, detail="Service not found")
    
    if not service.get("is_stateful"):
        raise HTTPException(
            status_code=400, 
            detail="Service is not stateful - backups only supported for postgres, mysql, redis, mongodb"
        )
    
    return service


async def _get_agent_for_service(
    service_id: str,
    env: str,
    do_token: str,
    service_droplet_store: ServiceDropletStore,
    droplet_store: DropletStore,
):
    """Get NodeAgentClient for the server running a service."""
    from shared_libs.backend.infra.node_agent import AsyncNodeAgentClient
    
    # Get droplet running this service
    links = await service_droplet_store.get_droplets_for_service(
        service_id, env, healthy_only=True
    )
    
    if not links:
        raise HTTPException(
            status_code=404,
            detail=f"No healthy server found running this service in {env} environment"
        )
    
    # Use first healthy droplet
    link = links[0]
    droplet = await droplet_store.get(link["droplet_id"])
    
    if not droplet or not droplet.get("ip"):
        raise HTTPException(
            status_code=404,
            detail="Server IP not found"
        )
    
    # Create agent client
    agent = AsyncNodeAgentClient(
        host=droplet["ip"],
        do_token=do_token,
    )
    
    return agent, link.get("container_name")


# =============================================================================
# Endpoints
# =============================================================================

@router.get("", response_model=Dict[str, List[dict]])
async def list_backups(
    project_name: Optional[str] = Query(None, description="Filter by project name"),
    service_name: Optional[str] = Query(None, description="Filter by service name"),
    limit: int = Query(100, ge=1, le=500),
    user: UserIdentity = Depends(get_current_user),
    backup_store: BackupStore = Depends(get_backup_store),
    project_store: ProjectStore = Depends(get_project_store),
):
    """
    List all backups for the workspace.
    
    Optionally filter by project and/or service name.
    """
    workspace_id = str(user.id)
    
    # If filtering by project, get project_id first
    service_ids = None
    if project_name:
        project = await project_store.get_by_name(workspace_id, project_name)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # TODO: Could filter by project's services if needed
    
    backups = await backup_store.list_for_workspace(workspace_id, limit=limit)
    
    return {"backups": backups}


@router.get("/service/{service_id}", response_model=Dict[str, List[dict]])
async def list_service_backups(
    service_id: str,
    limit: int = Query(50, ge=1, le=200),
    user: UserIdentity = Depends(get_current_user),
    backup_store: BackupStore = Depends(get_backup_store),
    service_store: ServiceStore = Depends(get_service_store),
):
    """List all backups for a specific service."""
    workspace_id = str(user.id)
    
    # Validate service exists and belongs to user
    service = await _get_service_with_validation(service_id, workspace_id, service_store)
    
    backups = await backup_store.list_for_service(service_id, limit=limit)
    
    return {
        "service": {
            "id": service["id"],
            "name": service["name"],
            "service_type": service.get("service_type"),
        },
        "backups": backups,
    }


@router.post("/service/{service_id}/backup", response_model=BackupResultResponse, status_code=status.HTTP_201_CREATED)
async def trigger_backup(
    service_id: str,
    data: BackupTriggerRequest,
    do_token: str = Query(..., description="DigitalOcean API token"),
    user: UserIdentity = Depends(get_current_user),
    backup_store: BackupStore = Depends(get_backup_store),
    service_store: ServiceStore = Depends(get_service_store),
    service_droplet_store: ServiceDropletStore = Depends(get_service_droplet_store),
    droplet_store: DropletStore = Depends(get_droplet_store),
    project_store: ProjectStore = Depends(get_project_store),
):
    """
    Trigger a manual backup for a stateful service.
    
    Requires DO token to connect to the server running the service.
    """
    from shared_libs.backend.infra.backup import BackupService
    
    workspace_id = str(user.id)
    
    # Validate service
    service = await _get_service_with_validation(service_id, workspace_id, service_store)
    service_type = service.get("service_type")
    
    if service_type not in ("postgres", "mysql", "redis", "mongodb"):
        raise HTTPException(
            status_code=400,
            detail=f"Backup not supported for service type: {service_type}"
        )
    
    # Get project for path organization
    project = await project_store.get(service["project_id"])
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Get agent connection
    agent, container_name = await _get_agent_for_service(
        service_id, data.env, do_token,
        service_droplet_store, droplet_store
    )
    
    if not container_name:
        raise HTTPException(
            status_code=400,
            detail="Container name not found for service deployment"
        )
    
    # Create initial backup record (in_progress)
    backup_record = await backup_store.create(
        workspace_id=workspace_id,
        service_id=service_id,
        service_type=service_type,
        filename="",  # Will be updated
        storage_type="local",
        storage_path="",
        status="in_progress",
        triggered_by="manual",
    )
    
    try:
        # Execute backup
        backup_svc = BackupService()
        result = await backup_svc.backup_service(
            agent=agent,
            service_id=service_id,
            service_type=service_type,
            container_name=container_name,
            workspace_id=workspace_id,
            project=project["name"],
            service_name=service["name"],
            config=data.config or {},
        )
        
        if result.success:
            # Update backup record with results
            await backup_store.update_status(
                backup_id=backup_record["id"],
                status="completed",
                filename=result.filename,
                size_bytes=result.size_bytes,
                storage_type=result.storage_type,
                storage_path=result.storage_path,
            )
            
            return BackupResultResponse(
                success=True,
                backup_id=backup_record["id"],
                filename=result.filename,
                size_bytes=result.size_bytes,
                duration_ms=result.duration_ms,
            )
        else:
            # Update backup record with failure
            await backup_store.update_status(
                backup_id=backup_record["id"],
                status="failed",
                error_message=result.error,
            )
            
            return BackupResultResponse(
                success=False,
                backup_id=backup_record["id"],
                error=result.error,
                duration_ms=result.duration_ms,
            )
            
    except Exception as e:
        # Update backup record with failure
        await backup_store.update_status(
            backup_id=backup_record["id"],
            status="failed",
            error_message=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{backup_id}/restore", response_model=RestoreResultResponse)
async def restore_backup(
    backup_id: str,
    data: BackupRestoreRequest,
    do_token: str = Query(..., description="DigitalOcean API token"),
    user: UserIdentity = Depends(get_current_user),
    backup_store: BackupStore = Depends(get_backup_store),
    service_store: ServiceStore = Depends(get_service_store),
    service_droplet_store: ServiceDropletStore = Depends(get_service_droplet_store),
    droplet_store: DropletStore = Depends(get_droplet_store),
):
    """
    Restore a service from a backup.
    
    ⚠️ WARNING: This will overwrite the current data in the service.
    
    Requires DO token to connect to the server running the service.
    """
    from shared_libs.backend.infra.backup import BackupService
    
    workspace_id = str(user.id)
    
    # Get backup record
    backup = await backup_store.get(backup_id)
    if not backup:
        raise HTTPException(status_code=404, detail="Backup not found")
    
    if backup.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=404, detail="Backup not found")
    
    if backup.get("status") != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot restore from backup with status: {backup.get('status')}"
        )
    
    # Validate service still exists
    service_id = backup["service_id"]
    service = await _get_service_with_validation(service_id, workspace_id, service_store)
    
    # Get agent connection
    agent, container_name = await _get_agent_for_service(
        service_id, data.env, do_token,
        service_droplet_store, droplet_store
    )
    
    if not container_name:
        raise HTTPException(
            status_code=400,
            detail="Container name not found for service deployment"
        )
    
    try:
        # Execute restore
        backup_svc = BackupService()
        result = await backup_svc.restore_service(
            agent=agent,
            backup_record=backup,
            container_name=container_name,
            config=data.config or {},
        )
        
        return RestoreResultResponse(
            success=result.success,
            backup_id=backup_id,
            service_id=service_id,
            error=result.error,
            duration_ms=result.duration_ms,
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{backup_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_backup(
    backup_id: str,
    delete_file: bool = Query(True, description="Also delete backup file from storage"),
    user: UserIdentity = Depends(get_current_user),
    backup_store: BackupStore = Depends(get_backup_store),
):
    """
    Delete a backup record and optionally the backup file.
    
    By default, both the database record and storage file are deleted.
    Set delete_file=false to keep the file (e.g., for audit purposes).
    """
    from shared_libs.backend.infra.backup import BackupService
    
    workspace_id = str(user.id)
    
    # Get backup record
    backup = await backup_store.get(backup_id)
    if not backup:
        raise HTTPException(status_code=404, detail="Backup not found")
    
    if backup.get("workspace_id") != workspace_id:
        raise HTTPException(status_code=404, detail="Backup not found")
    
    # Delete file from storage if requested
    if delete_file and backup.get("storage_path"):
        try:
            backup_svc = BackupService()
            await backup_svc.storage.delete(backup["storage_path"])
        except FileNotFoundError:
            pass  # File already deleted, continue with DB cleanup
        except Exception as e:
            # Log but don't fail the request
            pass
    
    # Delete database record
    await backup_store.delete(backup_id)
