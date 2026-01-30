import os
from pathlib import Path

from fastapi import FastAPI
from shared_libs.backend.app_kernel import create_service, ServiceConfig, load_env_hierarchy
from shared_libs.backend.app_kernel.auth import hash_password

from .src.routes import router
from .src.stores import init_schema


SERVICE_DIR = Path(__file__).parent

async def seed_admin(db):
    """Create admin user if none exists."""
    existing = await db.find_entities("auth_users", where_clause="[role] = ?", params=("admin",), limit=1)
    if not existing:
        await db.save_entity("auth_users", {
            "id": "admin",
            "username": "admin",
            "email": "vergnetp@yahoo.fr",
            "password_hash": hash_password(os.environ.get('ADMIN_PASSWORD','admin')),
            "role": "admin",
            "is_active": True,
        })

async def full_init(db):
    await init_schema(db)
    await seed_admin(db)

def create_app() -> FastAPI:
    """Application factory."""
    # Load .env FIRST
    load_env_hierarchy(__file__)
    
    # Ensure data dir
    data_dir = SERVICE_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    
    db_path = data_dir / "deploy_api.db"
    
    config = ServiceConfig(
        jwt_secret=os.environ.get("JWT_SECRET"),
        database_url=f"sqlite:///{db_path}",
        redis_url=os.environ.get("REDIS_URL", ""),
        cors_origins=["*"],
        debug=os.environ.get("DEBUG", "false").lower() == "true",
    )
    
    return create_service(
        name="deploy_api3",
        routers=[router],
        schema_init=full_init,
        config=config,
    )


app = create_app()