"""
Deploy API routes.

Workspaces, members, and invites are handled by app_kernel.saas.
"""

from .projects import router as projects_router
from .deployments import router as deployments_router
from .infra_routes import router as infra_router
from .networking_routes import router as networking_router
from .agent_routes import router as agent_router
from .admin_routes import router as admin_router
from .deploy_routes import router as deploy_router

__all__ = [
    "projects_router",
    "deployments_router",
    "infra_router",
    "networking_router",
    "agent_router",
    "admin_router",
    "deploy_router",
]
