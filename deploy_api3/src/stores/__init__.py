# src/stores/__init__.py
"""
Database stores with typed entity returns.

All stores return typed dataclass entities from models.py,
providing IDE autocomplete and compile-time type checking.

Usage:
    from src.stores import projects, droplets
    
    project = await projects.get(db, project_id)
    project.name         # ✅ IDE autocomplete
    project.workspace_id # ✅ type checked
    
    droplets = await droplets.list_for_workspace(db, workspace_id)
    for d in droplets:
        print(d.ip)      # ✅ typed as Droplet
"""

from . import projects, services, deployments, droplets, containers, snapshots

__all__ = [
    "projects",
    "services", 
    "deployments",
    "droplets",
    "containers",
    "snapshots",
    "init_indexes",
]


async def init_indexes(db) -> None:
    """
    Create indexes for performance.
    Tables are auto-created by the schemaless entity framework.
    """
    # Projects
    await db.execute("CREATE INDEX IF NOT EXISTS idx_projects_workspace ON projects(workspace_id)")
    await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_name ON projects(workspace_id, name) WHERE deleted_at IS NULL")
    
    # Services
    await db.execute("CREATE INDEX IF NOT EXISTS idx_services_project ON services(project_id)")
    
    # Deployments
    await db.execute("CREATE INDEX IF NOT EXISTS idx_deployments_service ON deployments(service_id, env)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_deployments_status ON deployments(status)")
    
    # Droplets
    await db.execute("CREATE INDEX IF NOT EXISTS idx_droplets_workspace ON droplets(workspace_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_droplets_do_id ON droplets(do_droplet_id)")
    
    # Containers
    await db.execute("CREATE INDEX IF NOT EXISTS idx_containers_droplet ON containers(droplet_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_containers_deployment ON containers(deployment_id)")
    await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_containers_name_droplet ON containers(container_name, droplet_id)")
    
    # Snapshots
    await db.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_workspace ON snapshots(workspace_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_do_id ON snapshots(do_snapshot_id)")
