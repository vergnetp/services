#!/usr/bin/env python3
"""
Deploy API Worker - Background job processor.

Runs deployment and rollback jobs from the queue.
Also runs scheduled tasks like health checks.

Usage:
    python -m services.deploy_api.worker
    
Environment variables:
    REDIS_URL - Redis connection URL (required)
    DATABASE_PATH - SQLite database path
    HEALTH_CHECK_INTERVAL - Seconds between health checks (default: 60)
    HEALTH_CHECK_CLEANUP_INTERVAL - Seconds between cleanup runs (default: 86400)
"""

import asyncio
import sys
import os

from shared_libs.backend.app_kernel.jobs import run_worker, get_job_client
from shared_libs.backend.app_kernel import get_logger
from shared_libs.backend.app_kernel.db import init_db_session, close_db, get_db_connection

from .config import get_settings
from .src.workers import TASKS


# Scheduler intervals (in seconds)
HEALTH_CHECK_INTERVAL = int(os.environ.get("HEALTH_CHECK_INTERVAL", "60"))
HEALTH_CHECK_CLEANUP_INTERVAL = int(os.environ.get("HEALTH_CHECK_CLEANUP_INTERVAL", "86400"))


async def init_app():
    """Initialize database and streaming for worker processes."""
    settings = get_settings()
    # Note: Data dir creation handled by kernel based on manifest database.path
    
    # Use kernel's DB session (same as main app)
    init_db_session(
        database_name=settings.database_path,
        database_type=settings.database_type,
        host=settings.database_host,
        port=settings.database_port,
        user=settings.database_user,
        password=settings.database_password,
    )
    
    # Initialize streaming (for deploy task events)
    if settings.redis_url:
        try:
            from shared_libs.backend.streaming import init_streaming
            from shared_libs.backend.job_queue import QueueRedisConfig
            
            redis_config = QueueRedisConfig(url=settings.redis_url)
            init_streaming(redis_config)
            get_logger().info("Worker streaming initialized")
        except Exception as e:
            get_logger().warning(f"Failed to init streaming: {e}")
    
    get_logger().info("Worker database initialized")


async def shutdown_app():
    """Cleanup database connections."""
    await close_db()
    get_logger().info("Worker database closed")


async def health_check_scheduler(stop_event: asyncio.Event):
    """
    Scheduler that periodically enqueues health check tasks for all workspaces.
    
    Runs alongside the worker and enqueues check_health tasks at regular intervals.
    """
    logger = get_logger()
    settings = get_settings()
    
    logger.info(
        f"Health check scheduler started",
        extra={
            "check_interval": HEALTH_CHECK_INTERVAL,
            "cleanup_interval": HEALTH_CHECK_CLEANUP_INTERVAL,
        }
    )
    
    last_cleanup = 0
    
    while not stop_event.is_set():
        try:
            # Wait for next check interval
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=HEALTH_CHECK_INTERVAL)
                # If we get here, stop_event was set
                break
            except asyncio.TimeoutError:
                # Normal timeout, continue with health checks
                pass
            
            # Get all workspaces with active droplets
            try:
                async with get_db_connection() as conn:
                    # Find distinct workspace_ids from droplets table
                    droplets = await conn.find_entities(
                        "droplets",
                        limit=1000,
                    )
                    
                    workspace_ids = set()
                    for droplet in droplets:
                        ws_id = droplet.get("workspace_id")
                        if ws_id:
                            workspace_ids.add(ws_id)
                
                if not workspace_ids:
                    logger.debug("No workspaces with droplets found, skipping health check")
                    continue
                
                # Enqueue health check for each workspace
                job_client = get_job_client()
                
                for workspace_id in workspace_ids:
                    try:
                        await job_client.enqueue(
                            "check_health",
                            {"workspace_id": workspace_id},
                            priority="low",  # Health checks are background, don't interfere with deploys
                        )
                        logger.debug(f"Enqueued health check for workspace {workspace_id}")
                    except Exception as e:
                        logger.error(f"Failed to enqueue health check for {workspace_id}: {e}")
                
                logger.info(
                    f"Scheduled health checks for {len(workspace_ids)} workspaces",
                    extra={"workspace_ids": list(workspace_ids)}
                )
                
            except Exception as e:
                logger.error(f"Error getting workspaces for health check: {e}")
            
            # Check if it's time for cleanup
            import time
            current_time = time.time()
            if current_time - last_cleanup >= HEALTH_CHECK_CLEANUP_INTERVAL:
                try:
                    job_client = get_job_client()
                    await job_client.enqueue(
                        "cleanup_health_checks",
                        {"days": 7},
                        priority="low",
                    )
                    logger.info("Scheduled health check cleanup")
                    last_cleanup = current_time
                except Exception as e:
                    logger.error(f"Failed to enqueue cleanup: {e}")
                
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Health check scheduler error: {e}")
            # Wait a bit before retrying
            await asyncio.sleep(10)
    
    logger.info("Health check scheduler stopped")


async def main():
    """Run the worker process with health check scheduler."""
    settings = get_settings()
    logger = get_logger()
    
    if not settings.redis_url:
        logger.error("REDIS_URL not configured - workers require Redis")
        sys.exit(1)
    
    logger.info(f"Starting deploy-api worker with {len(TASKS)} tasks")
    logger.info(f"Tasks: {list(TASKS.keys())}")
    logger.info(f"Redis key prefix: {settings.redis_key_prefix}")
    
    # Get manifest path for auto-adding kernel integration tasks
    from pathlib import Path
    manifest_path = Path(__file__).parent / "manifest.yaml"
    
    # Create stop event for scheduler
    stop_event = asyncio.Event()
    
    # Start health check scheduler as a background task
    scheduler_task = asyncio.create_task(health_check_scheduler(stop_event))
    
    try:
        # Run worker with init/shutdown hooks
        await run_worker(
            tasks=TASKS,
            redis_url=settings.redis_url,
            key_prefix=settings.redis_key_prefix,
            manifest_path=str(manifest_path),
            init_app=init_app,
            shutdown_app=shutdown_app,
        )
    finally:
        # Stop scheduler
        stop_event.set()
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    asyncio.run(main())
