"""
Deploy Routes - Direct async streaming (no Redis/workers needed).

Pattern:
    1. Record deployment to DB (get deployment_id)
    2. Build DeployJobConfig
    3. Return StreamingResponse with async generator
    4. Generator yields events as deployment progresses
    5. Events flow directly: Deploy → Generator → SSE → Client

This is the same pattern used by provisioning and snapshot creation.
No Redis, no workers, just direct async streaming.
"""

import json
from fastapi import APIRouter, HTTPException, Query, Depends, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

from shared_libs.backend.app_kernel.auth import get_current_user, UserIdentity
from shared_libs.backend.app_kernel.db import db_connection
from shared_libs.backend.app_kernel.observability import get_logger
from shared_libs.backend.infra.deploy import (
    DeployJobConfig,
    DiscoveredService,
    InjectionContext,
    build_injection_env_vars,
    find_services_needing_redeploy,
    format_redeploy_warning,
    DockerfileGenerator,
)
from shared_libs.backend.infra.deploy.orchestrator import (
    deploy_with_streaming,
    rollback_with_streaming,
    stateful_deploy_with_streaming,
    create_snapshot_with_streaming,
)

from ..deps import get_deployment_store, get_project_store, get_service_store, get_droplet_store, get_service_droplet_store
from ..stores import DeploymentStore, ProjectStore, ServiceStore, DropletStore, ServiceDropletStore


logger = get_logger()


router = APIRouter(prefix="/infra", tags=["Deploy"])


# =============================================================================
# Dockerfile Generation - Backend generates, user can edit
# =============================================================================

class DockerfileGenerateRequest(BaseModel):
    """Request to generate a Dockerfile from file structure."""
    files: List[str] = Field(..., description="List of file paths in the upload")
    main_folder: str = Field(..., description="Main service folder (e.g., 'deploy_api')")
    dep_folders: List[str] = Field(default=[], description="Dependency folders (e.g., ['shared_libs'])")
    port: int = Field(default=8000, description="Port to expose")
    env_vars: Dict[str, str] = Field(default={}, description="Environment variables")


class DockerfileGenerateResponse(BaseModel):
    """Response with generated Dockerfile."""
    dockerfile: str
    type: str = Field(description="Detected service type (python-fastapi, node, etc.)")
    source: str = Field(default="generated", description="Always 'generated'")


@router.post("/dockerfile/generate", response_model=DockerfileGenerateResponse)
async def generate_dockerfile(
    request: DockerfileGenerateRequest,
    user: UserIdentity = Depends(get_current_user),
):
    """
    Generate a Dockerfile from uploaded file structure.
    
    Frontend workflow:
    1. User uploads files
    2. Frontend extracts file list
    3. Call this endpoint to get generated Dockerfile
    4. Show user an editable preview
    5. User modifies if needed
    6. Deploy with final Dockerfile
    """
    result = DockerfileGenerator.generate_from_structure(
        files=request.files,
        main_folder=request.main_folder,
        dep_folders=request.dep_folders,
        port=request.port,
        env_vars=request.env_vars,
    )
    
    return DockerfileGenerateResponse(
        dockerfile=result["dockerfile"],
        type=result["type"],
        source=result["source"],
    )


# =============================================================================
# Helper: Convert DB records to DiscoveredService
# =============================================================================

async def discover_stateful_services(
    service_droplet_store: ServiceDropletStore,
    service_store: ServiceStore,
    droplet_store: DropletStore,
    project_id: str,
    env: str,
) -> List[DiscoveredService]:
    """
    Query DB for stateful services in project/env.
    Returns list of DiscoveredService for use with injection module.
    
    Stateful services are scoped to project - if you need Redis,
    deploy it in the same project as the services that use it.
    """
    logger.info(
        "Discovering stateful services for auto-injection",
        project_id=project_id,
        env=env,
    )
    
    records = await service_droplet_store.get_stateful_services_for_project(
        project_id=project_id,
        env=env,
        service_store=service_store,
        droplet_store=droplet_store,
    )
    
    logger.info(
        f"📊 Database query returned {len(records)} stateful service(s)",
        records=[{
            "service_name": r.get("service_name"),
            "service_type": r.get("service_type"),
            "host": r.get("host"),
            "port": r.get("port"),
        } for r in records],
    )
    
    discovered = [
        DiscoveredService(
            service_type=r.get("service_type", ""),
            host=r.get("host", ""),
            port=r.get("port", 0),
            service_name=r.get("service_name", ""),
            service_id=r.get("service_id", ""),
        )
        for r in records
    ]
    
    return discovered


