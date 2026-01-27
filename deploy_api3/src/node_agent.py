"""
Node Agent Client - includes graceful drain, image cleanup, configurable health path.
"""

import hmac
import hashlib
from typing import Optional, List, Dict, Any

from backend.http_client import AsyncHttpClient


def generate_api_key(do_token: str) -> str:
    return hmac.new(do_token.encode(), b"node-agent:", hashlib.sha256).hexdigest()


class NodeAgentClient:
    """Async client for node agent HTTP API."""
    
    def __init__(self, host: str, port: int, do_token: str):
        self.host = host
        self.port = port
        self.api_key = generate_api_key(do_token)
        self._client: Optional[AsyncHttpClient] = None
    
    @property
    def client(self) -> AsyncHttpClient:
        if self._client is None:
            self._client = AsyncHttpClient(base_url=f"http://{self.host}:{self.port}")
            self._client.set_auth_header("X-API-Key", self.api_key)
        return self._client
    
    async def close(self):
        if self._client:
            await self._client.close()
            self._client = None
    
    # =========================================================================
    # Health & Status
    # =========================================================================
    
    async def ping(self) -> Dict[str, Any]:
        response = await self.client.get("/ping")
        return response.json()
    
    async def health(self, container_name: str, container_port: int, http_path: str = None, timeout: int = 10) -> Dict[str, Any]:
        """
        Health check: TCP ping first, then optional HTTP for webservices.
        
        Args:
            container_name: Container to check
            container_port: Port to TCP ping
            http_path: Optional HTTP endpoint (webservice only, e.g. "/health")
            timeout: Check timeout in seconds
        
        Returns:
            {'status': 'healthy'} or {'status': 'unhealthy', 'reason': '...'}
        """
        response = await self.client.get(
            f"/containers/{container_name}/health",
            params={
                "container_port": container_port,
                "http_path": http_path,  # None = TCP only
                "timeout": timeout,
            }
        )
        return response.json()
    
    async def get_metrics(self) -> Dict[str, Any]:
        response = await self.client.get("/metrics")
        return response.json()
    
    # =========================================================================
    # Container Management
    # =========================================================================
    
    async def start_container(
        self,
        container_name: str,
        image_name: str,
        env_variables: List[str],
        container_port: int,
        host_port: int,
        volumes: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        payload = {
            "container_name": container_name,
            "image_name": image_name,
            "env_variables": env_variables,
            "container_port": container_port,
            "host_port": host_port,
            "volumes": volumes or ["/data:/app/data"],
            "restart_policy": "unless-stopped",
        }
        response = await self.client.post("/containers/start", json=payload)
        return response.json()
    
    async def drain_container(self, container_name: str, timeout: int = 30) -> Dict[str, Any]:
        """Gracefully drain connections before stopping."""
        response = await self.client.post(
            f"/containers/{container_name}/drain",
            params={"timeout": timeout}
        )
        return response.json()
    
    async def remove_container(
        self,
        container_name: str,
        force: bool = False,
        drain: bool = True,
        drain_timeout: int = 30,
    ) -> Dict[str, Any]:
        """Stop and remove container. If drain=True, gracefully drain first."""
        response = await self.client.post(
            f"/containers/{container_name}/remove",
            params={"force": force, "drain": drain, "drain_timeout": drain_timeout}
        )
        return response.json()
    
    async def restart_container(self, container_name: str) -> Dict[str, Any]:
        response = await self.client.post(f"/containers/{container_name}/restart")
        return response.json()
    
    async def list_containers(self) -> List[Dict[str, Any]]:
        response = await self.client.get("/containers")
        return response.json().get("containers", [])
    
    async def get_container_status(self, container_name: str) -> Dict[str, Any]:
        response = await self.client.get(f"/containers/{container_name}/status")
        return response.json()
    
    async def get_container_logs(self, container_name: str, tail: int = 100) -> str:
        response = await self.client.get(f"/containers/{container_name}/logs", params={"tail": tail})
        return response.text
    
    # =========================================================================
    # Image Management
    # =========================================================================
    
    async def upload(self, image_data: bytes, image_name: str) -> Dict[str, Any]:
        """Upload Docker image to droplet."""
        response = await self.client.post(
            "/images/upload",
            data=image_data,
            params={"name": image_name},
            headers={"Content-Type": "application/octet-stream"},
        )
        return response.json()
    
    async def list_images(self, prefix: Optional[str] = None) -> List[Dict[str, Any]]:
        params = {"prefix": prefix} if prefix else {}
        response = await self.client.get("/images/list", params=params)
        return response.json().get("images", [])
    
    async def cleanup_images(self, image_prefix: str, keep_latest: int = 3) -> Dict[str, Any]:
        """Remove old image versions, keeping the latest N."""
        response = await self.client.post(
            "/images/cleanup",
            json={"image_prefix": image_prefix, "keep_latest": keep_latest}
        )
        return response.json()
    
    # =========================================================================
    # Nginx Management
    # =========================================================================
    
    async def configure_nginx(self, private_ips: List[str], host_port: int, domain: str) -> Dict[str, Any]:
        response = await self.client.post("/nginx/configure", json={
            "private_ips": private_ips,
            "host_port": host_port,
            "domain": domain,
        })
        return response.json()
    
    async def nginx_test(self) -> Dict[str, Any]:
        response = await self.client.get("/nginx/test")
        return response.json()
    
    async def nginx_reload(self) -> Dict[str, Any]:
        response = await self.client.post("/nginx/reload")
        return response.json()
    
    # =========================================================================
    # File Operations
    # =========================================================================
    
    async def write_file(self, path: str, content: str, mode: int = 644) -> Dict[str, Any]:
        response = await self.client.post("/files/write", json={"path": path, "content": content, "mode": mode})
        return response.json()
    
    async def read_file(self, path: str) -> str:
        response = await self.client.get("/files/read", params={"path": path})
        return response.json().get("content", "")
