"""
Deployment worker tasks - runs actual deployments via infra code.

This is the bridge between deploy_api and your existing infra library.

Note: Job status (running/completed/failed) is automatically tracked in Redis
by the kernel worker. Tasks can optionally call update_progress() for step updates.
"""

import json
import traceback
from typing import Dict, Any, Optional
from datetime import datetime

try:
    from shared_libs.backend.app_kernel import get_logger
    from shared_libs.backend.app_kernel.jobs import get_job_client
    from shared_libs.backend.app_kernel.db import get_db_connection
except ImportError:
    import logging
    def get_logger():
        return logging.getLogger(__name__)
    def get_job_client():
        raise RuntimeError("Job client not available")
    def get_db_connection():
        raise RuntimeError("DB connection not available")


def _get_logger():
    """Lazy logger getter to avoid import-time issues."""
    return get_logger()


async def _update_progress(job_id: str, step: str, progress: int):
    """Update job progress in Redis via kernel."""
    try:
        job_client = get_job_client()
        await job_client.update_progress(job_id, step=step, progress=progress)
    except Exception:
        pass  # Progress updates are optional


async def _sync_run_to_db(
    job_id: str, 
    status: str, 
    error: Optional[str] = None,
    result: Optional[Dict] = None,
):
    """
    Sync job status to deployment_runs table for historical records.
    
    The primary status is in Redis (managed by kernel). This syncs to DB
    for persistence beyond Redis TTL and for domain-specific queries.
    """
    try:
        async with get_db_connection() as conn:
            runs = await conn.find_entities(
                "deployment_runs",
                where_clause="job_id = ?",
                params=(job_id,),
                limit=1,
            )
            
            if not runs:
                return
            
            run = runs[0]
            run["status"] = status
            
            if status == "running" and not run.get("started_at"):
                run["started_at"] = datetime.utcnow().isoformat()
            
            if status in ("completed", "failed"):
                run["completed_at"] = datetime.utcnow().isoformat()
                
            if error:
                run["error"] = error
            if result:
                run["result_json"] = json.dumps(result)
            
            await conn.save_entity("deployment_runs", run)
            
    except Exception as e:
        _get_logger().warning(f"Failed to sync run to DB: {e}")


async def run_deployment(payload: Dict[str, Any], ctx) -> Dict[str, Any]:
    """
    Execute a deployment using the infra Deployer.
    
    This runs your existing deployment code as a background job.
    
    Args:
        payload: Deployment parameters:
            - workspace_id: Tenant ID (maps to infra's "user")
            - project_name: Project name
            - env: Environment (prod, uat, dev)
            - services: Optional list of services to deploy
            - force: Force rebuild
            - triggered_by: User who triggered
        ctx: JobContext with job_id, task_name, etc.
    
    Returns:
        Deployment result
    """
    logger = _get_logger()
    job_id = ctx.job_id
    
    workspace_id = payload["workspace_id"]
    project_name = payload["project_name"]
    env = payload["env"]
    services = payload.get("services")
    force = payload.get("force", False)
    triggered_by = payload.get("triggered_by", "system")
    
    logger.info(
        f"Starting deployment",
        extra={
            "job_id": job_id,
            "workspace_id": workspace_id,
            "project_name": project_name,
            "env": env,
            "services": services,
            "triggered_by": triggered_by,
        }
    )
    
    # Sync running status to DB
    await _sync_run_to_db(job_id, "running")
    
    try:
        # Update job progress
        await _update_progress(job_id, step="initializing", progress=5)
        
        # Try to import infra modules - fall back to mock if not available
        try:
            from infra.deployer import Deployer
            use_mock = False
        except ImportError:
            logger.warning("infra module not available, using mock deployment")
            use_mock = True
        
        if use_mock:
            # Mock deployment for testing
            import asyncio
            await _update_progress(job_id, step="mock_building", progress=30)
            await asyncio.sleep(2)  # Simulate work
            await _update_progress(job_id, step="mock_deploying", progress=60)
            await asyncio.sleep(2)
            await _update_progress(job_id, step="mock_verifying", progress=90)
            await asyncio.sleep(1)
            
            result = {
                "mock": True,
                "services_deployed": services or ["all"],
                "env": env,
                "message": "Mock deployment completed successfully"
            }
        else:
            # Real deployment
            from shared_libs.backend.app_kernel.db import get_db_connection
            from ..stores import CredentialsStore
            
            async with get_db_connection() as conn:
                creds_store = CredentialsStore(conn)
                credentials = await creds_store.get(workspace_id, project_name, env)
            
            if not credentials:
                raise ValueError(f"No credentials found for {workspace_id}/{project_name}/{env}")
            
            await _update_progress(job_id, step="loading_config", progress=10)
            
            deployer = Deployer(user=workspace_id, project_name=project_name)
            
            await _update_progress(job_id, step="building_images", progress=20)
            
            if services:
                result = deployer.deploy_services(
                    env=env,
                    services=services,
                    force_rebuild=force,
                    credentials=credentials,
                )
            else:
                result = deployer.deploy(
                    env=env,
                    force_rebuild=force,
                    credentials=credentials,
                )
        
        await _update_progress(job_id, step="completed", progress=100)
        
        logger.info(
            f"Deployment completed",
            extra={
                "job_id": job_id,
                "workspace_id": workspace_id,
                "project_name": project_name,
                "env": env,
                "result": result,
            }
        )
        
        # Mark as completed
        await _sync_run_to_db(job_id, "completed", result=result)
        
        return {
            "status": "success",
            "workspace_id": workspace_id,
            "project_name": project_name,
            "env": env,
            "result": result,
        }
        
    except Exception as e:
        error_msg = str(e)
        logger.error(
            f"Deployment failed",
            extra={
                "job_id": job_id,
                "workspace_id": workspace_id,
                "project_name": project_name,
                "env": env,
                "error": error_msg,
                "traceback": traceback.format_exc(),
            }
        )
        
        # Mark as failed with error
        await _sync_run_to_db(job_id, "failed", error=error_msg)
        
        raise


