"""
Deployment orchestration with all improvements:
1. Deployment locking
2. Graceful container shutdown (drain)
3. Deployment timeout
4. Retry on transient failures (via shared_libs.resilience)
5. Scale down - pick unhealthy first
6. Dependency warnings
7. Image cleanup (keep 100 versions)
8. Health: TCP ping + optional HTTP for webservices
9. Partial failure recovery options
10. Pre-deploy validation
"""

import json
import asyncio
from typing import Optional, List, Dict, Any, AsyncIterator, Callable
from datetime import datetime, timezone

from shared_libs.backend.resilience import retry_with_backoff, with_timeout

from .stores import projects, services, deployments, droplets, containers
from .node_agent import NodeAgentClient
from .naming import (
    get_domain_name, get_container_name, get_image_name, get_image_base_name,
    get_container_port, get_host_port, parse_env_variables,
)
from .stateful import get_stateful_urls
from .locks import acquire_deploy_lock, release_deploy_lock, get_lock_info
from config import settings


# =============================================================================
# Configuration
# =============================================================================

DEFAULT_DEPLOY_TIMEOUT = 120  # seconds per droplet
DEFAULT_DRAIN_TIMEOUT = 30
IMAGE_VERSIONS_TO_KEEP = 100  # ~50GB at 0.5GB/image, safe for any droplet


# =============================================================================
# SSE Streaming
# =============================================================================

class StreamContext:
    def __init__(self):
        self._logs: List[str] = []
    
    def __call__(self, msg: str, level: str = "info"):
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self._logs.append(f"[{ts}] {msg}")
    
    def flush(self) -> str:
        return "\n".join(self._logs)


def sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"

def sse_log(message: str, level: str = "info") -> str:
    return sse_event("log", {"message": message, "level": level, "ts": _now_iso()})

def sse_progress(percent: int, step: str) -> str:
    return sse_event("progress", {"percent": percent, "step": step})

def sse_complete(success: bool, deployment_id: str, error: str = None, recovery_options: List[str] = None) -> str:
    data = {"success": success, "deployment_id": deployment_id, "error": error}
    if recovery_options:
        data["recovery_options"] = recovery_options
    return sse_event("complete", data)

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# =============================================================================
# Pre-deploy Validation (#10)
# =============================================================================

async def validate_deploy_request(
    db,
    user_id: str,
    existing_droplet_ids: List[str],
    snapshot_id: Optional[str],
    service_id: Optional[str] = None,
    env: Optional[str] = None,
) -> List[str]:
    """Validate before starting deployment. Returns list of errors."""
    errors = []
    
    for did in existing_droplet_ids:
        d = await droplets.get(db, did)
        if not d:
            errors.append(f"Droplet {did} not found")
        elif d.get('workspace_id') != user_id:
            errors.append(f"Droplet {did} belongs to another user")
        elif d.get('health_status') == 'problematic':
            errors.append(f"Droplet {d.get('name', did)} is flagged as problematic")
        elif not d.get('ip'):
            errors.append(f"Droplet {d.get('name', did)} has no IP address")
    
    if snapshot_id:
        from .stores import snapshots
        snap = await snapshots.get(db, snapshot_id)
        if not snap:
            errors.append(f"Snapshot {snapshot_id} not found")
    
    if service_id and env:
        lock = await get_lock_info(service_id, env)
        if lock:
            errors.append(f"Deployment in progress ({lock.get('expires_in')}s remaining)")
    
    return errors


# =============================================================================
# Agent Helpers with Drain (#2) and Image Cleanup (#7)
# =============================================================================

async def configure_nginx(ip: str, private_ips: List[str], host_port: int, domain: str, do_token: str) -> Dict[str, Any]:
    agent = NodeAgentClient(host=ip, port=settings.node_agent_port, do_token=do_token)
    try:
        return await agent.configure_nginx(private_ips, host_port, domain)
    finally:
        await agent.close()