# =============================================================================
# Helper: Wrap stream to capture and save final result
# =============================================================================

async def stream_and_save_result(
    stream_fn,
    job_config: DeployJobConfig,
    deployment_store: DeploymentStore,
    deployment_id: str,
    # For service_droplet recording
    service_store: ServiceStore = None,
    service_droplet_store: ServiceDropletStore = None,
    droplet_store: DropletStore = None,
    project_id: str = None,
    workspace_id: str = None,
):
    """
    Wrap streaming deploy to:
    1. Yield events to client
    2. Collect log messages for persistence
    3. Capture final 'done' event
    4. Save result and logs to deployment record
    5. Save to service_droplets for service mesh
    6. Warn about apps needing redeploy (for stateful service deploys)
    
    NOTE: Uses try/finally to ensure status is saved even if client disconnects!
    """
    final_result = None
    collected_logs = []  # Collect log entries for persistence
    client_disconnected = False
    
    try:
        async for event in stream_fn(job_config):
            event_dict = event.to_dict()
            yield f"data: {json.dumps(event_dict)}\n\n"
            
            # Collect log/error/progress events for persistence
            if event.type in ("log", "error", "progress"):
                collected_logs.append({
                    "type": event.type,
                    "message": event.message,
                    "timestamp": event.timestamp,
                    **(event.data or {}),
                })
            
            # Capture done event - save immediately in case client disconnects
            if event.type == "done":
                final_result = event.data
                # Save result RIGHT AWAY before yielding more
                from datetime import datetime, timezone
                success = final_result.get("success", False)
                await deployment_store.update_deployment(
                    deployment_id=deployment_id,
                    status="success" if success else "failed",
                    completed_at=datetime.now(timezone.utc).isoformat(),
                    result=final_result,
                    logs=collected_logs,
                )
                # Continue to record service_droplets and yield warnings
    except GeneratorExit:
        # Client disconnected - mark this so we don't try to save twice
        client_disconnected = True
        # If we already got the done event and saved, we're good
        # If not, mark as interrupted
        if not final_result:
            import logging
            logging.warning(f"Client disconnected before deployment {deployment_id} completed - marking as interrupted")
            from datetime import datetime, timezone
            await deployment_store.update_deployment(
                deployment_id=deployment_id,
                status="interrupted",
                completed_at=datetime.now(timezone.utc).isoformat(),
                result={"error": "Client disconnected before completion"},
                logs=collected_logs,
            )
        raise  # Re-raise to properly close the generator
    
    # Service_droplet recording (only if success and stores provided)
    if final_result and final_result.get("success", False):
        # Record to service_droplets for service mesh / auto-injection
        if service_droplet_store and service_store and droplet_store and project_id:
            try:
                # Get or create service record
                service = await service_store.get_or_create(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    name=job_config.name,
                    port=job_config.port,
                    is_stateful=job_config.is_stateful,
                    service_type=job_config.name.lower() if job_config.is_stateful else "app",
                )
                
                # Get droplet from server IP
                server_ip = final_result.get("server_ip") or (job_config.server_ips[0] if job_config.server_ips else None)
                if server_ip:
                    droplet = await droplet_store.get_by_ip(workspace_id, server_ip)
                    if droplet:
                        # Record the deployment location with port info
                        await service_droplet_store.link(
                            workspace_id=workspace_id,
                            service_id=service["id"],
                            droplet_id=droplet["id"],
                            env=job_config.environment,
                            container_name=final_result.get("container") or job_config.name,
                            host_port=final_result.get("port") or job_config.port,
                            container_port=job_config.port,
                        )
                
                # For stateful deploys, warn about existing apps that need redeploy
                if job_config.is_stateful:
                    existing_apps = await service_store.list_for_project(project_id)
                    non_stateful_apps = [
                        app for app in existing_apps 
                        if not app.get("is_stateful") and app.get("name") != job_config.name
                    ]
                    if non_stateful_apps:
                        app_names = [app.get("name") for app in non_stateful_apps]
                        warning = f"⚠️ Existing services should be redeployed to get {job_config.name.upper()}_URL: {', '.join(app_names)}"
                        # Emit warning event
                        yield f"data: {json.dumps({'type': 'warning', 'data': {'message': warning}})}\n\n"
                        
            except Exception as e:
                # Don't fail deploy if recording fails
                import logging
                logging.warning(f"Failed to record service_droplet: {e}")