async def run_rollback(payload: Dict[str, Any], ctx) -> Dict[str, Any]:
    """
    Execute a rollback using the infra RollbackManager.
    
    Args:
        payload: Rollback parameters
        ctx: JobContext with job_id, task_name, etc.
    
    Returns:
        Rollback result
    """
    logger = _get_logger()
    job_id = ctx.job_id
    
    workspace_id = payload["workspace_id"]
    project_name = payload["project_name"]
    env = payload["env"]
    triggered_by = payload.get("triggered_by", "system")
    
    logger.info(
        f"Starting rollback",
        extra={
            "job_id": job_id,
            "workspace_id": workspace_id,
            "project_name": project_name,
            "env": env,
            "triggered_by": triggered_by,
        }
    )
    
    # Mark as running
    await _sync_run_to_db(job_id, "running")
    
    try:
        await _update_progress(job_id, step="initializing", progress=10)
        
        # Try to import infra modules - fall back to mock if not available
        try:
            from infra.rollback_manager import RollbackManager
            use_mock = False
        except ImportError:
            logger.warning("infra module not available, using mock rollback")
            use_mock = True
        
        if use_mock:
            # Mock rollback for testing
            import asyncio
            await _update_progress(job_id, step="mock_rolling_back", progress=40)
            await asyncio.sleep(2)
            await _update_progress(job_id, step="mock_verifying", progress=80)
            await asyncio.sleep(1)
            
            result = {
                "mock": True,
                "env": env,
                "message": "Mock rollback completed successfully"
            }
        else:
            # Real rollback
            from shared_libs.backend.app_kernel.db import get_db_connection
            from ..stores import CredentialsStore
            
            async with get_db_connection() as conn:
                creds_store = CredentialsStore(conn)
                credentials = await creds_store.get(workspace_id, project_name, env)
            
            if not credentials:
                raise ValueError(f"No credentials found for {workspace_id}/{project_name}/{env}")
            
            await _update_progress(job_id, step="rolling_back", progress=30)
            
            rollback_mgr = RollbackManager(
                user=workspace_id,
                project_name=project_name,
            )
            
            result = rollback_mgr.rollback(
                env=env,
                credentials=credentials,
            )
        
        await _update_progress(job_id, step="completed", progress=100)
        
        logger.info(
            f"Rollback completed",
            extra={
                "job_id": job_id,
                "workspace_id": workspace_id,
                "project_name": project_name,
                "env": env,
            }
        )
        
        # Mark as completed
        await _sync_run_to_db(job_id, "completed", result=result)
        
        return {
            "status": "success",
            "workspace_id": workspace_id,
            "project_name": project_name,
            "env": env,
            "result": result,
        }
        
    except Exception as e:
        error_msg = str(e)
        logger.error(
            f"Rollback failed",
            extra={
                "job_id": job_id,
                "error": error_msg,
                "traceback": traceback.format_exc(),
            }
        )
        
        # Mark as failed with error
        await _sync_run_to_db(job_id, "failed", error=error_msg)
        
        raise