async def clear_old_container(
    ip: str,
    container_name: str,
    do_token: str,
    image_base_name: str = None,
    drain: bool = True,
    drain_timeout: int = DEFAULT_DRAIN_TIMEOUT,
) -> Dict[str, Any]:
    """Remove container with graceful drain and optional image cleanup."""
    agent = NodeAgentClient(host=ip, port=settings.node_agent_port, do_token=do_token)
    try:
        result = await agent.remove_container(container_name, drain=drain, drain_timeout=drain_timeout)
        
        # Cleanup old images (#7)
        if image_base_name:
            await agent.cleanup_images(image_base_name, keep_latest=IMAGE_VERSIONS_TO_KEEP)
        
        return result
    except Exception as e:
        return {"error": str(e)}
    finally:
        await agent.close()


# =============================================================================
# Deploy To Single Droplet with Timeout (#3) and Retries (#4)
# =============================================================================

async def deploy_to(
    db, droplet_id: str, droplet_ip: str, deployment_id: str, container_name: str,
    image_name: str, image: bytes, env_variables: Dict[str, str],
    container_port: int, host_port: int, do_token: str, stream: StreamContext,
    http_health_path: str = None,
    timeout: int = DEFAULT_DEPLOY_TIMEOUT,
) -> Dict[str, Any]:
    """Deploy with timeout and retries via resilience module."""
    
    @retry_with_backoff(max_retries=2, base_delay=5.0, max_delay=30.0, exceptions=(ConnectionError, TimeoutError, OSError))
    @with_timeout(seconds=timeout)
    async def _deploy_with_resilience():
        return await _deploy_to_impl(
            db, droplet_id, droplet_ip, deployment_id, container_name,
            image_name, image, env_variables, container_port, host_port,
            do_token, stream, http_health_path
        )
    
    try:
        result = await _deploy_with_resilience()
        if result['status'] == 'success':
            return result
        # Non-retryable failure (health check failed, etc.)
        await containers.upsert(db, {
            'container_name': container_name, 'droplet_id': droplet_id,
            'deployment_id': deployment_id, 'status': 'failed',
            'health_status': 'unhealthy', 'error': result.get('error'),
        })
        return result
    except asyncio.TimeoutError:
        error = f'Timeout after {timeout}s'
        stream(f'   {droplet_ip} - {error}')
        await containers.upsert(db, {
            'container_name': container_name, 'droplet_id': droplet_id,
            'deployment_id': deployment_id, 'status': 'failed',
            'health_status': 'unhealthy', 'error': error,
        })
        return {'status': 'failed', 'error': error}
    except Exception as e:
        # All retries exhausted
        error = str(e)
        stream(f'   {droplet_ip} - failed after retries: {error}')
        await containers.upsert(db, {
            'container_name': container_name, 'droplet_id': droplet_id,
            'deployment_id': deployment_id, 'status': 'failed',
            'health_status': 'unhealthy', 'error': error,
        })
        return {'status': 'failed', 'error': error}


async def _deploy_to_impl(
    db, droplet_id: str, droplet_ip: str, deployment_id: str, container_name: str,
    image_name: str, image: bytes, env_variables: Dict[str, str],
    container_port: int, host_port: int, do_token: str, stream: StreamContext,
    http_health_path: str,
) -> Dict[str, Any]:
    """Actual deploy implementation."""
    stream(f'deploying to {droplet_ip}...')
    agent = NodeAgentClient(host=droplet_ip, port=settings.node_agent_port, do_token=do_token)
    
    try:
        if image:
            stream(f'   {droplet_ip} - uploading image...')
            await agent.upload(image, image_name)
        
        stream(f'   {droplet_ip} - starting container...')
        env_list = [f"{k}={v}" for k, v in env_variables.items()]
        await agent.start_container(
            container_name=container_name, image_name=image_name, env_variables=env_list,
            container_port=container_port, host_port=host_port,
        )
        
        # Health check: TCP first, then optional HTTP for webservices
        status = await agent.health(container_name, container_port, http_path=http_health_path)
        
        if status.get('status') == 'healthy':
            stream(f'deployed to {droplet_ip}.')
            await containers.upsert(db, {
                'container_name': container_name, 'droplet_id': droplet_id,
                'deployment_id': deployment_id, 'status': 'running', 'health_status': 'healthy',
            })
            return {'status': 'success'}
        else:
            return {'status': 'failed', 'error': status.get('reason', 'health check failed')}
    finally:
        await agent.close()


