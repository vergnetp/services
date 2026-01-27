import os
from pathlib import Path

from fastapi import FastAPI
from shared_libs.backend.app_kernel import create_service, ServiceConfig, load_env_hierarchy

from .src.routes import router
from .src.stores import init_schema


SERVICE_DIR = Path(__file__).parent


def create_app() -> FastAPI:
    """Application factory."""
    # Load .env FIRST
    load_env_hierarchy(__file__)
    
    # Ensure data dir
    data_dir = SERVICE_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    
    config = ServiceConfig(
        jwt_secret=os.environ.get("JWT_SECRET", "dev-secret-change-me"),
        database_name=str(data_dir / "deploy_api.db"),
        database_type="sqlite",
        redis_url=os.environ.get("REDIS_URL", ""),
        cors_origins=["*"],
        debug=os.environ.get("DEBUG", "false").lower() == "true",
    )
    
    return create_service(
        name="deploy_api3",
        routers=[router],
        schema_init=init_schema,
        config=config,
    )


app = create_app()