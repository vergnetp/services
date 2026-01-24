"""
FastAPI dependencies for deploy_api.

Database connection is managed by app_kernel:
- FastAPI routes: use db_connection dependency (one conn per request)
- Workers/scripts: use get_db_connection() context manager

Workspaces, members, and invites are handled by app_kernel.saas.
This module provides deploy_api specific store dependencies.
"""

import os
from fastapi import Depends
from typing import Optional

# Use kernel's db_connection dependency (handles pooling correctly)
from shared_libs.backend.app_kernel.db import db_connection

# Also export get_db_connection as get_db for async context manager usage in routes
# This is used when routes need manual DB access outside of FastAPI dependency injection
from shared_libs.backend.app_kernel.db import get_db_connection as get_db

from .stores import (
    ProjectStore,
    ServiceStore,
    DropletStore,
    ServiceDropletStore,
    CredentialsStore,
    DeploymentStore,
    DeployConfigStore,
    BackupStore,
)


# =============================================================================
# Queue Manager Singleton
# =============================================================================

_queue_manager = None


def get_queue_manager():
    """
    Get the global QueueManager instance.
    
    Requires REDIS_URL environment variable.
    Uses same key_prefix as worker to ensure jobs are routed correctly.
    """
    global _queue_manager
    
    if _queue_manager is None:
        from shared_libs.backend.job_queue import QueueManager, QueueConfig, QueueRedisConfig
        from ..config import get_settings
        
        settings = get_settings()
        redis_url = settings.redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        key_prefix = settings.redis_key_prefix  # "deploy:" - must match worker
        
        redis_config = QueueRedisConfig(url=redis_url)
        config = QueueConfig(redis=redis_config, key_prefix=key_prefix)
        
        _queue_manager = QueueManager(config)
    
    return _queue_manager


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


async def get_backup_store(db = Depends(db_connection)):
    """Get backup store - shares request connection."""
    return BackupStore(db)