# =============================================================================
# Main Deploy Function
# =============================================================================

async def deploy(
    db, user_id: str, project_name: str, service_name: str, service_description: str,
    service_type: str, image: bytes, image_name: str, env_variables: List[str], env: str,
    do_token: str, cf_token: str, existing_droplet_ids: List[str] = None,
    new_droplets_nb: int = 0, new_droplets_region: str = 'lon1',
    new_droplets_size: str = 's-1vcpu-1gb', new_droplets_snapshot_id: str = None,
    http_health_path: str = None,  # Optional HTTP health endpoint (webservice only)
) -> AsyncIterator[str]:
    """Main deployment with all improvements."""
    deployment_id = None
    lock_id = None
    service_id = None
    stream = StreamContext()
    
    try:
        existing_droplet_ids = existing_droplet_ids or []
        if not existing_droplet_ids and new_droplets_nb == 0:
            yield sse_log("No droplets specified", "error")
            yield sse_complete(False, "", "No droplets specified")
            return
        
        # === VALIDATION (#10) ===
        yield sse_log('Validating...')
        errors = await validate_deploy_request(db, user_id, existing_droplet_ids, new_droplets_snapshot_id)
        if errors:
            for err in errors:
                yield sse_log(f'Validation error: {err}', 'error')
            yield sse_complete(False, "", errors[0])
            return
        
        # Setup project/service
        yield sse_progress(5, "setup")
        project = await projects.get_by_name(db, user_id, project_name)
        if not project:
            project = await projects.create(db, {'workspace_id': user_id, 'name': project_name})
        
        service = await services.get_by_name(db, project['id'], service_name)
        if not service:
            service = await services.create(db, {
                'project_id': project['id'], 'name': service_name,
                'description': service_description, 'service_type': service_type,
                'http_health_path': http_health_path if service_type == 'webservice' else None,
            })
        service_id = service['id']
        
        # Use stored http_health_path for webservices (#8)
        if service_type == 'webservice':
            http_health_path = service.get('http_health_path') or http_health_path
        else:
            http_health_path = None  # TCP only for non-webservices
        
        # === LOCKING (#1) ===
        yield sse_log('Acquiring lock...')
        lock_id = await acquire_deploy_lock(service_id, env, timeout=600, holder=user_id)
        if not lock_id:
            yield sse_log('Deployment already in progress', 'error')
            yield sse_complete(False, "", "Deployment locked")
            return
        
        # Provision new droplets
        new_droplets = []
        if new_droplets_nb > 0:
            yield sse_log(f'Provisioning {new_droplets_nb} droplets...')
            yield sse_progress(10, "provisioning")
            from .provision import create_droplet
            tasks = [create_droplet(db=db, user_id=user_id, snapshot_id=new_droplets_snapshot_id,
                    region=new_droplets_region, size=new_droplets_size, do_token=do_token)
                    for _ in range(new_droplets_nb)]
            new_droplets = await asyncio.gather(*tasks)
        
        # Gather target droplets
        yield sse_progress(15, "resolving")
        existing = [await droplets.get(db, did) for did in existing_droplet_ids]
        existing = [d for d in existing if d and d.get('ip')]
        all_droplets = existing + [d for d in new_droplets if not d.get('error')]
        
        if not all_droplets:
            yield sse_log("No valid droplets", "error")
            yield sse_complete(False, "", "No valid droplets")
            return
        
        ids = [d['id'] for d in all_droplets]
        ips = [d['ip'] for d in all_droplets]
        private_ips = [d.get('private_ip') or d['ip'] for d in all_droplets]
        yield sse_log(f'Targets: {ips}')
        
        # Version
        yield sse_progress(20, "versioning")
        last_dep = await deployments.get_latest(db, service_id, env, status='success')
        last_version = last_dep['version'] if last_dep else 0
        version = last_version + 1
        yield sse_log(f'Version: v{version}')
        
        last_container = get_container_name(user_id, project_name, service_name, env, last_version) if last_version > 0 else None
        container_name = get_container_name(user_id, project_name, service_name, env, version)
        final_image_name = image_name or get_image_name(user_id, project_name, service_name, env, version)
        image_base = get_image_base_name(user_id, project_name, service_name, env)
        host_port = get_host_port(user_id, project_name, service_name, env, version, service_type)
        container_port = get_container_port(service_type)
        
        # Parse env + stateful URLs with warnings (#6)
        env_dict = parse_env_variables(env_variables)
        if service_type in ('webservice', 'worker', 'schedule'):
            stateful_urls, warnings = await get_stateful_urls(db, project['id'], env, ids[0] if ids else None)
            for w in warnings:
                yield sse_log(f'Warning: {w}', 'warning')
            if stateful_urls:
                yield sse_log(f'Injecting: {list(stateful_urls.keys())}')
                env_dict = {**stateful_urls, **env_dict}
        
        # Save deployment
        yield sse_progress(25, "saving")
        deployment = await deployments.create(db, {
            'service_id': service_id, 'version': version, 'env': env,
            'image_name': final_image_name, 'env_variables': env_dict, 'droplet_ids': ids,
            'is_rollback': image is None and image_name is not None,
            'status': 'in_progress', 'triggered_by': user_id, 'triggered_at': _now_iso(),
        })
        deployment_id = deployment['id']
        
        # Stateful: clean BEFORE (expect downtime) with drain (#2)
        if service_type not in ('webservice', 'worker', 'schedule') and last_version > 0:
            yield sse_log('Draining old containers (stateful)...')
            yield sse_progress(30, "cleanup_stateful")
            tasks = [clear_old_container(ip, last_container, do_token, image_base, drain=True) for ip in ips]
            await asyncio.gather(*tasks, return_exceptions=True)
        
        # Deploy in parallel with timeout+retries (#3, #4)
        yield sse_log(f'Deploying to {len(all_droplets)} servers...')
        yield sse_progress(35, "deploying")
        deploy_tasks = [
            deploy_to(db=db, droplet_id=d['id'], droplet_ip=d['ip'], deployment_id=deployment_id,
                     container_name=container_name, image_name=final_image_name, image=image,
                     env_variables=env_dict, container_port=container_port, host_port=host_port,
                     do_token=do_token, stream=stream, http_health_path=http_health_path)
            for d in all_droplets
        ]
        statuses = await asyncio.gather(*deploy_tasks)
        yield sse_progress(70, "deployed")
        
        # Results
        success_count = sum(1 for s in statuses if s.get('status') == 'success')
        failed_count = len(ips) - success_count
        yield sse_log(f'Results: {success_count}/{len(ips)} successful')
        
        if success_count == len(ips):
            # === ALL SUCCESS ===
            if service_type == 'webservice':
                yield sse_log('Updating nginx...')
                yield sse_progress(80, "nginx")
                domain = get_domain_name(user_id, project_name, service_name, env)
                nginx_tasks = [configure_nginx(ip, private_ips, host_port, domain, do_token) for ip in ips]
                await asyncio.gather(*nginx_tasks, return_exceptions=True)
                yield sse_progress(90, "dns")
                from .dns import setup_multi_server
                asyncio.create_task(setup_multi_server(cf_token, domain, ips))
            
            # Clean old with drain + image cleanup (#2, #7)
            if service_type in ('webservice', 'worker', 'schedule') and last_version > 0:
                yield sse_log('Draining old containers...')
                yield sse_progress(95, "cleanup")
                tasks = [clear_old_container(ip, last_container, do_token, image_base, drain=True) for ip in ips]
                await asyncio.gather(*tasks, return_exceptions=True)
            
            await deployments.mark_success(db, deployment_id, stream.flush())
            yield sse_progress(100, "complete")
            yield sse_complete(True, deployment_id)
            
        elif success_count == 0:
            # === ALL FAILED ===
            error = next((s.get('error') for s in statuses if s.get('error')), 'All failed')
            await deployments.mark_failed(db, deployment_id, error, stream.flush())
            yield sse_complete(False, deployment_id, error)
            
        else:
            # === PARTIAL (#9) ===
            error = next((s.get('error') for s in statuses if s.get('error')), 'Partial failure')
            failed_ips = [ips[i] for i, s in enumerate(statuses) if s.get('status') != 'success']
            success_ips = [ips[i] for i, s in enumerate(statuses) if s.get('status') == 'success']
            
            yield sse_log(f'Partial: {failed_count} failed', 'warning')
            
            await deployments.update(db, deployment_id, {
                'status': 'partial', 'error': error, 'log': stream.flush(),
                'failed_droplet_ips': failed_ips, 'success_droplet_ips': success_ips,
            })
            
            yield sse_complete(False, deployment_id, error, 
                             recovery_options=['retry_failed', 'rollback_all', 'continue_partial'])
            
    except Exception as e:
        if deployment_id:
            await deployments.mark_failed(db, deployment_id, str(e), stream.flush())
        yield sse_log(f'Error: {e}', 'error')
        yield sse_complete(False, deployment_id or '', str(e))
    finally:
        # === RELEASE LOCK (#1) ===
        if lock_id and service_id:
            await release_deploy_lock(service_id, env, lock_id)