# Task registry for app_kernel jobs
TASKS = {
    "deploy": run_deployment,
    "rollback": run_rollback,
}

# Import new streaming-based tasks from infra.deploy.orchestrator
# These are used by job_queue workers for queue-based SSE streaming
try:
    from shared_libs.backend.infra.deploy.orchestrator import DEPLOY_TASKS
    # Merge with streaming task names prefixed
    for name, task in DEPLOY_TASKS.items():
        TASKS[f"stream_{name}"] = task
except ImportError:
    pass  # infra module not available


# =============================================================================
# Health Check Task
# =============================================================================

# Thresholds for auto-healing
CONTAINER_RESTART_THRESHOLD = 3  # Consecutive failures before restarting container
DROPLET_REBOOT_THRESHOLD = 5     # Consecutive failures before rebooting droplet
MAX_HEALING_ATTEMPTS = 2         # Max healing attempts per failure cycle (resets on healthy)


async def check_health(payload: Dict[str, Any], ctx) -> Dict[str, Any]:
    """
    Check health of all droplets and containers for a workspace.
    
    This is typically run on a schedule (e.g., every minute).
    
    Args:
        payload: Health check parameters:
            - workspace_id: Tenant ID
        ctx: JobContext with job_id, task_name, etc.
    
    Returns:
        Health check summary
    """
    logger = _get_logger()
    job_id = ctx.job_id
    
    workspace_id = payload["workspace_id"]
    
    logger.info(
        f"Starting health check",
        extra={
            "job_id": job_id,
            "workspace_id": workspace_id,
        }
    )
    
    results = {
        "workspace_id": workspace_id,
        "droplets_checked": 0,
        "containers_checked": 0,
        "healthy": 0,
        "unhealthy": 0,
        "unreachable": 0,
        "actions_taken": [],
    }
    
    try:
        from shared_libs.backend.app_kernel.db import get_db_connection
        from ..stores import DropletStore, HealthCheckStore, CredentialsStore
        
        async with get_db_connection() as conn:
            droplet_store = DropletStore(conn)
            health_store = HealthCheckStore(conn)
            creds_store = CredentialsStore(conn)
            
            # Get all droplets for this workspace
            droplets = await droplet_store.list_for_workspace(workspace_id)
            
            if not droplets:
                logger.info(f"No droplets found for workspace {workspace_id}")
                return results
            
            # Get credentials to create node agent client
            # We need DO token for the NodeAgentClient
            # For now, get the first available credentials
            all_creds = await conn.find_entities(
                "credentials",
                where_clause="[workspace_id] = ?",
                params=(workspace_id,),
                limit=1,
            )
            
            if not all_creds:
                logger.warning(f"No credentials found for workspace {workspace_id}")
                return results
            
            creds = all_creds[0]
            do_token = creds.get("do_token")
            
            if not do_token:
                logger.warning(f"No DO token in credentials for workspace {workspace_id}")
                return results
            
            # Import node agent client
            try:
                from shared_libs.backend.infra.node_agent.client import NodeAgentClient
            except ImportError:
                logger.error("NodeAgentClient not available")
                return results
            
            for droplet in droplets:
                droplet_id = droplet["droplet_id"]
                droplet_ip = droplet.get("ip_address") or droplet.get("public_ip")
                private_ip = droplet.get("private_ip")
                
                # Prefer private IP if in VPC
                check_ip = private_ip or droplet_ip
                
                if not check_ip:
                    logger.warning(f"No IP for droplet {droplet_id}")
                    continue
                
                results["droplets_checked"] += 1
                
                try:
                    # Create node agent client
                    agent_client = NodeAgentClient(
                        server_ip=check_ip,
                        do_token=do_token,
                    )
                    
                    # Check droplet-level health (agent responding)
                    import time
                    start_time = time.time()
                    
                    try:
                        # Use agent's health check endpoint - it already determines status
                        health_response = await agent_client.check_containers_health()
                        response_time_ms = int((time.time() - start_time) * 1000)
                        
                        # Agent is responding
                        agent_status = "healthy"
                        agent_error = None
                        
                        # Get containers with health already determined by agent
                        containers = health_response.data.get("containers", [])
                        summary = health_response.data.get("summary", {})
                        
                        for container in containers:
                            container_name = container.get("name", "unknown")
                            container_health = container.get("health", "unknown")
                            container_state = container.get("state", "unknown")
                            
                            results["containers_checked"] += 1
                            
                            # Map agent's health status
                            if container_health in ("healthy", "running"):
                                status = "healthy"
                                results["healthy"] += 1
                            elif container_health == "unhealthy":
                                status = "unhealthy"
                                results["unhealthy"] += 1
                            elif container_health == "starting":
                                status = "degraded"
                                results["unhealthy"] += 1
                            else:
                                status = "unhealthy"
                                results["unhealthy"] += 1
                            
                            # Record container health
                            await health_store.record(
                                workspace_id=workspace_id,
                                droplet_id=droplet_id,
                                container_name=container_name,
                                status=status,
                                response_time_ms=response_time_ms,
                                error_message=None if status == "healthy" else f"Container health: {container_health}, state: {container_state}",
                            )
                            
                            # Check for healing action needed
                            if status in ("unhealthy", "unreachable"):
                                consecutive = await health_store.count_consecutive_failures(
                                    droplet_id=droplet_id,
                                    container_name=container_name,
                                )
                                
                                if consecutive >= CONTAINER_RESTART_THRESHOLD:
                                    # Check if we've already tried healing too many times
                                    healing_attempts = await health_store.count_recent_healing_attempts(
                                        droplet_id=droplet_id,
                                        container_name=container_name,
                                    # Count all healing attempts (both success and failed)
                                    # Container-level checks only have container actions
                                    )
                                    
                                    if healing_attempts >= MAX_HEALING_ATTEMPTS:
                                        logger.warning(
                                            f"Container {container_name} still unhealthy after {healing_attempts} restart attempts, skipping",
                                            extra={"droplet_id": droplet_id, "consecutive": consecutive}
                                        )
                                    else:
                                        # Try to restart container
                                        action = await _try_restart_container(
                                            agent_client,
                                            health_store,
                                            workspace_id,
                                            droplet_id,
                                            container_name,
                                            consecutive,
                                            logger,
                                        )
                                        if action:
                                            results["actions_taken"].append(action)
                        
                    except Exception as agent_error:
                        # Agent not responding
                        agent_status = "unreachable"
                        response_time_ms = int((time.time() - start_time) * 1000)
                        results["unreachable"] += 1
                        
                        # Record droplet-level health failure
                        await health_store.record(
                            workspace_id=workspace_id,
                            droplet_id=droplet_id,
                            container_name=None,
                            status="unreachable",
                            response_time_ms=response_time_ms,
                            error_message=str(agent_error),
                        )
                        
                        # Check if we should reboot
                        consecutive = await health_store.count_consecutive_failures(
                            droplet_id=droplet_id,
                            container_name=None,
                        )
                        
                        if consecutive >= DROPLET_REBOOT_THRESHOLD:
                            # Check if we've already tried rebooting too many times
                            # Droplet-level checks only have droplet actions
                            healing_attempts = await health_store.count_recent_healing_attempts(
                                droplet_id=droplet_id,
                                container_name=None,
                            )
                            
                            if healing_attempts >= MAX_HEALING_ATTEMPTS:
                                logger.warning(
                                    f"Droplet {droplet_id} still unreachable after {healing_attempts} reboot attempts, skipping",
                                    extra={"consecutive": consecutive}
                                )
                            else:
                                action = await _try_reboot_droplet(
                                    do_token,
                                    health_store,
                                    workspace_id,
                                    droplet_id,
                                    consecutive,
                                    logger,
                                )
                                if action:
                                    results["actions_taken"].append(action)
                    
                    # Record droplet-level health (if agent responded)
                    if agent_status == "healthy":
                        await health_store.record(
                            workspace_id=workspace_id,
                            droplet_id=droplet_id,
                            container_name=None,
                            status="healthy",
                            response_time_ms=response_time_ms,
                        )
                        results["healthy"] += 1
                    
                except Exception as e:
                    logger.error(
                        f"Error checking droplet {droplet_id}",
                        extra={"error": str(e), "traceback": traceback.format_exc()}
                    )
                    results["unreachable"] += 1
        
        logger.info(
            f"Health check completed",
            extra={
                "job_id": job_id,
                "workspace_id": workspace_id,
                "results": results,
            }
        )
        
        return results
        
    except Exception as e:
        logger.error(
            f"Health check failed",
            extra={
                "job_id": job_id,
                "workspace_id": workspace_id,
                "error": str(e),
                "traceback": traceback.format_exc(),
            }
        )
        raise


