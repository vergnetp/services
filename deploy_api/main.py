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
from fastapi.staticfiles import StaticFiles
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
)
from .src.workers import TASKS


# Static files directory
STATIC_DIR = Path(__file__).parent / "static"


# =============================================================================
# Lifecycle (optional - for app-specific setup)
# =============================================================================

async def on_startup():
    """Initialize deploy API (after kernel setup)."""
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
    app_settings.ensure_data_dir()
    
    # Load all infrastructure config from manifest.yaml
    # Environment variables override manifest values via ${VAR:-default} syntax
    config = ServiceConfig.from_manifest(get_manifest_path())
    
    app = create_service(
        name="deploy-api",
        version="0.1.0",
        description=__doc__,
        
        # Routes (workspaces handled by kernel.saas)
        routers=[
            projects_router,
            deployments_router,
            infra_router,
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
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    
    # Serve UI at root
    @app.get("/", response_class=HTMLResponse)
    async def serve_ui():
        """Serve the deploy dashboard UI."""
        index_file = STATIC_DIR / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return HTMLResponse("<h1>Deploy API</h1><p>UI not found. API available at /docs</p>")
    
    # Serve infra test page
    @app.get("/infra-test", response_class=HTMLResponse)
    async def serve_infra_test():
        """Serve the infra test console."""
        test_file = STATIC_DIR / "infra-test.html"
        if test_file.exists():
            return FileResponse(test_file)
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