# =============================================================================
# Request Models
# =============================================================================

class DeployRequest(BaseModel):
    """Deployment request."""
    # Required
    name: str = Field(..., description="Service name")
    
    # Deployment type
    deployment_type: str = Field("service", description="service, worker, or snapshot")
    snapshot_name: Optional[str] = Field(None, description="For snapshot type: name for the snapshot")
    
    # Project context
    project: Optional[str] = Field(None, description="Project name")
    environment: str = Field("prod", description="Environment")
    
    # Source
    source_type: str = Field("image", description="image, git, code, image_file")
    image: Optional[str] = Field(None, description="Docker image")
    git_url: Optional[str] = Field(None, description="Git repo URL")
    git_branch: str = Field("main", description="Git branch")
    git_token: Optional[str] = Field(None, description="Git auth token")
    git_folders: Optional[List[Dict[str, Any]]] = Field(None, description="Git folders")
    dockerfile: Optional[str] = Field(None, description="Dockerfile content")
    code_tar_b64: Optional[str] = Field(None, description="Base64 code tar")
    image_tar_b64: Optional[str] = Field(None, description="Base64 image tar")
    exclude_patterns: Optional[List[str]] = Field(None, description="Exclude patterns")
    
    # Infrastructure
    server_ips: List[str] = Field(default_factory=list, description="Server IPs")
    new_server_count: int = Field(0, description="New servers to provision")
    snapshot_id: Optional[str] = Field(None, description="Snapshot ID")
    region: str = Field("lon1", description="Region")
    size: str = Field("s-1vcpu-1gb", description="Server size")
    
    # Container
    port: int = Field(8000, description="Container port")
    container_port: Optional[int] = Field(None, description="Internal port")
    host_port: Optional[int] = Field(None, description="External port")
    env_vars: Dict[str, str] = Field(default_factory=dict, description="Env vars")
    tags: List[str] = Field(default_factory=list, description="Tags")
    
    # Service mesh
    depends_on: List[str] = Field(default_factory=list, description="Dependencies")
    setup_sidecar: bool = Field(True, description="Setup nginx sidecar")
    is_stateful: bool = Field(False, description="Is stateful service")
    
    # Domain
    setup_domain: bool = Field(False, description="Auto-provision domain")
    base_domain: str = Field("digitalpixo.com", description="Base domain")
    domain_aliases: List[str] = Field(default_factory=list, description="Aliases")
    
    # Meta
    comment: Optional[str] = Field(None, description="Deployment comment")


class RollbackRequest(BaseModel):
    """Rollback request."""
    deployment_id: Optional[str] = Field(None, description="Target deployment ID")
    version: Optional[int] = Field(None, description="Target version")
    server_ips: List[str] = Field(default_factory=list, description="Specific servers")
    comment: Optional[str] = Field(None, description="Comment")


class StatefulDeployRequest(BaseModel):
    """Stateful service deployment request."""
    name: str = Field(..., description="Service type: postgres, redis, etc")
    server_ip: str = Field(..., description="Server IP")
    project: Optional[str] = Field(None, description="Project name")
    environment: str = Field("prod", description="Environment")
    env_vars: Dict[str, str] = Field(default_factory=dict, description="Env vars")
    port: Optional[int] = Field(None, description="Override port")


