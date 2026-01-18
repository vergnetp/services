"""
Infrastructure Routes - Servers, provisioning, snapshots, architecture.

Thin wrappers around infra.provisioning, infra.fleet, infra.cloud services.
"""

from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import json

from shared_libs.backend.app_kernel.auth import get_current_user, UserIdentity

router = APIRouter(prefix="/infra", tags=["Infrastructure"])


def _get_do_token(do_token: str = None) -> str:
    if do_token:
        return do_token
    raise HTTPException(400, "DigitalOcean token required")


# =============================================================================
# Setup Routes
# =============================================================================

@router.get("/setup/status")
async def get_setup_status(
    do_token: str = Query(...),
    user: UserIdentity = Depends(get_current_user),
):
    """Get environment setup status."""
    from shared_libs.backend.infra.setup import SetupService
    service = SetupService(_get_do_token(do_token), str(user.id))
    return service.get_status()


@router.post("/setup/init/stream")
async def init_setup_stream(
    do_token: str = Query(...),
    user: UserIdentity = Depends(get_current_user),
):
    """Initialize environment with base snapshot. Returns SSE stream."""
    from shared_libs.backend.infra.setup import SetupService
    service = SetupService(_get_do_token(do_token), str(user.id))
    
    def generate():
        for event in service.init_environment():
            yield f"data: {json.dumps(event.to_dict())}\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/setup/init")
async def init_setup(
    do_token: str = Query(...),
    user: UserIdentity = Depends(get_current_user),
):
    """Initialize environment (non-streaming, returns when done)."""
    from shared_libs.backend.infra.setup import SetupService
    service = SetupService(_get_do_token(do_token), str(user.id))
    result = service.init_environment_sync()
    return result


# =============================================================================
# Server/Fleet Routes
# =============================================================================

@router.get("/servers")
async def list_servers(
    do_token: str = Query(...),
    user: UserIdentity = Depends(get_current_user),
):
    """List managed servers."""
    from shared_libs.backend.infra.fleet import AsyncFleetService
    service = AsyncFleetService(_get_do_token(do_token), str(user.id))
    servers = await service.list_servers()
    return {"servers": [s.to_dict() for s in servers]}


@router.get("/fleet/health")
async def get_fleet_health(
    do_token: str = Query(...),
    user: UserIdentity = Depends(get_current_user),
):
    """Get health status of all servers."""
    from shared_libs.backend.infra.fleet import AsyncFleetService
    service = AsyncFleetService(_get_do_token(do_token), str(user.id))
    health = await service.get_fleet_health()
    return health.to_dict()


@router.delete("/servers/{droplet_id}")
async def delete_server(
    droplet_id: str,
    do_token: str = Query(...),
    force: bool = Query(False),
    user: UserIdentity = Depends(get_current_user),
):
    """Delete a managed server."""
    from shared_libs.backend.infra.fleet import AsyncFleetService
    service = AsyncFleetService(_get_do_token(do_token), str(user.id))
    result = await service.delete_server(droplet_id, force=force)
    if not result.get("success"):
        raise HTTPException(400, result.get("error", "Delete failed"))
    return result


# =============================================================================
# Provisioning Routes
# =============================================================================

class ProvisionRequest(BaseModel):
    name: Optional[str] = None
    snapshot_id: Optional[str] = None
    region: str = "lon1"
    size: str = "s-2vcpu-2gb"
    tags: List[str] = []
    do_token: Optional[str] = None


@router.post("/servers/provision")
async def provision_servers(
    req: ProvisionRequest,
    user: UserIdentity = Depends(get_current_user),
):
    """Provision a new server from snapshot."""
    from shared_libs.backend.infra.provisioning import AsyncProvisioningService
    
    token = _get_do_token(req.do_token)
    service = AsyncProvisioningService(token, str(user.id))
    result = await service.provision_server(
        region=req.region,
        size=req.size,
        snapshot_id=req.snapshot_id,
        name=req.name,
        tags=req.tags,
    )
    return result.to_dict()


@router.post("/servers/provision/stream")
async def provision_servers_stream(
    req: ProvisionRequest,
    do_token: str = Query(None),
    user: UserIdentity = Depends(get_current_user),
):
    """Provision new servers with streaming progress."""
    from shared_libs.backend.infra.provisioning import AsyncProvisioningService
    
    token = _get_do_token(req.do_token or do_token)
    service = AsyncProvisioningService(token, str(user.id))
    
    async def generate():
        async for event in service.provision_with_progress(
            region=req.region,
            size=req.size,
            snapshot_id=req.snapshot_id,
            name=req.name,
            tags=req.tags,
        ):
            yield f"data: {json.dumps(event.to_dict())}\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# =============================================================================
# Snapshot Routes
# =============================================================================

@router.get("/snapshots")
async def list_snapshots(
    do_token: str = Query(...),
    user: UserIdentity = Depends(get_current_user),
):
    """List available snapshots."""
    from shared_libs.backend.infra.cloud import SnapshotService
    service = SnapshotService(_get_do_token(do_token))
    return {"snapshots": service.list_snapshots()}


