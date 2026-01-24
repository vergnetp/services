"""
Generated routes - AUTO-GENERATED from manifest.yaml
DO NOT EDIT - changes will be overwritten on regenerate
"""

from fastapi import APIRouter

from .project import router as project_router
from .service import router as service_router
from .droplet import router as droplet_router
from .service_droplet import router as service_droplet_router
from .deployment import router as deployment_router
from .deploy_config import router as deploy_config_router
from .credential import router as credential_router
from .health_check import router as health_check_router

# Combined router for all generated CRUD endpoints
router = APIRouter()

router.include_router(project_router)
router.include_router(service_router)
router.include_router(droplet_router)
router.include_router(service_droplet_router)
router.include_router(deployment_router)
router.include_router(deploy_config_router)
router.include_router(credential_router)
router.include_router(health_check_router)