# =============================================================================
# Rollback
# =============================================================================

async def rollback(
    db, user_id: str, service_id: str, env: str, do_token: str, cf_token: str,
    target_version: int = None,
) -> AsyncIterator[str]:
    """Rollback to previous version."""
    try:
        service = await services.get(db, service_id)
        if not service:
            yield sse_complete(False, '', 'Service not found')
            return
        
        project = await projects.get(db, service['project_id'])
        current = await deployments.get_latest(db, service_id, env, status='success')
        if not current:
            yield sse_complete(False, '', 'No deployment to rollback')
            return
        
        yield sse_log(f'Current: v{current["version"]}')
        
        if target_version is None:
            target = await deployments.get_previous(db, service_id, env, current['version'], status='success')
        else:
            target = await deployments.get_by_version(db, service_id, env, target_version)
        
        if not target:
            yield sse_complete(False, '', 'No target version')
            return
        
        yield sse_log(f'Rolling back to v{target["version"]}')
        
        current_ids = current.get('droplet_ids', [])
        if isinstance(current_ids, str):
            current_ids = json.loads(current_ids)
        
        env_vars = target.get('env_variables', {})
        if isinstance(env_vars, str):
            env_vars = json.loads(env_vars)
        
        async for event in deploy(
            db=db, user_id=user_id, project_name=project['name'], service_name=service['name'],
            service_description=None, service_type=service['service_type'],
            image=None, image_name=target['image_name'],
            env_variables=[f"{k}={v}" for k, v in env_vars.items()],
            env=env, do_token=do_token, cf_token=cf_token, existing_droplet_ids=current_ids,
            http_health_path=service.get('http_health_path') if service['service_type'] == 'webservice' else None,
        ):
            yield event
    except Exception as e:
        yield sse_complete(False, '', str(e))


