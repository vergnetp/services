"""
Networking Routes - Nginx, Cloudflare, DNS management.

Thin wrappers around infra.networking and infra.dns services.
"""

from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any

from shared_libs.backend.app_kernel.auth import get_current_user, UserIdentity

router = APIRouter(prefix="/infra", tags=["Networking"])


def _get_do_token(do_token: str = None) -> str:
    if do_token:
        return do_token
    raise HTTPException(400, "DigitalOcean token required")


# =============================================================================
# Nginx Routes
# =============================================================================

class NginxEnsureRequest(BaseModel):
    server_ips: List[str]
    do_token: Optional[str] = None


@router.post("/nginx/ensure")
async def ensure_nginx(
    req: NginxEnsureRequest,
    user: UserIdentity = Depends(get_current_user),
):
    """Ensure nginx is running on servers."""
    from shared_libs.backend.infra.networking import BulkNginxService
    service = BulkNginxService(_get_do_token(req.do_token), str(user.id))
    result = await service.ensure_on_servers(req.server_ips)
    return result.to_dict()


class NginxSidecarRequest(BaseModel):
    server_ip: str
    project: str
    environment: str
    service: str
    container_name: str
    container_port: int
    is_stateful: bool = False
    do_token: Optional[str] = None


@router.post("/nginx/sidecar")
async def setup_nginx_sidecar(
    req: NginxSidecarRequest,
    user: UserIdentity = Depends(get_current_user),
):
    """Setup nginx sidecar config on a server."""
    from shared_libs.backend.infra.networking import BulkNginxService
    service = BulkNginxService(_get_do_token(req.do_token), str(user.id))
    result = await service.setup_sidecar_on_servers(
        server_ips=[req.server_ip],
        project=req.project,
        environment=req.environment,
        service=req.service,
        container_name=req.container_name,
        container_port=req.container_port,
        is_stateful=req.is_stateful,
    )
    return result.to_dict()


@router.put("/nginx/sidecar")
async def update_nginx_sidecar(
    req: NginxSidecarRequest,
    user: UserIdentity = Depends(get_current_user),
):
    """Update nginx sidecar config."""
    return await setup_nginx_sidecar(req, user)


class NginxLBRequest(BaseModel):
    server_ips: List[str]
    name: str
    backends: List[Dict[str, Any]]
    listen_port: int = 80
    domain: Optional[str] = None
    lb_method: str = "least_conn"
    do_token: Optional[str] = None


@router.post("/nginx/lb")
async def setup_nginx_lb(
    req: NginxLBRequest,
    user: UserIdentity = Depends(get_current_user),
):
    """Setup nginx load balancer."""
    from shared_libs.backend.infra.networking import BulkNginxService
    service = BulkNginxService(_get_do_token(req.do_token), str(user.id))
    result = await service.setup_lb_on_servers(
        server_ips=req.server_ips,
        name=req.name,
        backends=req.backends,
        listen_port=req.listen_port,
        domain=req.domain,
        lb_method=req.lb_method,
    )
    return result.to_dict()


@router.put("/nginx/lb")
async def update_nginx_lb(
    req: NginxLBRequest,
    user: UserIdentity = Depends(get_current_user),
):
    """Update nginx load balancer."""
    return await setup_nginx_lb(req, user)


class NginxLBRemoveRequest(BaseModel):
    server_ips: List[str]
    name: str
    do_token: Optional[str] = None


@router.delete("/nginx/lb")
async def remove_nginx_lb(
    req: NginxLBRemoveRequest,
    user: UserIdentity = Depends(get_current_user),
):
    """Remove nginx load balancer."""
    from shared_libs.backend.infra.networking import BulkNginxService
    service = BulkNginxService(_get_do_token(req.do_token), str(user.id))
    result = await service.remove_lb_on_servers(req.server_ips, req.name)
    return result.to_dict()


class FixNginxRequest(BaseModel):
    server_ips: List[str]
    do_token: Optional[str] = None


@router.post("/servers/fix-nginx")
async def fix_nginx_on_servers(
    req: FixNginxRequest,
    user: UserIdentity = Depends(get_current_user),
):
    """Fix nginx on servers."""
    from shared_libs.backend.infra.networking import BulkNginxService
    service = BulkNginxService(_get_do_token(req.do_token), str(user.id))
    result = await service.ensure_on_servers(req.server_ips)
    return result.to_dict()


# =============================================================================
# Cloudflare DNS Routes
# =============================================================================

class CloudflareCleanupRequest(BaseModel):
    base_domain: str = "digitalpixo.com"
    dry_run: bool = True
    cf_token: Optional[str] = None
    do_token: Optional[str] = None


@router.post("/cloudflare/cleanup")
async def cleanup_cloudflare_dns(
    req: CloudflareCleanupRequest,
    user: UserIdentity = Depends(get_current_user),
):
    """Cleanup orphaned DNS records."""
    from shared_libs.backend.infra.dns import AsyncDnsCleanupService
    if not req.cf_token:
        raise HTTPException(400, "Cloudflare token required")
    service = AsyncDnsCleanupService(do_token=_get_do_token(req.do_token), cf_token=req.cf_token)
    result = await service.cleanup_orphaned(zone_name=req.base_domain, dry_run=req.dry_run)
    return result.to_dict()


class CloudflareDomainRequest(BaseModel):
    domain: str
    server_ips: List[str]
    container_name: str
    container_port: int
    proxied: bool = True
    cf_token: Optional[str] = None
    do_token: Optional[str] = None


@router.post("/cloudflare/domain")
async def setup_cloudflare_domain(
    req: CloudflareDomainRequest,
    user: UserIdentity = Depends(get_current_user),
):
    """Setup DNS and nginx for domain."""
    from shared_libs.backend.infra.networking import DomainService
    from shared_libs.backend.infra.node_agent import NodeAgentClient
    
    if not req.cf_token:
        raise HTTPException(400, "Cloudflare token required")
    
    token = _get_do_token(req.do_token)
    service = DomainService(cloudflare_token=req.cf_token)
    
    def agent_factory(ip: str) -> NodeAgentClient:
        return NodeAgentClient(ip, token)  # NodeAgentClient generates key from do_token
    
    result = await service.provision_domain(
        container_name=req.container_name,
        server_ips=req.server_ips,
        container_port=req.container_port,
        agent_client_factory=agent_factory,
        proxied=req.proxied,
    )
    return {
        "success": result.success,
        "domain": result.domain,
        "dns_created": result.dns_created,
        "nginx_configured": result.nginx_configured,
        "ssl_configured": result.ssl_configured,
        "error": result.error,
    }


class CloudflareLBRequest(BaseModel):
    name: str
    domain: str
    server_ips: List[str]
    cf_token: Optional[str] = None


@router.post("/cloudflare/lb")
async def setup_cloudflare_lb(
    req: CloudflareLBRequest,
    user: UserIdentity = Depends(get_current_user),
):
    """Setup Cloudflare load balancer (DNS round-robin)."""
    from shared_libs.backend.infra.dns import AsyncCloudflareLBService
    
    if not req.cf_token:
        raise HTTPException(400, "Cloudflare token required")
    
    service = AsyncCloudflareLBService(req.cf_token)
    result = await service.setup_lb(domain=req.domain, server_ips=req.server_ips)
    return result.to_dict()
