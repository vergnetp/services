"""
Database schema - AUTO-GENERATED from manifest.yaml
DO NOT EDIT - changes will be overwritten on regenerate
"""

from typing import Any


async def init_schema(db: Any) -> None:
    """Initialize database schema. Called by kernel after DB connection."""

    # Project
    await db.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            workspace_id TEXT,
            name TEXT NOT NULL,
            description TEXT,
            docker_hub_user TEXT,
            created_by TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_projects_workspace ON projects(workspace_id)")
    await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_name ON projects(workspace_id, name)")

    # Service
    await db.execute("""
        CREATE TABLE IF NOT EXISTS services (
            id TEXT PRIMARY KEY,
            workspace_id TEXT,
            project_id TEXT NOT NULL,
            name TEXT NOT NULL,
            port INTEGER DEFAULT 8000,
            health_endpoint TEXT DEFAULT '/health',
            description TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_services_workspace ON services(workspace_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_services_project ON services(project_id)")
    await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_services_name ON services(project_id, name)")

    # Droplet
    await db.execute("""
        CREATE TABLE IF NOT EXISTS droplets (
            id TEXT PRIMARY KEY,
            workspace_id TEXT,
            do_droplet_id TEXT NOT NULL,
            name TEXT,
            ip TEXT,
            region TEXT,
            size TEXT,
            status TEXT DEFAULT 'active',
            snapshot_id TEXT,
            created_by TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_droplets_workspace ON droplets(workspace_id)")
    await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_droplets_do_id ON droplets(workspace_id, do_droplet_id)")

    # ServiceDroplet (junction)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS service_droplets (
            id TEXT PRIMARY KEY,
            workspace_id TEXT,
            service_id TEXT NOT NULL,
            droplet_id TEXT NOT NULL,
            env TEXT NOT NULL,
            container_name TEXT,
            is_healthy INTEGER DEFAULT 1,
            last_healthy_at TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_service_droplets_workspace ON service_droplets(workspace_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_service_droplets_service ON service_droplets(service_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_service_droplets_droplet ON service_droplets(droplet_id)")
    await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_service_droplets_unique ON service_droplets(service_id, droplet_id, env)")

    # Deployment
    await db.execute("""
        CREATE TABLE IF NOT EXISTS deployments (
            id TEXT PRIMARY KEY,
            workspace_id TEXT,
            service_id TEXT NOT NULL,
            env TEXT NOT NULL,
            version INTEGER,
            source_type TEXT DEFAULT 'image',
            image_name TEXT,
            image_digest TEXT,
            git_url TEXT,
            git_branch TEXT,
            git_commit TEXT,
            droplet_ids TEXT,
            port INTEGER,
            env_vars TEXT,
            status TEXT DEFAULT 'pending',
            triggered_by TEXT NOT NULL,
            comment TEXT,
            is_rollback INTEGER DEFAULT 0,
            rollback_from_id TEXT,
            source_version INTEGER,
            config_snapshot TEXT,
            started_at TEXT,
            completed_at TEXT,
            duration_seconds REAL,
            result_json TEXT,
            error TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_deployments_workspace ON deployments(workspace_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_deployments_service ON deployments(service_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_deployments_status ON deployments(status)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_deployments_version ON deployments(service_id, env, version)")

    # DeployConfig
    await db.execute("""
        CREATE TABLE IF NOT EXISTS deploy_configs (
            id TEXT PRIMARY KEY,
            workspace_id TEXT,
            service_id TEXT NOT NULL,
            env TEXT NOT NULL,
            source_type TEXT DEFAULT 'git',
            git_url TEXT,
            git_branch TEXT DEFAULT 'main',
            git_folders TEXT,
            main_folder_path TEXT,
            dependency_folder_paths TEXT,
            exclude_patterns TEXT,
            port INTEGER DEFAULT 8000,
            env_vars TEXT,
            dockerfile_path TEXT DEFAULT 'Dockerfile',
            snapshot_id TEXT,
            region TEXT,
            size TEXT DEFAULT 's-1vcpu-1gb',
            created_at TEXT,
            updated_at TEXT
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_deploy_configs_workspace ON deploy_configs(workspace_id)")
    await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_deploy_configs_unique ON deploy_configs(service_id, env)")

    # Credential
    await db.execute("""
        CREATE TABLE IF NOT EXISTS credentials (
            id TEXT PRIMARY KEY,
            workspace_id TEXT,
            project_id TEXT NOT NULL,
            env TEXT NOT NULL,
            encrypted_blob TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_credentials_workspace ON credentials(workspace_id)")
    await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_credentials_unique ON credentials(project_id, env)")