# =============================================================================
# Scale with Unhealthy-First Removal (#5)
# =============================================================================

async def scale(
    db, user_id: str, service_id: str, env: str, target_count: int,
    do_token: str, cf_token: str, region: str = 'lon1', size: str = 's-1vcpu-1gb',
    snapshot_id: str = None,
) -> AsyncIterator[str]:
    """Scale service. Removes unhealthy droplets first."""
    try:
        service = await services.get(db, service_id)
        project = await projects.get(db, service['project_id'])
        current = await deployments.get_latest(db, service_id, env, status='success')
        
        if not current:
            yield sse_complete(False, '', 'No deployment to scale')
            return
        
        current_ids = current.get('droplet_ids', [])
        if isinstance(current_ids, str):
            current_ids = json.loads(current_ids)
        
        yield sse_log(f'Scaling from {len(current_ids)} to {target_count}')
        
        if target_count == len(current_ids):
            yield sse_complete(True, current['id'])
            return
        
        if target_count > len(current_ids):
            # SCALE UP
            new_count = target_count - len(current_ids)
            env_vars = current.get('env_variables', {})
            if isinstance(env_vars, str):
                env_vars = json.loads(env_vars)
            
            async for event in deploy(
                db=db, user_id=user_id, project_name=project['name'], service_name=service['name'],
                service_description=None, service_type=service['service_type'],
                image=None, image_name=current['image_name'],
                env_variables=[f"{k}={v}" for k, v in env_vars.items()],
                env=env, do_token=do_token, cf_token=cf_token,
                existing_droplet_ids=current_ids, new_droplets_nb=new_count,
                new_droplets_region=region, new_droplets_size=size, new_droplets_snapshot_id=snapshot_id,
                http_health_path=service.get('http_health_path') if service['service_type'] == 'webservice' else None,
            ):
                yield event
        else:
            # SCALE DOWN - remove unhealthy first (#5)
            remove_count = len(current_ids) - target_count
            yield sse_log(f'Removing {remove_count} droplets (unhealthy first)')
            
            # Get droplet info and sort
            infos = [await droplets.get(db, did) for did in current_ids]
            infos = [d for d in infos if d]
            
            # Sort: unhealthy first, then oldest
            infos.sort(key=lambda d: (
                0 if d.get('health_status') != 'healthy' else 1,
                d.get('created_at', '9999')
            ))
            
            remove = infos[:remove_count]
            keep = infos[remove_count:]
            
            unhealthy_count = sum(1 for d in remove if d.get('health_status') != 'healthy')
            if unhealthy_count:
                yield sse_log(f'Removing {unhealthy_count} unhealthy droplets')
            
            remove_ips = [d['ip'] for d in remove if d.get('ip')]
            keep_ids = [d['id'] for d in keep]
            keep_ips = [d['ip'] for d in keep if d.get('ip')]
            keep_private_ips = [d.get('private_ip') or d['ip'] for d in keep if d.get('ip')]
            
            container_name = get_container_name(user_id, project['name'], service['name'], env, current['version'])
            image_base = get_image_base_name(user_id, project['name'], service['name'], env)
            
            # Drain and stop with image cleanup
            yield sse_log('Draining containers...')
            tasks = [clear_old_container(ip, container_name, do_token, image_base, drain=True) for ip in remove_ips]
            await asyncio.gather(*tasks, return_exceptions=True)
            
            await deployments.update(db, current['id'], {'droplet_ids': keep_ids})
            
            for d in remove:
                await containers.delete_by_droplet_and_name(db, d['id'], container_name)
            
            if service['service_type'] == 'webservice':
                yield sse_log('Updating nginx...')
                host_port = get_host_port(user_id, project['name'], service['name'], env, current['version'], service['service_type'])
                domain = get_domain_name(user_id, project['name'], service['name'], env)
                nginx_tasks = [configure_nginx(ip, keep_private_ips, host_port, domain, do_token) for ip in keep_ips]
                await asyncio.gather(*nginx_tasks, return_exceptions=True)
            
            yield sse_log(f'Scaled to {target_count}')
            yield sse_complete(True, current['id'])
    except Exception as e:
        yield sse_complete(False, '', str(e))