async def _try_restart_container(
    agent_client,
    health_store,
    workspace_id: str,
    droplet_id: str,
    container_name: str,
    consecutive_failures: int,
    logger,
) -> Optional[Dict[str, Any]]:
    """Attempt to restart a container via node agent."""
    logger.warning(
        f"Attempting to restart container after {consecutive_failures} failures",
        extra={
            "droplet_id": droplet_id,
            "container_name": container_name,
        }
    )
    
    try:
        # Restart via node agent
        await agent_client.restart_container(container_name)
        
        # Record action
        await health_store.record(
            workspace_id=workspace_id,
            droplet_id=droplet_id,
            container_name=container_name,
            status="unhealthy",
            action_taken="restarted",
            attempt_count=consecutive_failures,
        )
        
        logger.info(
            f"Successfully restarted container {container_name}",
            extra={"droplet_id": droplet_id}
        )
        
        return {
            "action": "restart_container",
            "droplet_id": droplet_id,
            "container_name": container_name,
            "success": True,
        }
        
    except Exception as e:
        # Record failed restart
        await health_store.record(
            workspace_id=workspace_id,
            droplet_id=droplet_id,
            container_name=container_name,
            status="unhealthy",
            action_taken="restart_failed",
            attempt_count=consecutive_failures,
            error_message=str(e),
        )
        
        logger.error(
            f"Failed to restart container {container_name}",
            extra={"droplet_id": droplet_id, "error": str(e)}
        )
        
        return {
            "action": "restart_container",
            "droplet_id": droplet_id,
            "container_name": container_name,
            "success": False,
            "error": str(e),
        }


