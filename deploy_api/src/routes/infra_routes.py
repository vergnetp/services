"""
Infrastructure API Routes - Thin layer over infra services.

All business logic lives in shared_libs.backend.infra.
This file only handles HTTP request/response.

Auth: All endpoints require JWT bearer token (except presets).
DO token: Stored per-user or passed in request (pass-through mode).
"""

import os
from fastapi import APIRouter, HTTPException, Query, Depends, UploadFile, File, Form, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from starlette.responses import StreamingResponse
import json

router = APIRouter(prefix="/infra", tags=["Infrastructure"])


# ==========================================
# Auth
# ==========================================

from shared_libs.backend.app_kernel.auth import get_current_user, UserIdentity


# ==========================================
# Credentials Helpers
# ==========================================

def _get_do_token(do_token: str = None) -> str:
    """
    Get DO token from request parameter.
    This is a thin wrapper - no database storage.
    Token must be passed with each request via query param or body.
    """
    if do_token:
        return do_token
    
    raise HTTPException(
        400, 
        "DigitalOcean token required. Pass do_token as query parameter."
    )


def _get_node_agent_key(do_token: str, user_id) -> str:
    """Derive node agent API key from DO token and user ID."""
    from shared_libs.backend.infra.cloud import generate_node_agent_key
    return generate_node_agent_key(do_token, str(user_id))


def _build_deploy_env(
    user_id: str,
    project: str,
    environment: str,
    service: str,
    depends_on: List[str],
    base_env_vars: Dict[str, str],
) -> Dict[str, str]:
    """Build env vars with auto-injected service discovery."""
    from shared_libs.backend.infra.deploy import DeployEnvBuilder, is_stateful_service
    
    # Check if this IS a stateful service (postgres, redis, etc.)
    if is_stateful_service(service):
        # Build env vars for the service itself (POSTGRES_USER, etc.)
        builder = DeployEnvBuilder(
            user=user_id,
            project=project,
            env=environment,
            service=service,
            base_env_vars=base_env_vars,
        )
        return builder.build_stateful_service_env()
    
    # Regular service - inject connection strings for dependencies
    builder = DeployEnvBuilder(
        user=user_id,
        project=project,
        env=environment,
        service=service,
        base_env_vars=base_env_vars,
    )
    
    for dep in depends_on:
        builder.add_dependency(dep)
    
    return builder.build_env_vars()


def _build_deploy_volumes(
    user_id: str,
    project: str,
    environment: str,
    service: str,
    persist_data: bool,
    custom_volumes: List[str],
) -> List[str]:
    """Build volume mounts for deployment."""
    volumes = list(custom_volumes)  # Start with custom volumes
    
    if persist_data:
        from shared_libs.backend.infra.deploy import build_deploy_volumes
        auto_volumes = build_deploy_volumes(user_id, project, environment, service)
        volumes.extend(auto_volumes)
    
    return volumes


async def _ensure_nginx_on_server(client, log_fn=None):
    """
    Ensure nginx is running on the server.
    Thin wrapper around client.ensure_nginx_running().
    """
    try:
        if log_fn:
            log_fn("🔧 Setting up nginx on server...")
        
        result = await client.ensure_nginx_running()
        
        if result.success:
            status = result.data.get("status", "started")
            if status == "already_running":
                if log_fn:
                    log_fn("✅ Nginx already running")
            else:
                if log_fn:
                    log_fn("✅ Nginx started on ports 80/443")
            return True
        else:
            if log_fn:
                log_fn(f"⚠️ Nginx setup failed: {result.error}")
            return False
            
    except Exception as e:
        if log_fn:
            log_fn(f"⚠️ Nginx setup error: {e}")
        return False


async def _setup_service_nginx_config(
    client,
    user_id: str,
    project: str,
    environment: str,
    service: str,
    container_name: str,
    container_port: int,
    is_stateful: bool = False,
    backends: List[Dict[str, Any]] = None,
    mode: str = "single_server",
    log_fn=None,
):
    """
    Set up nginx sidecar config for a service.
    Thin wrapper around NginxService.setup_service_sidecar().
    """
    from shared_libs.backend.infra.networking import NginxService
    
    nginx = NginxService(client, log=log_fn)
    result = await nginx.setup_service_sidecar(
        user_id=user_id,
        project=project,
        environment=environment,
        service=service,
        container_name=container_name,
        container_port=container_port,
        is_stateful=is_stateful,
        backends=backends,
        mode=mode,
    )
    
    if result.success:
        return result.data
    return None


async def _update_sidecar_backends(
    client,
    user_id: str,
    project: str,
    environment: str,
    service: str,
    backends: List[Dict[str, Any]],
    log_fn=None,
):
    """
    Update nginx sidecar config with new backends.
    Thin wrapper around NginxService.update_sidecar_backends().
    """
    from shared_libs.backend.infra.networking import NginxService
    
    nginx = NginxService(client, log=log_fn)
    result = await nginx.update_sidecar_backends(
        user_id=user_id,
        project=project,
        environment=environment,
        service=service,
        backends=backends,
    )
    
    if result.success:
        return result.data
    return None


async def _ensure_data_directories(client, volumes: List[str], log_fn=None):
    """
    Create host directories for volume mounts.
    Thin wrapper around NginxService.ensure_data_directories().
    """
    from shared_libs.backend.infra.networking import NginxService
    
    nginx = NginxService(client, log=log_fn)
    await nginx.ensure_data_directories(volumes)


async def _setup_nginx_http_lb(
    client,
    name: str,
    backends: List[Dict[str, Any]],
    listen_port: int = 80,
    domain: str = None,
    lb_method: str = "least_conn",
    health_check: bool = True,
    log_fn=None,
):
    """
    Set up nginx HTTP load balancer.
    Thin wrapper around NginxService.setup_http_lb().
    """
    from shared_libs.backend.infra.networking import NginxService
    
    nginx = NginxService(client, log=log_fn)
    result = await nginx.setup_http_lb(
        name=name,
        backends=backends,
        listen_port=listen_port,
        domain=domain,
        lb_method=lb_method,
        health_check=health_check,
    )
    
    if result.success:
        return result.data
    return None


async def _remove_nginx_lb(client, name: str, log_fn=None):
    """
    Remove an nginx LB config.
    Thin wrapper around NginxService.remove_http_lb().
    """
    from shared_libs.backend.infra.networking import NginxService
    
    nginx = NginxService(client, log=log_fn)
    result = await nginx.remove_http_lb(name)
    return result.success


async def _update_nginx_lb_backends(
    client,
    name: str,
    backends: List[Dict[str, Any]],
    log_fn=None,
):
    """
    Update backends for an existing nginx LB.
    Thin wrapper around NginxService.update_http_lb_backends().
    """
    from shared_libs.backend.infra.networking import NginxService
    
    nginx = NginxService(client, log=log_fn)
    result = await nginx.update_http_lb_backends(
        name=name,
        backends=backends,
    )
    
    if result.success:
        return result.data
    return None


# ==========================================
# Prepare Session Store (two-phase deploy)
# ==========================================

import time
import threading
from dataclasses import dataclass, field
from typing import List
import uuid

@dataclass
class PrepareSession:
    """Session for two-phase deployment."""
    session_id: str
    user_id: str
    ready_ips: List[str]
    api_key: str
    created_at: float
    ttl: float = 300  # 5 minutes
    
    def is_expired(self) -> bool:
        return time.time() - self.created_at > self.ttl


class PrepareSessionStore:
    """In-memory store for prepare sessions with TTL."""
    
    def __init__(self):
        self._sessions: Dict[str, PrepareSession] = {}
        self._lock = threading.Lock()
    
    def create(self, user_id: str, ready_ips: List[str], api_key: str) -> PrepareSession:
        """Create a new session."""
        session_id = str(uuid.uuid4())
        session = PrepareSession(
            session_id=session_id,
            user_id=user_id,
            ready_ips=ready_ips,
            api_key=api_key,
            created_at=time.time(),
        )
        with self._lock:
            self._cleanup_expired()
            self._sessions[session_id] = session
        return session
    
    def get(self, session_id: str, user_id: str) -> Optional[PrepareSession]:
        """Get session if valid and owned by user."""
        with self._lock:
            self._cleanup_expired()
            session = self._sessions.get(session_id)
            if session and session.user_id == user_id and not session.is_expired():
                return session
            return None
    
    def consume(self, session_id: str, user_id: str) -> Optional[PrepareSession]:
        """Get and delete session (one-time use)."""
        with self._lock:
            self._cleanup_expired()
            session = self._sessions.get(session_id)
            if session and session.user_id == user_id and not session.is_expired():
                del self._sessions[session_id]
                return session
            return None
    
    def _cleanup_expired(self):
        """Remove expired sessions."""
        expired = [k for k, v in self._sessions.items() if v.is_expired()]
        for k in expired:
            del self._sessions[k]


# Global session store
_prepare_store: Optional[PrepareSessionStore] = None

def get_prepare_store() -> PrepareSessionStore:
    global _prepare_store
    if _prepare_store is None:
        _prepare_store = PrepareSessionStore()
    return _prepare_store


# ==========================================
# Request/Response Models
# ==========================================

class SnapshotConfigModel(BaseModel):
    """Snapshot configuration."""
    name: str = "docker-ready-ubuntu-24"
    install_docker: bool = True
    apt_packages: List[str] = []
    pip_packages: List[str] = []
    docker_images: List[str] = []
    custom_commands: List[str] = []
    install_node_agent: bool = True
    node_agent_api_key: Optional[str] = None  # Auto-derived from DO token + user_id


class EnsureSnapshotRequest(BaseModel):
    """Request to ensure snapshot exists."""
    do_token: Optional[str] = None  # Pass-through mode (not stored)
    region: str = "lon1"
    size: str = "s-1vcpu-1gb"
    config: SnapshotConfigModel = Field(default_factory=SnapshotConfigModel)
    force_recreate: bool = False
    cleanup_on_failure: bool = True
    remove_ssh_key: bool = True  # Remove deployer SSH key from DO after snapshot creation


class ProvisionRequest(BaseModel):
    """Request to provision a server."""
    do_token: Optional[str] = None  # Pass-through mode (not stored)
    name: str = ""  # Empty = generate friendly name
    region: str = "lon1"
    size: str = "s-1vcpu-1gb"
    snapshot_id: str  # Required - must use a snapshot
    ssh_keys: List[str] = []
    tags: List[str] = []
    vpc_uuid: Optional[str] = None  # Auto-created if not specified
    project: Optional[str] = None  # Project name for filtering (e.g., "deploy-api")
    environment: str = "prod"  # Environment (prod, staging, dev)


class AgentDeployRequest(BaseModel):
    """Request to deploy via node agent."""
    do_token: Optional[str] = None  # Pass-through mode (not stored)
    server_ip: str
    image: str
    name: str
    ports: Dict[str, str] = {}
    env_vars: Dict[str, str] = {}
    volumes: List[str] = []


class SetCredentialsRequest(BaseModel):
    """Request to store credentials."""
    do_token: str


# ==========================================
# Credentials Endpoints (thin wrapper - no storage)
# ==========================================

@router.post("/credentials")
async def set_credentials(
    req: SetCredentialsRequest,
    user: UserIdentity = Depends(get_current_user),
):
    """
    Validate DO token and return node agent key.
    Note: Token is NOT stored on server - pass with each request.
    """
    from shared_libs.backend.infra.cloud import generate_node_agent_key
    agent_key = generate_node_agent_key(req.do_token, str(user.id))
    
    return {
        "success": True,
        "message": "Token validated (not stored - pass with each request)",
        "node_agent_key": agent_key,
    }


@router.get("/credentials")
async def get_credentials_status(
    do_token: str = Query(None, description="DO token for pass-through"),
    user: UserIdentity = Depends(get_current_user),
):
    """Check if DO token is provided (via query param or cookie)."""
    has_do_token = do_token is not None and len(do_token) > 10
    
    result = {"has_do_token": has_do_token}
    
    if has_do_token:
        from shared_libs.backend.infra.cloud import generate_node_agent_key
        result["node_agent_key"] = generate_node_agent_key(do_token, str(user.id))
        result["user_id"] = str(user.id)  # Debug: show user_id being used
    
    return result


@router.delete("/credentials")
async def delete_credentials(user: UserIdentity = Depends(get_current_user)):
    """No-op - credentials are stored client-side only."""
    return {"success": True, "message": "Clear token from browser storage"}


# ==========================================
# Credentials
# ==========================================

@router.get("/credentials")
async def get_credentials(
    do_token: str = Query(..., description="DO token"),
    user: UserIdentity = Depends(get_current_user),
):
    """Get derived credentials for debugging (e.g., node agent API key)."""
    token = _get_do_token(do_token)
    agent_key = _get_node_agent_key(token, str(user.id))
    
    return {
        "agent_key": agent_key,
        "user_id": str(user.id),
        "token_prefix": token[:8] + "...",
    }


# ==========================================
# Setup / Initialization
# ==========================================

@router.get("/setup/status")
async def get_setup_status(
    do_token: str = Query(..., description="DO token"),
    user: UserIdentity = Depends(get_current_user),
):
    """Check if base snapshot exists and is ready."""
    from shared_libs.backend.infra.cloud import SnapshotService
    
    token = _get_do_token(do_token)
    service = SnapshotService(token)
    snapshots = service.list_snapshots()
    
    # Look for base snapshot (created by us)
    base_snapshot = None
    for s in snapshots:
        name = s.get("name", "")
        if name.startswith("base-") or name == "base-docker-ubuntu":
            base_snapshot = s
            break
    
    if not base_snapshot:
        return {
            "ready": False,
            "status": "no_snapshot",
            "message": "No base snapshot found. Run setup to create one.",
        }
    
    regions = base_snapshot.get("regions", [])
    all_regions = ["nyc1", "nyc3", "ams3", "sfo2", "sfo3", "sgp1", "lon1", "fra1", "tor1", "blr1", "syd1"]
    
    return {
        "ready": True,
        "status": "ready",
        "snapshot": {
            "id": base_snapshot.get("id"),
            "name": base_snapshot.get("name"),
            "regions": regions,
            "all_regions": len(regions) >= len(all_regions),
        },
        "message": f"Base snapshot ready in {len(regions)} region(s)",
    }


@router.post("/setup/init/stream")
async def init_setup_stream(
    do_token: str = Query(..., description="DO token"),
    user: UserIdentity = Depends(get_current_user),
):
    """
    Initialize environment: create base snapshot and transfer to all regions.
    Returns SSE stream with progress.
    """
    from shared_libs.backend.infra.cloud import (
        SnapshotService, SnapshotConfig, SNAPSHOT_PRESETS, 
        generate_node_agent_key
    )
    from fastapi.responses import StreamingResponse
    import json
    import threading
    import queue
    
    token = _get_do_token(do_token)
    api_key = generate_node_agent_key(token, str(user.id))
    msg_queue = queue.Queue()
    
    def setup_worker():
        """Run setup in background thread."""
        def log(msg):
            msg_queue.put({'type': 'log', 'message': msg})
        
        def progress(pct):
            msg_queue.put({'type': 'progress', 'percent': pct})
        
        try:
            log('🚀 Starting environment setup...')
            progress(5)
            
            service = SnapshotService(token)
            
            # Check if base snapshot already exists
            snapshots = service.list_snapshots()
            base_snapshot = None
            for s in snapshots:
                name = s.get("name", "")
                if name.startswith("base-") or name == "base-docker-ubuntu":
                    base_snapshot = s
                    break
            
            if base_snapshot:
                snap_name = base_snapshot.get('name')
                log(f'✅ Base snapshot already exists: {snap_name}')
                snapshot_id = base_snapshot.get("id")
            else:
                # Create base snapshot with streaming logs
                log('📦 Creating base snapshot (this takes 5-10 minutes)...')
                progress(10)
                
                # Get base preset config
                preset = SNAPSHOT_PRESETS.get("base", SNAPSHOT_PRESETS["minimal"])
                preset_config = preset["config"]
                
                # Import agent version for snapshot naming
                from shared_libs.backend.infra.node_agent import AGENT_VERSION
                snapshot_name = f"base-agent-v{AGENT_VERSION.replace('.', '-')}"
                
                config = SnapshotConfig(
                    name=snapshot_name,
                    install_docker=preset_config.install_docker,
                    apt_packages=preset_config.apt_packages,
                    pip_packages=preset_config.pip_packages,
                    docker_images=preset_config.docker_images,
                    node_agent_api_key=api_key,
                )
                
                # Use streaming version for detailed logs
                # NOTE: cleanup_on_failure=False keeps droplet for SSH debugging on error
                snapshot_id = None
                for event in service.ensure_snapshot_stream(config, region="lon1", cleanup_on_failure=False):
                    msg_queue.put(event)
                    if event.get('type') == 'done':
                        data = event.get('data', {})
                        if data.get('success'):
                            snapshot_id = data.get('snapshot_id')
                        else:
                            raise Exception(data.get('error', 'Snapshot creation failed'))
                
                if not snapshot_id:
                    raise Exception('No snapshot ID returned')
            
            progress(60)
            
            # Transfer to all regions
            all_regions = ["nyc1", "nyc3", "ams3", "sfo2", "sfo3", "sgp1", "lon1", "fra1", "tor1", "blr1", "syd1"]
            
            # Check current regions
            snapshots = service.list_snapshots()
            current_snapshot = next((s for s in snapshots if str(s.get("id")) == str(snapshot_id)), None)
            current_regions = current_snapshot.get("regions", []) if current_snapshot else []
            
            missing_regions = [r for r in all_regions if r not in current_regions]
            
            if missing_regions:
                log(f'🌍 Transferring to {len(missing_regions)} regions...')
                
                # Wait for DO API to propagate the new snapshot, then retry
                import time
                transfer_success = False
                for attempt in range(3):
                    time.sleep(5)  # Wait 5 seconds between attempts
                    
                    try:
                        result = service.transfer_snapshot_to_all_regions(snapshot_id, wait=False)
                        transferring = len(result.get('transferring_to', []))
                        log(f'✅ Transfer initiated to {transferring} regions (runs in background)')
                        transfer_success = True
                        break
                    except Exception as e:
                        if attempt < 2:
                            log(f'⏳ Waiting for snapshot to be available (attempt {attempt + 1}/3)...')
                        else:
                            log(f'⚠️ Transfer failed after 3 attempts: {str(e)}')
                            log('💡 You can manually transfer via "All Regions" button later')
            else:
                log('✅ Snapshot already available in all regions')
            
            progress(100)
            msg_queue.put({'type': 'done', 'success': True, 'snapshot_id': snapshot_id})
            
        except Exception as e:
            msg_queue.put({'type': 'error', 'message': str(e)})
            msg_queue.put({'type': 'done', 'success': False, 'error': str(e)})
        
        msg_queue.put({'type': '__END__'})
    
    # Start worker thread
    thread = threading.Thread(target=setup_worker, daemon=True)
    thread.start()
    
    def generate():
        """Generate SSE events from queue."""
        while True:
            try:
                event = msg_queue.get(timeout=1)
                if event.get('type') == '__END__':
                    break
                yield f"data: {json.dumps(event)}\n\n"
            except queue.Empty:
                yield ": keepalive\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/info")
async def get_info():
    """Get infra API info (no auth required)."""
    return {
        "version": "1.0",
        "auth_required": True,
    }


# ==========================================
# Container Registry
# ==========================================

@router.get("/registry")
async def get_registry(
    do_token: str = Query(..., description="DO token"),
    user: UserIdentity = Depends(get_current_user),
):
    """Get container registry info."""
    from shared_libs.backend.infra.cloud import DOClient
    
    token = _get_do_token(do_token)
    client = DOClient(token)
    registry = client.get_registry()
    
    if not registry:
        return {"exists": False, "registry": None}
    
    return {
        "exists": True,
        "registry": registry,
        "endpoint": client.get_registry_endpoint(),
    }


@router.post("/registry")
async def create_registry(
    do_token: str = Query(..., description="DO token"),
    region: str = Query("fra1", description="Registry region"),
    user: UserIdentity = Depends(get_current_user),
):
    """Create or get existing container registry."""
    from shared_libs.backend.infra.cloud import DOClient
    
    token = _get_do_token(do_token)
    client = DOClient(token)
    registry = client.ensure_registry(region=region)
    
    return {
        "registry": registry,
        "endpoint": client.get_registry_endpoint(),
    }


@router.get("/registry/repositories")
async def list_repositories(
    do_token: str = Query(..., description="DO token"),
    user: UserIdentity = Depends(get_current_user),
):
    """List repositories in registry."""
    from shared_libs.backend.infra.cloud import DOClient
    
    token = _get_do_token(do_token)
    client = DOClient(token)
    repos = client.list_registry_repositories()
    
    return {"repositories": repos}


