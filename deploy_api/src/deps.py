"""
FastAPI dependencies for deploy_api.

Database connection is managed by app_kernel:
- FastAPI routes: use db_connection dependency (one conn per request)
- Workers/scripts: use get_db_connection() context manager

Workspaces, members, and invites are handled by app_kernel.saas.
This module provides deploy_api specific store dependencies.
"""

from fastapi import Depends

# Use kernel's db_connection dependency (handles pooling correctly)
from shared_libs.backend.app_kernel.db import db_connection

from .stores import (
    ProjectStore,
    ServiceStore,
    DropletStore,
    ServiceDropletStore,
    CredentialsStore,
    DeploymentStore,
    DeployConfigStore,
)


# =============================================================================
# Store Dependencies (FastAPI - share kernel's connection)
# =============================================================================

async def get_project_store(db = Depends(db_connection)):
    """Get project store - shares request connection."""
    return ProjectStore(db)


async def get_service_store(db = Depends(db_connection)):
    """Get service store - shares request connection."""
    return ServiceStore(db)


async def get_droplet_store(db = Depends(db_connection)):
    """Get droplet store - shares request connection."""
    return DropletStore(db)


async def get_service_droplet_store(db = Depends(db_connection)):
    """Get service-droplet junction store - shares request connection."""
    return ServiceDropletStore(db)


async def get_credentials_store(db = Depends(db_connection)):
    """Get credentials store - shares request connection."""
    return CredentialsStore(db)


async def get_deployment_store(db = Depends(db_connection)):
    """Get deployment store - shares request connection."""
    return DeploymentStore(db)


async def get_deploy_config_store(db = Depends(db_connection)):
    """Get deploy config store - shares request connection."""
    return DeployConfigStore(db)
