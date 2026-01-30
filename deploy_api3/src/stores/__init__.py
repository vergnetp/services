# src/stores/__init__.py
"""
Database stores with typed entity returns.

Schema: Tables with indexed + queried columns.
Other columns added dynamically by save_entity (schemaless).
"""

from . import projects, services, deployments, droplets, containers, snapshots

__all__ = [
    "projects",
    "services", 
    "deployments",
    "droplets",
    "containers",
    "snapshots",
    "init_schema",
]


async def init_schema(db) -> None:
    """
    Create tables with indexed/queried columns.
    Non-queried columns added by save_entity at runtime.
    """
    # Projects
    await db.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            workspace_id TEXT,
            name TEXT,
            deleted_at TEXT
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_projects_workspace ON projects(workspace_id)")
    
    # Services
    await db.execute("""
        CREATE TABLE IF NOT EXISTS services (
            id TEXT PRIMARY KEY,
            project_id TEXT,
            name TEXT,
            deleted_at TEXT
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_services_project ON services(project_id)")
    
    # Deployments
    await db.execute("""
        CREATE TABLE IF NOT EXISTS deployments (
            id TEXT PRIMARY KEY,
            service_id TEXT,
            env TEXT,
            version INTEGER,
            status TEXT
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_deployments_service ON deployments(service_id, env)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_deployments_status ON deployments(status)")
    
    # Droplets
    await db.execute("""
        CREATE TABLE IF NOT EXISTS droplets (
            id TEXT PRIMARY KEY,
            workspace_id TEXT,
            do_droplet_id TEXT,
            deleted_at TEXT
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_droplets_workspace ON droplets(workspace_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_droplets_do_id ON droplets(do_droplet_id)")
    
    # Containers
    await db.execute("""
        CREATE TABLE IF NOT EXISTS containers (
            id TEXT PRIMARY KEY,
            droplet_id TEXT,
            deployment_id TEXT,
            container_name TEXT,
            status TEXT
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_containers_droplet ON containers(droplet_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_containers_deployment ON containers(deployment_id)")
    
    # Snapshots
    await db.execute("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id TEXT PRIMARY KEY,
            workspace_id TEXT,
            do_snapshot_id TEXT,
            is_base INTEGER DEFAULT 0
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_workspace ON snapshots(workspace_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_do_id ON snapshots(do_snapshot_id)")