# =============================================================================
# Partial Recovery (#9)
# =============================================================================

async def recover_partial(
    db, user_id: str, deployment_id: str, action: str,
    do_token: str, cf_token: str,
) -> AsyncIterator[str]:
    """Recover from partial failure: retry_failed, rollback_all, continue_partial."""
    dep = await deployments.get(db, deployment_id)
    if not dep or dep.get('status') != 'partial':
        yield sse_complete(False, '', 'Not a partial deployment')
        return
    
    service = await services.get(db, dep['service_id'])
    project = await projects.get(db, service['project_id'])
    
    if action == 'rollback_all':
        async for event in rollback(db, user_id, service['id'], dep['env'], do_token, cf_token):
            yield event
            
    elif action == 'continue_partial':
        success_ips = dep.get('success_droplet_ips', [])
        if not success_ips:
            yield sse_complete(False, '', 'No successful droplets')
            return
        
        if service['service_type'] == 'webservice':
            domain = get_domain_name(user_id, project['name'], service['name'], dep['env'])
            host_port = get_host_port(user_id, project['name'], service['name'], dep['env'], dep['version'], service['service_type'])
            
            # Get private IPs
            all_d = await droplets.list_for_workspace(db, user_id)
            private_ips = []
            for ip in success_ips:
                for d in all_d:
                    if d.get('ip') == ip:
                        private_ips.append(d.get('private_ip') or ip)
                        break
            
            nginx_tasks = [configure_nginx(ip, private_ips, host_port, domain, do_token) for ip in success_ips]
            await asyncio.gather(*nginx_tasks, return_exceptions=True)
            
            from .dns import setup_multi_server
            await setup_multi_server(cf_token, domain, success_ips)
        
        await deployments.update(db, deployment_id, {'status': 'partial_accepted'})
        yield sse_complete(True, deployment_id)
        
    elif action == 'retry_failed':
        failed_ips = dep.get('failed_droplet_ips', [])
        if not failed_ips:
            yield sse_complete(False, '', 'No failed droplets')
            return
        
        all_d = await droplets.list_for_workspace(db, user_id)
        failed_ids = [d['id'] for d in all_d if d.get('ip') in failed_ips]
        
        env_vars = dep.get('env_variables', {})
        if isinstance(env_vars, str):
            env_vars = json.loads(env_vars)
        
        async for event in deploy(
            db=db, user_id=user_id, project_name=project['name'], service_name=service['name'],
            service_description=None, service_type=service['service_type'],
            image=None, image_name=dep['image_name'],
            env_variables=[f"{k}={v}" for k, v in env_vars.items()],
            env=dep['env'], do_token=do_token, cf_token=cf_token,
            existing_droplet_ids=failed_ids,
            http_health_path=service.get('http_health_path') if service['service_type'] == 'webservice' else None,
        ):
            yield event
    else:
        yield sse_complete(False, '', f'Unknown action: {action}')


