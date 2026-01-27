"""
Deploy API - Main entry point.

A deployment platform API for DigitalOcean infrastructure.
"""

from backend.app_kernel import create_service, ServiceConfig
from ._gen import init_schema, gen_router
from .src.routes import router as custom_router
from .config import settings, DEPLOY_API_VERSION


def _build_config() -> ServiceConfig:
    """Build kernel configuration from settings."""
    settings.ensure_data_dir()
    
    return ServiceConfig(
        # Auth
        jwt_secret=settings.jwt_secret,
        
        # Database
        database_name=settings.database_path,
        database_type=settings.database_type,
        
        # Redis (optional)
        redis_url=settings.redis_url if settings.redis_url else None,
    )


# Create the FastAPI app
app = create_service(
    name="deploy_api",
    config=_build_config(),
    schema_init=init_schema,
    routers=[gen_router, custom_router],  # Generated CRUD + custom routes
)


@app.get("/")
async def root():
    """Root endpoint with version info."""
    return {
        "service": "deploy_api",
        "version": DEPLOY_API_VERSION,
        "status": "ok",
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}
