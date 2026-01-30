# =============================================================================
# src/agent_client.py
# =============================================================================
"""
Agent Client - HTTP client to call the node agent on droplets.

Authentication:
- Long-lived API key derived from DO token (HMAC)
- Short-lived JWT (10 min) for actual requests
- JWT cached per droplet to avoid re-minting

Flow:
1. First request to droplet: mint JWT locally, send as Bearer token
2. Subsequent requests: use cached JWT
3. On 401 (expired): invalidate cache, mint fresh JWT, retry
"""

import hmac
import hashlib
import base64
import time
import json
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

from shared_libs.backend.http_client import AsyncHttpClient


# =============================================================================
# JWT Token Management
# =============================================================================

JWT_EXPIRY_SECONDS = 600  # 10 minutes
JWT_REFRESH_BUFFER = 60   # Refresh 1 min before expiry

@dataclass
class CachedToken:
    """Cached JWT token for a droplet."""
    token: str
    expires_at: float


# Token cache: droplet_ip -> CachedToken
_token_cache: Dict[str, CachedToken] = {}


def generate_api_key(do_token: str) -> str:
    """Generate long-lived API key for node agent authentication."""
    return hmac.new(do_token.encode(), b"node-agent:", hashlib.sha256).hexdigest()


def generate_jwt(api_key: str, droplet_ip: str, ttl: int = JWT_EXPIRY_SECONDS) -> str:
    """
    Generate short-lived JWT signed with the API key.
    
    JWT structure (simple, no library needed):
    - Header: {"alg": "HS256", "typ": "JWT"}
    - Payload: {"sub": droplet_ip, "iat": timestamp, "exp": timestamp}
    - Signature: HMAC-SHA256(header.payload, api_key)
    """
    now = int(time.time())
    
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": droplet_ip,
        "iat": now,
        "exp": now + ttl,
    }
    
    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b'=').decode()
    
    header_b64 = b64url(json.dumps(header, separators=(',', ':')).encode())
    payload_b64 = b64url(json.dumps(payload, separators=(',', ':')).encode())
    
    message = f"{header_b64}.{payload_b64}"
    signature = hmac.new(api_key.encode(), message.encode(), hashlib.sha256).digest()
    signature_b64 = b64url(signature)
    
    return f"{message}.{signature_b64}"


def get_cached_token(droplet_ip: str) -> Optional[str]:
    """Get cached JWT if still valid (with refresh buffer)."""
    cached = _token_cache.get(droplet_ip)
    if cached and cached.expires_at > time.time() + JWT_REFRESH_BUFFER:
        return cached.token
    return None


def cache_token(droplet_ip: str, token: str, expires_at: float):
    """Cache a JWT token for a droplet."""
    _token_cache[droplet_ip] = CachedToken(token=token, expires_at=expires_at)


def invalidate_token(droplet_ip: str):
    """Remove cached token (e.g., on 401)."""
    _token_cache.pop(droplet_ip, None)


def get_or_create_token(droplet_ip: str, do_token: str) -> str:
    """Get cached JWT or create a new one."""
    token = get_cached_token(droplet_ip)
    if token:
        return token
    
    # Mint new token
    api_key = generate_api_key(do_token)
    token = generate_jwt(api_key, droplet_ip)
    expires_at = time.time() + JWT_EXPIRY_SECONDS
    cache_token(droplet_ip, token, expires_at)
    
    return token


# =============================================================================
# Agent IP Resolution
# =============================================================================

async def get_agent_ip(db, droplet) -> str:
    """
    Get the IP to use for agent calls based on managed mode.
    
    In managed mode (same DO account), agent only listens on VPC IP.
    In customer mode (different DO account), agent listens on public IP.
    
    Args:
        db: Database connection
        droplet: Droplet entity with ip, private_ip, and snapshot_id
    
    Returns:
        IP address to use for agent calls
    """
    from .utils import get_agent_ip_for_droplet
    return await get_agent_ip_for_droplet(db, droplet)


# =============================================================================
# HTTP Client
# =============================================================================

async def call_agent(droplet_ip: str, endpoint: str, do_token: str, method: str = 'GET', 
                     json_data: Dict = None, data: bytes = None, params: Dict = None,
                     headers: Dict = None, timeout: int = 30, retry_on_401: bool = True) -> Dict[str, Any]:
    """
    Call node agent on droplet.
    
    Uses JWT auth by default, falls back to fresh JWT on 401.
    """
    url = f"http://{droplet_ip}:9999{endpoint}"
    
    # Get or create JWT
    token = get_or_create_token(droplet_ip, do_token)
    
    req_headers = {"Authorization": f"Bearer {token}"}
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
                    response = await client.post(url, json=json_data, params=params, headers=req_headers)
            else:
                return {'error': f'Unsupported method: {method}'}
            
            # Handle 401 - token expired, retry with fresh token
            if response.status_code == 401 and retry_on_401:
                invalidate_token(droplet_ip)
                return await call_agent(
                    droplet_ip, endpoint, do_token, method,
                    json_data=json_data, data=data, params=params,
                    headers=headers, timeout=timeout, retry_on_401=False
                )
            
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
    
    return await call_agent(droplet_ip, '/build', do_token, method='POST', json_data={
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
    return await call_agent(droplet_ip, '/start_container', do_token, method='POST', json_data={
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
    return await call_agent(droplet_ip, '/configure_nginx', do_token, method='POST', json_data={
        'private_ips': private_ips,
        'host_port': host_port,
        'domain': domain,
    })