@router.get("/snapshots/presets")
async def get_snapshot_presets():
    """Get available snapshot presets."""
    from shared_libs.backend.infra.cloud import SNAPSHOT_PRESETS
    return {"presets": list(SNAPSHOT_PRESETS.keys())}


class SnapshotBuildRequest(BaseModel):
    name: Optional[str] = None
    preset_name: Optional[str] = "base"
    base_image: str = "ubuntu-22-04-x64"
    install_docker: bool = True
    install_nginx: bool = True
    install_certbot: bool = True
    region: str = "lon1"


@router.post("/snapshots/ensure/stream")
async def ensure_snapshot_stream(
    req: SnapshotBuildRequest = None,
    preset_name: str = Query("base"),
    region: str = Query("lon1"),
    do_token: str = Query(...),
    user: UserIdentity = Depends(get_current_user),
):
    """Create snapshot if not exists. Returns SSE stream."""
    from shared_libs.backend.infra.cloud import SnapshotService, SNAPSHOT_PRESETS, SnapshotConfig
    from shared_libs.backend.infra.node_agent import AGENT_VERSION
    
    token = _get_do_token(do_token)
    service = SnapshotService(token)
    
    if req and req.name:
        config = SnapshotConfig(
            name=req.name,
            base_image=req.base_image,
            install_docker=req.install_docker,
            apt_packages=["nginx"] if req.install_nginx else [],
            pip_packages=["certbot", "certbot-nginx"] if req.install_certbot else [],
            docker_images=[],
            # node_agent_api_key auto-generated by SnapshotService from do_token
        )
        use_region = req.region or region
    else:
        preset = SNAPSHOT_PRESETS.get(preset_name, SNAPSHOT_PRESETS["minimal"])
        preset_config = preset["config"]
        config = SnapshotConfig(
            name=f"{preset_name}-agent-v{AGENT_VERSION.replace('.', '-')}",
            install_docker=preset_config.install_docker,
            apt_packages=preset_config.apt_packages,
            pip_packages=preset_config.pip_packages,
            docker_images=preset_config.docker_images,
            # node_agent_api_key auto-generated by SnapshotService from do_token
        )
        use_region = region
    
    def generate():
        for event in service.ensure_snapshot_stream(config, region=use_region):
            yield f"data: {json.dumps(event)}\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/snapshots/build")
async def build_snapshot(
    preset_name: str = Query("base"),
    region: str = Query("lon1"),
    do_token: str = Query(...),
    user: UserIdentity = Depends(get_current_user),
):
    """Build a snapshot (non-streaming)."""
    from shared_libs.backend.infra.cloud import SnapshotService, SNAPSHOT_PRESETS, SnapshotConfig
    from shared_libs.backend.infra.node_agent import AGENT_VERSION
    
    token = _get_do_token(do_token)
    service = SnapshotService(token)
    
    preset = SNAPSHOT_PRESETS.get(preset_name, SNAPSHOT_PRESETS["minimal"])
    preset_config = preset["config"]
    
    config = SnapshotConfig(
        name=f"{preset_name}-agent-v{AGENT_VERSION.replace('.', '-')}",
        install_docker=preset_config.install_docker,
        apt_packages=preset_config.apt_packages,
        pip_packages=preset_config.pip_packages,
        docker_images=preset_config.docker_images,
        # node_agent_api_key auto-generated by SnapshotService from do_token
    )
    
    result = service.ensure_snapshot(config, region=region)
    return result


@router.delete("/snapshots/{snapshot_id}")
async def delete_snapshot(
    snapshot_id: str,
    do_token: str = Query(...),
    user: UserIdentity = Depends(get_current_user),
):
    """Delete a snapshot."""
    from shared_libs.backend.infra.cloud import SnapshotService
    service = SnapshotService(_get_do_token(do_token))
    service.delete_snapshot(snapshot_id)
    return {"success": True, "deleted": snapshot_id}


@router.post("/snapshots/{snapshot_id}/transfer-all")
async def transfer_snapshot_to_all_regions(
    snapshot_id: str,
    do_token: str = Query(...),
    user: UserIdentity = Depends(get_current_user),
):
    """Transfer snapshot to all regions."""
    from shared_libs.backend.infra.cloud import SnapshotService
    service = SnapshotService(_get_do_token(do_token))
    result = service.transfer_snapshot_to_all_regions(snapshot_id, wait=False)
    return result


# =============================================================================
# Architecture Routes
# =============================================================================

class ArchitectureRequest(BaseModel):
    server_ips: Optional[List[str]] = None
    project: Optional[str] = None
    environment: Optional[str] = None
    do_token: Optional[str] = None


