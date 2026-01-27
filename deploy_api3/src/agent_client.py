"""
Agent Client - HTTP client to call the node agent on droplets.
The agent runs at {droplet_ip}:9999 as a Flask app.
"""

import hmac
import hashlib
from typing import Dict, Any, List

from shared_libs.backend.http_client import AsyncHttpClient


def generate_api_key(do_token: str) -> str:
    """Generate API key for node agent authentication (must match agent's key)."""
    return hmac.new(do_token.encode(), b"node-agent:", hashlib.sha256).hexdigest()


async def call_agent(droplet_ip: str, endpoint: str, do_token: str, method: str = 'GET', 
                     json: Dict = None, data: bytes = None, params: Dict = None, 
                     timeout: int = 30) -> Dict[str, Any]:
    """
    Call node agent on droplet.
    
    Args:
        droplet_ip: IP of the droplet
        endpoint: API endpoint (e.g., '/ping', '/health')
        do_token: DigitalOcean token (used to derive API key)
        method: HTTP method
        json: JSON body
        data: Raw bytes (for image upload)
        params: Query parameters
        timeout: Request timeout
    
    Returns:
        Response JSON or {'error': '...'} on failure
    """
    api_key = generate_api_key(do_token)
    url = f"http://{droplet_ip}:9999{endpoint}"
    
    async with AsyncHttpClient(timeout=timeout) as client:
        client.set_auth_header("X-API-Key", api_key)
        
        try:
            if method == 'GET':
                response = await client.get(url, params=params)
            elif method == 'POST':
                if data:
                    response = await client.post(url, data=data, params=params,
                                                 headers={"Content-Type": "application/octet-stream"})
                else:
                    response = await client.post(url, json=json, params=params)
            else:
                return {'error': f'Unsupported method: {method}'}
            
            return response.json()
        except Exception as e:
            return {'error': str(e)}


# =============================================================================
# Convenience Functions (matching pseudo code)
# =============================================================================

async def ping(droplet_ip: str, do_token: str) -> Dict[str, Any]:
    """Check if agent is alive."""
    return await call_agent(droplet_ip, '/ping', do_token, timeout=10)


async def upload_image(droplet_ip: str, image_data: bytes, image_name: str, do_token: str) -> Dict[str, Any]:
    """Upload Docker image to droplet."""
    return await call_agent(droplet_ip, '/upload', do_token, method='POST', 
                           data=image_data, params={'name': image_name}, timeout=300)


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


async def health(droplet_ip: str, container_name: str, do_token: str) -> Dict[str, Any]:
    """
    Check container health (log parsing + TCP ping).
    
    Returns:
        {'status': 'healthy|unhealthy|degraded', 'reason': '...', 'details': [...]}
    """
    return await call_agent(droplet_ip, '/health', do_token, params={'container_name': container_name})


async def container_status(droplet_ip: str, container_name: str, do_token: str) -> Dict[str, Any]:
    """Get container status."""
    return await call_agent(droplet_ip, f'/containers/{container_name}/status', do_token)


async def restart_container(droplet_ip: str, container_name: str, do_token: str) -> Dict[str, Any]:
    """Restart a container."""
    return await call_agent(droplet_ip, f'/containers/{container_name}/restart', do_token, method='POST')


async def configure_nginx(droplet_ip: str, private_ips: List[str], host_port: int, 
                          domain: str, do_token: str) -> Dict[str, Any]:
    """Configure nginx upstream on droplet."""
    return await call_agent(droplet_ip, '/configure_nginx', do_token, method='POST', json={
        'private_ips': private_ips,
        'host_port': host_port,
        'domain': domain,
    })