@router.get("/registry/credentials")
async def get_registry_credentials(
    do_token: str = Query(..., description="DO token"),
    user: UserIdentity = Depends(get_current_user),
):
    """Get Docker credentials for registry login."""
    from shared_libs.backend.infra.cloud import DOClient
    
    token = _get_do_token(do_token)
    client = DOClient(token)
    
    # Make sure registry exists
    registry = client.get_registry()
    if not registry:
        raise HTTPException(400, "No registry exists. Create one first.")
    
    creds = client.get_registry_credentials()
    
    return {
        "endpoint": client.get_registry_endpoint(),
        "credentials": creds,
    }


# ==========================================
# Base Image Builder
# ==========================================

class ImageBuildRequest(BaseModel):
    """Request to build a base image and bake into snapshot."""
    name: str  # Snapshot name, e.g. "ocr-ready"
    template: str  # "python", "node", "python-node"
    apt_packages: List[str] = []
    pip_packages: List[str] = []  # Only for python templates
    npm_packages: List[str] = []  # Only for node templates
    extra_docker_images: List[str] = []  # Additional images to pre-pull


@router.post("/images/build/stream")
async def build_image_stream(
    req: ImageBuildRequest,
    do_token: str = Query(..., description="DO token"),
    user: UserIdentity = Depends(get_current_user),
):
    """
    Build a custom snapshot from the base snapshot.
    Returns SSE stream with progress.
    """
    from shared_libs.backend.infra.cloud import SnapshotService
    import json
    import threading
    import queue
    
    token = _get_do_token(do_token)
    msg_queue = queue.Queue()
    
    # Generate Dockerfile from request
    dockerfile = generate_dockerfile(req)
    
    def build_worker():
        """Run build in background thread, emit events to queue."""
        service = SnapshotService(token)
        
        for event in service.build_custom_snapshot_stream(
            name=req.name,
            dockerfile=dockerfile,
            extra_images=req.extra_docker_images,
            region="lon1",
        ):
            msg_queue.put(event)
        
        msg_queue.put({'type': '__END__'})
    
    # Start worker thread
    thread = threading.Thread(target=build_worker, daemon=True)
    thread.start()
    
    def generate():
        """Generate SSE events from queue."""
        while True:
            try:
                event = msg_queue.get(timeout=1)
                if event.get('type') == '__END__':
                    break
                yield f"data: {json.dumps(event)}\n\n"
            except queue.Empty:
                yield ": keepalive\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def generate_dockerfile(req: ImageBuildRequest) -> str:
    """Generate Dockerfile from template."""
    lines = []
    
    if req.template == "python":
        lines.append("FROM python:3.11-slim")
    elif req.template == "node":
        lines.append("FROM node:20-slim")
    elif req.template == "python-node":
        lines.append("FROM python:3.11-slim")
        lines.append("RUN apt-get update && apt-get install -y curl && \\")
        lines.append("    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \\")
        lines.append("    apt-get install -y nodejs && \\")
        lines.append("    rm -rf /var/lib/apt/lists/*")
    else:
        raise HTTPException(400, f"Unknown template: {req.template}")
    
    # APT packages
    if req.apt_packages:
        apt_list = " ".join(req.apt_packages)
        lines.append(f"RUN apt-get update && apt-get install -y {apt_list} && rm -rf /var/lib/apt/lists/*")
    
    # Pip packages
    if req.pip_packages and req.template in ("python", "python-node"):
        pip_list = " ".join(req.pip_packages)
        lines.append(f"RUN pip install --no-cache-dir {pip_list}")
    
    # NPM packages
    if req.npm_packages and req.template in ("node", "python-node"):
        npm_list = " ".join(req.npm_packages)
        lines.append(f"RUN npm install -g {npm_list}")
    
    lines.append("WORKDIR /app")
    
    return "\n".join(lines)


@router.get("/images")
async def list_images(
    do_token: str = Query(..., description="DO token"),
    user: UserIdentity = Depends(get_current_user),
):
    """List base image snapshots (snapshots with built-in custom images)."""
    from shared_libs.backend.infra.cloud import DOClient
    
    token = _get_do_token(do_token)
    client = DOClient(token)
    
    # Get all snapshots, filter for ones that look like base images
    snapshots = client.list_snapshots()
    
    # Base image snapshots have format: name-tag (e.g., ocr-ready-base)
    # Exclude standard base snapshots (base-docker-ubuntu, base-agent-v*)
    images = []
    for s in snapshots:
        name = s.get("name", "")
        if name.startswith("base-docker-ubuntu") or name.startswith("base-agent-"):
            continue  # Skip standard base snapshots
        if "-" in name and not name.startswith("base-"):
            images.append({
                "name": name,
                "id": s.get("id"),
                "size_gb": s.get("size_gigabytes", 0),
                "regions": s.get("regions", []),
                "created_at": s.get("created_at"),
            })
    
    return {"images": images}


# ==========================================
# Snapshot Endpoints
# ==========================================

@router.get("/snapshots/presets")
async def list_snapshot_presets():
    """List available snapshot presets."""
    from shared_libs.backend.infra.cloud import SNAPSHOT_PRESETS, get_preset_info
    
    return {
        "presets": {name: get_preset_info(name) for name in SNAPSHOT_PRESETS.keys()},
        "default": "standard",
    }


@router.post("/snapshots/ensure-preset/{preset_name}")
async def ensure_snapshot_from_preset(
    preset_name: str,
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None, description="Pass-through mode (not stored)"),
    region: str = Query("lon1"),
    size: str = Query("s-1vcpu-1gb"),
    force_recreate: bool = Query(False),
    extra_docker_images: Optional[str] = Query(None),
    extra_apt_packages: Optional[str] = Query(None),
    extra_pip_packages: Optional[str] = Query(None),
):
    """Create snapshot from preset with optional additions."""
    from shared_libs.backend.infra.cloud import SNAPSHOT_PRESETS, get_preset, SnapshotConfig, SnapshotService, generate_node_agent_key
    
    token = _get_do_token(do_token)
    
    if preset_name not in SNAPSHOT_PRESETS:
        raise HTTPException(400, f"Unknown preset: {preset_name}")
    
    preset_config = get_preset(preset_name)
    
    # Build config from preset with extras
    docker_images = list(preset_config.docker_images)
    apt_packages = list(preset_config.apt_packages)
    pip_packages = list(preset_config.pip_packages)
    
    if extra_docker_images:
        docker_images.extend([x.strip() for x in extra_docker_images.split(",") if x.strip()])
    if extra_apt_packages:
        apt_packages.extend([x.strip() for x in extra_apt_packages.split(",") if x.strip()])
    if extra_pip_packages:
        pip_packages.extend([x.strip() for x in extra_pip_packages.split(",") if x.strip()])
    
    # Use deterministic API key from DO token + user_id
    api_key = generate_node_agent_key(token, str(user.id))
    
    config = SnapshotConfig(
        name=f"docker-{preset_name}-ubuntu-24",
        docker_images=docker_images,
        apt_packages=apt_packages,
        pip_packages=pip_packages,
        install_node_agent=preset_config.install_node_agent,
        node_agent_api_key=api_key,
    )
    
    service = SnapshotService(token)
    result = service.ensure_snapshot(config, region, size, force_recreate)
    
    return {
        "success": result.success,
        "snapshot_id": result.snapshot_id,
        "snapshot_name": result.snapshot_name,
        "api_key": result.api_key,
        "created": result.created,
        "message": result.message,
        "error": result.error,
    }


@router.post("/snapshots/ensure-preset/{preset_name}/stream")
async def ensure_snapshot_from_preset_stream(
    preset_name: str,
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None, description="Pass-through mode (not stored)"),
    region: str = Query("lon1"),
    size: str = Query("s-1vcpu-1gb"),
    force_recreate: bool = Query(False),
    remove_ssh_key: bool = Query(True),
):
    """Create snapshot from preset with SSE streaming progress."""
    from shared_libs.backend.infra.cloud import SNAPSHOT_PRESETS, get_preset, SnapshotConfig, SnapshotService, generate_node_agent_key
    
    token = _get_do_token(do_token)
    
    if preset_name not in SNAPSHOT_PRESETS:
        raise HTTPException(400, f"Unknown preset: {preset_name}")
    
    preset_config = get_preset(preset_name)
    api_key = generate_node_agent_key(token, str(user.id))
    
    config = SnapshotConfig(
        name=f"docker-{preset_name}-ubuntu-24",
        docker_images=list(preset_config.docker_images),
        apt_packages=list(preset_config.apt_packages),
        pip_packages=list(preset_config.pip_packages),
        install_node_agent=preset_config.install_node_agent,
        node_agent_api_key=api_key,
    )
    
    service = SnapshotService(token)
    
    def generate():
        for event in service.ensure_snapshot_stream(config, region, size, force_recreate, True, remove_ssh_key):
            event_type = event.get("type", "log")
            if event_type == "log":
                yield f"data: {json.dumps({'type': 'log', 'message': event.get('message', '')})}\n\n"
            elif event_type == "progress":
                yield f"data: {json.dumps({'type': 'progress', 'step': event.get('step'), 'total': event.get('total')})}\n\n"
            elif event_type == "done":
                yield f"data: {json.dumps({'type': 'done', 'data': event.get('data', {})})}\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/snapshots/ensure/stream")
async def ensure_snapshot_stream(
    req: EnsureSnapshotRequest,
    do_token: str = Query(None, description="DO token"),
    user: UserIdentity = Depends(get_current_user),
):
    """Create snapshot with SSE streaming progress."""
    from shared_libs.backend.infra.cloud import SnapshotConfig, SnapshotService, generate_node_agent_key
    
    token = _get_do_token(do_token or req.do_token)
    
    # Use deterministic API key from DO token + user_id
    api_key = req.config.node_agent_api_key or generate_node_agent_key(token, str(user.id))
    
    config = SnapshotConfig(
        name=req.config.name,
        install_docker=req.config.install_docker,
        apt_packages=req.config.apt_packages,
        pip_packages=req.config.pip_packages,
        docker_images=req.config.docker_images,
        custom_commands=req.config.custom_commands,
        install_node_agent=req.config.install_node_agent,
        node_agent_api_key=api_key,
    )
    
    service = SnapshotService(token)
    
    def generate():
        for event in service.ensure_snapshot_stream(
            config, req.region, req.size, req.force_recreate, req.cleanup_on_failure, req.remove_ssh_key
        ):
            event_type = event.get("type", "log")
            if event_type == "log":
                yield f"data: {json.dumps({'type': 'log', 'message': event.get('message', '')})}\n\n"
            elif event_type == "progress":
                yield f"data: {json.dumps({'type': 'progress', **event})}\n\n"
            elif event_type == "done":
                data = event.get("data", {})
                if data.get("success"):
                    yield f"data: {json.dumps({'type': 'complete', **data})}\n\n"
                else:
                    error_data = {
                        'type': 'error',
                        'message': data.get('error', 'Unknown error'),
                    }
                    # Include droplet_ip if droplet was kept for debugging
                    if data.get('droplet_ip'):
                        error_data['droplet_ip'] = data['droplet_ip']
                    yield f"data: {json.dumps(error_data)}\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/snapshots/ensure")
async def ensure_snapshot(
    req: EnsureSnapshotRequest,
    do_token: str = Query(None, description="DO token"),
    user: UserIdentity = Depends(get_current_user),
):
    """Ensure snapshot exists (blocking)."""
    from shared_libs.backend.infra.cloud import SnapshotConfig, SnapshotService, generate_node_agent_key
    
    token = _get_do_token(do_token or req.do_token)
    
    # Use deterministic API key from DO token + user_id
    api_key = req.config.node_agent_api_key or generate_node_agent_key(token, str(user.id))
    
    config = SnapshotConfig(
        name=req.config.name,
        install_docker=req.config.install_docker,
        apt_packages=req.config.apt_packages,
        pip_packages=req.config.pip_packages,
        docker_images=req.config.docker_images,
        custom_commands=req.config.custom_commands,
        install_node_agent=req.config.install_node_agent,
        node_agent_api_key=api_key,
    )
    
    service = SnapshotService(token)
    result = service.ensure_snapshot(
        config, req.region, req.size, req.force_recreate, req.cleanup_on_failure, req.remove_ssh_key
    )
    
    return {
        "success": result.success,
        "snapshot_id": result.snapshot_id,
        "snapshot_name": result.snapshot_name,
        "api_key": result.api_key,
        "created": result.created,
        "message": result.message,
        "error": result.error,
    }


@router.post("/snapshots/preview-script")
async def preview_snapshot_script(config: SnapshotConfigModel):
    """Preview cloud-init script without creating anything."""
    from shared_libs.backend.infra.cloud import CloudInitConfig, build_cloudinit_script
    
    cloudinit_config = CloudInitConfig(
        install_docker=config.install_docker,
        apt_packages=config.apt_packages,
        pip_packages=config.pip_packages,
        docker_images=config.docker_images if config.install_docker else [],
        custom_commands=config.custom_commands,
        install_node_agent=config.install_node_agent,
        node_agent_api_key=config.node_agent_api_key,
    )
    
    user_data, api_key = build_cloudinit_script(cloudinit_config)
    
    return {
        "script_length": len(user_data),
        "script": user_data,
        "api_key": api_key,
    }


@router.get("/snapshots")
async def list_snapshots(
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None, description="Pass-through mode (not stored)"),
):
    """List all snapshots."""
    from shared_libs.backend.infra.cloud import SnapshotService
    
    token = _get_do_token(do_token)
    service = SnapshotService(token)
    snapshots = service.list_snapshots()
    
    return {
        "snapshots": [
            {
                "id": s.get("id"),
                "name": s.get("name"),
                "regions": s.get("regions", []),
                "size_gigabytes": s.get("size_gigabytes"),
                "created_at": s.get("created_at"),
            }
            for s in snapshots
        ]
    }


@router.delete("/snapshots/{snapshot_id}")
async def delete_snapshot(
    snapshot_id: str,
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None, description="Pass-through mode (not stored)"),
):
    """Delete a snapshot."""
    from shared_libs.backend.infra.cloud import SnapshotService
    
    token = _get_do_token(do_token)
    service = SnapshotService(token)
    success = service.delete_snapshot(snapshot_id)
    
    if not success:
        raise HTTPException(500, "Failed to delete snapshot")
    
    return {"success": True, "deleted": snapshot_id}


@router.post("/snapshots/{snapshot_id}/transfer-all")
async def transfer_snapshot_to_all_regions(
    snapshot_id: str,
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None, description="Pass-through mode (not stored)"),
    wait: bool = Query(False, description="Wait for all transfers to complete (slow!)"),
):
    """
    Transfer a snapshot to all available regions.
    
    This makes the snapshot available everywhere for provisioning.
    Transfers happen in parallel and typically take 5-15 minutes per region.
    """
    from shared_libs.backend.infra.cloud import DOClient
    
    token = _get_do_token(do_token)
    client = DOClient(token)
    
    result = client.transfer_snapshot_to_all_regions(snapshot_id, wait=wait)
    
    return {
        "success": True,
        "snapshot_id": result["snapshot_id"],
        "snapshot_name": result["snapshot_name"],
        "already_available_in": result["already_in"],
        "transferring_to": result["transferring_to"],
        "actions": result["actions"],
        "message": f"Snapshot transfer initiated to {len(result['transferring_to'])} regions" if result["transferring_to"] else "Snapshot already available in all regions",
    }


@router.post("/snapshots/{snapshot_id}/transfer")
async def transfer_snapshot_to_region(
    snapshot_id: str,
    region: str = Query(..., description="Target region slug (e.g., nyc1)"),
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None, description="Pass-through mode (not stored)"),
    wait: bool = Query(False, description="Wait for transfer to complete"),
):
    """Transfer a snapshot to a specific region."""
    from shared_libs.backend.infra.cloud import DOClient
    
    token = _get_do_token(do_token)
    client = DOClient(token)
    
    action = client.transfer_snapshot(snapshot_id, region, wait=wait)
    
    return {
        "success": True,
        "snapshot_id": snapshot_id,
        "target_region": region,
        "action_id": action.get("id"),
        "status": action.get("status", "in-progress"),
    }


@router.get("/actions/{action_id}")
async def get_action_status(
    action_id: int,
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None),
):
    """Get status of a DO action (transfer, snapshot, etc.)."""
    from shared_libs.backend.infra.cloud import DOClient
    
    token = _get_do_token(do_token)
    client = DOClient(token)
    
    action = client.get_action(action_id)
    
    return {
        "id": action.get("id"),
        "status": action.get("status"),
        "type": action.get("type"),
        "started_at": action.get("started_at"),
        "completed_at": action.get("completed_at"),
        "region_slug": action.get("region_slug"),
    }


# ==========================================
# Server/Droplet Endpoints
# ==========================================

@router.get("/servers")
async def list_servers(
    user: UserIdentity = Depends(get_current_user),
    project: Optional[str] = Query(None, description="Filter by project name"),
    environment: Optional[str] = Query(None, description="Filter by environment (prod, staging, dev)"),
    tag: Optional[str] = Query("deployed-via-api", description="Filter by tag (default: deployed-via-api, use 'all' for no filter)"),
    region: Optional[str] = Query(None, description="Filter by region (e.g. lon1, nyc1)"),
    size: Optional[str] = Query(None, description="Filter by size (e.g. s-1vcpu-1gb)"),
    status: Optional[str] = Query(None, description="Filter by status (e.g. active, new)"),
    do_token: Optional[str] = Query(None, description="Pass-through mode (not stored)"),
):
    """List droplets with optional filtering by project, environment, region, etc."""
    from shared_libs.backend.infra.cloud import DOClient
    
    token = _get_do_token(do_token)
    client = DOClient(token)
    
    # Handle tag filtering:
    # - 'all': Show all droplets (no tag filter)
    # - None or default: Use project filter if specified, else 'deployed-via-api'
    # - specific tag: Use that tag
    if tag == 'all':
        filter_tag = None
        filter_project = project
    elif project:
        # Project filter takes priority - don't pass default tag
        filter_tag = None
        filter_project = project
    else:
        filter_tag = tag  # Default: 'deployed-via-api'
        filter_project = None
    
    # Use DOClient with project/environment filtering
    droplets = client.list_droplets(
        project=filter_project,
        environment=environment,
        tag=filter_tag,
    )
    
    # Convert to response format
    result = []
    for d in droplets:
        d_dict = d.to_dict()
        
        # Apply additional filters (region, size, status)
        if region and d_dict.get('region') != region:
            continue
        if size and d_dict.get('size') != size:
            continue
        if status and d_dict.get('status') != status:
            continue
        
        result.append(d_dict)
    
    return {
        "servers": result,
        "filters": {
            "project": project,
            "environment": environment,
            "tag": tag,
            "region": region,
            "size": size,
            "status": status,
        },
        "total_unfiltered": len(droplets)
    }


@router.get("/projects")
async def list_projects(
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None, description="Pass-through mode (not stored)"),
):
    """Get list of unique projects from deployed servers."""
    from shared_libs.backend.infra.cloud import DOClient
    
    token = _get_do_token(do_token)
    client = DOClient(token)
    
    # Get all droplets (no filter)
    droplets = client.list_droplets(tag="deployed-via-api")
    
    # Extract unique projects and environments
    projects = set()
    environments = set()
    
    for d in droplets:
        if d.project:
            projects.add(d.project)
        if d.environment:
            environments.add(d.environment)
    
    return {
        "projects": sorted(list(projects)),
        "environments": sorted(list(environments)),
    }


@router.get("/containers")
async def list_containers(
    user: UserIdentity = Depends(get_current_user),
    project: Optional[str] = Query(None, description="Filter by project"),
    environment: Optional[str] = Query(None, description="Filter by environment"),
    do_token: Optional[str] = Query(None, description="Pass-through mode"),
):
    """Get list of containers across all servers (for logs view)."""
    from shared_libs.backend.infra.cloud import DOClient
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    
    token = _get_do_token(do_token)
    api_key = _get_node_agent_key(token, str(user.id))
    client = DOClient(token)
    
    # Get servers filtered by project/environment
    if project:
        droplets = client.list_droplets(project=project, environment=environment)
    else:
        droplets = client.list_droplets(tag="deployed-via-api", environment=environment)
    
    # Get containers from each server
    containers_by_server = {}
    for d in droplets:
        if not d.ip or not d.is_active:
            continue
        
        try:
            agent = NodeAgentClient(d.ip, api_key)
            result = await agent.list_containers()
            if result.success:
                containers_by_server[d.ip] = {
                    "server_name": d.name,
                    "project": d.project,
                    "environment": d.environment,
                    "containers": result.data.get("containers", [])
                }
        except:
            pass
    
    return {
        "servers": containers_by_server,
        "filters": {"project": project, "environment": environment}
    }