# =============================================================================
# Helpers
# =============================================================================

def _get_do_token(do_token: str = None) -> str:
    if do_token:
        return do_token.strip()  # Remove any whitespace
    raise HTTPException(400, "DigitalOcean token required")


def _build_config_snapshot(req: DeployRequest) -> Dict[str, Any]:
    """Build config snapshot for deployment record (masks secrets)."""
    return {
        "deployment_type": req.deployment_type,
        "snapshot_name": req.snapshot_name,
        "source_type": req.source_type,
        "git_url": req.git_url,
        "git_branch": req.git_branch,
        "git_folders": req.git_folders,
        "exclude_patterns": req.exclude_patterns,
        "image": req.image,
        "dockerfile": req.dockerfile[:100] if req.dockerfile else None,
        "port": req.port,
        "container_port": req.container_port,
        "host_port": req.host_port,
        "env_vars": {k: "***" if "secret" in k.lower() or "password" in k.lower() else v 
                    for k, v in (req.env_vars or {}).items()},
        "tags": req.tags or [],
        "server_ips": req.server_ips or [],
        "snapshot_id": req.snapshot_id,
        "region": req.region,
        "size": req.size,
        "setup_domain": req.setup_domain,
        "base_domain": req.base_domain,
    }


# =============================================================================
# Deploy Routes
# =============================================================================