async def _try_reboot_droplet(
    do_token: str,
    health_store,
    workspace_id: str,
    droplet_id: str,
    consecutive_failures: int,
    logger,
) -> Optional[Dict[str, Any]]:
    """Attempt to reboot a droplet via DigitalOcean API."""
    logger.warning(
        f"Attempting to reboot droplet after {consecutive_failures} failures",
        extra={"droplet_id": droplet_id}
    )
    
    try:
        from shared_libs.backend.cloud import AsyncDOClient
        
        async with AsyncDOClient(api_token=do_token) as do_client:
            # Convert string droplet_id to int for DO API
            do_droplet_id = int(droplet_id)
            
            # Reboot
            result = await do_client.reboot_droplet(do_droplet_id, wait=False)
            
            # Record action
            await health_store.record(
                workspace_id=workspace_id,
                droplet_id=droplet_id,
                container_name=None,
                status="unreachable",
                action_taken="rebooted",
                attempt_count=consecutive_failures,
            )
            
            logger.info(
                f"Successfully initiated reboot for droplet {droplet_id}",
                extra={"action_id": result.get("id")}
            )
            
            return {
                "action": "reboot_droplet",
                "droplet_id": droplet_id,
                "success": True,
                "action_id": result.get("id"),
            }
            
    except Exception as e:
        # Record failed reboot
        await health_store.record(
            workspace_id=workspace_id,
            droplet_id=droplet_id,
            container_name=None,
            status="unreachable",
            action_taken="reboot_failed",
            attempt_count=consecutive_failures,
            error_message=str(e),
        )
        
        logger.error(
            f"Failed to reboot droplet {droplet_id}",
            extra={"error": str(e)}
        )
        
        return {
            "action": "reboot_droplet",
            "droplet_id": droplet_id,
            "success": False,
            "error": str(e),
        }


async def cleanup_health_checks(payload: Dict[str, Any], ctx) -> Dict[str, Any]:
    """
    Clean up old health check records.
    
    Run periodically (e.g., daily) to prevent database bloat.
    
    Args:
        payload: Cleanup parameters:
            - days: Records older than this are deleted (default: 7)
        ctx: JobContext
    
    Returns:
        Cleanup summary
    """
    logger = _get_logger()
    
    days = payload.get("days", 7)
    
    logger.info(f"Starting health check cleanup, removing records older than {days} days")
    
    try:
        from shared_libs.backend.app_kernel.db import get_db_connection
        from ..stores import HealthCheckStore
        
        async with get_db_connection() as conn:
            health_store = HealthCheckStore(conn)
            deleted_count = await health_store.cleanup_old(days=days)
        
        logger.info(f"Cleaned up {deleted_count} old health check records")
        
        return {
            "deleted_count": deleted_count,
            "days_threshold": days,
        }
        
    except Exception as e:
        logger.error(f"Health check cleanup failed", extra={"error": str(e)})
        raise


# Add health check tasks to registry
TASKS["check_health"] = check_health
TASKS["cleanup_health_checks"] = cleanup_health_checks