"""
DNS management logic.

Handles Cloudflare DNS record management for deployments.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from config import settings


# =============================================================================
# Domain Setup
# =============================================================================

async def setup_domain(
    cf_token: str,
    domain: str,
    server_ip: str,
    proxied: bool = True,
) -> Dict[str, Any]:
    """
    Set up DNS for a domain pointing to a server.
    
    Creates or updates A record.
    """
    from backend.cloud import AsyncCloudflareClient
    
    async with AsyncCloudflareClient(api_token=cf_token) as client:
        try:
            record = await client.upsert_a_record(
                domain=domain,
                ip=server_ip,
                proxied=proxied,
            )
            
            return {
                "domain": domain,
                "ip": server_ip,
                "record_id": record.id,
                "proxied": record.proxied,
                "status": "created",
            }
            
        except Exception as e:
            return {
                "domain": domain,
                "error": str(e),
            }


async def remove_domain(
    cf_token: str,
    domain: str,
) -> Dict[str, Any]:
    """
    Remove DNS record for a domain.
    """
    from backend.cloud import AsyncCloudflareClient
    
    async with AsyncCloudflareClient(api_token=cf_token) as client:
        try:
            success = await client.remove_domain(domain)
            
            return {
                "domain": domain,
                "status": "removed" if success else "not_found",
            }
            
        except Exception as e:
            return {
                "domain": domain,
                "error": str(e),
            }


# =============================================================================
# Multi-Server Setup (Load Balancing)
# =============================================================================

async def setup_multi_server(
    cf_token: str,
    domain: str,
    server_ips: List[str],
    proxied: bool = True,
) -> Dict[str, Any]:
    """
    Set up DNS with multiple servers (Cloudflare round-robin).
    
    Creates multiple A records for the same domain.
    """
    from backend.cloud import AsyncCloudflareClient
    
    async with AsyncCloudflareClient(api_token=cf_token) as client:
        try:
            records = await client.setup_multi_server(
                domain=domain,
                server_ips=server_ips,
                proxied=proxied,
            )
            
            return {
                "domain": domain,
                "servers": server_ips,
                "records": len(records),
                "status": "created",
            }
            
        except Exception as e:
            return {
                "domain": domain,
                "error": str(e),
            }


async def add_server_to_domain(
    cf_token: str,
    domain: str,
    server_ip: str,
    proxied: bool = True,
) -> Dict[str, Any]:
    """
    Add a server to existing domain (for scaling).
    """
    from backend.cloud import AsyncCloudflareClient
    
    async with AsyncCloudflareClient(api_token=cf_token) as client:
        try:
            record = await client.add_server(
                domain=domain,
                server_ip=server_ip,
                proxied=proxied,
            )
            
            return {
                "domain": domain,
                "ip": server_ip,
                "record_id": record.id,
                "status": "added",
            }
            
        except Exception as e:
            return {
                "domain": domain,
                "error": str(e),
            }


async def remove_server_from_domain(
    cf_token: str,
    domain: str,
    server_ip: str,
) -> Dict[str, Any]:
    """
    Remove a server from domain (for scaling down).
    """
    from backend.cloud import AsyncCloudflareClient
    
    async with AsyncCloudflareClient(api_token=cf_token) as client:
        try:
            success = await client.remove_server(
                domain=domain,
                server_ip=server_ip,
            )
            
            return {
                "domain": domain,
                "ip": server_ip,
                "status": "removed" if success else "not_found",
            }
            
        except Exception as e:
            return {
                "domain": domain,
                "error": str(e),
            }


async def list_domain_servers(
    cf_token: str,
    domain: str,
) -> Dict[str, Any]:
    """
    List all servers for a domain.
    """
    from backend.cloud import AsyncCloudflareClient
    
    async with AsyncCloudflareClient(api_token=cf_token) as client:
        try:
            servers = await client.list_servers(domain)
            
            return {
                "domain": domain,
                "servers": servers,
                "count": len(servers),
            }
            
        except Exception as e:
            return {
                "domain": domain,
                "error": str(e),
            }


# =============================================================================
# DNS Cleanup
# =============================================================================

async def cleanup_orphaned_records(
    cf_token: str,
    zone: str,
    active_ips: List[str],
) -> Dict[str, Any]:
    """
    Remove DNS records pointing to IPs that no longer exist.
    
    Useful for cleaning up after deleting droplets.
    """
    from backend.cloud import AsyncCloudflareClient
    
    async with AsyncCloudflareClient(api_token=cf_token) as client:
        try:
            result = await client.cleanup_orphaned_records(
                zone=zone,
                active_ips=set(active_ips),
                log_fn=print,  # TODO: use proper logging
            )
            
            return result
            
        except Exception as e:
            return {
                "zone": zone,
                "error": str(e),
            }


# =============================================================================
# Service Domain Helpers
# =============================================================================

def get_service_domain(
    service_name: str,
    environment: str,
    project_name: str,
    base_domain: Optional[str] = None,
) -> str:
    """
    Generate domain for a service.
    
    Format: {service}-{env}.{project}.{base_domain}
    Or: {service}-{env}-{project}.{base_domain}
    """
    base = base_domain or settings.base_domain
    
    if environment == "prod":
        # Production: service.project.domain
        return f"{service_name}.{project_name}.{base}"
    else:
        # Other envs: service-env.project.domain
        return f"{service_name}-{environment}.{project_name}.{base}"


async def setup_service_dns(
    db,
    cf_token: str,
    service_id: str,
    server_ips: List[str],
    custom_domain: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Set up DNS for a service deployment.
    
    Uses custom domain if provided, otherwise generates from service info.
    """
    from .stores import services, projects
    
    service = await services.get(db, service_id)
    if not service:
        return {"error": "Service not found"}
    
    project = await projects.get(db, service.get("project_id"))
    if not project:
        return {"error": "Project not found"}
    
    # Determine domain
    if custom_domain:
        domain = custom_domain
    else:
        domain = get_service_domain(
            service_name=service.get("name"),
            environment=service.get("environment", "prod"),
            project_name=project.get("name"),
        )
    
    # Set up DNS
    if len(server_ips) == 1:
        result = await setup_domain(cf_token, domain, server_ips[0])
    else:
        result = await setup_multi_server(cf_token, domain, server_ips)
    
    # Update service with domain
    if "error" not in result:
        await services.update(db, service_id, {"domain": domain})
        result["service_id"] = service_id
    
    return result


async def remove_service_dns(
    db,
    cf_token: str,
    service_id: str,
) -> Dict[str, Any]:
    """
    Remove DNS for a service.
    """
    from .stores import services
    
    service = await services.get(db, service_id)
    if not service:
        return {"error": "Service not found"}
    
    domain = service.get("domain")
    if not domain:
        return {"error": "Service has no domain configured"}
    
    result = await remove_domain(cf_token, domain)
    
    if result.get("status") == "removed":
        await services.update(db, service_id, {"domain": None})
    
    return result
