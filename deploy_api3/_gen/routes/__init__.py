"""
Generated routes - AUTO-GENERATED from manifest.yaml
DO NOT EDIT - changes will be overwritten on regenerate
"""

from fastapi import APIRouter

from .project import router as project_router
from .service import router as service_router
from .deployment import router as deployment_router
from .droplet import router as droplet_router
from .container import router as container_router
from .snapshot import router as snapshot_router

# Combined router for all generated CRUD endpoints
router = APIRouter()

router.include_router(project_router)
router.include_router(service_router)
router.include_router(deployment_router)
router.include_router(droplet_router)
router.include_router(container_router)
router.include_router(snapshot_router)