@router.post("/servers/provision")
async def provision_server(
    req: ProvisionRequest,
    do_token: str = Query(None, description="DO token (query param)"),
    user: UserIdentity = Depends(get_current_user),
):
    """Provision a new server with VPC networking."""
    from shared_libs.backend.infra.cloud import DOClient
    from shared_libs.backend.infra.utils import generate_friendly_name
    from pathlib import Path
    
    # Token from query param OR body
    token = _get_do_token(do_token or req.do_token)
    client = DOClient(token)
    
    # Generate friendly name if not provided
    server_name = req.name.strip() if req.name else generate_friendly_name()
    
    # Ensure 'deployed-via-api' tag is present
    tags = list(req.tags) if req.tags else []
    if 'deployed-via-api' not in tags:
        tags.append('deployed-via-api')
    
    # SSH keys - only use if explicitly provided
    # For SaaS/production: NO SSH keys = SSH-free management via node_agent
    # For dev/debug: User can explicitly pass ssh_keys in request
    ssh_keys = list(req.ssh_keys) if req.ssh_keys else []
    
    # VPC is auto-handled by infra layer (create_droplet auto-ensures VPC)
    # User can still explicitly pass vpc_uuid if they want a specific one
    
    # Validate snapshot exists and is available in target region
    from shared_libs.backend.infra.cloud import SnapshotService
    snapshot_service = SnapshotService(token)
    snapshots = snapshot_service.list_snapshots()
    
    # Find the snapshot
    snapshot = None
    for s in snapshots:
        if str(s.get("id")) == str(req.snapshot_id):
            snapshot = s
            break
    
    if not snapshot:
        raise HTTPException(
            400,
            f"Snapshot '{req.snapshot_id}' not found. Create a snapshot first."
        )
    
    available_regions = snapshot.get("regions", [])
    if req.region not in available_regions:
        raise HTTPException(
            400,
            f"Snapshot '{snapshot.get('name')}' is not available in region '{req.region}'. "
            f"Available regions: {', '.join(available_regions)}. "
            f"Either choose a different region or transfer the snapshot first."
        )
    
    # Generate API key for this user
    api_key = _get_node_agent_key(token, str(user.id))
    
    try:
        droplet = client.create_droplet(
            name=server_name,
            region=req.region,
            size=req.size,
            image=req.snapshot_id,
            ssh_keys=ssh_keys,
            tags=tags,
            vpc_uuid=req.vpc_uuid,  # If None, infra auto-creates VPC
            project=req.project,
            environment=req.environment,
            node_agent_api_key=api_key,  # Infra auto-generates cloud-init
            wait=True,
        )
    except Exception as e:
        error_msg = str(e)
        if "not available in the selected region" in error_msg:
            raise HTTPException(
                400,
                f"Image/snapshot not available in region '{req.region}'. "
                f"Try a different region or use a base image like 'ubuntu-24-04-x64'."
            )
        raise
    
    return {
        "success": True,
        "server": droplet.to_dict(),
        "vpc_uuid": droplet.vpc_uuid,
    }


@router.delete("/servers/{server_id}")
async def delete_server(
    server_id: int,
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None, description="Pass-through mode (not stored)"),
):
    """Delete a server."""
    from shared_libs.backend.infra.cloud import DOClient
    
    token = _get_do_token(do_token)
    client = DOClient(token)
    result = client.delete_droplet(server_id)
    
    if not result.success:
        raise HTTPException(500, result.error or "Failed to delete server")
    
    return {"success": True, "deleted": server_id}


@router.get("/ssh-keys")
async def list_ssh_keys(
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None, description="Pass-through mode (not stored)"),
):
    """List SSH keys."""
    from shared_libs.backend.infra.cloud import DOClient
    
    token = _get_do_token(do_token)
    client = DOClient(token)
    keys = client.list_ssh_keys()
    
    return {"ssh_keys": keys}


# ==========================================
# VPC Endpoints
# ==========================================

@router.get("/vpcs")
async def list_vpcs(
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None, description="Pass-through mode (not stored)"),
):
    """List all VPCs."""
    from shared_libs.backend.infra.cloud import DOClient
    
    token = _get_do_token(do_token)
    client = DOClient(token)
    vpcs = client.list_vpcs()
    
    return {"vpcs": vpcs}


@router.post("/vpcs")
async def create_vpc(
    name: str = Query(...),
    region: str = Query("lon1"),
    ip_range: str = Query("10.120.0.0/20"),
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None, description="Pass-through mode (not stored)"),
):
    """Create a new VPC."""
    from shared_libs.backend.infra.cloud import DOClient
    
    token = _get_do_token(do_token)
    client = DOClient(token)
    vpc = client.create_vpc(name=name, region=region, ip_range=ip_range)
    
    return {"success": True, "vpc": vpc}


@router.get("/vpcs/{vpc_id}/members")
async def list_vpc_members(
    vpc_id: str,
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None, description="Pass-through mode (not stored)"),
):
    """List all resources in a VPC."""
    from shared_libs.backend.infra.cloud import DOClient
    
    token = _get_do_token(do_token)
    client = DOClient(token)
    members = client.get_vpc_members(vpc_id)
    
    return {"members": members}


# ==========================================
# Node Agent Endpoints
# ==========================================

@router.post("/agent/deploy")
async def deploy_via_agent(
    req: AgentDeployRequest,
    do_token: str = Query(None, description="DO token"),
    user: UserIdentity = Depends(get_current_user),
):
    """Deploy container via node agent."""
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    
    api_key = _get_node_agent_key(do_token or req.do_token, user.id)
    
    async with NodeAgentClient(req.server_ip, api_key) as client:
        result = await client.deploy_container(
            image=req.image,
            name=req.name,
            ports=req.ports,
            env_vars=req.env_vars,
            volumes=req.volumes,
        )
        return result


@router.get("/agent/{server_ip}/health")
async def agent_health(
    server_ip: str,
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None, description="Pass-through mode (not stored)"),
):
    """Check node agent health."""
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    
    api_key = _get_node_agent_key(do_token, user.id)
    
    try:
        async with NodeAgentClient(server_ip, api_key) as client:
            result = await client.health()
            if result.success:
                return result.data
            return {"status": "unhealthy", "error": result.error}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


@router.get("/agent/{server_ip}/containers")
async def agent_list_containers(
    server_ip: str,
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None, description="Pass-through mode (not stored)"),
):
    """List containers via node agent."""
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    
    api_key = _get_node_agent_key(do_token, user.id)
    
    async with NodeAgentClient(server_ip, api_key) as client:
        return await client.list_containers()


@router.post("/agent/{server_ip}/containers/{container_name}/stop")
async def agent_stop_container(
    server_ip: str,
    container_name: str,
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None, description="Pass-through mode (not stored)"),
):
    """Stop container via node agent."""
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    
    api_key = _get_node_agent_key(do_token, user.id)
    
    async with NodeAgentClient(server_ip, api_key) as client:
        return await client.stop_container(container_name)


@router.get("/agent/{server_ip}/containers/{container_name}/logs")
async def agent_container_logs(
    server_ip: str,
    container_name: str,
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None, description="Pass-through mode (not stored)"),
    lines: int = Query(100),
):
    """Get container logs via node agent."""
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    
    api_key = _get_node_agent_key(do_token, user.id)
    
    async with NodeAgentClient(server_ip, api_key) as client:
        return await client.container_logs(container_name, lines)


@router.get("/service/{server_ip}/logs")
async def get_service_logs(
    server_ip: str,
    project: str = Query(..., description="Project name"),
    environment: str = Query(..., description="Environment (prod, staging, dev)"),
    service: str = Query(..., description="Service name"),
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None),
    lines: int = Query(200),
):
    """Get logs for a service by project/env/service identifiers."""
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    
    api_key = _get_node_agent_key(do_token, user.id)
    
    async with NodeAgentClient(server_ip, api_key) as client:
        result = await client.get_service_logs(
            workspace_id=str(user.id),
            project=project,
            environment=environment,
            service=service,
            lines=lines,
        )
        return {
            "container_name": result.data.get('container_name', ''),
            "logs": result.data.get('logs', '') if result.success else result.error,
        }


@router.get("/agent/{server_ip}/metrics")
async def get_server_metrics(
    server_ip: str,
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None),
):
    """Get CPU, memory, disk metrics for a server."""
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    
    api_key = _get_node_agent_key(do_token, user.id)
    
    async with NodeAgentClient(server_ip, api_key) as client:
        result = await client.get_metrics()
        if result.success:
            return result.data
        return {"error": result.error}


@router.get("/agent/{server_ip}/health")
async def get_server_health(
    server_ip: str,
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None),
):
    """Get health status of all containers on a server."""
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    
    api_key = _get_node_agent_key(do_token, user.id)
    
    async with NodeAgentClient(server_ip, api_key) as client:
        result = await client.check_containers_health()
        if result.success:
            return result.data
        return {"error": result.error, "summary": {"status": "error"}}


@router.post("/agent/{server_ip}/containers/{container_name}/restart")
async def restart_container(
    server_ip: str,
    container_name: str,
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None),
):
    """Restart a container on a server."""
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    
    api_key = _get_node_agent_key(do_token, user.id)
    
    async with NodeAgentClient(server_ip, api_key) as client:
        result = await client.restart_container(container_name)
        if result.success:
            return {"status": "restarted", "container": container_name, "server": server_ip}
        raise HTTPException(500, result.error)


@router.get("/fleet/health")
async def get_fleet_health(
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None),
):
    """Get health status of all servers in the fleet."""
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    from shared_libs.backend.infra.cloud.digitalocean import DOClient
    from shared_libs.backend.infra.cloud import generate_node_agent_key
    import asyncio
    
    token = do_token or _get_do_token(user.id)
    if not token:
        raise HTTPException(400, "No DigitalOcean token available")
    
    api_key = generate_node_agent_key(token, str(user.id))
    
    # Get all servers from DO
    try:
        do_client = DOClient(token)
        droplets = do_client.list_droplets(tag="deployed-via-api")
        servers = [{"ip": d.ip, "name": d.name, "region": d.region} for d in droplets if d.ip]
    except Exception as e:
        return {"servers": [], "summary": {"total": 0, "healthy": 0, "unhealthy": 0, "unreachable": 0}, "error": str(e)}
    
    if not servers:
        return {"servers": [], "summary": {"total": 0, "healthy": 0, "unhealthy": 0, "unreachable": 0}}
    
    async def check_server(server_info):
        ip = server_info.get("ip")
        try:
            async with NodeAgentClient(ip, api_key, timeout=10) as client:
                # Check agent is alive first
                ping = await client.ping()
                if not ping.success:
                    return {"ip": ip, "name": server_info.get("name"), "region": server_info.get("region"), "status": "unreachable", "error": "Agent not responding"}
                
                agent_version = ping.data.get("version", "unknown") if ping.data else "unknown"
                
                # Get container health
                result = await client.check_containers_health()
                if result.success:
                    summary = result.data.get("summary", {})
                    return {
                        "ip": ip,
                        "name": server_info.get("name"),
                        "region": server_info.get("region"),
                        "status": "online",
                        "agent_version": agent_version,
                        "containers": summary.get("total", 0),
                        "healthy": summary.get("healthy", 0),
                        "unhealthy": summary.get("unhealthy", 0),
                        "health_status": summary.get("status", "unknown"),
                    }
                else:
                    return {"ip": ip, "name": server_info.get("name"), "region": server_info.get("region"), "status": "online", "agent_version": agent_version, "error": result.error}
        except Exception as e:
            return {"ip": ip, "name": server_info.get("name"), "region": server_info.get("region"), "status": "unreachable", "error": str(e)}
    
    # Check all servers in parallel
    results = await asyncio.gather(*[check_server(s) for s in servers])
    
    # Summary
    total = len(results)
    online = sum(1 for r in results if r.get("status") == "online")
    healthy = sum(1 for r in results if r.get("status") == "online" and r.get("health_status") in ("healthy", "empty"))
    unhealthy = sum(1 for r in results if r.get("status") == "online" and r.get("health_status") == "unhealthy")
    unreachable = sum(1 for r in results if r.get("status") == "unreachable")
    
    return {
        "servers": results,
        "summary": {
            "total": total,
            "online": online,
            "healthy": healthy,
            "unhealthy": unhealthy,
            "unreachable": unreachable,
            "status": "healthy" if unreachable == 0 and unhealthy == 0 else "degraded" if online > 0 else "down"
        }
    }


# =============================================================================
# Cron/Scheduler Management
# =============================================================================

@router.get("/agent/{server_ip}/cron/jobs")
async def list_cron_jobs(
    server_ip: str,
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None),
):
    """List all managed cron jobs on a server."""
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    
    api_key = _get_node_agent_key(do_token, user.id)
    
    async with NodeAgentClient(server_ip, api_key) as client:
        result = await client.list_cron_jobs()
        if result.success:
            return result.data
        raise HTTPException(500, result.error)


@router.post("/agent/{server_ip}/cron/remove")
async def remove_cron_job(
    server_ip: str,
    job_id: str = Query(..., description="Job ID to remove"),
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None),
):
    """Remove a cron job from a server."""
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    
    api_key = _get_node_agent_key(do_token, user.id)
    
    async with NodeAgentClient(server_ip, api_key) as client:
        result = await client.remove_cron_job(job_id)
        if result.success:
            return result.data
        raise HTTPException(500, result.error)


class DockerCronRequest(BaseModel):
    """Request to schedule a Docker container."""
    id: str
    schedule: str
    image: str
    container_name: str = ""
    env: Dict[str, str] = {}
    volumes: List[str] = []
    network: str = ""
    command: str = ""
    description: str = ""


@router.post("/agent/{server_ip}/cron/docker")
async def schedule_docker_cron(
    server_ip: str,
    req: DockerCronRequest,
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None),
):
    """Schedule a Docker container to run on a cron schedule."""
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    
    api_key = _get_node_agent_key(do_token, user.id)
    
    async with NodeAgentClient(server_ip, api_key) as client:
        result = await client.schedule_docker_run(
            job_id=req.id,
            schedule=req.schedule,
            image=req.image,
            container_name=req.container_name,
            env_vars=req.env,
            volumes=req.volumes,
            network=req.network,
            command=req.command,
            description=req.description,
        )
        if result.success:
            return result.data
        raise HTTPException(500, result.error)


# =============================================================================
# Secrets Rotation
# =============================================================================

class RotateSecretRequest(BaseModel):
    """Request to rotate a secret."""
    secret_name: str
    new_value: Optional[str] = None  # Auto-generate if not provided
    password_length: int = 32
    containers: List[str] = []  # Container names to restart
    server_ips: List[str] = []  # Servers where containers run
    env_var_name: Optional[str] = None  # Defaults to secret_name


@router.post("/secrets/rotate")
async def rotate_secret(
    req: RotateSecretRequest,
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None),
):
    """
    Rotate a secret and optionally restart containers.
    
    Requires INFISICAL_TOKEN and INFISICAL_PROJECT_ID env vars.
    """
    from shared_libs.backend.vault import SecretsRotator
    from shared_libs.backend.infra.cloud import generate_node_agent_key
    
    token = do_token or _get_do_token(user.id)
    node_agent_key = generate_node_agent_key(token, str(user.id)) if token else None
    
    rotator = SecretsRotator(node_agent_key=node_agent_key)
    
    if not rotator.vault:
        raise HTTPException(400, "Vault not configured. Set INFISICAL_TOKEN and INFISICAL_PROJECT_ID.")
    
    result = await rotator.rotate_secret(
        secret_name=req.secret_name,
        new_value=req.new_value,
        password_length=req.password_length,
        containers=req.containers,
        server_ips=req.server_ips,
        env_var_name=req.env_var_name,
    )
    
    if result.success:
        return {
            "status": "rotated",
            "secret_name": result.secret_name,
            "containers_updated": result.containers_updated,
            # Don't return actual values in response for security
        }
    raise HTTPException(500, result.error)


@router.post("/secrets/generate")
async def generate_secret(
    length: int = Query(32, ge=8, le=128),
    include_special: bool = Query(True),
    secret_type: str = Query("password", regex="^(password|api_key)$"),
    prefix: str = Query("sk"),
    user: UserIdentity = Depends(get_current_user),
):
    """Generate a new random secret (does not store it)."""
    from shared_libs.backend.vault import generate_password, generate_api_key
    
    if secret_type == "api_key":
        value = generate_api_key(prefix=prefix)
    else:
        value = generate_password(length=length, include_special=include_special)
    
    return {"value": value, "type": secret_type}


@router.get("/secrets/status")
async def get_vault_status(
    user: UserIdentity = Depends(get_current_user),
):
    """Check vault configuration status."""
    from shared_libs.backend.vault import vault_status
    
    status = vault_status()
    return {
        "configured": status.get("infisical_configured", False),
        "environment": status.get("infisical_env", "unknown"),
    }


@router.get("/costs")
async def get_costs(
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None),
):
    """Get cost summary by project/environment."""
    from shared_libs.backend.infra.cloud.digitalocean.cost_tracker import CostTracker
    
    token = do_token or _get_do_token(user.id)
    if not token:
        raise HTTPException(400, "No DigitalOcean token available")
    
    tracker = CostTracker(token)
    summary = await tracker.get_cost_summary()
    
    return {
        "total_monthly": summary.total_monthly,
        "total_hourly": summary.total_hourly,
        "by_project": summary.by_project,
        "by_environment": summary.by_environment,
        "by_region": summary.by_region,
        "droplet_count": len(summary.droplets),
        "droplets": [
            {
                "id": d.id,
                "name": d.name,
                "size": d.size,
                "monthly_cost": d.monthly_cost,
                "project": d.project,
                "environment": d.environment,
                "region": d.region,
            }
            for d in summary.droplets
        ],
    }


@router.get("/costs/balance")
async def get_balance(
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None),
):
    """Get current DO account balance."""
    from shared_libs.backend.infra.cloud.digitalocean.cost_tracker import CostTracker
    
    token = do_token or _get_do_token(user.id)
    if not token:
        raise HTTPException(400, "No DigitalOcean token available")
    
    tracker = CostTracker(token)
    return await tracker.get_balance()


@router.post("/agent/{server_ip}/containers/{container_name}/remove")
async def agent_remove_container(
    server_ip: str,
    container_name: str,
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None, description="Pass-through mode (not stored)"),
):
    """Remove container via node agent."""
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    
    api_key = _get_node_agent_key(do_token, user.id)
    
    async with NodeAgentClient(server_ip, api_key) as client:
        return await client.remove_container(container_name)


@router.post("/agent/{server_ip}/containers/{container_name}/restart")
async def agent_restart_container(
    server_ip: str,
    container_name: str,
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None),
):
    """Restart container via node agent."""
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    
    api_key = _get_node_agent_key(do_token, user.id)
    
    async with NodeAgentClient(server_ip, api_key) as client:
        return await client.restart_container(container_name)


@router.post("/agent/{server_ip}/containers/{container_name}/start")
async def agent_start_container(
    server_ip: str,
    container_name: str,
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None),
):
    """Start a stopped container via node agent."""
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    
    api_key = _get_node_agent_key(do_token, user.id)
    
    async with NodeAgentClient(server_ip, api_key) as client:
        return await client.start_container(container_name)


@router.post("/agent/{server_ip}/containers/{container_name}/stop")
async def agent_stop_container(
    server_ip: str,
    container_name: str,
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None),
):
    """Stop a running container via node agent."""
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    
    api_key = _get_node_agent_key(do_token, user.id)
    
    async with NodeAgentClient(server_ip, api_key) as client:
        return await client.stop_container(container_name)


class AgentBuildRequest(BaseModel):
    """Request to build Docker image."""
    context_path: str = "/app/"
    image_tag: str = "app:latest"
    dockerfile: Optional[str] = None


class AgentDockerfileRequest(BaseModel):
    """Request to get/generate Dockerfile."""
    context_path: str = "/app/"


@router.post("/agent/{server_ip}/dockerfile")
async def agent_get_dockerfile(
    server_ip: str,
    req: AgentDockerfileRequest,
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None, description="Pass-through mode (not stored)"),
):
    """Get or generate Dockerfile for preview before build."""
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    
    api_key = _get_node_agent_key(do_token, user.id)
    
    async with NodeAgentClient(server_ip, api_key) as client:
        return await client.get_dockerfile(context_path=req.context_path)


@router.post("/agent/{server_ip}/build")
async def agent_build_image(
    server_ip: str,
    req: AgentBuildRequest,
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None, description="Pass-through mode (not stored)"),
):
    """Build Docker image via node agent."""
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    
    api_key = _get_node_agent_key(do_token, user.id)
    
    async with NodeAgentClient(server_ip, api_key) as client:
        return await client.build_image(
            context_path=req.context_path,
            image_tag=req.image_tag,
            dockerfile=req.dockerfile,
        )


class AgentRunContainerRequest(BaseModel):
    """Request to run a container."""
    image: str
    name: str
    ports: Dict[str, str] = {}
    env_vars: Dict[str, str] = {}
    volumes: List[str] = []
    restart_policy: str = "unless-stopped"


@router.post("/agent/{server_ip}/containers/run")
async def agent_run_container(
    server_ip: str,
    req: AgentRunContainerRequest,
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None, description="Pass-through mode (not stored)"),
):
    """Run container via node agent."""
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    
    api_key = _get_node_agent_key(do_token, user.id)
    
    async with NodeAgentClient(server_ip, api_key) as client:
        return await client.run_container(
            image=req.image,
            name=req.name,
            ports=req.ports,
            env_vars=req.env_vars,
            volumes=req.volumes,
            restart_policy=req.restart_policy,
        )