@router.post("/architecture")
async def get_architecture(
    req: ArchitectureRequest,
    user: UserIdentity = Depends(get_current_user),
):
    """Get architecture topology."""
    from shared_libs.backend.infra.architecture import AsyncArchitectureService
    service = AsyncArchitectureService(_get_do_token(req.do_token), str(user.id))
    topology = await service.get_topology(
        server_ips=req.server_ips,
        project=req.project,
        environment=req.environment,
    )
    return topology.to_dict()


@router.get("/architecture/projects")
async def get_architecture_projects(
    do_token: str = Query(...),
    user: UserIdentity = Depends(get_current_user),
):
    """Get projects from architecture."""
    from shared_libs.backend.infra.architecture import AsyncArchitectureService
    service = AsyncArchitectureService(_get_do_token(do_token), str(user.id))
    projects = await service.get_projects()
    return {"projects": projects}


@router.get("/projects")
async def get_projects(
    do_token: str = Query(...),
    user: UserIdentity = Depends(get_current_user),
):
    """Get projects (alias for architecture/projects)."""
    from shared_libs.backend.infra.architecture import AsyncArchitectureService
    service = AsyncArchitectureService(_get_do_token(do_token), str(user.id))
    projects = await service.get_projects()
    return {"projects": projects}


# =============================================================================
# Info Routes
# =============================================================================

@router.get("/info")
async def get_info():
    """Get API info."""
    from shared_libs.backend.infra.node_agent import AGENT_VERSION
    from shared_libs.backend.infra import __version__ as infra_version
    return {
        "api": "deploy_api",
        "infra_version": infra_version,
        "agent_version": AGENT_VERSION,
    }


@router.get("/regions")
async def get_regions():
    """Get available DO regions."""
    from shared_libs.backend.infra.cloud import DO_REGIONS
    return {"regions": DO_REGIONS}


@router.get("/sizes")
async def get_sizes():
    """Get available droplet sizes with formatted descriptions."""
    from shared_libs.backend.infra.cloud import DROPLET_SIZES
    
    sizes = []
    for s in DROPLET_SIZES:
        mem = s["memory"]
        mem_str = f"{mem // 1024}GB" if mem >= 1024 else f"{mem}MB"
        desc = f"${s['price_monthly']}/mo - {mem_str} / {s['vcpus']} vCPU"
        sizes.append({**s, "description": desc})
    
    return {"sizes": sizes}


@router.get("/stateful-types")
async def get_stateful_types():
    """Get available stateful service types."""
    from shared_libs.backend.infra.deploy import get_stateful_service_types
    return {"types": get_stateful_service_types()}


@router.get("/debug/agent-key")
async def debug_agent_key(
    do_token: str = Query(...),
    user: UserIdentity = Depends(get_current_user),
):
    """Debug: Show what API key would be generated from DO token."""
    from shared_libs.backend.infra.cloud import generate_node_agent_key
    key = generate_node_agent_key(do_token)  # NO user_id - must match snapshot
    return {
        "key_prefix": key[:8],
        "key_full": key,  # Remove in production!
        "user_id": str(user.id),
        "note": "Key is generated from DO token only (no user_id). Compare with: cat /etc/node-agent/api-key on server"
    }


@router.get("/debug/agent-key-raw")
async def debug_agent_key_raw(
    do_token: str = Query(...),
    user_id: str = Query(""),
):
    """Debug: Show what API key would be generated (no auth required)."""
    from shared_libs.backend.infra.cloud import generate_node_agent_key
    key_with_user = generate_node_agent_key(do_token, user_id)
    key_without_user = generate_node_agent_key(do_token, "")
    return {
        "with_user_id": {
            "key_prefix": key_with_user[:8],
            "key_full": key_with_user,
            "user_id_used": user_id,
        },
        "without_user_id": {
            "key_prefix": key_without_user[:8],
            "key_full": key_without_user,
        },
        "note": "Compare with: cat /etc/node-agent/api-key on server"
    }


@router.get("/services/{service_name}/connection")
async def get_service_connection(
    service_name: str,
    project: str = Query(...),
    environment: str = Query("prod"),
    host: str = Query(...),
    port: int = Query(...),
    user: UserIdentity = Depends(get_current_user),
):
    """
    Get connection info for a stateful service.
    
    Regenerates deterministic credentials based on user/project/env/service.
    Use this to retrieve connection URL if you forgot it after deployment.
    """
    from shared_libs.backend.infra.deploy.env_builder import get_connection_info, is_stateful_service
    
    if not is_stateful_service(service_name):
        raise HTTPException(400, f"{service_name} is not a stateful service")
    
    info = get_connection_info(
        user=str(user.id),
        project=project,
        env=environment,
        service=service_name,
        host=host,
        port=port,
    )
    
    return info


@router.get("/registry")
async def get_registry_credentials(
    user: UserIdentity = Depends(get_current_user),
):
    """Get docker registry credentials."""
    import os
    return {
        "registry": os.getenv("DOCKER_REGISTRY", "docker.io"),
        "username": os.getenv("DOCKER_USERNAME", ""),
        "configured": bool(os.getenv("DOCKER_USERNAME")),
    }
