"""
Deploy API - Deployment Management Service

API wrapper for the infra deployment system.
Provides REST endpoints for:
- Project configuration
- Service management
- Deployment triggering and status
- Credentials management

All infrastructure config is in manifest.yaml:
- Database, Auth, SaaS, Email, Redis, CORS, etc.
"""

from pathlib import Path

from fastapi import FastAPI
from shared_libs.backend.app_kernel import CacheBustedStaticFiles
from fastapi.responses import HTMLResponse, FileResponse

from shared_libs.backend.app_kernel import (
    create_service,
    ServiceConfig,
    get_logger,
)

from .config import get_app_settings, get_manifest_path
from ._gen.db_schema import init_schema
from .src.routes import (
    projects_router,
    deployments_router,
    infra_router,
    networking_router,
    agent_router,
    admin_router,
    deploy_router,
)
from .src.workers import TASKS


# Static files directory
STATIC_DIR = Path(__file__).parent / "static"


# =============================================================================
# Lifecycle (optional - for app-specific setup)
# =============================================================================

async def on_startup():
    """Initialize deploy API (after kernel setup)."""
    import os
    
    # Initialize streaming (for queue-based SSE)
    redis_url = os.environ.get("REDIS_URL")
    if redis_url:
        try:
            from shared_libs.backend.streaming import init_streaming
            from shared_libs.backend.job_queue import QueueRedisConfig
            
            redis_config = QueueRedisConfig(url=redis_url)
            init_streaming(redis_config)
            get_logger().info("Streaming initialized with Redis")
        except Exception as e:
            get_logger().warning(f"Failed to init streaming: {e} - SSE deploys won't work")
    else:
        get_logger().warning("REDIS_URL not set - SSE streaming disabled")
    
    get_logger().info("Deploy API started")


async def on_shutdown():
    """Cleanup on shutdown."""
    get_logger().info("Deploy API shutting down")


# =============================================================================
# Create App
# =============================================================================

def create_app() -> FastAPI:
    """Create the deploy-api application."""
    app_settings = get_app_settings()
    # Note: Data dir creation handled by kernel based on manifest database.path
    
    # Load all infrastructure config from manifest.yaml
    # Environment variables override manifest values via ${VAR:-default} syntax
    config = ServiceConfig.from_manifest(get_manifest_path())
    
    app = create_service(
        name="deploy-api",
        version="0.1.0",
        description=__doc__,
        
        # Routes (workspaces handled by kernel.saas)
        # deploy_router first so thin routes override fat ones in infra_router
        routers=[
            deploy_router,  # Thin deploy routes (queue-based streaming)
            projects_router,
            deployments_router,
            infra_router,
            networking_router,
            agent_router,
            admin_router,
        ],
        
        # Background tasks (deployment jobs)
        tasks=TASKS,
        
        # Configuration from manifest.yaml
        config=config,
        
        # Enable auto-wiring (billing routes, tasks, etc.)
        manifest_path=get_manifest_path(),
        
        # Database schema init (kernel calls this after DB init)
        schema_init=init_schema,
        
        # Lifecycle (optional)
        on_startup=on_startup,
        on_shutdown=on_shutdown,
    )
    
    # NOTE: Tracing middleware is now handled by app_kernel based on manifest.yaml
    # Enable tracing by adding to manifest.yaml:
    #   tracing:
    #     enabled: true
    #     db_path: data/traces.db
    
    # API info endpoint
    @app.get("/api")
    async def api_info():
        return {
            "service": "deploy-api",
            "version": "0.1.0",
            "docs": "/docs",
        }
    
    # Health check endpoint
    @app.get("/health")
    async def health_check():
        """Health check endpoint for monitoring."""
        return {"status": "healthy", "service": "deploy-api"}
    
    # Mount static files
    if STATIC_DIR.exists():
        app.mount("/static", CacheBustedStaticFiles(directory=str(STATIC_DIR)), name="static")
    
    # Cache-busting headers for HTML responses
    NO_CACHE_HEADERS = {
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Pragma': 'no-cache',
        'Expires': '0',
        'CDN-Cache-Control': 'no-store',
        'Cloudflare-CDN-Cache-Control': 'no-store',
    }
    
    # Serve UI at root
    @app.get("/", response_class=HTMLResponse)
    async def serve_ui():
        """Serve the deploy dashboard UI."""
        index_file = STATIC_DIR / "index.html"
        if index_file.exists():
            return FileResponse(index_file, headers=NO_CACHE_HEADERS)
        return HTMLResponse("<h1>Deploy API</h1><p>UI not found. API available at /docs</p>")
    
    # Serve infra test page
    @app.get("/infra-test", response_class=HTMLResponse)
    async def serve_infra_test():
        """Serve the infra test console."""
        test_file = STATIC_DIR / "infra-test.html"
        if test_file.exists():
            return FileResponse(test_file, headers=NO_CACHE_HEADERS)
        return HTMLResponse("<h1>Infra Test</h1><p>Test page not found.</p>")
    
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    settings = get_app_settings()
    uvicorn.run(
        "services.deploy_api.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