@router.post("/deploy/multipart")
async def deploy_multipart(
    # File upload - param name must match form field name 'code_tar'
    code_tar: Optional[UploadFile] = File(None),
    # Query params
    do_token: str = Query(...),
    cf_token: Optional[str] = Query(None),
    # Form fields (or query params for compatibility)
    name: str = Form(None),
    service_name: str = Query(None),  # Alias
    project: Optional[str] = Query(None),
    environment: str = Query("prod"),
    source_type: str = Form("code"),
    image: Optional[str] = Form(None),
    server_ips: Optional[str] = Form(None),  # Comma-separated or JSON
    new_server_count: int = Query(0),
    snapshot_id: Optional[str] = Query(None),
    region: str = Query("lon1"),
    size: str = Query("s-1vcpu-1gb"),
    port: int = Form(8000),
    env_vars: Optional[str] = Form(None),  # JSON string
    is_stateful: str = Form("false"),  # String from form, will parse to bool
    setup_domain: bool = Query(False),
    base_domain: str = Query("digitalpixo.com"),
    domain_aliases: Optional[str] = Query(None),  # JSON array string
    dockerfile: Optional[str] = Form(None),
    comment: Optional[str] = Form(None),
    user: UserIdentity = Depends(get_current_user),
    db = Depends(db_connection),
    deployment_store: DeploymentStore = Depends(get_deployment_store),
    project_store: ProjectStore = Depends(get_project_store),
    service_store: ServiceStore = Depends(get_service_store),
    droplet_store: DropletStore = Depends(get_droplet_store),
    service_droplet_store: ServiceDropletStore = Depends(get_service_droplet_store),
):
    """
    Deploy with file upload (multipart form).
    
    For code deployments where files are uploaded as tar/zip.
    Auto-injects URLs for all stateful services in the same project.
    """
    import json as json_mod
    import base64
    
    token = _get_do_token(do_token)
    workspace_id = str(user.id)
    
    # Parse is_stateful from string (form data sends strings)
    parsed_is_stateful = is_stateful.lower() in ('true', '1', 'yes')
    
    # Parse name (accept either form field or query param)
    svc_name = name or service_name
    if not svc_name:
        raise HTTPException(400, "Service name required (name or service_name)")
    
    # Parse server_ips
    parsed_server_ips = []
    if server_ips:
        try:
            parsed_server_ips = json_mod.loads(server_ips)
        except:
            parsed_server_ips = [ip.strip() for ip in server_ips.split(",") if ip.strip()]
    
    # Parse env_vars
    parsed_env_vars = {}
    if env_vars:
        try:
            parsed_env_vars = json_mod.loads(env_vars)
        except:
            pass
    
    # Parse domain_aliases
    parsed_aliases = []
    if domain_aliases:
        try:
            parsed_aliases = json_mod.loads(domain_aliases)
        except:
            pass
    
    # Read uploaded file
    code_tar_b64 = None
    if code_tar:
        content = await code_tar.read()
        code_tar_b64 = base64.b64encode(content).decode()
    
    # Get or create project
    project_name = project or "default"
    project_entity = await project_store.get_by_name(workspace_id, project_name)
    if not project_entity:
        project_entity = await project_store.create(workspace_id, project_name)
    project_id = project_entity["id"]
    
    # Auto-inject URLs for stateful services in this project
    auto_injected_env = {}
    discovered = await discover_stateful_services(
        service_droplet_store=service_droplet_store,
        service_store=service_store,
        droplet_store=droplet_store,
        project_id=project_id,
        env=environment,
    )
    
    logger.info(
        f"Stateful service discovery for project={project_name}, env={environment}",
        discovered_count=len(discovered) if discovered else 0,
        discovered_services=[s.get("service_name") for s in (discovered or [])],
    )
    
    if discovered:
        auto_injected_env = build_injection_env_vars(
            user=workspace_id,
            project=project_name,
            env=environment,
            discovered_services=discovered,
        )
        logger.info(
            f"đŸ'‰ Auto-injected env vars",
            injected_vars=list(auto_injected_env.keys()),
            injected_values={k: v[:20] + "..." if len(v) > 20 else v for k, v in auto_injected_env.items()},
        )
    else:
        logger.warning(f"⚠️ No stateful services discovered for project={project_name}, env={environment}")
    
    # Merge auto-injected with user-provided (user takes precedence)
    final_env_vars = {**auto_injected_env, **parsed_env_vars}
    
    logger.info(
        f"🔧 Final env vars for {svc_name}",
        total_vars=len(final_env_vars),
        auto_injected=len(auto_injected_env),
        user_provided=len(parsed_env_vars),
        has_redis_url="REDIS_URL" in final_env_vars,
        has_database_url="DATABASE_URL" in final_env_vars,
    )
    
    # Build DeployRequest
    req = DeployRequest(
        name=svc_name,
        project=project_name,
        environment=environment,
        source_type=source_type,
        image=image,
        server_ips=parsed_server_ips,
        new_server_count=new_server_count,
        snapshot_id=snapshot_id,
        region=region,
        size=size,
        port=port,
        env_vars=final_env_vars,
        is_stateful=parsed_is_stateful,
        setup_domain=setup_domain,
        base_domain=base_domain,
        domain_aliases=parsed_aliases,
        dockerfile=dockerfile,
        code_tar_b64=code_tar_b64,
        comment=comment,
    )
    
    # 1. Record deployment to DB
    record = await deployment_store.record_deployment(
        workspace_id=workspace_id,
        project=project_name,
        environment=req.environment,
        service_name=req.name,
        source_type=req.source_type,
        image_name=req.image if req.source_type == "image" else None,
        git_url=None,
        git_branch=None,
        server_ips=req.server_ips or [],
        port=req.port,
        env_vars=final_env_vars,
        user_env_vars=parsed_env_vars,  # Store user-provided only (for rollback)
        deployed_by=workspace_id,
        comment=req.comment,
        config_snapshot=_build_config_snapshot(req),
    )
    
    # 2. Build job config
    job_config = DeployJobConfig(
        name=req.name,
        workspace_id=workspace_id,
        do_token=token,
        project=project_name,
        environment=req.environment,
        source_type=req.source_type,
        image=req.image,
        dockerfile=req.dockerfile,
        code_tar_b64=req.code_tar_b64,
        server_ips=req.server_ips,
        new_server_count=req.new_server_count,
        snapshot_id=req.snapshot_id,
        region=req.region,
        size=req.size,
        port=req.port,
        env_vars=final_env_vars,
        setup_sidecar=True,
        is_stateful=req.is_stateful,
        setup_domain=req.setup_domain,
        base_domain=req.base_domain,
        domain_aliases=req.domain_aliases,
        cloudflare_token=cf_token,
        deployment_id=record.id,
    )
    
    # 3. Stream deployment with result saving
    if req.is_stateful:
        stream_fn = stateful_deploy_with_streaming
    else:
        stream_fn = deploy_with_streaming
    
    return StreamingResponse(
        stream_and_save_result(
            stream_fn=stream_fn,
            job_config=job_config,
            deployment_store=deployment_store,
            deployment_id=record.id,
            service_store=service_store,
            service_droplet_store=service_droplet_store,
            droplet_store=droplet_store,
            project_id=project_id,
            workspace_id=workspace_id,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# =============================================================================
# Deploy Route (THIN - ~40 lines)
# =============================================================================

@router.post("/deploy")
async def deploy(
    req: DeployRequest,
    do_token: str = Query(..., description="DO token"),
    cf_token: Optional[str] = Query(None, description="Cloudflare token"),
    user: UserIdentity = Depends(get_current_user),
    db = Depends(db_connection),
    deployment_store: DeploymentStore = Depends(get_deployment_store),
    project_store: ProjectStore = Depends(get_project_store),
    service_store: ServiceStore = Depends(get_service_store),
    droplet_store: DropletStore = Depends(get_droplet_store),
    service_droplet_store: ServiceDropletStore = Depends(get_service_droplet_store),
):
    """
    Deploy service to servers.
    
    Returns SSE stream with progress.
    Auto-injects URLs for all stateful services in the same project.
    """
    token = _get_do_token(do_token)
    workspace_id = str(user.id)
    
    # Get or create project
    project_name = req.project or "default"
    project = await project_store.get_by_name(workspace_id, project_name)
    if not project:
        project = await project_store.create(workspace_id, project_name)
    project_id = project["id"]
    
    # Auto-inject URLs for stateful services in this project/env
    # (only for non-stateful deploys - stateful services don't need this)
    auto_injected_env = {}
    if not req.is_stateful:
        discovered = await discover_stateful_services(
            service_droplet_store=service_droplet_store,
            service_store=service_store,
            droplet_store=droplet_store,
            project_id=project_id,
            env=req.environment,
        )
        if discovered:
            auto_injected_env = build_injection_env_vars(
                user=workspace_id,
                project=project_name,
                env=req.environment,
                discovered_services=discovered,
            )
    
    # Merge auto-injected with user-provided (user takes precedence)
    final_env_vars = {**auto_injected_env, **(req.env_vars or {})}
    
    # 1. Record deployment to DB
    record = await deployment_store.record_deployment(
        workspace_id=workspace_id,
        project=project_name,
        environment=req.environment,
        service_name=req.name,
        source_type=req.source_type,
        image_name=req.image if req.source_type == "image" else None,
        git_url=req.git_url if req.source_type == "git" else None,
        git_branch=req.git_branch,
        server_ips=req.server_ips or [],
        port=req.port,
        env_vars=final_env_vars,
        user_env_vars=req.env_vars or {},  # Store user-provided only (for rollback)
        deployed_by=workspace_id,
        comment=req.comment,
        config_snapshot=_build_config_snapshot(req),
    )
    
    # 2. Build job config
    job_config = DeployJobConfig(
        name=req.name,
        workspace_id=workspace_id,
        do_token=token,
        deployment_type=req.deployment_type,
        snapshot_name=req.snapshot_name,
        project=project_name,
        environment=req.environment,
        source_type=req.source_type,
        image=req.image,
        git_url=req.git_url,
        git_branch=req.git_branch,
        git_token=req.git_token,
        git_folders=req.git_folders,
        dockerfile=req.dockerfile,
        code_tar_b64=req.code_tar_b64,
        image_tar_b64=req.image_tar_b64,
        exclude_patterns=req.exclude_patterns,
        server_ips=req.server_ips or [],
        new_server_count=req.new_server_count,
        snapshot_id=req.snapshot_id,
        region=req.region,
        size=req.size,
        port=req.port,
        container_port=req.container_port,
        host_port=req.host_port,
        env_vars=final_env_vars,
        tags=req.tags or [],
        depends_on=req.depends_on or [],
        setup_sidecar=req.setup_sidecar,
        is_stateful=req.is_stateful,
        setup_domain=req.setup_domain,
        cloudflare_token=cf_token,
        base_domain=req.base_domain,
        domain_aliases=req.domain_aliases or [],
        deployment_id=record.id,
        comment=req.comment,
        deployed_by=workspace_id,
    )
    
    # 3. Stream deployment with result saving
    # Select stream function based on deployment_type
    if req.deployment_type == "snapshot":
        stream_fn = create_snapshot_with_streaming
    elif req.is_stateful:
        stream_fn = stateful_deploy_with_streaming
    else:
        stream_fn = deploy_with_streaming
    
    # For snapshots, skip service_droplet recording (no service to track)
    skip_service_recording = req.deployment_type == "snapshot"
    
    return StreamingResponse(
        stream_and_save_result(
            stream_fn=stream_fn,
            job_config=job_config,
            deployment_store=deployment_store,
            deployment_id=record.id,
            service_store=None if skip_service_recording else service_store,
            service_droplet_store=None if skip_service_recording else service_droplet_store,
            droplet_store=None if skip_service_recording else droplet_store,
            project_id=None if skip_service_recording else project_id,
            workspace_id=workspace_id,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# =============================================================================
# Rollback Route (THIN - ~50 lines)
# =============================================================================

@router.post("/deployments/rollback")
async def rollback(
    project: str = Query(..., description="Project name"),
    environment: str = Query(..., description="Environment"),
    service_name: str = Query(..., description="Service name"),
    req: RollbackRequest = None,
    do_token: str = Query(..., description="DO token"),
    user: UserIdentity = Depends(get_current_user),
    deployment_store: DeploymentStore = Depends(get_deployment_store),
    project_store: ProjectStore = Depends(get_project_store),
    service_store: ServiceStore = Depends(get_service_store),
    droplet_store: DropletStore = Depends(get_droplet_store),
    service_droplet_store: ServiceDropletStore = Depends(get_service_droplet_store),
):
    """
    Rollback service to previous deployment.
    
    Returns SSE stream with progress.
    Re-discovers stateful services for fresh connection URLs.
    """
    req = req or RollbackRequest()
    token = _get_do_token(do_token)
    workspace_id = str(user.id)
    
    # Find target deployment
    target = None
    if req.deployment_id:
        target = await deployment_store.get_deployment(req.deployment_id)
        if not target or target.workspace_id != workspace_id:
            raise HTTPException(404, "Deployment not found")
    elif req.version is not None:
        target = await deployment_store.get_by_version(
            workspace_id=workspace_id,
            project=project,
            service_name=service_name,
            env=environment,
            version=req.version,
        )
        if not target:
            raise HTTPException(404, f"Version {req.version} not found")
    else:
        target = await deployment_store.get_previous(
            workspace_id=workspace_id,
            project=project,
            environment=environment,
            service_name=service_name,
        )
        if not target:
            raise HTTPException(404, "No previous deployment found")
    
    if not target.image_name:
        raise HTTPException(400, "Cannot rollback: no image recorded")
    if not target.server_ips:
        raise HTTPException(400, "Cannot rollback: no servers recorded")
    
    server_ips = req.server_ips if req.server_ips else target.server_ips
    
    # Re-discover stateful services for FRESH connection URLs
    # (stateful services may have moved to different IPs since original deployment)
    project_entity = await project_store.get_by_name(workspace_id, project)
    auto_injected_env = {}
    if project_entity:
        discovered = await discover_stateful_services(
            service_droplet_store=service_droplet_store,
            service_store=service_store,
            droplet_store=droplet_store,
            project_id=project_entity["id"],
            env=environment,
        )
        if discovered:
            auto_injected_env = build_injection_env_vars(
                user=workspace_id,
                project=project,
                env=environment,
                discovered_services=discovered,
            )
            logger.info(
                f"🔄 Rollback: re-discovered stateful services",
                discovered_count=len(discovered),
                injected_vars=list(auto_injected_env.keys()),
            )
    
    # Use user_env_vars from target deployment (excludes auto-injected)
    # This preserves user secrets while getting fresh stateful service URLs
    user_env_vars = target.user_env_vars or {}
    final_env_vars = {**auto_injected_env, **user_env_vars}
    
    # Record rollback deployment
    record = await deployment_store.record_deployment(
        workspace_id=workspace_id,
        project=project,
        environment=environment,
        service_name=service_name,
        source_type="image",
        image_name=target.image_name,
        server_ips=server_ips,
        port=target.port or 8000,
        env_vars=final_env_vars,
        user_env_vars=user_env_vars,  # Preserve user vars for future rollbacks
        deployed_by=workspace_id,
        comment=req.comment or f"Rollback to v{target.version}" if target.version else f"Rollback to {target.id[:8]}",
        is_rollback=True,
        rollback_from_id=target.id,
        source_version=target.version,
    )
    
    # Build job config
    job_config = DeployJobConfig(
        name=service_name,
        workspace_id=workspace_id,
        do_token=token,
        project=project,
        environment=environment,
        source_type="image",
        image=target.image_name,
        server_ips=server_ips,
        port=target.port or 8000,
        env_vars=final_env_vars,
        deployment_id=record.id,
        skip_pull=True,
        is_rollback=True,
        rollback_from_id=target.id,
    )
    
    # Stream rollback using shared helper (saves logs and result)
    return StreamingResponse(
        stream_and_save_result(
            stream_fn=rollback_with_streaming,
            job_config=job_config,
            deployment_store=deployment_store,
            deployment_id=record.id,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# =============================================================================
# Stateful Deploy Route (THIN - ~30 lines)
# =============================================================================

@router.post("/deploy/stateful")
async def deploy_stateful(
    req: StatefulDeployRequest,
    do_token: str = Query(..., description="DO token"),
    user: UserIdentity = Depends(get_current_user),
    db = Depends(db_connection),
    deployment_store: DeploymentStore = Depends(get_deployment_store),
    project_store: ProjectStore = Depends(get_project_store),
    service_store: ServiceStore = Depends(get_service_store),
    droplet_store: DropletStore = Depends(get_droplet_store),
    service_droplet_store: ServiceDropletStore = Depends(get_service_droplet_store),
):
    """
    Deploy stateful service (postgres, redis, etc).
    
    Returns SSE stream with progress.
    Records service for auto-injection into other deploys.
    """
    from shared_libs.backend.infra.deploy import get_stateful_image, get_service_container_port
    
    token = _get_do_token(do_token)
    workspace_id = str(user.id)
    
    # Get image and port for service type
    image = get_stateful_image(req.name)
    if not image:
        raise HTTPException(400, f"Unknown stateful service: {req.name}")
    port = req.port or get_service_container_port(req.name)
    
    # Get or create project
    project_name = req.project or "default"
    project = await project_store.get_by_name(workspace_id, project_name)
    if not project:
        project = await project_store.create(workspace_id, project_name)
    project_id = project["id"]
    
    # Record deployment
    record = await deployment_store.record_deployment(
        workspace_id=workspace_id,
        project=project_name,
        environment=req.environment,
        service_name=req.name,
        source_type="image",
        image_name=image,
        server_ips=[req.server_ip],
        port=port,
        env_vars=req.env_vars or {},
        deployed_by=workspace_id,
    )
    
    # Build job config
    job_config = DeployJobConfig(
        name=req.name,
        workspace_id=workspace_id,
        do_token=token,
        project=project_name,
        environment=req.environment,
        source_type="image",
        image=image,
        server_ips=[req.server_ip],
        port=port,
        env_vars=req.env_vars or {},
        deployment_id=record.id,
        is_stateful=True,
        skip_pull=True,  # Images pre-loaded in snapshot
    )
    
    # Stream stateful deploy with result saving
    return StreamingResponse(
        stream_and_save_result(
            stream_fn=stateful_deploy_with_streaming,
            job_config=job_config,
            deployment_store=deployment_store,
            deployment_id=record.id,
            service_store=service_store,
            service_droplet_store=service_droplet_store,
            droplet_store=droplet_store,
            project_id=project_id,
            workspace_id=workspace_id,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
