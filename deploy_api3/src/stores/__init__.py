# src/stores/__init__.py
"""Database stores."""

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
    """Initialize database schema."""
    
    await db.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            workspace_id TEXT,
            name TEXT NOT NULL,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_projects_workspace ON projects(workspace_id)")
    await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_name ON projects(workspace_id, name)")
    
    await db.execute("""
        CREATE TABLE IF NOT EXISTS services (
            id TEXT PRIMARY KEY,
            project_id TEXT,
            name TEXT NOT NULL,
            description TEXT,
            service_type TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_services_project ON services(project_id)")
    
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
            status TEXT,
            error TEXT,
            log TEXT,
            triggered_by TEXT,
            triggered_at TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_deployments_service ON deployments(service_id, env)")
    
    await db.execute("""
        CREATE TABLE IF NOT EXISTS droplets (
            id TEXT PRIMARY KEY,
            workspace_id TEXT,
            do_droplet_id TEXT,
            name TEXT,
            ip TEXT,
            private_ip TEXT,
            region TEXT,
            size TEXT,
            snapshot_id TEXT,
            status TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_droplets_workspace ON droplets(workspace_id)")
    
    await db.execute("""
        CREATE TABLE IF NOT EXISTS containers (
            id TEXT PRIMARY KEY,
            container_name TEXT,
            droplet_id TEXT,
            deployment_id TEXT,
            status TEXT,
            health_status TEXT,
            error TEXT,
            last_checked TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_containers_droplet ON containers(droplet_id)")
    
    await db.execute("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id TEXT PRIMARY KEY,
            workspace_id TEXT,
            do_snapshot_id TEXT,
            name TEXT,
            region TEXT,
            size_gigabytes REAL,
            agent_version TEXT,
            service_id TEXT,
            image_name TEXT,
            is_base INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_workspace ON snapshots(workspace_id)")