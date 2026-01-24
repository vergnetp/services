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
            is_stateful INTEGER DEFAULT 0,
            service_type TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_services_workspace ON services(workspace_id)")

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

    # ServiceDroplet
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
            host_port INTEGER,
            container_port INTEGER,
            internal_port INTEGER,
            private_ip TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_service_droplets_workspace ON service_droplets(workspace_id)")

    # Deployment
    await db.execute("""
        CREATE TABLE IF NOT EXISTS deployments (
            id TEXT PRIMARY KEY,
            workspace_id TEXT,
            service_id TEXT NOT NULL,
            env TEXT NOT NULL,
            source_type TEXT DEFAULT 'image',
            image_name TEXT,
            image_digest TEXT,
            git_url TEXT,
            git_branch TEXT,
            git_commit TEXT,
            droplet_ids TEXT,
            port INTEGER,
            env_vars TEXT,
            user_env_vars TEXT,
            status TEXT DEFAULT 'pending',
            triggered_by TEXT NOT NULL,
            comment TEXT,
            is_rollback INTEGER DEFAULT 0,
            rollback_from_id TEXT,
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

    # HealthCheck
    await db.execute("""
        CREATE TABLE IF NOT EXISTS health_checks (
            id TEXT PRIMARY KEY,
            workspace_id TEXT,
            droplet_id TEXT NOT NULL,
            container_name TEXT,
            status TEXT NOT NULL,
            response_time_ms INTEGER,
            error_message TEXT,
            action_taken TEXT,
            attempt_count INTEGER DEFAULT 0,
            checked_at TEXT NOT NULL,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_health_checks_workspace ON health_checks(workspace_id)")

    # Backup
    await db.execute("""
        CREATE TABLE IF NOT EXISTS backups (
            id TEXT PRIMARY KEY,
            workspace_id TEXT,
            service_id TEXT NOT NULL,
            service_type TEXT NOT NULL,
            filename TEXT NOT NULL,
            size_bytes INTEGER,
            storage_type TEXT DEFAULT 'local',
            storage_path TEXT NOT NULL,
            status TEXT DEFAULT 'completed',
            error_message TEXT,
            triggered_by TEXT DEFAULT 'scheduled',
            completed_at TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_backups_workspace ON backups(workspace_id)")
