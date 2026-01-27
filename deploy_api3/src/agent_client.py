# =============================================================================
# src/agent_client.py
# =============================================================================
"""
Agent Client - HTTP client to call the node agent on droplets.
"""

import hmac
import hashlib
import base64
from typing import Dict, Any, List

from shared_libs.backend.http_client import AsyncHttpClient


def generate_api_key(do_token: str) -> str:
    """Generate API key for node agent authentication."""
    return hmac.new(do_token.encode(), b"node-agent:", hashlib.sha256).hexdigest()


async def call_agent(droplet_ip: str, endpoint: str, do_token: str, method: str = 'GET', 
                     json: Dict = None, data: bytes = None, params: Dict = None,
                     headers: Dict = None, timeout: int = 30) -> Dict[str, Any]:
    """Call node agent on droplet."""
    api_key = generate_api_key(do_token)
    url = f"http://{droplet_ip}:9999{endpoint}"
    
    req_headers = {"X-API-Key": api_key}
    if headers:
        req_headers.update(headers)
    
    async with AsyncHttpClient(timeout=timeout) as client:
        try:
            if method == 'GET':
                response = await client.get(url, params=params, headers=req_headers)
            elif method == 'POST':
                if data:
                    req_headers["Content-Type"] = "application/octet-stream"
                    response = await client.post(url, data=data, params=params, headers=req_headers)
                else:
                    response = await client.post(url, json=json, params=params, headers=req_headers)
            else:
                return {'error': f'Unsupported method: {method}'}
            
            return response.json()
        except Exception as e:
            return {'error': str(e)}


# =============================================================================
# Ping / Health
# =============================================================================

async def ping(droplet_ip: str, do_token: str) -> Dict[str, Any]:
    """Check if agent is alive."""
    return await call_agent(droplet_ip, '/ping', do_token, timeout=10)


async def health(droplet_ip: str, container_name: str, do_token: str) -> Dict[str, Any]:
    """Check container health."""
    return await call_agent(droplet_ip, '/health', do_token, params={'container_name': container_name})


# =============================================================================
# Image Upload
# =============================================================================

async def upload_image(droplet_ip: str, image_data: bytes, image_name: str, do_token: str) -> Dict[str, Any]:
    """Upload Docker image tar to droplet."""
    return await call_agent(droplet_ip, '/upload', do_token, method='POST', 
                           data=image_data, params={'name': image_name}, timeout=300)


# =============================================================================
# Build
# =============================================================================

async def build_image(droplet_ip: str, image_name: str, do_token: str,
                      git_repos: List[Dict] = None,
                      source_zips: Dict[str, bytes] = None,
                      dockerfile_content: str = None) -> Dict[str, Any]:
    """
    Build image from any combination of git repos and zips.
    
    Args:
        git_repos: [{'url': '...', 'branch'?: '...', 'token'?: '...'}, ...]
        source_zips: {'name': bytes, ...}
        dockerfile_content: Dockerfile content (required if not in source)
    """
    zips_encoded = {}
    if source_zips:
        zips_encoded = {name: base64.b64encode(data).decode() for name, data in source_zips.items()}
    
    return await call_agent(droplet_ip, '/build', do_token, method='POST', json={
        'image_name': image_name,
        'git_repos': git_repos or [],
        'zips': zips_encoded,
        'dockerfile_content': dockerfile_content,
    }, timeout=660)


# =============================================================================
# Container Operations
# =============================================================================

async def start_container(droplet_ip: str, container_name: str, image_name: str,
                          env_variables: List[str], container_port: int, host_port: int,
                          do_token: str) -> Dict[str, Any]:
    """Start a container on droplet."""
    return await call_agent(droplet_ip, '/start_container', do_token, method='POST', json={
        'container_name': container_name,
        'image_name': image_name,
        'env_variables': env_variables,
        'container_port': container_port,
        'host_port': host_port,
    })


async def remove_container(droplet_ip: str, container_name: str, do_token: str) -> Dict[str, Any]:
    """Stop and remove container from droplet."""
    return await call_agent(droplet_ip, '/remove_container', do_token, method='POST',
                           params={'container_name': container_name})


async def container_status(droplet_ip: str, container_name: str, do_token: str) -> Dict[str, Any]:
    """Get container status."""
    return await call_agent(droplet_ip, f'/containers/{container_name}/status', do_token)


async def restart_container(droplet_ip: str, container_name: str, do_token: str) -> Dict[str, Any]:
    """Restart a container."""
    return await call_agent(droplet_ip, f'/containers/{container_name}/restart', do_token, method='POST')


# =============================================================================
# Nginx
# =============================================================================

async def configure_nginx(droplet_ip: str, private_ips: List[str], host_port: int, 
                          domain: str, do_token: str) -> Dict[str, Any]:
    """Configure nginx upstream on droplet."""
    return await call_agent(droplet_ip, '/configure_nginx', do_token, method='POST', json={
        'private_ips': private_ips,
        'host_port': host_port,
        'domain': domain,
    })