# =============================================================================
# Delete Operations
# =============================================================================

async def delete_droplet(db, user_id: str, droplet_id: str, do_token: str, cf_token: str) -> AsyncIterator[str]:
    """Delete droplet with nginx/DNS updates."""
    try:
        droplet = await droplets.get(db, droplet_id)
        if not droplet:
            yield sse_complete(False, '', 'Not found')
            return
        
        yield sse_log(f'Deleting {droplet["name"]}...')
        
        droplet_containers = await containers.list_for_droplet(db, droplet_id)
        
        if droplet_containers:
            yield sse_log(f'{len(droplet_containers)} containers affected')
            
            affected_deps = set(c['deployment_id'] for c in droplet_containers if c.get('deployment_id'))
            
            for dep_id in affected_deps:
                dep = await deployments.get(db, dep_id)
                if not dep:
                    continue
                
                service = await services.get(db, dep['service_id'])
                if not service or service['service_type'] != 'webservice':
                    continue
                
                project = await projects.get(db, service['project_id'])
                if not project:
                    continue
                
                domain = get_domain_name(user_id, project['name'], service['name'], dep['env'])
                
                dep_ids = dep.get('droplet_ids', [])
                if isinstance(dep_ids, str):
                    dep_ids = json.loads(dep_ids)
                remaining_ids = [d for d in dep_ids if d != droplet_id]
                
                if not remaining_ids:
                    yield sse_log(f'  Removing DNS for {domain}')
                    from .dns import remove_domain
                    await remove_domain(cf_token, domain)
                    continue
                
                remaining = [await droplets.get(db, did) for did in remaining_ids]
                remaining = [d for d in remaining if d]
                remaining_ips = [d['ip'] for d in remaining]
                remaining_private = [d.get('private_ip') or d['ip'] for d in remaining]
                
                host_port = get_host_port(user_id, project['name'], service['name'], dep['env'], dep['version'], service['service_type'])
                
                yield sse_log(f'  Updating nginx for {domain}')
                nginx_tasks = [configure_nginx(ip, remaining_private, host_port, domain, do_token) for ip in remaining_ips]
                await asyncio.gather(*nginx_tasks, return_exceptions=True)
                
                from .dns import setup_multi_server
                await setup_multi_server(cf_token, domain, remaining_ips)
            
            await containers.delete_by_droplet(db, droplet_id)
        
        yield sse_log('Deleting from DO...')
        from backend.cloud import AsyncDOClient
        async with AsyncDOClient(api_token=do_token) as client:
            await client.delete_droplet(droplet['do_droplet_id'], force=True)
        
        await droplets.delete(db, droplet_id)
        yield sse_complete(True, droplet_id)
    except Exception as e:
        yield sse_complete(False, '', str(e))


