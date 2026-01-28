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
    "init_schema",
]


async def init_schema(db) -> None:
    """
    Create tables and indexes.
    The entity framework will auto-add new columns as needed.
    """
    # Projects
    await db.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            workspace_id TEXT,
            name TEXT,
            created_at TEXT,
            updated_at TEXT,
            created_by TEXT,
            updated_by TEXT,
            deleted_at TEXT
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_projects_workspace ON projects(workspace_id)")
    await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_name ON projects(workspace_id, name) WHERE deleted_at IS NULL")
    
    # Services
    await db.execute("""
        CREATE TABLE IF NOT EXISTS services (
            id TEXT PRIMARY KEY,
            project_id TEXT,
            name TEXT,
            description TEXT,
            service_type TEXT,
            created_at TEXT,
            updated_at TEXT,
            created_by TEXT,
            updated_by TEXT,
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
            image_name TEXT,
            container_name TEXT,
            env_variables TEXT,
            droplet_ids TEXT,
            is_rollback INTEGER DEFAULT 0,
            status TEXT,
            error TEXT,
            log TEXT,
            triggered_by TEXT,
            triggered_at TEXT,
            created_at TEXT,
            updated_at TEXT,
            created_by TEXT,
            updated_by TEXT
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_deployments_service ON deployments(service_id, env)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_deployments_status ON deployments(status)")
    
    # Droplets
    await db.execute("""
        CREATE TABLE IF NOT EXISTS droplets (
            id TEXT PRIMARY KEY,
            workspace_id TEXT,
            do_droplet_id INTEGER,
            name TEXT,
            ip TEXT,
            private_ip TEXT,
            region TEXT,
            size TEXT,
            vpc_uuid TEXT,
            snapshot_id TEXT,
            status TEXT DEFAULT 'active',
            health_status TEXT DEFAULT 'healthy',
            failure_count INTEGER DEFAULT 0,
            last_checked TEXT,
            last_failure_at TEXT,
            last_failure_reason TEXT,
            problematic_reason TEXT,
            flagged_at TEXT,
            last_reboot_at TEXT,
            created_at TEXT,
            updated_at TEXT,
            created_by TEXT,
            updated_by TEXT,
            deleted_at TEXT
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_droplets_workspace ON droplets(workspace_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_droplets_do_id ON droplets(do_droplet_id)")
    
    # Containers
    await db.execute("""
        CREATE TABLE IF NOT EXISTS containers (
            id TEXT PRIMARY KEY,
            container_name TEXT,
            droplet_id TEXT,
            deployment_id TEXT,
            status TEXT DEFAULT 'pending',
            health_status TEXT DEFAULT 'unknown',
            failure_count INTEGER DEFAULT 0,
            last_failure_at TEXT,
            last_failure_reason TEXT,
            last_healthy_at TEXT,
            last_restart_at TEXT,
            last_checked TEXT,
            error TEXT,
            created_at TEXT,
            updated_at TEXT,
            created_by TEXT,
            updated_by TEXT
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_containers_droplet ON containers(droplet_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_containers_deployment ON containers(deployment_id)")
    await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_containers_name_droplet ON containers(container_name, droplet_id)")
    
    # Snapshots
    await db.execute("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id TEXT PRIMARY KEY,
            workspace_id TEXT,
            do_snapshot_id TEXT,
            name TEXT,
            region TEXT,
            size_gigabytes REAL,
            agent_version TEXT,
            is_base INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT,
            created_by TEXT,
            updated_by TEXT
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_workspace ON snapshots(workspace_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_do_id ON snapshots(do_snapshot_id)")
