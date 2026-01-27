"""
Entity stores for deploy_api.

Usage:
    from src.stores import ProjectStore, ServiceStore, ...
    
    store = ProjectStore()
    project = await store.get(db, project_id)
"""

from .base import BaseStore, WorkspaceScopedStore
from .project import ProjectStore
from .service import ServiceStore
from .droplet import DropletStore
from .deployment import DeploymentStore
from .container import ContainerStore
from .snapshot import SnapshotStore

__all__ = [
    # Base classes
    "BaseStore",
    "WorkspaceScopedStore",
    # Entity stores
    "ProjectStore",
    "ServiceStore",
    "DropletStore",
    "DeploymentStore",
    "ContainerStore",
    "SnapshotStore",
]

# Singleton instances for convenience
# Usage: from src.stores import projects, services, ...
projects = ProjectStore()
services = ServiceStore()
droplets = DropletStore()
deployments = DeploymentStore()
containers = ContainerStore()
snapshots = SnapshotStore()