class AgentPullRequest(BaseModel):
    """Request to pull a Docker image."""
    image: str


@router.post("/agent/{server_ip}/pull")
async def agent_pull_image(
    server_ip: str,
    req: AgentPullRequest,
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None, description="Pass-through mode (not stored)"),
):
    """Pull Docker image via node agent."""
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    
    api_key = _get_node_agent_key(do_token, user.id)
    
    async with NodeAgentClient(server_ip, api_key) as client:
        return await client.pull_image(req.image)


class AgentGitCloneRequest(BaseModel):
    """Request to clone a git repository."""
    repo_url: str
    branch: str = "main"
    target_path: str = "/app/"
    access_token: Optional[str] = None  # For private repos


@router.post("/agent/{server_ip}/git/clone")
async def agent_git_clone(
    server_ip: str,
    req: AgentGitCloneRequest,
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None, description="Pass-through mode (not stored)"),
):
    """Clone git repository via node agent."""
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    
    api_key = _get_node_agent_key(do_token, user.id)
    
    async with NodeAgentClient(server_ip, api_key) as client:
        return await client.git_clone(
            repo_url=req.repo_url,
            branch=req.branch,
            target_path=req.target_path,
            access_token=req.access_token,
        )


@router.get("/agent/health")
async def agent_health_simple(
    server_ip: str = Query(...),
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None, description="Pass-through mode (not stored)"),
):
    """Check node agent health (simplified, with server_ip as query param)."""
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    
    api_key = _get_node_agent_key(do_token, user.id)
    
    try:
        async with NodeAgentClient(server_ip, api_key) as client:
            result = await client.health()
            # Return the data directly, not wrapped in AgentResponse
            if result.success:
                return result.data
            return {"status": "unhealthy", "error": result.error}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


# ==========================================
# Status/Health Endpoints
# ==========================================

@router.get("/status")
async def get_status(
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None, description="Pass-through mode (not stored)"),
):
    """Get infrastructure status."""
    from shared_libs.backend.infra.cloud import DOClient, SnapshotService
    
    token = _get_do_token(do_token)
    client = DOClient(token)
    snapshot_service = SnapshotService(token)
    
    droplets = client.list_droplets()
    snapshots = snapshot_service.list_snapshots()
    
    return {
        "servers": {
            "total": len(droplets),
            "active": len([d for d in droplets if d.is_active]),
        },
        "snapshots": {
            "total": len(snapshots),
        },
    }


# ==========================================
# Deploy Endpoints (via Node Agent)
# ==========================================

class DeployRequest(BaseModel):
    """Deploy a service to a server."""
    do_token: Optional[str] = None  # Pass-through mode (not stored)
    server_ip: str
    service_name: str
    image: str
    ports: Dict[str, str] = {}
    env_vars: Dict[str, str] = {}
    volumes: List[str] = []
    restart_policy: str = "unless-stopped"


@router.post("/deploy/single")
async def deploy_service(
    req: DeployRequest,
    do_token: str = Query(None, description="DO token"),
    user: UserIdentity = Depends(get_current_user),
):
    """Deploy a service to a server via node agent."""
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    
    api_key = _get_node_agent_key(do_token or req.do_token, user.id)
    
    async with NodeAgentClient(req.server_ip, api_key) as client:
        # Stop existing container if any
        try:
            await client.stop_container(req.service_name)
        except Exception:
            pass  # Container might not exist
        
        # Pull latest image
        await client.pull_image(req.image)
        
        # Run new container
        result = await client.run_container(
            image=req.image,
            name=req.service_name,
            ports=req.ports,
            env_vars=req.env_vars,
            volumes=req.volumes,
            restart_policy=req.restart_policy,
        )
        
        # AgentResponse has .success, .data, .error
        if result.success:
            return {
                "success": True,
                "container_id": result.data.get("container_id") if result.data else None,
                "service": req.service_name,
            }
        else:
            return {
                "success": False,
                "error": result.error,
                "service": req.service_name,
            }


@router.post("/deploy/stop")
async def stop_deployment(
    server_ip: str = Query(...),
    service_name: str = Query(...),
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None, description="Pass-through mode (not stored)"),
):
    """Stop a deployed service."""
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    
    api_key = _get_node_agent_key(do_token, user.id)
    
    async with NodeAgentClient(server_ip, api_key) as client:
        result = await client.stop_container(service_name)
        return {"success": result.success, "service": service_name, "error": result.error if not result.success else None}


@router.get("/deploy/status/{service_name}")
async def get_deployment_status(
    service_name: str,
    server_ip: str = Query(...),
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None, description="Pass-through mode (not stored)"),
):
    """Get deployment status."""
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    
    api_key = _get_node_agent_key(do_token, user.id)
    
    async with NodeAgentClient(server_ip, api_key) as client:
        return await client.container_status(service_name)


@router.get("/deploy/logs/{service_name}")
async def get_deployment_logs(
    service_name: str,
    server_ip: str = Query(...),
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None, description="Pass-through mode (not stored)"),
    lines: int = Query(100),
):
    """Get deployment logs."""
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    
    api_key = _get_node_agent_key(do_token, user.id)
    
    async with NodeAgentClient(server_ip, api_key) as client:
        return await client.container_logs(service_name, lines)


# ==========================================
# Test Endpoints
# ==========================================

class DOTokenTestRequest(BaseModel):
    """Request to test DO token."""
    token: str


@router.post("/test/do-token")
async def test_do_token(req: DOTokenTestRequest):
    """Test if a DigitalOcean token is valid."""
    from shared_libs.backend.infra.cloud import DOClient
    
    try:
        client = DOClient(req.token)
        account = client.get_account()
        return {
            "valid": True,
            "email": account.get("email"),
            "droplet_limit": account.get("droplet_limit"),
            "status": account.get("status"),
        }
    except Exception as e:
        return {"valid": False, "error": str(e)}


class DockerTestRequest(BaseModel):
    """Request to test Docker command."""
    server: Optional[str] = None  # Empty = localhost
    command: str = "ps"
    args: Dict[str, Any] = {}