async def delete_service(db, user_id: str, service_id: str, env: str = None, do_token: str = None, cf_token: str = None) -> AsyncIterator[str]:
    """Delete service with drain."""
    try:
        service = await services.get(db, service_id)
        if not service:
            yield sse_complete(False, '', 'Not found')
            return
        
        project = await projects.get(db, service['project_id'])
        yield sse_log(f'Deleting {project["name"]}/{service["name"]}')
        
        service_deps = await deployments.list_for_service(db, service_id, env=env, limit=1000)
        image_base = get_image_base_name(user_id, project['name'], service['name'], env or 'prod')
        
        to_remove = []
        for dep in service_deps:
            dep_ids = dep.get('droplet_ids', [])
            if isinstance(dep_ids, str):
                dep_ids = json.loads(dep_ids)
            for did in dep_ids:
                d = await droplets.get(db, did)
                if d and d.get('ip'):
                    cn = get_container_name(user_id, project['name'], service['name'], dep['env'], dep['version'])
                    to_remove.append((d['ip'], cn))
        
        if to_remove:
            yield sse_log(f'Draining {len(to_remove)} containers...')
            tasks = [clear_old_container(ip, cn, do_token, image_base, drain=True) for ip, cn in to_remove]
            await asyncio.gather(*tasks, return_exceptions=True)
        
        if service['service_type'] == 'webservice':
            envs = set(dep['env'] for dep in service_deps)
            domains = [get_domain_name(user_id, project['name'], service['name'], e) for e in envs]
            yield sse_log(f'Removing DNS: {domains}')
            from .dns import remove_domain
            dns_tasks = [remove_domain(cf_token, d) for d in domains]
            await asyncio.gather(*dns_tasks, return_exceptions=True)
        
        await containers.delete_by_service(db, service_id, env=env)
        await deployments.delete_by_service(db, service_id, env=env)
        
        if not env:
            await services.delete(db, service_id)
        
        yield sse_complete(True, service_id)
    except Exception as e:
        yield sse_complete(False, '', str(e))


async def delete_project(db, user_id: str, project_id: str, do_token: str, cf_token: str) -> AsyncIterator[str]:
    """Delete project and all services."""
    try:
        project = await projects.get(db, project_id)
        if not project:
            yield sse_complete(False, '', 'Not found')
            return
        
        yield sse_log(f'Deleting project {project["name"]}')
        project_services = await services.list_for_project(db, project_id)
        
        for svc in project_services:
            async for event in delete_service(db, user_id, svc['id'], env=None, do_token=do_token, cf_token=cf_token):
                yield event
        
        await projects.delete(db, project_id)
        yield sse_complete(True, project_id)
    except Exception as e:
        yield sse_complete(False, '', str(e))
