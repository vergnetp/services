"""
Node Agent Client.

Async client for communicating with node agents on droplets.
"""

import hmac
import hashlib
from typing import Optional, List, Dict, Any

from backend.http_client import AsyncHttpClient


def generate_api_key(do_token: str) -> str:
    """
    Generate API key for node agent authentication.
    
    Key = HMAC-SHA256(do_token, "node-agent:")
    """
    return hmac.new(
        do_token.encode(),
        b"node-agent:",
        hashlib.sha256
    ).hexdigest()


class NodeAgentClient:
    """
    Async client for node agent HTTP API.
    
    Usage:
        agent = NodeAgentClient(host="1.2.3.4", port=9999, do_token="xxx")
        await agent.pull_image("nginx:latest")
        await agent.run_container(name="web", image="nginx:latest")
        await agent.close()
    """
    
    def __init__(self, host: str, port: int, do_token: str):
        self.host = host
        self.port = port
        self.api_key = generate_api_key(do_token)
        self._client: Optional[AsyncHttpClient] = None
    
    @property
    def client(self) -> AsyncHttpClient:
        if self._client is None:
            self._client = AsyncHttpClient(
                base_url=f"http://{self.host}:{self.port}",
            )
            self._client.set_auth_header("X-API-Key", self.api_key)
        return self._client
    
    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.close()
            self._client = None
    
    # =========================================================================
    # Health & Status
    # =========================================================================
    
    async def ping(self) -> Dict[str, Any]:
        """Check if agent is alive."""
        response = await self.client.get("/ping")
        return response.json()
    
    async def get_metrics(self) -> Dict[str, Any]:
        """Get system metrics."""
        response = await self.client.get("/metrics")
        return response.json()
    
    # =========================================================================
    # Container Management
    # =========================================================================
    
    async def list_containers(self) -> List[Dict[str, Any]]:
        """List all containers."""
        response = await self.client.get("/containers")
        data = response.json()
        return data.get("containers", [])
    
    async def run_container(
        self,
        name: str,
        image: str,
        ports: Optional[List[str]] = None,
        environment: Optional[List[str]] = None,
        volumes: Optional[List[str]] = None,
        network: Optional[str] = None,
        restart_policy: str = "unless-stopped",
        health_check: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Start a new container."""
        payload = {
            "name": name,
            "image": image,
            "restart_policy": restart_policy,
        }
        if ports:
            payload["ports"] = ports
        if environment:
            payload["environment"] = environment
        if volumes:
            payload["volumes"] = volumes
        if network:
            payload["network"] = network
        if health_check:
            payload["health_check"] = health_check
        
        response = await self.client.post("/containers/run", json=payload)
        return response.json()
    
    async def start_container(self, name: str) -> Dict[str, Any]:
        """Start a stopped container."""
        response = await self.client.post(f"/containers/{name}/start")
        return response.json()
    
    async def stop_container(self, name: str, timeout: int = 10) -> Dict[str, Any]:
        """Stop a running container."""
        response = await self.client.post(
            f"/containers/{name}/stop",
            params={"timeout": timeout}
        )
        return response.json()
    
    async def restart_container(self, name: str) -> Dict[str, Any]:
        """Restart a container."""
        response = await self.client.post(f"/containers/{name}/restart")
        return response.json()
    
    async def remove_container(
        self, 
        name: str, 
        force: bool = False,
        volumes: bool = False,
    ) -> Dict[str, Any]:
        """Remove a container."""
        response = await self.client.post(
            f"/containers/{name}/remove",
            params={"force": force, "volumes": volumes}
        )
        return response.json()
    
    async def get_container_status(self, name: str) -> Dict[str, Any]:
        """Get container status."""
        response = await self.client.get(f"/containers/{name}/status")
        return response.json()
    
    async def get_container_health(self, name: str) -> Dict[str, Any]:
        """Get container health status."""
        response = await self.client.get(f"/containers/{name}/health")
        return response.json()
    
    async def get_all_health(self) -> Dict[str, Any]:
        """Get health status for all containers."""
        response = await self.client.get("/containers/all/health")
        return response.json()
    
    async def get_container_logs(
        self, 
        name: str, 
        tail: int = 100,
    ) -> str:
        """Get container logs."""
        response = await self.client.get(
            f"/containers/{name}/logs",
            params={"tail": tail}
        )
        return response.text
    
    async def exec_in_container(
        self,
        name: str,
        command: List[str],
        user: str = "root",
        workdir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute command in container."""
        payload = {"command": command, "user": user}
        if workdir:
            payload["workdir"] = workdir
        
        response = await self.client.post(f"/containers/{name}/exec", json=payload)
        return response.json()
    
    # =========================================================================
    # Image Management
    # =========================================================================
    
    async def list_images(self, prefix: Optional[str] = None) -> List[Dict[str, Any]]:
        """List Docker images."""
        params = {}
        if prefix:
            params["prefix"] = prefix
        
        response = await self.client.get("/images/list", params=params)
        data = response.json()
        return data.get("images", [])
    
    async def pull_image(
        self,
        image: str,
        registry: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Pull a Docker image."""
        payload = {"image": image}
        if registry:
            payload["registry"] = registry
        if username:
            payload["username"] = username
        if password:
            payload["password"] = password
        
        response = await self.client.post("/images/pull", json=payload)
        return response.json()
    
    async def tag_image(self, source: str, target: str) -> Dict[str, Any]:
        """Tag an image."""
        response = await self.client.post("/images/tag", json={
            "source_image": source,
            "target_image": target,
        })
        return response.json()
    
    async def cleanup_images(self) -> Dict[str, Any]:
        """Cleanup unused images."""
        response = await self.client.post("/images/cleanup")
        return response.json()
    
    # =========================================================================
    # Nginx Management
    # =========================================================================
    
    async def nginx_test(self) -> Dict[str, Any]:
        """Test nginx configuration."""
        response = await self.client.get("/nginx/test")
        return response.json()
    
    async def nginx_reload(self) -> Dict[str, Any]:
        """Reload nginx."""
        response = await self.client.post("/nginx/reload")
        return response.json()
    
    # =========================================================================
    # File Operations
    # =========================================================================
    
    async def write_file(
        self,
        path: str,
        content: str,
        mode: int = 644,
    ) -> Dict[str, Any]:
        """Write file on droplet."""
        response = await self.client.post("/files/write", json={
            "path": path,
            "content": content,
            "mode": mode,
        })
        return response.json()
    
    async def read_file(self, path: str) -> str:
        """Read file from droplet."""
        response = await self.client.get("/files/read", params={"path": path})
        data = response.json()
        return data.get("content", "")
    
    async def file_exists(self, path: str) -> bool:
        """Check if file exists."""
        response = await self.client.get("/files/exists", params={"path": path})
        data = response.json()
        return data.get("exists", False)
    
    # =========================================================================
    # Service Control
    # =========================================================================
    
    async def get_service_status(self, service: str) -> Dict[str, Any]:
        """Get service status (nginx, docker, node-agent)."""
        response = await self.client.get(f"/services/{service}/status")
        return response.json()
    
    async def restart_service(self, service: str) -> Dict[str, Any]:
        """Restart a service."""
        response = await self.client.post(f"/services/{service}/restart")
        return response.json()
