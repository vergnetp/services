"""
Custom API routes for deploy_api.

These are thin wrappers - business logic lives in src/*.py modules.
"""

from fastapi import APIRouter

from .deploy import router as deploy_router
from .infra import router as infra_router
from .health import router as health_router

router = APIRouter()

# Mount all custom routers
router.include_router(deploy_router)
router.include_router(infra_router)
router.include_router(health_router)

__all__ = ["router"]
