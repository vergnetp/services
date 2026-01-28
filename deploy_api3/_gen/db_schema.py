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
            created_at TEXT,
            updated_at TEXT,
            deleted_at TEXT
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_projects_workspace ON projects(workspace_id)")

    # Service
    await db.execute("""
        CREATE TABLE IF NOT EXISTS services (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            service_type TEXT,
            created_at TEXT,
            updated_at TEXT,
            deleted_at TEXT
        )
    """)

    # Deployment
    await db.execute("""
        CREATE TABLE IF NOT EXISTS deployments (
            id TEXT PRIMARY KEY,
            service_id TEXT NOT NULL,
            env TEXT NOT NULL,
            version INTEGER NOT NULL,
            image_name TEXT,
            container_name TEXT,
            env_variables TEXT,
            droplet_ids TEXT,
            is_rollback INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            error TEXT,
            log TEXT,
            triggered_by TEXT,
            triggered_at TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)

    # Droplet
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
            deleted_at TEXT
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_droplets_workspace ON droplets(workspace_id)")

    # Container
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
            updated_at TEXT
        )
    """)

    # Snapshot
    await db.execute("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id TEXT PRIMARY KEY,
            workspace_id TEXT,
            do_snapshot_id TEXT,
            name TEXT,
            region TEXT,
            size_gigabytes REAL DEFAULT 0,
            agent_version TEXT,
            is_base INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_workspace ON snapshots(workspace_id)")