@router.post("/test/docker")
async def test_docker(
    req: DockerTestRequest,
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None),
):
    """
    Test Docker commands locally (READ-ONLY).
    
    Only allows safe, read-only commands: ps, images, logs.
    Destructive commands (run, stop, rm, exec) are disabled for security.
    Use node_agent endpoints for remote Docker management.
    """
    import subprocess
    
    # Only support localhost for direct Docker commands
    if req.server and req.server != "localhost":
        return {"error": "Remote Docker requires node_agent. Use /agent/* endpoints for remote servers."}
    
    # SECURITY: Only allow read-only commands
    ALLOWED_COMMANDS = {"ps", "images", "logs"}
    if req.command not in ALLOWED_COMMANDS:
        return {
            "error": f"Command '{req.command}' not allowed. Only read-only commands: {', '.join(ALLOWED_COMMANDS)}",
            "hint": "Use /agent/* endpoints for full Docker control on remote servers.",
        }
    
    try:
        if req.command == "ps":
            cmd = ["docker", "ps", "--format", "json"]
            if req.args.get("all"):
                cmd.insert(2, "-a")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                import json
                lines = [l for l in result.stdout.strip().split("\n") if l]
                containers = [json.loads(l) for l in lines] if lines else []
                return {"containers": containers}
            return {"error": result.stderr}
            
        elif req.command == "images":
            result = subprocess.run(
                ["docker", "images", "--format", "json"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                import json
                lines = [l for l in result.stdout.strip().split("\n") if l]
                images = [json.loads(l) for l in lines] if lines else []
                return {"images": images}
            return {"error": result.stderr}
            
        elif req.command == "logs":
            container = req.args.get("container")
            if not container:
                return {"error": "container required"}
            result = subprocess.run(
                ["docker", "logs", "--tail", str(req.args.get("tail", 100)), container],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return {"logs": result.stdout + result.stderr}
            
    except subprocess.TimeoutExpired:
        return {"error": "Command timed out"}
    except FileNotFoundError:
        return {"error": "Docker not installed or not in PATH"}
    except Exception as e:
        return {"error": str(e)}


class HealthCheckRequest(BaseModel):
    """Request to run health check."""
    type: str = "http"  # http, tcp, docker
    target: str  # URL, host:port, or container name
    timeout: int = 10


@router.post("/test/health")
async def test_health_check(req: HealthCheckRequest):
    """Run a health check."""
    from shared_libs.backend.infra.monitoring import HealthChecker
    
    checker = HealthChecker()
    
    try:
        if req.type == "http":
            result = await checker.check_http(req.target, timeout=req.timeout)
            return {
                "healthy": result.is_healthy,
                "status": result.status.value,
                "message": result.message,
                "response_time_ms": result.response_time_ms,
                "details": result.details,
            }
        elif req.type == "tcp":
            if ":" in req.target:
                host, port = req.target.rsplit(":", 1)
                result = await checker.check_tcp(host, int(port), timeout=req.timeout)
                return {
                    "healthy": result.is_healthy,
                    "status": result.status.value,
                    "message": result.message,
                    "response_time_ms": result.response_time_ms,
                    "details": result.details,
                }
            else:
                return {"healthy": False, "error": "TCP target must be host:port"}
        elif req.type == "docker":
            result = await checker.check_docker_health(req.target)
            return {
                "healthy": result.is_healthy,
                "status": result.status.value,
                "message": result.message,
                "details": result.details,
            }
        else:
            return {"healthy": False, "error": f"Unknown check type: {req.type}"}
    except Exception as e:
        return {"healthy": False, "error": str(e)}


class NginxConfigRequest(BaseModel):
    """Request to generate nginx config."""
    service_name: str
    backends: List[str]  # ["localhost:8000", "10.0.0.1:8000"]
    domain: Optional[str] = None
    ssl: bool = False
    websocket: bool = False


@router.post("/test/nginx-config")
async def generate_nginx_config(req: NginxConfigRequest):
    """Generate nginx config for a service."""
    # Simple nginx config generator for testing
    upstream_name = f"upstream_{req.service_name}"
    
    # Build upstream block
    backend_lines = "\n".join([f"        server {b};" for b in req.backends])
    upstream_block = f"""upstream {upstream_name} {{
{backend_lines}
}}"""
    
    # Build location block
    location_block = f"""    location / {{
        proxy_pass http://{upstream_name};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;"""
    
    if req.websocket:
        location_block += """
        
        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;"""
    
    location_block += "\n    }"
    
    # Build server block
    domain = req.domain or "localhost"
    listen_port = "443 ssl" if req.ssl else "80"
    
    server_block = f"""server {{
    listen {listen_port};
    server_name {domain};
"""
    
    if req.ssl:
        server_block += f"""
    ssl_certificate /etc/letsencrypt/live/{domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{domain}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
"""
    
    server_block += f"""
{location_block}
}}"""
    
    # Add HTTP -> HTTPS redirect if SSL
    if req.ssl:
        server_block = f"""server {{
    listen 80;
    server_name {domain};
    return 301 https://$server_name$request_uri;
}}

""" + server_block
    
    config = f"""# Nginx config for {req.service_name}
# Generated by deploy-api

{upstream_block}

{server_block}
"""
    
    return {"config": config}



@router.post("/deploy/upload")
async def upload_code(
    server_ip: str = Query(..., description="Server IP to upload to"),
    do_token: str = Query(..., description="DO token"),
    user: UserIdentity = Depends(get_current_user),
    file: UploadFile = File(..., description="Code archive (tar.gz or zip)"),
):
    """
    Upload code to a server for deployment.
    Accepts tar.gz or zip files.
    Extracts to /app on the server.
    """
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    import io
    import zipfile
    import tarfile
    
    token = _get_do_token(do_token)
    api_key = _get_node_agent_key(token, user.id)
    
    # Read file content
    content = await file.read()
    
    # Convert to tar.gz if zip
    if file.filename.endswith('.zip'):
        # Convert zip to tar.gz
        zip_buffer = io.BytesIO(content)
        tar_buffer = io.BytesIO()
        
        # Use current time for all files so Docker detects changes
        import time
        current_time = time.time()
        
        with zipfile.ZipFile(zip_buffer, 'r') as zf:
            with tarfile.open(fileobj=tar_buffer, mode='w:gz') as tf:
                for zip_info in zf.infolist():
                    name = zip_info.filename
                    
                    # DEBUG: Check for version in HTML files
                    if name.endswith('.html') and 'index' in name:
                        try:
                            html_content = zf.read(name).decode('utf-8', errors='ignore')
                            import re
                            title_match = re.search(r'<title>([^<]+)</title>', html_content, re.IGNORECASE)
                            if title_match:
                                print(f"[DEBUG] SERVER ZIP: {name} has title: {title_match.group(1)}")
                        except:
                            pass
                    
                    # Create tar info with CURRENT timestamp (critical for Docker cache busting)
                    tar_info = tarfile.TarInfo(name=name)
                    tar_info.mtime = current_time  # Docker uses mtime to detect changes!
                    
                    if zip_info.is_dir():
                        # Directory entry
                        tar_info.type = tarfile.DIRTYPE
                        tar_info.mode = 0o755
                        tf.addfile(tar_info)
                    else:
                        # File entry
                        data = zf.read(name)
                        tar_info.size = len(data)
                        tar_info.mode = 0o644
                        tf.addfile(tar_info, io.BytesIO(data))
        
        tar_data = tar_buffer.getvalue()
    else:
        tar_data = content
    
    # Upload to server
    async with NodeAgentClient(server_ip, api_key) as client:
        result = await client.upload_tar(tar_data, extract_path="/app/")
    
    # AgentResponse has .success, .data, .error
    if result.success:
        return {
            "success": True,
            "path": result.data.get("path", "/app/") if result.data else "/app/",
            "message": f"Code uploaded to {server_ip}:/app",
        }
    else:
        return {
            "success": False,
            "error": result.error or "Upload failed",
            "message": result.error or "Upload failed",
        }


# =============================================================================
# UNIFIED MULTI-SERVER DEPLOYMENT
# =============================================================================

# Import from infra - no duplicate code
from shared_libs.backend.infra.deploy.service import (
    DeploySource,
    MultiDeployConfig,
    ServerResult,
    MultiDeployResult,
    DeploymentService,
)

class UnifiedDeployRequest(BaseModel):
    """Unified deployment request for code, git, or image deployments."""
    # App config
    name: str
    port: int = 8000
    container_port: Optional[int] = None  # For image_file: internal container port
    host_port: Optional[int] = None       # For image_file: external host port
    env_vars: Dict[str, str] = {}
    environment: str = "prod"
    tags: List[str] = []
    project: Optional[str] = None  # Project name (defaults to service name)
    
    # Service mesh / dependencies
    depends_on: List[str] = []  # Services this depends on (e.g., ["postgres", "redis"])
    setup_sidecar: bool = True  # Set up nginx sidecar after deploy
    is_stateful: bool = False   # Is this a stateful service (auto-detected from name)
    
    # Domain config
    setup_domain: bool = False  # Auto-provision domain
    base_domain: str = "digitalpixo.com"  # Base domain for subdomains
    domain_aliases: List[str] = []  # Custom domain aliases
    
    # Source: code, git, image, or image_file
    source_type: str  # "code", "git", "image", "image_file"
    
    # For code source (base64 tar)
    code_tar_b64: Optional[str] = None
    dockerfile: Optional[str] = None
    
    # For git source
    git_url: Optional[str] = None
    git_branch: str = "main"
    git_token: Optional[str] = None
    git_folders: Optional[List[Dict[str, Any]]] = None  # [{path: str, isMain: bool}]
    
    # For image source (registry pull)
    image: Optional[str] = None
    
    # For image_file source (local docker save tar)
    image_tar_b64: Optional[str] = None  # base64 encoded docker save output
    
    # Infrastructure
    server_ips: List[str] = []  # Existing servers
    new_server_count: int = 0
    snapshot_id: Optional[str] = None
    region: str = "lon1"
    size: str = "s-1vcpu-1gb"


@router.post("/deploy")
async def deploy_unified(
    req: UnifiedDeployRequest,
    do_token: str = Query(..., description="DO token"),
    cf_token: Optional[str] = Query(None, description="Cloudflare token (required if setup_domain=True)"),
    user: UserIdentity = Depends(get_current_user),
):
    """
    Unified deployment endpoint for multi-server deployments.
    
    Supports:
    - Code upload (source_type="code")
    - Git clone (source_type="git") 
    - Docker image (source_type="image")
    
    Handles multiple existing servers and/or provisioning new ones.
    Returns SSE stream with progress logs.
    """
    import json
    import base64
    import queue
    import threading
    
    token = _get_do_token(do_token)
    api_key = _get_node_agent_key(token, str(user.id))  # Ensure string
    msg_queue = queue.Queue()
    
    def log(msg: str):
        msg_queue.put({"type": "log", "message": msg})
    
    # Debug: log api key prefix
    log(f"🔑 Using API key: {api_key[:8]}...")
    
    def deploy_worker():
        """Run deployment in background thread."""
        import asyncio
        
        try:
            # Build config
            source_type = DeploySource.from_value(req.source_type)
            
            config = MultiDeployConfig(
                name=req.name,
                port=req.port,
                container_port=req.container_port,
                host_port=req.host_port,
                env_vars=req.env_vars,
                environment=req.environment,
                tags=req.tags,
                source_type=source_type,
                git_url=req.git_url,
                git_branch=req.git_branch,
                git_token=req.git_token,
                image=req.image,
                server_ips=req.server_ips,
                new_server_count=req.new_server_count,
                snapshot_id=req.snapshot_id,
                region=req.region,
                size=req.size,
                dockerfile=req.dockerfile,
                project=req.project,  # For container naming
                workspace_id=str(user.id),  # For container naming
                # Service mesh
                depends_on=req.depends_on,
                setup_sidecar=req.setup_sidecar,
                is_stateful=req.is_stateful,
                # Domain config
                setup_domain=req.setup_domain,
                cloudflare_token=cf_token,
                base_domain=req.base_domain,
                domain_aliases=req.domain_aliases,
            )
            
            # Decode code if provided (service handles zip→tar conversion)
            if req.code_tar_b64:
                config.code_tar = base64.b64decode(req.code_tar_b64)
            
            # Decode image tar if provided
            if req.image_tar_b64:
                config.image_tar = base64.b64decode(req.image_tar_b64)
            
            # Create service and deploy
            service = DeploymentService(
                do_token=token,
                agent_key=api_key,
                log=log,
            )
            
            # Run async deploy in new event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(service.deploy(config))
            loop.close()
            
            # Send done with architecture info
            msg_queue.put({
                "type": "done",
                "success": result.success,
                "servers": [
                    {
                        "ip": s.ip, 
                        "name": s.name, 
                        "success": s.success, 
                        "url": s.url, 
                        "error": s.error,
                        "container_name": s.container_name,  # Actual container name (may have _secondary)
                        "internal_port": s.internal_port,
                        "sidecar_configured": s.sidecar_configured,
                    }
                    for s in result.servers
                ],
                "successful_count": result.successful_count,
                "failed_count": result.failed_count,
                "error": result.error,
                # Architecture info
                "service_name": result.service_name,
                "project": result.project,
                "environment": result.environment,
                "container_name": result.container_name,
                "internal_port": result.internal_port,
                "depends_on": result.depends_on,
                # Dependent containers that were restarted
                "restarted_dependents": result.restarted_dependents,
                # Domain info
                "domain": result.domain,
                "domain_aliases": result.domain_aliases,
            })
            
        except Exception as e:
            import traceback
            log(f"❌ Error: {e}")
            traceback.print_exc()
            msg_queue.put({
                "type": "done",
                "success": False,
                "error": str(e),
            })
    
    # Start worker thread
    thread = threading.Thread(target=deploy_worker, daemon=True)
    thread.start()
    
    # SSE generator
    async def event_stream():
        import asyncio
        
        while True:
            try:
                msg = msg_queue.get(timeout=0.5)
                yield f"data: {json.dumps(msg)}\n\n"
                
                if msg.get("type") == "done":
                    break
            except queue.Empty:
                # Send keepalive
                yield f"data: {json.dumps({'type': 'ping'})}\n\n"
            
            await asyncio.sleep(0.1)
    
    from starlette.responses import StreamingResponse
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@router.post("/deploy/multipart")
async def deploy_multipart(
    request: Request,
    # Query params (available immediately, before body is read)
    do_token: str = Query(..., description="DO token"),
    cf_token: Optional[str] = Query(None, description="Cloudflare token"),
    snapshot_id: Optional[str] = Query(None),
    new_server_count: int = Query(0),
    region: str = Query("lon1"),
    size: str = Query("s-1vcpu-1gb"),
    project_name: Optional[str] = Query(None, alias="project", description="Project name for tagging"),
    env_name: str = Query("prod", alias="environment", description="Environment"),
    # Domain config
    setup_domain: bool = Query(False, description="Auto-provision domain"),
    base_domain: str = Query("digitalpixo.com", description="Base domain for subdomains"),
    domain_aliases: str = Query("[]", description="JSON array of domain aliases"),
    user: UserIdentity = Depends(get_current_user),
):
    """
    Multipart deployment endpoint - memory efficient for large files.
    
    Key optimization: provisioning starts IMMEDIATELY from query params,
    while file upload continues in parallel. This saves ~30-40s.
    
    Query params (for early provisioning):
    - do_token, snapshot_id, new_server_count, region, size
    
    Form fields:
    - name, port, source_type, env_vars, tags, etc.
    
    Files:
    - code_tar, image_tar
    
    Returns SSE stream with progress logs.
    """
    import json as json_mod
    import queue
    import threading
    import tempfile
    import os
    import asyncio
    
    token = _get_do_token(do_token)
    api_key = _get_node_agent_key(token, str(user.id))
    msg_queue = queue.Queue()
    
    def log(msg: str):
        msg_queue.put({"type": "log", "message": msg})
    
    log(f"🔑 Using API key: {api_key[:8]}...")
    
    # Start provisioning IMMEDIATELY if needed (before reading file!)
    provision_task = None
    provisioned_servers = []
    
    if new_server_count > 0 and snapshot_id:
        log(f"🆕 Provisioning {new_server_count} server(s) in parallel with upload...")
        
        async def provision_now():
            from shared_libs.backend.infra.cloud import DOClient
            from shared_libs.backend.infra.utils.naming import generate_friendly_name
            
            client = DOClient(token)
            names = [generate_friendly_name() for _ in range(new_server_count)]
            
            # Start all droplets - infra layer handles API key via node_agent_api_key
            droplet_ids = []
            for name in names:
                try:
                    droplet = client.create_droplet(
                        name=name,
                        region=region,
                        size=size,
                        image=snapshot_id,
                        tags=["deployed-via-api"],
                        project=project_name,  # From query param
                        environment=env_name,  # From query param
                        node_agent_api_key=api_key,  # Infra auto-generates cloud-init
                        wait=False,
                    )
                    droplet_ids.append((droplet.id, name))
                    log(f"   🔄 {name} creating...")
                except Exception as e:
                    log(f"   ❌ {name}: {e}")
            
            if not droplet_ids:
                return []
            
            log(f"   ⏳ Waiting for {len(droplet_ids)} droplet(s)...")
            
            # Poll until ready
            servers = []
            for droplet_id, name in droplet_ids:
                for _ in range(120):
                    try:
                        droplet = client.get_droplet(droplet_id)
                        if droplet and droplet.status == "active" and droplet.ip:
                            log(f"   ✅ {name} ({droplet.ip})")
                            servers.append({"ip": droplet.ip, "name": name})
                            break
                    except:
                        pass
                    await asyncio.sleep(2)
                else:
                    log(f"   ❌ {name}: timeout")
            
            return servers
        
        provision_task = asyncio.create_task(provision_now())
    
    # Now read the form data (file upload happens here, in parallel with provisioning)
    log(f"📤 Receiving upload...")
    form = await request.form()
    
    # Extract form fields
    name = form.get("name", "")
    source_type = form.get("source_type", "")
    port = int(form.get("port", 8000))
    container_port = int(form.get("container_port", 0)) or None
    host_port = int(form.get("host_port", 0)) or None
    env_vars = form.get("env_vars", "{}")
    # Use query param, fallback to form, then default
    environment = env_name or form.get("environment", "prod")
    project = project_name or form.get("project", name)  # Default to service name
    tags = form.get("tags", "[]")
    dockerfile = form.get("dockerfile")
    git_url = form.get("git_url")
    git_branch = form.get("git_branch", "main")
    git_token = form.get("git_token")
    git_folders_str = form.get("git_folders")
    image = form.get("image")
    server_ips = form.get("server_ips", "[]")
    
    # Parse JSON fields
    try:
        env_vars_dict = json_mod.loads(env_vars) if env_vars else {}
        tags_list = json_mod.loads(tags) if tags else []
        server_ips_list = json_mod.loads(server_ips) if server_ips else []
        git_folders = json_mod.loads(git_folders_str) if git_folders_str else None
    except json_mod.JSONDecodeError as e:
        raise HTTPException(400, f"Invalid JSON in form field: {e}")
    
    # Save uploaded files to temp paths
    code_tar_path = None
    image_tar_path = None
    
    code_tar = form.get("code_tar")
    image_tar = form.get("image_tar")
    
    if code_tar and hasattr(code_tar, 'read'):
        suffix = ".tar.gz" if code_tar.filename.endswith(".gz") else ".tar"
        fd, code_tar_path = tempfile.mkstemp(suffix=suffix)
        content = await code_tar.read()
        with os.fdopen(fd, 'wb') as f:
            f.write(content)
        log(f"📦 Received code: {len(content) / 1024 / 1024:.1f}MB")
    
    if image_tar and hasattr(image_tar, 'read'):
        fd, image_tar_path = tempfile.mkstemp(suffix=".tar")
        content = await image_tar.read()
        with os.fdopen(fd, 'wb') as f:
            f.write(content)
        log(f"🐳 Received image: {len(content) / 1024 / 1024:.1f}MB")
    
    # Wait for provisioning to complete (if started)
    if provision_task:
        provisioned_servers = await provision_task
        
        # Wait for cloud-init to update API keys on new servers
        if provisioned_servers:
            log(f"⏳ Waiting for API keys on {len(provisioned_servers)} new server(s)...")
            from shared_libs.backend.infra.node_agent import NodeAgentClient
            
            verified_servers = []
            for server in provisioned_servers:
                ip = server["ip"]
                agent = NodeAgentClient(ip, api_key)
                for attempt in range(45):  # 90 seconds
                    try:
                        resp = await agent.list_containers()  # Authenticated endpoint
                        if resp.success:
                            verified_servers.append(server)
                            log(f"   ✅ {ip} API key verified")
                            break
                    except:
                        pass
                    await asyncio.sleep(2)
                else:
                    log(f"   ❌ {ip} API key not ready after 90s")
            
            provisioned_servers = verified_servers
    
    def deploy_worker():
        """Run deployment in background thread."""
        import asyncio
        
        try:
            # Build config
            src_type = DeploySource.from_value(source_type)
            
            # Combine existing + provisioned servers
            all_server_ips = server_ips_list + [s["ip"] for s in provisioned_servers]
            
            # Parse domain aliases
            import json as json_mod2
            domain_aliases_list = []
            try:
                domain_aliases_list = json_mod2.loads(domain_aliases)
            except:
                pass
            
            config = MultiDeployConfig(
                name=name,
                port=port,
                container_port=container_port,
                host_port=host_port,
                env_vars=env_vars_dict,
                environment=environment,
                tags=tags_list,
                source_type=src_type,
                git_url=git_url,
                git_branch=git_branch,
                git_token=git_token,
                git_folders=git_folders,
                image=image,
                server_ips=all_server_ips,
                new_server_count=0,  # Already provisioned above
                snapshot_id=snapshot_id,
                region=region,
                size=size,
                dockerfile=dockerfile,
                project=project,  # For container naming
                workspace_id=str(user.id),  # For container naming
                # Domain config
                setup_domain=setup_domain,
                cloudflare_token=cf_token,
                base_domain=base_domain,
                domain_aliases=domain_aliases_list,
            )
            
            # Read file contents (from temp files, not memory)
            if code_tar_path:
                with open(code_tar_path, 'rb') as f:
                    config.code_tar = f.read()
            
            if image_tar_path:
                with open(image_tar_path, 'rb') as f:
                    config.image_tar = f.read()
            
            # Create service and deploy
            service = DeploymentService(
                do_token=token,
                agent_key=api_key,
                log=log,
            )
            
            # Run async deploy in new event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(service.deploy(config))
            loop.close()
            
            # Send done
            msg_queue.put({
                "type": "done",
                "success": result.success,
                "servers": [
                    {"ip": s.ip, "name": s.name, "success": s.success, "url": s.url, "error": s.error}
                    for s in result.servers
                ],
                "successful_count": result.successful_count,
                "failed_count": result.failed_count,
                "error": result.error,
                # Domain info
                "domain": result.domain,
                "domain_aliases": result.domain_aliases,
            })
            
        except Exception as e:
            import traceback
            log(f"❌ Error: {e}")
            traceback.print_exc()
            msg_queue.put({
                "type": "done",
                "success": False,
                "error": str(e),
            })
        finally:
            # Cleanup temp files
            if code_tar_path and os.path.exists(code_tar_path):
                os.unlink(code_tar_path)
            if image_tar_path and os.path.exists(image_tar_path):
                os.unlink(image_tar_path)
    
    # Start worker thread
    thread = threading.Thread(target=deploy_worker, daemon=True)
    thread.start()
    
    # SSE generator
    async def event_stream():
        import asyncio
        
        while True:
            try:
                msg = msg_queue.get(timeout=0.5)
                yield f"data: {json_mod.dumps(msg)}\n\n"
                
                if msg.get("type") == "done":
                    break
            except queue.Empty:
                yield f"data: {json_mod.dumps({'type': 'ping'})}\n\n"
            
            await asyncio.sleep(0.1)
    
    from starlette.responses import StreamingResponse
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


# ==========================================
# Two-Phase Deployment
# ==========================================

class PrepareRequest(BaseModel):
    """Request to prepare servers for deployment."""
    do_token: str
    server_ips: List[str] = []  # Existing servers
    new_server_count: int = 0   # New servers to provision
    snapshot_id: Optional[str] = None
    region: str = "lon1"
    size: str = "s-1vcpu-1gb"
    project: Optional[str] = None  # Project name for filtering
    environment: str = "prod"  # Environment (prod, staging, dev)


class PrepareResponse(BaseModel):
    """Response with session for streaming phase."""
    session_id: str
    ready_ips: List[str]
    expires_in: int  # seconds


@router.post("/deploy/prepare", response_model=PrepareResponse)
async def deploy_prepare(
    data: PrepareRequest,
    user: UserIdentity = Depends(get_current_user),
):
    """
    Phase 1: Prepare servers for deployment.
    
    Provisions new servers and/or validates existing ones.
    Returns a session_id to use with /deploy/stream.
    
    This allows true streaming even for new server deployments:
    1. POST /deploy/prepare → provisions servers, returns session_id
    2. POST /deploy/stream?session_id=xxx → streams image directly to ready servers
    """
    import asyncio
    
    token = _get_do_token(data.do_token)
    api_key = _get_node_agent_key(token, str(user.id))
    
    ready_ips = list(data.server_ips)  # Copy existing IPs
    
    # Provision new servers if requested
    if data.new_server_count > 0:
        if not data.snapshot_id:
            raise HTTPException(400, "snapshot_id required for new servers")
        
        from shared_libs.backend.infra.cloud import DOClient
        from shared_libs.backend.infra.utils.naming import generate_friendly_name
        
        client = DOClient(token)
        names = [generate_friendly_name() for _ in range(data.new_server_count)]
        
        # Create droplets - infra layer handles API key via node_agent_api_key param
        droplet_ids = []
        for dname in names:
            try:
                droplet = client.create_droplet(
                    name=dname,
                    region=data.region,
                    size=data.size,
                    image=data.snapshot_id,
                    tags=["deployed-via-api"],
                    project=data.project,
                    environment=data.environment,
                    node_agent_api_key=api_key,  # Infra auto-generates cloud-init
                    wait=False,
                )
                droplet_ids.append((droplet.id, dname))
            except Exception as e:
                raise HTTPException(500, f"Failed to create droplet {dname}: {e}")
        
        # Wait for droplets to be ready
        for droplet_id, dname in droplet_ids:
            for _ in range(120):  # 4 minute timeout
                try:
                    droplet = client.get_droplet(droplet_id)
                    if droplet and droplet.status == "active" and droplet.ip:
                        ready_ips.append(droplet.ip)
                        break
                except:
                    pass
                await asyncio.sleep(2)
            else:
                raise HTTPException(500, f"Timeout waiting for droplet {dname}")
    
    if not ready_ips:
        raise HTTPException(400, "No servers specified or provisioned")
    
    # Wait for agents to be ready WITH CORRECT API KEY
    # We use list_containers() which requires auth, not health() which is public
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    
    verified_ips = []
    for ip in ready_ips:
        agent = NodeAgentClient(ip, api_key)
        for attempt in range(45):  # 90 second timeout per server (cloud-init needs time to update key)
            try:
                # Use authenticated endpoint to verify API key is correct
                resp = await agent.list_containers()
                if resp.success:
                    verified_ips.append(ip)
                    break
            except:
                pass
            await asyncio.sleep(2)
        else:
            raise HTTPException(500, f"Agent on {ip} not responding with correct API key after 90s")
    
    # Create session
    store = get_prepare_store()
    session = store.create(
        user_id=str(user.id),
        ready_ips=verified_ips,
        api_key=api_key,
    )
    
    return PrepareResponse(
        session_id=session.session_id,
        ready_ips=verified_ips,
        expires_in=int(session.ttl),
    )


@router.post("/deploy/stream")
async def deploy_stream(
    request: Request,
    # All params in query (so we can stream body)
    do_token: Optional[str] = Query(None),  # Not required if session_id provided
    name: str = Query(...),
    image: str = Query(..., description="Image name after load"),
    port: int = Query(8000),
    container_port: Optional[int] = Query(None),
    host_port: Optional[int] = Query(None),
    project: Optional[str] = Query(None, description="Project name for filtering"),
    environment: str = Query("prod"),
    env_vars: str = Query("{}", description="JSON object of environment variables"),
    server_ips: str = Query("[]", description="JSON array of IPs"),
    new_server_count: int = Query(0),
    snapshot_id: Optional[str] = Query(None),
    region: str = Query("lon1"),
    size: str = Query("s-1vcpu-1gb"),
    # Two-phase: use session from /deploy/prepare
    session_id: Optional[str] = Query(None, description="Session from /deploy/prepare for true streaming"),
    # NEW: Auto env var injection
    auto_env: bool = Query(False, description="Auto-inject service discovery env vars (DB_HOST, REDIS_URL, etc.)"),
    depends_on: str = Query("[]", description="JSON array of service dependencies (e.g., ['postgres', 'redis'])"),
    # NEW: Volume mounts
    volumes: str = Query("[]", description="JSON array of volume mounts (e.g., ['/host:/container'])"),
    persist_data: bool = Query(False, description="Auto-mount /data volume for persistence"),
    user: UserIdentity = Depends(get_current_user),
):
    """
    TRUE STREAMING deploy endpoint for image_file source.
    
    All params in query string, raw image tar in request body.
    
    TWO MODES:
    1. With session_id: Uses pre-prepared servers from /deploy/prepare (TRUE streaming)
    2. Without session_id: Legacy mode - provisions inline (upload buffers while provisioning)
    
    NEW FEATURES:
    - auto_env=true: Auto-inject DATABASE_URL, REDIS_URL based on dependencies
    - depends_on=["postgres","redis"]: Specify what services this container needs
    - persist_data=true: Mount /data/{user}/{project}/{env}/{service}/data to /app/data
    - volumes=["..."]: Custom volume mounts
    
    For best performance with new servers:
    1. Call POST /deploy/prepare first to provision
    2. Then POST /deploy/stream?session_id=xxx to stream directly
    """
    import json as json_mod
    import queue
    import asyncio
    import time as time_mod
    
    # Parse env_vars JSON
    try:
        env_vars_dict = json_mod.loads(env_vars) if env_vars else {}
    except:
        env_vars_dict = {}
    
    # Parse depends_on JSON
    try:
        depends_on_list = json_mod.loads(depends_on) if depends_on else []
    except:
        depends_on_list = []
    
    # Parse volumes JSON
    try:
        volumes_list = json_mod.loads(volumes) if volumes else []
    except:
        volumes_list = []
    
    # Build final env vars (with auto-injection if enabled)
    project_name = project or name
    service_name = name
    workspace_id = str(user.id)
    
    if auto_env and depends_on_list:
        final_env_vars = _build_deploy_env(
            user_id=workspace_id,
            project=project_name,
            environment=environment,
            service=service_name,
            depends_on=depends_on_list,
            base_env_vars=env_vars_dict,
        )
    else:
        final_env_vars = env_vars_dict
    
    # Build final volumes (with auto data volume if enabled)
    final_volumes = _build_deploy_volumes(
        user_id=workspace_id,
        project=project_name,
        environment=environment,
        service=service_name,
        persist_data=persist_data,
        custom_volumes=volumes_list,
    )
    
    msg_queue = queue.Queue()
    
    def log(msg: str):
        msg_queue.put({"type": "log", "message": msg})
    
    # Log auto-injection info (after log function is defined)
    if auto_env and depends_on_list:
        log(f"🔧 Auto-injecting env vars for dependencies: {depends_on_list}")
    if persist_data:
        log(f"💾 Auto-mounting data volume for persistence")
    if final_volumes:
        log(f"📁 Volumes: {len(final_volumes)} mount(s)")
    
    # Check for two-phase session
    session = None
    if session_id:
        store = get_prepare_store()
        session = store.consume(session_id, str(user.id))
        if not session:
            msg_queue.put({"type": "done", "success": False, "error": "Invalid or expired session"})
            async def error_stream():
                while True:
                    try:
                        msg = msg_queue.get(timeout=0.5)
                        yield f"data: {json_mod.dumps(msg)}\n\n"
                        if msg.get("type") == "done":
                            break
                    except:
                        yield f"data: {json_mod.dumps({'type': 'ping'})}\n\n"
            from starlette.responses import StreamingResponse
            return StreamingResponse(error_stream(), media_type="text/event-stream")
        
        # Use session's prepared servers
        api_key = session.api_key
        ready_servers = session.ready_ips
        log(f"🔑 Using prepared session with {len(ready_servers)} server(s)")
    else:
        # Legacy mode - need do_token
        if not do_token:
            msg_queue.put({"type": "done", "success": False, "error": "do_token required (or use session_id from /deploy/prepare)"})
            async def error_stream():
                while True:
                    try:
                        msg = msg_queue.get(timeout=0.5)
                        yield f"data: {json_mod.dumps(msg)}\n\n"
                        if msg.get("type") == "done":
                            break
                    except:
                        yield f"data: {json_mod.dumps({'type': 'ping'})}\n\n"
            from starlette.responses import StreamingResponse
            return StreamingResponse(error_stream(), media_type="text/event-stream")
        
        token = _get_do_token(do_token)
        api_key = _get_node_agent_key(token, str(user.id))
        ready_servers = None  # Will be determined below
    
    # Check deployment lock
    # Service identity = container_name = {ws_short}_{project}_{env}_{service}
    from shared_libs.backend.infra.deploy import get_deployment_lock_manager
    from shared_libs.backend.infra.utils.naming import DeploymentNaming
    
    lock_mgr = get_deployment_lock_manager()
    
    # Generate container name using proper naming convention
    # Using user.id as workspace_id for now (personal workspace)
    workspace_id = str(user.id)
    project_name = project or name  # Use project param, fallback to app name
    service_name = name  # Service is always the app name
    
    container_name = DeploymentNaming.get_container_name(
        workspace_id=workspace_id,
        project=project_name,
        env=environment,
        service_name=service_name,
    )
    
    # Calculate internal port for sidecar
    from shared_libs.backend.infra.networking.ports import DeploymentPortResolver
    internal_port = DeploymentPortResolver.get_internal_port(
        workspace_id, project_name, environment, service_name
    )
    
    lock = lock_mgr.acquire(
        container_name=container_name,
        workspace_id=workspace_id,
        project=project_name,
        environment=environment,
        service=service_name,
    )
    if not lock:
        lock_info = lock_mgr.get_lock_info(container_name)
        if lock_info and lock_info.get("in_cooldown"):
            error_msg = f"Deployment completed recently. Wait {int(lock_info['cooldown_remaining'])}s before redeploying."
        else:
            error_msg = "Deployment already in progress for this service"
        
        msg_queue.put({"type": "done", "success": False, "error": error_msg})
        
        async def error_stream():
            while True:
                try:
                    msg = msg_queue.get(timeout=0.5)
                    yield f"data: {json_mod.dumps(msg)}\n\n"
                    if msg.get("type") == "done":
                        break
                except:
                    yield f"data: {json_mod.dumps({'type': 'ping'})}\n\n"
        
        from starlette.responses import StreamingResponse
        return StreamingResponse(error_stream(), media_type="text/event-stream")
    
    # Two-phase mode: skip provisioning, go straight to streaming
    if session:
        # ready_servers already set from session
        log(f"🔨 Deploying {container_name} to {len(ready_servers)} prepared server(s)...")
        
        from shared_libs.backend.infra.node_agent import NodeAgentClient
        
        results = []
        
        if len(ready_servers) == 1:
            # TRUE STREAMING - pipe directly to single agent
            ip = ready_servers[0]
            agent = NodeAgentClient(ip, api_key)
            
            # Ensure nginx is running (for service mesh)
            if auto_env or depends_on_list:
                await _ensure_nginx_on_server(agent, log)
            
            # Create data directories for volumes
            if final_volumes:
                await _ensure_data_directories(agent, final_volumes, log)
            
            stream_start = time_mod.time()
            
            async def body_stream():
                async for chunk in request.stream():
                    yield chunk
            
            load_result = await agent.load_image_stream(body_stream())
            
            stream_time = time_mod.time() - stream_start
            
            if load_result.success:
                log(f"   [{ip}] Image loaded in {stream_time:.1f}s")
                actual_port = host_port or port
                container_p = container_port or port
                
                run_result = await agent.run_container(
                    image=image,
                    name=container_name,
                    ports={str(actual_port): str(container_p)},
                    env_vars=final_env_vars,
                    volumes=final_volumes if final_volumes else None,
                    replace_existing=True,  # Infra handles stop/remove
                )
                
                if run_result.success:
                    url = f"http://{ip}:{actual_port}"
                    log(f"   [{ip}] ✅ Running at {url}")
                    results.append({"ip": ip, "name": container_name, "success": True, "url": url})
                    
                    # Setup nginx stream config for stateful services
                    await _setup_service_nginx_config(
                        agent, workspace_id, project_name, environment, service_name,
                        container_name, container_p, log_fn=log
                    )
                else:
                    log(f"   [{ip}] ❌ Container failed: {run_result.error}")
                    # Try to get container logs for debugging
                    try:
                        logs_result = await agent.container_logs(container_name, lines=50)
                        if logs_result.success and logs_result.data.get('logs'):
                            log(f"   [{ip}] 📋 Container startup logs:")
                            for line in logs_result.data['logs'].strip().split('\n')[-20:]:
                                log(f"      {line}")
                    except:
                        pass
                    results.append({"ip": ip, "name": container_name, "success": False, "error": run_result.error})
            else:
                log(f"   [{ip}] ❌ Load failed: {load_result.error}")
                results.append({"ip": ip, "name": container_name, "success": False, "error": load_result.error})
        
        else:
            # Multiple servers - TEE STREAMING: broadcast chunks to all agents simultaneously
            # This is faster than buffer-then-forward because upload and forward happen in parallel
            import httpx
            
            log(f"🔀 Deploying {container_name} to {len(ready_servers)} servers (tee-streaming)...")
            
            # Pre-setup: ensure nginx and directories on all servers
            if auto_env or depends_on_list or final_volumes:
                log("🔧 Pre-configuring servers...")
                for ip in ready_servers:
                    try:
                        agent = NodeAgentClient(ip, api_key)
                        if auto_env or depends_on_list:
                            await _ensure_nginx_on_server(agent)
                        if final_volumes:
                            await _ensure_data_directories(agent, final_volumes)
                    except Exception as e:
                        log(f"   [{ip}] ⚠️ Pre-config warning: {e}")
            
            stream_start = time_mod.time()
            total_size = 0
            
            # Create a queue for each agent to receive chunks
            queues = {ip: asyncio.Queue() for ip in ready_servers}
            results_dict = {}
            
            async def stream_to_agent(ip: str, q: asyncio.Queue):
                """Stream chunks from queue to agent."""
                agent_start = time_mod.time()
                
                async def chunk_generator():
                    while True:
                        chunk = await q.get()
                        if chunk is None:  # Sentinel for end
                            break
                        yield chunk
                
                try:
                    agent = NodeAgentClient(ip, api_key)
                    load_result = await agent.load_image_stream(chunk_generator())
                    
                    agent_time = time_mod.time() - agent_start
                    
                    if load_result.success:
                        log(f"   [{ip}] Image loaded in {agent_time:.1f}s")
                        actual_port = host_port or port
                        container_p = container_port or port
                        
                        run_result = await agent.run_container(
                            image=image,
                            name=container_name,
                            ports={str(actual_port): str(container_p)},
                            env_vars=final_env_vars,
                            volumes=final_volumes if final_volumes else None,
                            replace_existing=True,  # Infra handles stop/remove
                        )
                        
                        if run_result.success:
                            url = f"http://{ip}:{actual_port}"
                            log(f"   [{ip}] ✅ Running at {url}")
                            results_dict[ip] = {"ip": ip, "name": container_name, "success": True, "url": url}
                            
                            # Setup nginx stream config for this server
                            await _setup_service_nginx_config(
                                agent, workspace_id, project_name, environment, service_name,
                                container_name, container_p
                            )
                        else:
                            log(f"   [{ip}] ❌ Container failed: {run_result.error}")
                            # Try to get container logs for debugging
                            try:
                                logs_result = await agent.container_logs(container_name, lines=50)
                                if logs_result.success and logs_result.data.get('logs'):
                                    log(f"   [{ip}] 📋 Container startup logs:")
                                    for line in logs_result.data['logs'].strip().split('\n')[-20:]:
                                        log(f"      {line}")
                            except:
                                pass
                            results_dict[ip] = {"ip": ip, "name": container_name, "success": False, "error": run_result.error}
                    else:
                        log(f"   [{ip}] ❌ Load failed: {load_result.error}")
                        results_dict[ip] = {"ip": ip, "name": container_name, "success": False, "error": load_result.error}
                except Exception as e:
                    log(f"   [{ip}] ❌ Error: {e}")
                    results_dict[ip] = {"ip": ip, "name": container_name, "success": False, "error": str(e)}
            
            # Start all agent streaming tasks
            agent_tasks = [asyncio.create_task(stream_to_agent(ip, queues[ip])) for ip in ready_servers]
            
            # Read from browser and broadcast to all queues
            async for chunk in request.stream():
                total_size += len(chunk)
                for q in queues.values():
                    await q.put(chunk)
            
            # Signal end to all queues
            for q in queues.values():
                await q.put(None)
            
            # Wait for all agents to finish
            await asyncio.gather(*agent_tasks)
            
            total_time = time_mod.time() - stream_start
            log(f"📊 Tee-stream completed in {total_time:.1f}s ({total_size / 1024 / 1024:.1f}MB)")
            
            results = list(results_dict.values())
        
        # Completion for two-phase mode
        successful = sum(1 for r in results if r.get("success"))
        failed = len(results) - successful
        
        log("══════════════════════════════════════════════════")
        log(f"✅ Deployment Complete: {successful}/{len(results)} successful")
        
        if successful > 0:
            log("📋 Access:")
            for r in results:
                if r.get("success"):
                    log(f"   • {r.get('url')}")
        
        # Release deployment lock
        lock_mgr.release(lock.key, success=(successful > 0))
        
        msg_queue.put({
            "type": "done",
            "success": successful > 0,
            "servers": results,
            "successful_count": successful,
            "failed_count": failed,
            "container_name": container_name,
            "internal_port": internal_port,
            "service_name": service_name,
            "project": project_name,
            "environment": environment,
        })
        
        async def event_stream():
            while True:
                try:
                    msg = msg_queue.get(timeout=0.5)
                    yield f"data: {json_mod.dumps(msg)}\n\n"
                    if msg.get("type") == "done":
                        break
                except:
                    yield f"data: {json_mod.dumps({'type': 'ping'})}\n\n"
                await asyncio.sleep(0.1)
        
        from starlette.responses import StreamingResponse
        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
        )
    
    # Legacy mode - provision inline (rest of function handles this)
    token = _get_do_token(do_token)
    
    # Parse server IPs
    try:
        existing_ips = json_mod.loads(server_ips) if server_ips else []
    except:
        existing_ips = []
    
    log(f"🔑 Using API key: {api_key[:8]}...")
    
    # For new servers, require two-phase deploy (use /deploy/prepare first)
    if new_server_count > 0:
        lock_mgr.release(lock.key, success=False)
        msg_queue.put({
            "type": "done",
            "success": False,
            "error": "For new servers, use two-phase deploy: POST /deploy/prepare first, then /deploy/stream with session_id"
        })
        async def error_stream():
            while True:
                try:
                    msg = msg_queue.get(timeout=0.5)
                    yield f"data: {json_mod.dumps(msg)}\n\n"
                    if msg.get("type") == "done":
                        break
                except queue.Empty:
                    yield f"data: {json_mod.dumps({'type': 'ping'})}\n\n"
        from starlette.responses import StreamingResponse
        return StreamingResponse(error_stream(), media_type="text/event-stream")
    
    # STREAMING MODE - existing servers only (new servers require two-phase)
    # 1 server: true streaming, N servers: tee-streaming
    
    if not existing_ips:
        lock_mgr.release(lock.key, success=False)
        msg_queue.put({"type": "done", "success": False, "error": "No servers available"})
        async def error_stream():
            while True:
                try:
                    msg = msg_queue.get(timeout=0.5)
                    yield f"data: {json_mod.dumps(msg)}\n\n"
                    if msg.get("type") == "done":
                        break
                except queue.Empty:
                    yield f"data: {json_mod.dumps({'type': 'ping'})}\n\n"
        from starlette.responses import StreamingResponse
        return StreamingResponse(error_stream(), media_type="text/event-stream")
    
    # Check agents ready
    log(f"⏳ Checking node agent(s)...")
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    
    ready_servers = []
    for ip in existing_ips:
        agent = NodeAgentClient(ip, api_key)
        for attempt in range(15):
            try:
                resp = await agent.health()
                if resp.success:
                    version = resp.data.get("version", "?")
                    log(f"   ✅ {ip} agent ready (v{version})")
                    ready_servers.append(ip)
                    break
            except:
                pass
            await asyncio.sleep(2)
        else:
            log(f"   ❌ {ip} agent not responding")
    
    if not ready_servers:
        lock_mgr.release(lock.key, success=False)
        msg_queue.put({"type": "done", "success": False, "error": "No agents ready"})
        async def error_stream():
            while True:
                try:
                    msg = msg_queue.get(timeout=0.5)
                    yield f"data: {json_mod.dumps(msg)}\n\n"
                    if msg.get("type") == "done":
                        break
                except queue.Empty:
                    yield f"data: {json_mod.dumps({'type': 'ping'})}\n\n"
        from starlette.responses import StreamingResponse
        return StreamingResponse(error_stream(), media_type="text/event-stream")
    
    results = []
    
    if len(ready_servers) == 1:
        # Single server - TRUE STREAMING (fastest)
        ip = ready_servers[0]
        log(f"🔨 Deploying {container_name} to {ip}...")
        
        agent = NodeAgentClient(ip, api_key)
        
        # Ensure nginx is running (for service mesh)
        if auto_env or depends_on_list:
            await _ensure_nginx_on_server(agent, log)
        
        # Create data directories for volumes
        if final_volumes:
            await _ensure_data_directories(agent, final_volumes, log)
        
        stream_start = time.time()
        
        async def body_stream():
            async for chunk in request.stream():
                yield chunk
        
        load_result = await agent.load_image_stream(body_stream())
        
        stream_time = time.time() - stream_start
        
        if load_result.success:
            log(f"   [{ip}] Image loaded in {stream_time:.1f}s")
            actual_port = host_port or port
            container_p = container_port or port
            
            run_result = await agent.run_container(
                image=image,
                name=container_name,
                ports={str(actual_port): str(container_p)},
                env_vars=final_env_vars,
                volumes=final_volumes if final_volumes else None,
                replace_existing=True,  # Infra handles stop/remove
            )
            
            if run_result.success:
                url = f"http://{ip}:{actual_port}"
                log(f"   [{ip}] ✅ Running at {url}")
                results.append({"ip": ip, "name": container_name, "success": True, "url": url})
                
                # Setup nginx stream config for stateful services
                await _setup_service_nginx_config(
                    agent, workspace_id, project_name, environment, service_name,
                    container_name, container_p, log_fn=log
                )
            else:
                log(f"   [{ip}] ❌ Container failed: {run_result.error}")
                # Try to get container logs for debugging
                try:
                    logs_result = await agent.container_logs(container_name, lines=50)
                    if logs_result.success and logs_result.data.get('logs'):
                        log(f"   [{ip}] 📋 Container startup logs:")
                        for line in logs_result.data['logs'].strip().split('\n')[-20:]:
                            log(f"      {line}")
                except:
                    pass
                results.append({"ip": ip, "name": container_name, "success": False, "error": run_result.error})
        else:
            log(f"   [{ip}] ❌ Load failed after {stream_time:.1f}s: {load_result.error}")
            results.append({"ip": ip, "name": container_name, "success": False, "error": load_result.error})
    
    else:
        # Multiple servers - TEE STREAMING (broadcast chunks to all simultaneously)
        log(f"🔀 Deploying {container_name} to {len(ready_servers)} servers (tee-streaming)...")
        
        # Pre-setup: ensure nginx and directories on all servers
        if auto_env or depends_on_list or final_volumes:
            log("🔧 Pre-configuring servers...")
            for ip in ready_servers:
                try:
                    agent = NodeAgentClient(ip, api_key)
                    if auto_env or depends_on_list:
                        await _ensure_nginx_on_server(agent)
                    if final_volumes:
                        await _ensure_data_directories(agent, final_volumes)
                except Exception as e:
                    log(f"   [{ip}] ⚠️ Pre-config warning: {e}")
        
        stream_start = time.time()
        total_size = 0
        
        # Create a queue for each agent to receive chunks
        queues = {ip: asyncio.Queue() for ip in ready_servers}
        results_dict = {}
        
        async def stream_to_agent(ip: str, q: asyncio.Queue):
            """Stream chunks from queue to agent."""
            agent_start = time.time()
            
            async def chunk_generator():
                while True:
                    chunk = await q.get()
                    if chunk is None:  # Sentinel for end
                        break
                    yield chunk
            
            try:
                agent = NodeAgentClient(ip, api_key)
                load_result = await agent.load_image_stream(chunk_generator())
                
                agent_time = time.time() - agent_start
                
                if load_result.success:
                    log(f"   [{ip}] Image loaded in {agent_time:.1f}s")
                    actual_port = host_port or port
                    container_p = container_port or port
                    
                    run_result = await agent.run_container(
                        image=image,
                        name=container_name,
                        ports={str(actual_port): str(container_p)},
                        env_vars=final_env_vars,
                        volumes=final_volumes if final_volumes else None,
                        replace_existing=True,  # Infra handles stop/remove
                    )
                    
                    if run_result.success:
                        url = f"http://{ip}:{actual_port}"
                        log(f"   [{ip}] ✅ Running at {url}")
                        results_dict[ip] = {"ip": ip, "name": container_name, "success": True, "url": url}
                        
                        # Setup nginx stream config for this server
                        await _setup_service_nginx_config(
                            agent, workspace_id, project_name, environment, service_name,
                            container_name, container_p
                        )
                    else:
                        log(f"   [{ip}] ❌ Container failed: {run_result.error}")
                        # Try to get container logs for debugging
                        try:
                            logs_result = await agent.container_logs(container_name, lines=50)
                            if logs_result.success and logs_result.data.get('logs'):
                                log(f"   [{ip}] 📋 Container startup logs:")
                                for line in logs_result.data['logs'].strip().split('\n')[-20:]:
                                    log(f"      {line}")
                        except:
                            pass
                        results_dict[ip] = {"ip": ip, "name": container_name, "success": False, "error": run_result.error}
                else:
                    log(f"   [{ip}] ❌ Load failed: {load_result.error}")
                    results_dict[ip] = {"ip": ip, "name": container_name, "success": False, "error": load_result.error}
            except Exception as e:
                log(f"   [{ip}] ❌ Error: {e}")
                results_dict[ip] = {"ip": ip, "name": container_name, "success": False, "error": str(e)}
        
        # Start all agent streaming tasks
        agent_tasks = [asyncio.create_task(stream_to_agent(ip, queues[ip])) for ip in ready_servers]
        
        # Read from browser and broadcast to all queues
        async for chunk in request.stream():
            total_size += len(chunk)
            for q in queues.values():
                await q.put(chunk)
        
        # Signal end to all queues
        for q in queues.values():
            await q.put(None)
        
        # Wait for all agents to finish
        await asyncio.gather(*agent_tasks)
        
        total_time = time.time() - stream_start
        log(f"📊 Tee-stream completed in {total_time:.1f}s ({total_size / 1024 / 1024:.1f}MB)")
        
        results = list(results_dict.values())
    
    # Send completion
    successful = sum(1 for r in results if r.get("success"))
    failed = len(results) - successful
    
    log("══════════════════════════════════════════════════")
    log(f"✅ Deployment Complete: {successful}/{len(results)} successful")
    
    if successful > 0:
        log("📋 Access:")
        for r in results:
            if r.get("success"):
                log(f"   • {r.get('url')}")
    
    # Release deployment lock
    lock_mgr.release(lock.key, success=(successful > 0))
    
    msg_queue.put({
        "type": "done",
        "success": successful > 0,
        "servers": results,
        "successful_count": successful,
        "failed_count": failed,
    })
    
    async def event_stream():
        while True:
            try:
                msg = msg_queue.get(timeout=0.5)
                yield f"data: {json_mod.dumps(msg)}\n\n"
                if msg.get("type") == "done":
                    break
            except queue.Empty:
                yield f"data: {json_mod.dumps({'type': 'ping'})}\n\n"
            await asyncio.sleep(0.1)
    
    from starlette.responses import StreamingResponse
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )


# ==========================================
# Stateful Service Deployment
# ==========================================

class StatefulServiceRequest(BaseModel):
    """Request to deploy a stateful service (postgres, redis, etc.)."""
    service_type: str = Field(..., description="Service type: postgres, redis, mysql, mongo")
    project: str = Field(..., description="Project name")
    environment: str = Field("prod", description="Environment")
    server_ip: str = Field(..., description="Target server IP")
    do_token: str = Field(..., description="DigitalOcean token")
    image_tag: Optional[str] = Field(None, description="Custom image tag (default: latest)")
    extra_env_vars: Optional[Dict[str, str]] = Field(None, description="Additional env vars")


STATEFUL_SERVICE_IMAGES = {
    "postgres": "postgres:15-alpine",
    "postgresql": "postgres:15-alpine",
    "redis": "redis:7-alpine",
    "mysql": "mysql:8",
    "mariadb": "mariadb:11",
    "mongo": "mongo:7",
    "mongodb": "mongo:7",
}

STATEFUL_SERVICE_PORTS = {
    "postgres": 5432,
    "postgresql": 5432,
    "redis": 6379,
    "mysql": 3306,
    "mariadb": 3306,
    "mongo": 27017,
    "mongodb": 27017,
}


@router.post("/deploy/stateful")
async def deploy_stateful_service(
    req: StatefulServiceRequest,
    user: UserIdentity = Depends(get_current_user),
):
    """
    Deploy a stateful service (postgres, redis, mysql, mongo).
    
    This endpoint:
    1. Generates deterministic credentials
    2. Creates data volumes for persistence
    3. Deploys the container with proper env vars
    4. Sets up nginx stream proxy for internal access
    
    Returns the internal port for other services to connect.
    
    Example:
        POST /infra/deploy/stateful
        {
            "service_type": "postgres",
            "project": "myapp",
            "environment": "prod",
            "server_ip": "1.2.3.4",
            "do_token": "..."
        }
        
        Response:
        {
            "success": true,
            "container_name": "abc123_myapp_prod_postgres",
            "internal_port": 5186,
            "connection_info": {
                "host": "localhost",
                "port": 5186,
                "database": "...",
                "user": "...",
                "password": "..."
            }
        }
    """
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    from shared_libs.backend.infra.deploy import build_stateful_service_env, is_stateful_service
    from shared_libs.backend.infra.networking import DeploymentPortResolver
    from shared_libs.backend.infra.storage import VolumeManager
    from shared_libs.backend.infra.utils.naming import DeploymentNaming
    
    service_type = req.service_type.lower()
    
    if not is_stateful_service(service_type):
        raise HTTPException(400, f"Unknown stateful service: {service_type}. Supported: postgres, redis, mysql, mongo")
    
    # Get image and port
    image = req.image_tag or STATEFUL_SERVICE_IMAGES.get(service_type)
    container_port = STATEFUL_SERVICE_PORTS.get(service_type)
    
    if not image or not container_port:
        raise HTTPException(400, f"Unsupported service type: {service_type}")
    
    # Generate container name
    workspace_id = str(user.id)
    container_name = DeploymentNaming.get_container_name(
        workspace_id=workspace_id,
        project=req.project,
        env=req.environment,
        service_name=service_type,
    )
    
    # Build env vars for the service
    env_vars = build_stateful_service_env(
        user=workspace_id,
        project=req.project,
        env=req.environment,
        service=service_type,
        base_env_vars=req.extra_env_vars,
    )
    
    # Get volumes
    vm = VolumeManager()
    volumes = vm.get_standard_service_volumes(workspace_id, req.project, req.environment, service_type)
    volume_strs = [v.to_docker() for v in volumes]
    
    # Get internal port
    internal_port = DeploymentPortResolver.get_internal_port(
        workspace_id, req.project, req.environment, service_type
    )
    
    # Connect to agent
    api_key = _get_node_agent_key(req.do_token, workspace_id)
    client = NodeAgentClient(req.server_ip, api_key)
    
    try:
        # Ensure nginx is running
        await _ensure_nginx_on_server(client)
        
        # Create volume directories
        for vol in volume_strs:
            host_path = vol.split(":")[0]
            await client.create_directory(host_path)
        
        # Pull image
        pull_result = await client.pull_image(image)
        if not pull_result.success:
            raise HTTPException(500, f"Failed to pull image: {pull_result.error}")
        
        # Run container
        run_result = await client.run_container(
            image=image,
            name=container_name,
            ports=None,  # No host port mapping - use nginx
            env_vars=env_vars,
            volumes=volume_strs,
            restart_policy="unless-stopped",
            replace_existing=True,
        )
        
        if not run_result.success:
            raise HTTPException(500, f"Failed to start container: {run_result.error}")
        
        # Setup nginx stream config
        await _setup_service_nginx_config(
            client,
            workspace_id,
            req.project,
            req.environment,
            service_type,
            container_name,
            container_port,
            is_stateful=True,
        )
        
        # Build connection info
        connection_info = {
            "host": "localhost",
            "port": internal_port,
        }
        
        if service_type in ("postgres", "postgresql"):
            connection_info["database"] = env_vars.get("POSTGRES_DB")
            connection_info["user"] = env_vars.get("POSTGRES_USER")
            connection_info["password"] = env_vars.get("POSTGRES_PASSWORD")
            connection_info["url"] = f"postgresql://{connection_info['user']}:{connection_info['password']}@localhost:{internal_port}/{connection_info['database']}"
        elif service_type == "redis":
            connection_info["password"] = env_vars.get("REDIS_PASSWORD", "")
            connection_info["url"] = f"redis://:{connection_info['password']}@localhost:{internal_port}/0"
        elif service_type in ("mysql", "mariadb"):
            connection_info["database"] = env_vars.get("MYSQL_DATABASE")
            connection_info["user"] = env_vars.get("MYSQL_USER")
            connection_info["password"] = env_vars.get("MYSQL_PASSWORD")
            connection_info["url"] = f"mysql://{connection_info['user']}:{connection_info['password']}@localhost:{internal_port}/{connection_info['database']}"
        elif service_type in ("mongo", "mongodb"):
            connection_info["user"] = env_vars.get("MONGO_INITDB_ROOT_USERNAME")
            connection_info["password"] = env_vars.get("MONGO_INITDB_ROOT_PASSWORD")
            connection_info["url"] = f"mongodb://{connection_info['user']}:{connection_info['password']}@localhost:{internal_port}"
        
        return {
            "success": True,
            "container_name": container_name,
            "internal_port": internal_port,
            "connection_info": connection_info,
            "message": f"Service {service_type} deployed. Other services can connect to localhost:{internal_port}",
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Deployment failed: {str(e)}")


# ==========================================
# Cloudflare Domain & Load Balancer
# ==========================================

class DomainSetupRequest(BaseModel):
    """Request to set up a domain with Cloudflare."""
    domain: str = Field(..., description="Full domain name (e.g., api.example.com)")
    server_ip: str = Field(..., description="Server IP address")
    cloudflare_token: str = Field(..., description="Cloudflare API token")
    proxied: bool = Field(True, description="Enable Cloudflare proxy (handles SSL)")


class LoadBalancerSetupRequest(BaseModel):
    """Request to set up load balancing via multiple A records (FREE)."""
    domain: str = Field(..., description="Full domain name for the LB")
    server_ips: List[str] = Field(..., description="List of server IP addresses")
    cloudflare_token: str = Field(..., description="Cloudflare API token")
    proxied: bool = Field(True, description="Enable Cloudflare proxy")


class LoadBalancerUpdateRequest(BaseModel):
    """Request to add/remove server from LB."""
    domain: str = Field(..., description="Load balancer domain")
    server_ip: str = Field(..., description="Server IP to add/remove")
    cloudflare_token: str = Field(..., description="Cloudflare API token")


@router.post("/cloudflare/domain")
async def setup_domain(
    req: DomainSetupRequest,
    user: UserIdentity = Depends(get_current_user),
):
    """
    Set up a domain to point to your server.
    
    Creates/updates an A record in Cloudflare.
    
    With proxied=True (default):
    - Cloudflare handles SSL automatically (HTTPS works immediately)
    - DDoS protection enabled
    - Origin IP hidden
    
    Example:
        POST /infra/cloudflare/domain
        {
            "domain": "api.myapp.com",
            "server_ip": "1.2.3.4",
            "cloudflare_token": "...",
            "proxied": true
        }
        
    After this, https://api.myapp.com will work immediately.
    """
    from shared_libs.backend.infra.cloud import CloudflareClient, CloudflareError
    
    try:
        cf = CloudflareClient(req.cloudflare_token)
        record = cf.setup_domain(
            domain=req.domain,
            server_ip=req.server_ip,
            proxied=req.proxied,
        )
        
        return {
            "success": True,
            "domain": req.domain,
            "server_ip": req.server_ip,
            "proxied": req.proxied,
            "record_id": record.id,
            "message": f"Domain {req.domain} → {req.server_ip}" + 
                      (" (SSL via Cloudflare)" if req.proxied else " (direct, need own SSL)"),
        }
        
    except CloudflareError as e:
        raise HTTPException(400, f"Cloudflare error: {e.message}")
    except Exception as e:
        raise HTTPException(500, f"Failed to setup domain: {str(e)}")


@router.delete("/cloudflare/domain")
async def remove_domain(
    domain: str = Query(..., description="Domain to remove"),
    cloudflare_token: str = Query(..., description="Cloudflare API token"),
    user: UserIdentity = Depends(get_current_user),
):
    """
    Remove a domain's DNS record.
    
    Call this when decommissioning a service.
    """
    from shared_libs.backend.infra.cloud import CloudflareClient, CloudflareError
    
    try:
        cf = CloudflareClient(cloudflare_token)
        deleted = cf.remove_domain(domain)
        
        return {
            "success": deleted,
            "domain": domain,
            "message": f"Domain {domain} removed" if deleted else f"Domain {domain} not found",
        }
        
    except CloudflareError as e:
        raise HTTPException(400, f"Cloudflare error: {e.message}")
    except Exception as e:
        raise HTTPException(500, f"Failed to remove domain: {str(e)}")


@router.post("/cloudflare/lb")
async def setup_load_balancer(
    req: LoadBalancerSetupRequest,
    user: UserIdentity = Depends(get_current_user),
):
    """
    Set up FREE load balancing for multiple servers.
    
    Creates multiple A records for the same domain.
    Cloudflare automatically round-robins between them when proxied.
    
    This is FREE - no paid Cloudflare LB feature needed!
    
    Example:
        POST /infra/cloudflare/lb
        {
            "domain": "api.myapp.com",
            "server_ips": ["1.2.3.4", "5.6.7.8"],
            "cloudflare_token": "...",
            "proxied": true
        }
        
    After this, https://api.myapp.com distributes traffic across both servers.
    """
    from shared_libs.backend.infra.cloud import CloudflareClient, CloudflareError
    
    if len(req.server_ips) < 1:
        raise HTTPException(400, "At least one server IP required")
    
    try:
        cf = CloudflareClient(req.cloudflare_token)
        records = cf.setup_multi_server(
            domain=req.domain,
            server_ips=req.server_ips,
            proxied=req.proxied,
        )
        
        return {
            "success": True,
            "domain": req.domain,
            "server_ips": req.server_ips,
            "record_count": len(records),
            "proxied": req.proxied,
            "message": f"Load balancing {req.domain} → {len(req.server_ips)} servers (FREE via multi-A records)" +
                      (" + SSL via Cloudflare" if req.proxied else ""),
        }
        
    except CloudflareError as e:
        raise HTTPException(400, f"Cloudflare error: {e.message}")
    except Exception as e:
        raise HTTPException(500, f"Failed to setup load balancing: {str(e)}")


@router.post("/cloudflare/lb/add-server")
async def add_server_to_lb(
    req: LoadBalancerUpdateRequest,
    user: UserIdentity = Depends(get_current_user),
):
    """
    Add a server to an existing load-balanced domain.
    
    Creates an additional A record for the domain.
    
    Example:
        POST /infra/cloudflare/lb/add-server
        {
            "domain": "api.myapp.com",
            "server_ip": "9.10.11.12",
            "cloudflare_token": "..."
        }
    """
    from shared_libs.backend.infra.cloud import CloudflareClient, CloudflareError
    
    try:
        cf = CloudflareClient(req.cloudflare_token)
        record = cf.add_server(
            domain=req.domain,
            server_ip=req.server_ip,
        )
        
        # Get total count
        all_ips = cf.list_servers(req.domain)
        
        return {
            "success": True,
            "domain": req.domain,
            "added_ip": req.server_ip,
            "total_servers": len(all_ips),
            "all_ips": all_ips,
            "message": f"Added {req.server_ip} to {req.domain} (now {len(all_ips)} servers)",
        }
        
    except CloudflareError as e:
        raise HTTPException(400, f"Cloudflare error: {e.message}")
    except Exception as e:
        raise HTTPException(500, f"Failed to add server: {str(e)}")


@router.post("/cloudflare/lb/remove-server")
async def remove_server_from_lb(
    req: LoadBalancerUpdateRequest,
    user: UserIdentity = Depends(get_current_user),
):
    """
    Remove a server from a load-balanced domain.
    
    Deletes the A record for that IP.
    
    Example:
        POST /infra/cloudflare/lb/remove-server
        {
            "domain": "api.myapp.com",
            "server_ip": "1.2.3.4",
            "cloudflare_token": "..."
        }
    """
    from shared_libs.backend.infra.cloud import CloudflareClient, CloudflareError
    
    try:
        cf = CloudflareClient(req.cloudflare_token)
        deleted = cf.remove_server(
            domain=req.domain,
            server_ip=req.server_ip,
        )
        
        # Get remaining count
        all_ips = cf.list_servers(req.domain)
        
        return {
            "success": deleted,
            "domain": req.domain,
            "removed_ip": req.server_ip,
            "remaining_servers": len(all_ips),
            "all_ips": all_ips,
            "message": f"Removed {req.server_ip} from {req.domain} ({len(all_ips)} servers remaining)" if deleted else f"IP {req.server_ip} not found",
        }
        
    except CloudflareError as e:
        raise HTTPException(400, f"Cloudflare error: {e.message}")
    except Exception as e:
        raise HTTPException(500, f"Failed to remove server: {str(e)}")


@router.get("/cloudflare/lb/servers")
async def list_lb_servers(
    domain: str = Query(..., description="Domain to check"),
    cloudflare_token: str = Query(..., description="Cloudflare API token"),
    user: UserIdentity = Depends(get_current_user),
):
    """
    List all servers (A records) for a domain.
    """
    from shared_libs.backend.infra.cloud import CloudflareClient, CloudflareError
    
    try:
        cf = CloudflareClient(cloudflare_token)
        ips = cf.list_servers(domain)
        
        return {
            "success": True,
            "domain": domain,
            "server_count": len(ips),
            "server_ips": ips,
        }
        
    except CloudflareError as e:
        raise HTTPException(400, f"Cloudflare error: {e.message}")
    except Exception as e:
        raise HTTPException(500, f"Failed to list servers: {str(e)}")


@router.get("/cloudflare/zones")
async def list_cloudflare_zones(
    cloudflare_token: str = Query(..., description="Cloudflare API token"),
    user: UserIdentity = Depends(get_current_user),
):
    """
    List available Cloudflare zones (domains).
    
    Use this to verify your token works and see which domains you can manage.
    """
    from shared_libs.backend.infra.cloud import CloudflareClient, CloudflareError
    
    try:
        cf = CloudflareClient(cloudflare_token)
        zones = cf.list_zones()
        
        return {
            "success": True,
            "zones": [
                {
                    "id": z.get("id"),
                    "name": z.get("name"),
                    "status": z.get("status"),
                    "plan": z.get("plan", {}).get("name"),
                }
                for z in zones
            ],
        }
        
    except CloudflareError as e:
        raise HTTPException(400, f"Cloudflare error: {e.message}")
    except Exception as e:
        raise HTTPException(500, f"Failed to list zones: {str(e)}")


# ==========================================
# Nginx Load Balancer (FREE, with health checks)
# ==========================================

class NginxLBSetupRequest(BaseModel):
    """Request to set up nginx load balancer."""
    name: str = Field(..., description="Unique name for this LB (e.g., 'myapp_prod_api')")
    server_ip: str = Field(..., description="Server IP where nginx runs (the LB server)")
    backends: List[Dict[str, Any]] = Field(..., description="List of backend servers: [{ip, port, weight}]")
    do_token: str = Field(..., description="DigitalOcean API token")
    listen_port: int = Field(80, description="Port nginx listens on")
    domain: Optional[str] = Field(None, description="Optional domain for server_name")
    lb_method: str = Field("least_conn", description="Load balancing method: least_conn, round_robin, ip_hash")


class NginxLBUpdateRequest(BaseModel):
    """Request to update nginx LB backends."""
    name: str = Field(..., description="LB name")
    server_ip: str = Field(..., description="Server IP where nginx runs")
    backends: List[Dict[str, Any]] = Field(..., description="New list of backends")
    do_token: str = Field(..., description="DigitalOcean API token")


@router.post("/nginx/lb")
async def setup_nginx_lb(
    req: NginxLBSetupRequest,
    user: UserIdentity = Depends(get_current_user),
):
    """
    Set up nginx load balancer on a server.
    
    This creates an nginx upstream config that distributes traffic
    across multiple backend servers. FREE and includes health checks.
    
    Features:
    - Health checks (removes failed backends automatically)
    - Multiple LB methods: least_conn, round_robin, ip_hash
    - WebSocket support
    - Automatic failover to next backend
    
    Example:
        POST /infra/nginx/lb
        {
            "name": "myapp_prod_api",
            "server_ip": "1.2.3.4",
            "backends": [
                {"ip": "10.0.0.1", "port": 8000},
                {"ip": "10.0.0.2", "port": 8000},
                {"ip": "10.0.0.3", "port": 8000}
            ],
            "do_token": "...",
            "lb_method": "least_conn",
            "domain": "api.myapp.com"
        }
    
    After setup:
    - Traffic to server_ip:80 is distributed across backends
    - Failed backends are automatically removed
    - Point your domain to server_ip (or use Cloudflare)
    """
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    from shared_libs.backend.infra.cloud import generate_node_agent_key
    
    if not req.backends:
        raise HTTPException(400, "At least one backend required")
    
    try:
        # Connect to server
        token = _get_do_token(req.do_token)
        api_key = generate_node_agent_key(token, str(user.id))
        client = NodeAgentClient(req.server_ip, api_key)
        
        # Collect errors for debugging
        errors = []
        def log_error(msg):
            errors.append(msg)
            print(f"nginx/lb: {msg}")
        
        # Ensure nginx is running
        nginx_ok = await _ensure_nginx_on_server(client, log_fn=log_error)
        if not nginx_ok:
            error_detail = "; ".join(errors) if errors else "Unknown error"
            raise HTTPException(500, f"Failed to ensure nginx on server {req.server_ip}: {error_detail}")
        
        # Set up LB
        result = await _setup_nginx_http_lb(
            client=client,
            name=req.name,
            backends=req.backends,
            listen_port=req.listen_port,
            domain=req.domain,
            lb_method=req.lb_method,
            log_fn=log_error,
        )
        
        if not result:
            raise HTTPException(500, "Failed to configure nginx LB - check server logs")
        
        return {
            "success": True,
            "name": req.name,
            "lb_server": req.server_ip,
            "listen_port": req.listen_port,
            "domain": req.domain,
            "backends": req.backends,
            "lb_method": req.lb_method,
            "message": f"Nginx LB '{req.name}' configured with {len(req.backends)} backends",
        }
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"nginx/lb error: {traceback.format_exc()}")
        raise HTTPException(500, f"Failed to setup nginx LB: {str(e)}")


@router.put("/nginx/lb")
async def update_nginx_lb(
    req: NginxLBUpdateRequest,
    user: UserIdentity = Depends(get_current_user),
):
    """
    Update backends for an existing nginx LB.
    
    Use this to add/remove servers without recreating the LB.
    
    Example:
        PUT /infra/nginx/lb
        {
            "name": "myapp_prod_api",
            "server_ip": "1.2.3.4",
            "backends": [
                {"ip": "10.0.0.1", "port": 8000},
                {"ip": "10.0.0.4", "port": 8000}
            ],
            "do_token": "..."
        }
    """
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    from shared_libs.backend.infra.cloud import generate_node_agent_key
    
    if not req.backends:
        raise HTTPException(400, "At least one backend required")
    
    try:
        token = _get_do_token(req.do_token)
        api_key = generate_node_agent_key(token, str(user.id))
        client = NodeAgentClient(req.server_ip, api_key)
        
        result = await _update_nginx_lb_backends(
            client=client,
            name=req.name,
            backends=req.backends,
        )
        
        if not result:
            raise HTTPException(500, "Failed to update nginx LB")
        
        return {
            "success": True,
            "name": req.name,
            "backends": req.backends,
            "message": f"Nginx LB '{req.name}' updated with {len(req.backends)} backends",
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to update nginx LB: {str(e)}")


@router.delete("/nginx/lb")
async def delete_nginx_lb(
    name: str = Query(..., description="LB name to delete"),
    server_ip: str = Query(..., description="Server IP where nginx runs"),
    do_token: str = Query(..., description="DigitalOcean API token"),
    user: UserIdentity = Depends(get_current_user),
):
    """
    Delete an nginx LB configuration.
    
    Example:
        DELETE /infra/nginx/lb?name=myapp_prod_api&server_ip=1.2.3.4&do_token=...
    """
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    from shared_libs.backend.infra.cloud import generate_node_agent_key
    
    try:
        token = _get_do_token(do_token)
        api_key = generate_node_agent_key(token, str(user.id))
        client = NodeAgentClient(server_ip, api_key)
        
        success = await _remove_nginx_lb(client, name)
        
        return {
            "success": success,
            "name": name,
            "message": f"Nginx LB '{name}' deleted" if success else f"Failed to delete '{name}'",
        }
        
    except Exception as e:
        raise HTTPException(500, f"Failed to delete nginx LB: {str(e)}")


# ==========================================
# Nginx Sidecar (Service Mesh Pattern)
# ==========================================

class SidecarSetupRequest(BaseModel):
    """Request to set up nginx sidecar for service discovery."""
    server_ip: str = Field(..., description="Server IP where sidecar runs")
    project: str = Field(..., description="Project name")
    environment: str = Field(..., description="Environment")
    service: str = Field(..., description="Service name")
    container_name: str = Field(..., description="Container name (for single_server mode)")
    container_port: int = Field(..., description="Container port (5432, 6379, etc.)")
    do_token: str = Field(..., description="DigitalOcean API token")
    backends: Optional[List[Dict[str, Any]]] = Field(None, description="Backends for multi_server: [{ip, port}]")
    mode: str = Field("single_server", description="single_server (Docker DNS) or multi_server (IPs)")


class SidecarUpdateRequest(BaseModel):
    """Request to update sidecar backends."""
    server_ips: List[str] = Field(..., description="Server IPs where sidecars run (update all)")
    project: str = Field(..., description="Project name")
    environment: str = Field(..., description="Environment")
    service: str = Field(..., description="Service name")
    backends: List[Dict[str, Any]] = Field(..., description="New backends: [{ip, port}]")
    do_token: str = Field(..., description="DigitalOcean API token")


@router.post("/nginx/sidecar")
async def setup_sidecar(
    req: SidecarSetupRequest,
    user: UserIdentity = Depends(get_current_user),
):
    """
    Set up nginx sidecar for service discovery on a server.
    
    SIDECAR PATTERN: Every server runs nginx that provides:
    - Service discovery (apps connect to nginx:INTERNAL_PORT)
    - Load balancing (multiple backends)
    - Health checks (removes failed backends)
    - Zero-downtime deploys (update backends without app changes)
    
    Apps use Docker DNS: connect to "nginx:5234" instead of "postgres:5432"
    
    Example (single server):
        POST /infra/nginx/sidecar
        {
            "server_ip": "1.2.3.4",
            "project": "myapp",
            "environment": "prod", 
            "service": "postgres",
            "container_name": "abc123_myapp_prod_postgres",
            "container_port": 5432,
            "do_token": "...",
            "mode": "single_server"
        }
        
    Example (multi server):
        POST /infra/nginx/sidecar
        {
            "server_ip": "1.2.3.4",
            "project": "myapp",
            "environment": "prod",
            "service": "api",
            "container_name": "abc123_myapp_prod_api",
            "container_port": 8000,
            "do_token": "...",
            "mode": "multi_server",
            "backends": [
                {"ip": "10.0.0.1", "port": 8357},
                {"ip": "10.0.0.2", "port": 8357}
            ]
        }
    """
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    from shared_libs.backend.infra.cloud import generate_node_agent_key
    
    try:
        token = _get_do_token(req.do_token)
        api_key = generate_node_agent_key(token, str(user.id))
        client = NodeAgentClient(req.server_ip, api_key)
        
        # Ensure nginx is running
        await _ensure_nginx_on_server(client)
        
        # Set up sidecar config
        result = await _setup_service_nginx_config(
            client=client,
            user_id=str(user.id),
            project=req.project,
            environment=req.environment,
            service=req.service,
            container_name=req.container_name,
            container_port=req.container_port,
            backends=req.backends,
            mode=req.mode,
        )
        
        if not result:
            raise HTTPException(500, "Failed to configure sidecar")
        
        return {
            "success": True,
            "server_ip": req.server_ip,
            "project": req.project,
            "environment": req.environment,
            "service": req.service,
            "internal_port": result.get("internal_port"),
            "mode": req.mode,
            "message": f"Sidecar configured. Apps connect to nginx:{result.get('internal_port')}",
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to setup sidecar: {str(e)}")


@router.put("/nginx/sidecar")
async def update_sidecar(
    req: SidecarUpdateRequest,
    user: UserIdentity = Depends(get_current_user),
):
    """
    Update sidecar backends on multiple servers.
    
    Use this for:
    - Zero-downtime deploy: add new container to backends, remove old
    - Scaling: add/remove servers from the backend pool
    
    Updates ALL specified servers' sidecar configs to use the same backends.
    
    Example:
        PUT /infra/nginx/sidecar
        {
            "server_ips": ["1.2.3.4", "5.6.7.8"],
            "project": "myapp",
            "environment": "prod",
            "service": "api",
            "backends": [
                {"ip": "10.0.0.1", "port": 8357},
                {"ip": "10.0.0.2", "port": 8357},
                {"ip": "10.0.0.3", "port": 8357}
            ],
            "do_token": "..."
        }
    """
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    from shared_libs.backend.infra.cloud import generate_node_agent_key
    
    if not req.backends:
        raise HTTPException(400, "At least one backend required")
    
    try:
        token = _get_do_token(req.do_token)
        api_key = generate_node_agent_key(token, str(user.id))
        
        results = []
        errors = []
        
        for server_ip in req.server_ips:
            try:
                client = NodeAgentClient(server_ip, api_key)
                
                result = await _update_sidecar_backends(
                    client=client,
                    user_id=str(user.id),
                    project=req.project,
                    environment=req.environment,
                    service=req.service,
                    backends=req.backends,
                )
                
                if result:
                    results.append({"server_ip": server_ip, "success": True})
                else:
                    errors.append({"server_ip": server_ip, "error": "Failed to update"})
                    
            except Exception as e:
                errors.append({"server_ip": server_ip, "error": str(e)})
        
        return {
            "success": len(errors) == 0,
            "updated": results,
            "errors": errors,
            "backends": req.backends,
            "message": f"Updated {len(results)}/{len(req.server_ips)} servers",
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to update sidecars: {str(e)}")


# ==========================================
# Nginx Ensure/Fix
# ==========================================

class NginxEnsureRequest(BaseModel):
    """Request to ensure nginx is running on servers."""
    server_ips: List[str] = Field(..., description="Server IPs to ensure nginx on")
    do_token: str = Field(..., description="DO token")


@router.post("/nginx/ensure")
async def ensure_nginx_on_servers(
    req: NginxEnsureRequest,
    user: UserIdentity = Depends(get_current_user),
):
    """
    Ensure nginx sidecar is running on specified servers.
    
    Use this to fix servers that are missing the nginx sidecar.
    Creates nginx container if not exists, starts if stopped.
    
    Example:
        POST /infra/nginx/ensure
        {
            "server_ips": ["1.2.3.4", "5.6.7.8"],
            "do_token": "..."
        }
    
    Returns:
        {
            "success": true,
            "results": [
                {"ip": "1.2.3.4", "status": "started", "success": true},
                {"ip": "5.6.7.8", "status": "already_running", "success": true}
            ],
            "fixed": 1,
            "already_ok": 1,
            "failed": 0
        }
    """
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    from shared_libs.backend.infra.cloud import generate_node_agent_key
    from shared_libs.backend.infra.networking import NginxService
    
    try:
        token = _get_do_token(req.do_token)
        api_key = generate_node_agent_key(token, str(user.id))
        
        results = []
        fixed = 0
        already_ok = 0
        failed = 0
        
        for ip in req.server_ips:
            try:
                client = NodeAgentClient(ip, api_key)
                nginx = NginxService(client)
                
                result = await nginx.ensure_running()
                
                if result.success:
                    status = result.data.get("status", "started") if result.data else "started"
                    if status == "already_running":
                        already_ok += 1
                    else:
                        fixed += 1
                    results.append({
                        "ip": ip,
                        "status": status,
                        "success": True,
                    })
                else:
                    failed += 1
                    results.append({
                        "ip": ip,
                        "status": "failed",
                        "success": False,
                        "error": result.error,
                    })
                    
            except Exception as e:
                failed += 1
                results.append({
                    "ip": ip,
                    "status": "error",
                    "success": False,
                    "error": str(e),
                })
        
        return {
            "success": failed == 0,
            "results": results,
            "fixed": fixed,
            "already_ok": already_ok,
            "failed": failed,
            "message": f"Fixed {fixed}, already OK {already_ok}, failed {failed}",
        }
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Failed to ensure nginx: {str(e)}")


# ==========================================
# Architecture Topology
# ==========================================

class ArchitectureRequest(BaseModel):
    """Request to get architecture topology."""
    server_ips: Optional[List[str]] = Field(None, description="Server IPs to query (if empty, queries all user servers)")
    project: Optional[str] = Field(None, description="Filter by project")
    environment: Optional[str] = Field(None, description="Filter by environment")


@router.post("/architecture")
async def get_architecture(
    req: ArchitectureRequest,
    do_token: str = Query(..., description="DO token"),
    user: UserIdentity = Depends(get_current_user),
):
    """
    Get architecture topology showing services and their connections.
    
    Returns a graph structure with:
    - nodes: Services (containers) with their details
    - edges: Dependencies between services
    - servers: Server information
    
    Example response:
    ```json
    {
        "nodes": [
            {"id": "myapp_prod_api", "type": "service", "service": "api", "project": "myapp", "env": "prod", "servers": ["1.2.3.4"]},
            {"id": "myapp_prod_postgres", "type": "stateful", "service": "postgres", "project": "myapp", "env": "prod", "servers": ["1.2.3.4"]}
        ],
        "edges": [
            {"from": "myapp_prod_api", "to": "myapp_prod_postgres", "type": "depends_on"}
        ],
        "servers": [
            {"ip": "1.2.3.4", "name": "server-1", "region": "lon1", "containers": 2}
        ]
    }
    ```
    """
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    from shared_libs.backend.infra.cloud import generate_node_agent_key
    from shared_libs.backend.infra.cloud.digitalocean import DOClient
    
    try:
        token = _get_do_token(do_token)
        api_key = generate_node_agent_key(token, str(user.id))
        
        # Get server IPs
        server_ips = req.server_ips
        if not server_ips:
            # Query all user's servers
            do_client = DOClient(token)
            droplets = do_client.list_droplets(tag="deployed-via-api")
            server_ips = [d.ip for d in droplets if d.ip]
        
        if not server_ips:
            return {"nodes": [], "edges": [], "servers": [], "infrastructure": [], "message": "No servers found"}
        
        # Collect container info from all servers
        nodes = []
        edges = []
        servers_info = []
        infrastructure = []  # nginx, node-agent, etc.
        seen_services = set()
        seen_infra = set()
        
        # Known stateful services for categorization
        stateful_services = {"postgres", "postgresql", "mysql", "mariadb", "redis", "mongo", "mongodb", "opensearch", "elasticsearch"}
        
        # Infrastructure containers (not user-deployed services)
        infra_containers = {"nginx", "node-agent", "node_agent", "traefik", "caddy", "haproxy"}
        
        for ip in server_ips:
            try:
                client = NodeAgentClient(ip, api_key)
                
                # Get containers
                result = await client.list_containers()
                if not result.success:
                    servers_info.append({
                        "ip": ip,
                        "containers": 0,
                        "status": "error",
                        "error": result.error or "Failed to list containers",
                        "nginx_status": "unknown",
                        "agent_version": "unknown",
                    })
                    continue
                
                containers = result.data.get("containers", [])
                server_container_count = 0
                server_nginx_status = "not running"
                
                for container in containers:
                    # Docker JSON format uses capital letters: Names, State, Ports, Image
                    name = container.get("Names", container.get("name", ""))
                    state = container.get("State", container.get("status", ""))
                    
                    # Skip non-running containers
                    if state.lower() != "running":
                        continue
                    
                    server_container_count += 1
                    
                    # Check if this is an infrastructure container
                    name_lower = name.lower()
                    is_infra = any(infra in name_lower for infra in infra_containers)
                    
                    if is_infra:
                        # Track nginx status for this server
                        if "nginx" in name_lower:
                            server_nginx_status = "running"
                        
                        # Add to infrastructure list (dedupe by name)
                        infra_key = f"{name}@{ip}"
                        if infra_key not in seen_infra:
                            seen_infra.add(infra_key)
                            
                            ports_str = container.get("Ports", container.get("ports", ""))
                            port_info = []
                            if ports_str:
                                for port_mapping in str(ports_str).split(", "):
                                    if port_mapping.strip():
                                        port_info.append(port_mapping.strip())
                            
                            infrastructure.append({
                                "name": name,
                                "type": "nginx" if "nginx" in name_lower else "agent" if "agent" in name_lower else "proxy",
                                "server_ip": ip,
                                "status": "running",
                                "ports": port_info,
                                "image": container.get("Image", container.get("image", "")),
                            })
                        continue  # Don't add to main nodes
                    
                    # Parse container name: {workspace}_{project}_{env}_{service}
                    parts = name.split("_")
                    if len(parts) >= 4:
                        workspace_id = parts[0]
                        project = parts[1]
                        env = parts[2]
                        service = "_".join(parts[3:])  # Handle services with underscores
                    else:
                        # Unknown naming convention - use full name
                        workspace_id = "unknown"
                        project = name
                        env = "unknown"
                        service = name
                    
                    # Filter by project/environment if specified
                    if req.project and project != req.project:
                        continue
                    if req.environment and env != req.environment:
                        continue
                    
                    node_id = f"{project}_{env}_{service}"
                    
                    # Determine node type
                    service_lower = service.lower()
                    if service_lower in stateful_services:
                        node_type = "stateful"
                    elif service_lower == "nginx":
                        node_type = "proxy"
                    else:
                        node_type = "service"
                    
                    # Add or update node
                    if node_id not in seen_services:
                        seen_services.add(node_id)
                        
                        # Get port info - Docker returns Ports as string like "0.0.0.0:8000->8000/tcp"
                        ports_str = container.get("Ports", container.get("ports", ""))
                        port_info = []
                        container_port = None
                        host_port = None
                        if ports_str:
                            # Parse port string
                            for port_mapping in str(ports_str).split(", "):
                                if port_mapping.strip():
                                    port_info.append(port_mapping.strip())
                                    # Extract host:container ports from "0.0.0.0:18466->8000/tcp"
                                    if "->" in port_mapping:
                                        try:
                                            left, right = port_mapping.split("->")
                                            host_port = int(left.split(":")[-1])
                                            container_port = int(right.split("/")[0])
                                        except:
                                            pass
                        
                        # Calculate internal port for sidecar
                        from shared_libs.backend.infra.networking.ports import DeploymentPortResolver
                        internal_port = DeploymentPortResolver.get_internal_port(
                            workspace_id, project, env, service
                        )
                        
                        # Generate domain name
                        domain = f"{workspace_id}-{project}-{env}-{service}.digitalpixo.com".replace("_", "-")
                        
                        nodes.append({
                            "id": node_id,
                            "container_name": name,
                            "type": node_type,
                            "service": service,
                            "project": project,
                            "env": env,
                            "status": "running",
                            "ports": port_info,
                            "container_port": container_port,
                            "host_port": host_port,
                            "internal_port": internal_port,
                            "domain": domain,
                            "servers": [{"ip": ip, "container_port": host_port, "nginx_status": server_nginx_status}],
                            "image": container.get("Image", container.get("image", "")),
                        })
                    else:
                        # Add server to existing node
                        for node in nodes:
                            if node["id"] == node_id:
                                # Check if IP already in servers
                                existing_ips = [s["ip"] if isinstance(s, dict) else s for s in node["servers"]]
                                if ip not in existing_ips:
                                    # Get port from this container
                                    ports_str = container.get("Ports", container.get("ports", ""))
                                    host_port = None
                                    if ports_str and "->" in str(ports_str):
                                        try:
                                            left = str(ports_str).split("->")[0]
                                            host_port = int(left.split(":")[-1])
                                        except:
                                            pass
                                    node["servers"].append({"ip": ip, "container_port": host_port, "nginx_status": server_nginx_status})
                
                # Get agent version via ping
                agent_version = "unknown"
                try:
                    ping_result = await client.ping()
                    if ping_result.success:
                        agent_version = ping_result.data.get("version", "unknown")
                except:
                    pass
                
                # Add server info with nginx status
                servers_info.append({
                    "ip": ip,
                    "containers": server_container_count,
                    "status": "online",
                    "nginx_status": server_nginx_status,
                    "agent_version": agent_version,
                })
                
            except Exception as e:
                servers_info.append({
                    "ip": ip,
                    "containers": 0,
                    "status": "error",
                    "error": str(e),
                    "nginx_status": "unknown",
                    "agent_version": "unknown",
                })
        
        # Infer edges based on known patterns
        # Services typically connect to stateful services (postgres, redis, etc.)
        for node in nodes:
            if node["type"] == "service":
                # Check for potential dependencies
                project = node["project"]
                env = node["env"]
                
                for other_node in nodes:
                    if other_node["type"] == "stateful" and \
                       other_node["project"] == project and \
                       other_node["env"] == env:
                        edges.append({
                            "from": node["id"],
                            "to": other_node["id"],
                            "type": "depends_on",
                            "label": other_node["service"],
                        })
        
        # Also check env vars for DATABASE_URL, REDIS_URL, etc. to infer connections
        # (This would require querying container inspect, left as TODO)
        
        return {
            "nodes": nodes,
            "edges": edges,
            "servers": servers_info,
            "infrastructure": infrastructure,
            "filters": {
                "project": req.project,
                "environment": req.environment,
            },
        }
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Failed to get architecture: {str(e)}")


@router.get("/architecture/projects")
async def list_architecture_projects(
    do_token: str = Query(..., description="DO token"),
    user: UserIdentity = Depends(get_current_user),
):
    """
    List all projects/environments visible across servers.
    Useful for populating filter dropdowns.
    """
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    from shared_libs.backend.infra.cloud import generate_node_agent_key
    from shared_libs.backend.infra.cloud.digitalocean import DOClient
    
    try:
        token = _get_do_token(do_token)
        api_key = generate_node_agent_key(token, str(user.id))
        
        # Get all servers
        do_client = DOClient(token)
        droplets = do_client.list_droplets(tag="deployed-via-api")
        server_ips = [d.ip for d in droplets if d.ip]
        
        projects = set()
        environments = set()
        
        for ip in server_ips:
            try:
                client = NodeAgentClient(ip, api_key)
                result = await client.list_containers()
                if not result.success:
                    continue
                
                for container in result.data.get("containers", []):
                    # Docker JSON uses "Names" (capital N)
                    name = container.get("Names", container.get("name", ""))
                    parts = name.split("_")
                    if len(parts) >= 4:
                        projects.add(parts[1])
                        environments.add(parts[2])
            except:
                pass
        
        return {
            "projects": sorted(list(projects)),
            "environments": sorted(list(environments)),
        }
        
    except Exception as e:
        raise HTTPException(500, f"Failed to list projects: {str(e)}")


# =============================================================================
# Scheduler Routes
# =============================================================================

class ScheduleTaskRequest(BaseModel):
    """Request to create a scheduled task."""
    name: str
    task_type: str  # health_check, auto_restart, backup
    interval_minutes: int = 60
    enabled: bool = True
    config: Dict[str, Any] = {}


# Global scheduler instance
_task_scheduler = None


def get_task_scheduler():
    """Get or create the task scheduler."""
    global _task_scheduler
    if _task_scheduler is None:
        from shared_libs.backend.infra.scheduling import TaskScheduler, register_all_handlers
        _task_scheduler = TaskScheduler(check_interval=60)
        register_all_handlers(_task_scheduler)
    return _task_scheduler


@router.get("/scheduler/status")
async def get_scheduler_status(
    user: UserIdentity = Depends(get_current_user),
):
    """Get scheduler status and task summary."""
    scheduler = get_task_scheduler()
    status = scheduler.get_status()
    tasks = scheduler.list_tasks(str(user.id))
    
    return {
        **status,
        "tasks": [t.to_dict() for t in tasks],
    }


@router.get("/scheduler/tasks")
async def list_scheduled_tasks(
    user: UserIdentity = Depends(get_current_user),
):
    """List all scheduled tasks for the user."""
    scheduler = get_task_scheduler()
    tasks = scheduler.list_tasks(str(user.id))
    return {"tasks": [t.to_dict() for t in tasks]}


@router.post("/scheduler/tasks")
async def create_scheduled_task(
    req: ScheduleTaskRequest,
    user: UserIdentity = Depends(get_current_user),
    do_token: Optional[str] = Query(None),
):
    """Create a new scheduled task."""
    from shared_libs.backend.infra.scheduling import CentralizedTask, TaskType
    from shared_libs.backend.infra.cloud import generate_node_agent_key
    import uuid
    
    # Validate task type
    try:
        task_type = TaskType(req.task_type)
    except ValueError:
        raise HTTPException(400, f"Invalid task type: {req.task_type}. Valid: health_check, auto_restart, backup")
    
    # Generate API key for task
    token = do_token or _get_do_token(user.id)
    if token:
        api_key = generate_node_agent_key(token, str(user.id))
        req.config["api_key"] = api_key
    
    # Create task
    task = CentralizedTask(
        id=str(uuid.uuid4()),
        name=req.name,
        task_type=task_type,
        interval_minutes=req.interval_minutes,
        workspace_id=str(user.id),
        enabled=req.enabled,
        config=req.config,
    )
    
    scheduler = get_task_scheduler()
    scheduler.add_task(task)
    
    return {"task": task.to_dict()}


@router.delete("/scheduler/tasks/{task_id}")
async def delete_scheduled_task(
    task_id: str,
    user: UserIdentity = Depends(get_current_user),
):
    """Delete a scheduled task."""
    scheduler = get_task_scheduler()
    task = scheduler.get_task(task_id)
    
    if not task:
        raise HTTPException(404, "Task not found")
    
    if task.workspace_id != str(user.id):
        raise HTTPException(403, "Not authorized to delete this task")
    
    scheduler.remove_task(task_id)
    return {"deleted": task_id}


@router.post("/scheduler/tasks/{task_id}/enable")
async def enable_scheduled_task(
    task_id: str,
    user: UserIdentity = Depends(get_current_user),
):
    """Enable a scheduled task."""
    scheduler = get_task_scheduler()
    task = scheduler.get_task(task_id)
    
    if not task:
        raise HTTPException(404, "Task not found")
    
    if task.workspace_id != str(user.id):
        raise HTTPException(403, "Not authorized")
    
    scheduler.enable_task(task_id)
    return {"enabled": task_id}


@router.post("/scheduler/tasks/{task_id}/disable")
async def disable_scheduled_task(
    task_id: str,
    user: UserIdentity = Depends(get_current_user),
):
    """Disable a scheduled task."""
    scheduler = get_task_scheduler()
    task = scheduler.get_task(task_id)
    
    if not task:
        raise HTTPException(404, "Task not found")
    
    if task.workspace_id != str(user.id):
        raise HTTPException(403, "Not authorized")
    
    scheduler.disable_task(task_id)
    return {"disabled": task_id}


@router.post("/scheduler/tasks/{task_id}/run")
async def run_scheduled_task_now(
    task_id: str,
    user: UserIdentity = Depends(get_current_user),
):
    """Run a scheduled task immediately."""
    scheduler = get_task_scheduler()
    task = scheduler.get_task(task_id)
    
    if not task:
        raise HTTPException(404, "Task not found")
    
    if task.workspace_id != str(user.id):
        raise HTTPException(403, "Not authorized")
    
    success = await scheduler.run_task(task)
    
    return {
        "task_id": task_id,
        "success": success,
        "result": task.last_result,
        "status": task.last_status.value,
    }


@router.post("/scheduler/start")
async def start_scheduler(
    user: UserIdentity = Depends(get_current_user),
):
    """Start the scheduler background loop."""
    scheduler = get_task_scheduler()
    await scheduler.start()
    return {"status": "started"}


@router.post("/scheduler/stop")
async def stop_scheduler(
    user: UserIdentity = Depends(get_current_user),
):
    """Stop the scheduler background loop."""
    scheduler = get_task_scheduler()
    await scheduler.stop()
    return {"status": "stopped"}
