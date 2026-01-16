"""
Deploy API routes.

Workspaces, members, and invites are handled by app_kernel.saas.
"""

from .projects import router as projects_router
from .deployments import router as deployments_router
from .infra_routes import router as infra_router
from .admin_routes import router as admin_router

__all__ = [
    "projects_router",
    "deployments_router",
    "infra_router",
    "admin_router",
]
