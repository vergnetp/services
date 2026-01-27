"""
Deployment orchestration - matches pseudo code exactly.
Calls node agent via HTTP for all container operations.
"""

import json
import asyncio
from typing import Optional, List, Dict, Any, AsyncIterator
from datetime import datetime, timezone

from shared_libs.backend.resilience import retry_with_backoff

from .stores import projects, services, deployments, droplets, containers
from . import agent_client
from .naming import (
    get_domain_name, get_container_name, get_image_name,
    get_container_port, get_host_port, parse_env_variables,
)
from .stateful import get_stateful_urls
from .locks import acquire_deploy_lock, release_deploy_lock


# =============================================================================
# SSE Streaming
# =============================================================================

class StreamContext:
    def __init__(self):
        self._logs: List[str] = []
    
    def __call__(self, msg: str):
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self._logs.append(f"[{ts}] {msg}")
    
    def flush(self) -> str:
        return "\n".join(self._logs)


def sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"

def sse_log(message: str, level: str = "info") -> str:
    return sse_event("log", {"message": message, "level": level})

def sse_complete(success: bool, deployment_id: str, error: str = None) -> str:
    return sse_event("complete", {"success": success, "deployment_id": deployment_id, "error": error})

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# =============================================================================
# Deploy To Single Droplet (matches pseudo code)
# =============================================================================

@retry_with_backoff(max_retries=2, base_delay=5.0, exceptions=(ConnectionError, TimeoutError, OSError))
async def deploy_to(
    db, droplet_id: str, droplet_ip: str, deployment_id: str, container_name: str,
    image_name: str, image: bytes, env_variables: Dict[str, str],
    container_port: int, host_port: int, do_token: str, stream: StreamContext,
) -> Dict[str, Any]:
    """
    Deploy container to a single droplet.
    
    Pseudo code:
        stream(f'deploying to server {droplet_ip}...')
        if image:
           call {droplet_ip}:9999/upload?image=image&name=image_name
        call {droplet_ip}:9999/start_container?...
        status = call {droplet_ip}:9999/health?container_name=container_name
        if status=='healthy': 
           store.update_container(..., status='healthy')
           return {status:'success'}
        else:
           store.update_container(..., status='unhealthy')
           return {status:'failed', error:status.error}
    """
    try:
        stream(f'deploying to server {droplet_ip}...')
        
        # Upload image if provided
        if image:
            stream(f'   {droplet_ip} - uploading the image...')
            result = await agent_client.upload_image(droplet_ip, image, image_name, do_token)
            if result.get('error'):
                raise Exception(f"Upload failed: {result['error']}")
            stream(f'   {droplet_ip} - {image_name} uploaded.')
        
        # Start container
        stream(f'   {droplet_ip} - starting the container...')
        env_list = [f"{k}={v}" for k, v in env_variables.items()]
        result = await agent_client.start_container(
            droplet_ip, container_name, image_name, env_list, container_port, host_port, do_token
        )
        if result.get('error'):
            raise Exception(f"Start failed: {result['error']}")
        stream(f'   {droplet_ip} - {container_name} started.')
        
        # Health check (agent does: log parsing + TCP ping)
        status = await agent_client.health(droplet_ip, container_name, do_token)
        
        if status.get('status') == 'healthy':
            stream(f'deployed to server {droplet_ip}.')
            await containers.upsert(db, {
                'container_name': container_name, 'droplet_id': droplet_id,
                'deployment_id': deployment_id, 'status': 'running',
                'health_status': 'healthy', 'last_checked': _now_iso(),
            })
            return {'status': 'success', 'error': None}
        else:
            error = status.get('reason', 'health check failed')
            stream(f'failed to deploy to server {droplet_ip}: {error}')
            await containers.upsert(db, {
                'container_name': container_name, 'droplet_id': droplet_id,
                'deployment_id': deployment_id, 'status': 'failed',
                'health_status': 'unhealthy', 'error': error, 'last_checked': _now_iso(),
            })
            return {'status': 'failed', 'error': error}
    
    except Exception as e:
        error = str(e)
        stream(f'failed to deploy to server {droplet_ip}: {error}')
        await containers.upsert(db, {
            'container_name': container_name, 'droplet_id': droplet_id,
            'deployment_id': deployment_id, 'status': 'failed',
            'health_status': 'unhealthy', 'error': error, 'last_checked': _now_iso(),
        })
        return {'status': 'failed', 'error': error}


# =============================================================================
# Clear Old Container (matches pseudo code)
# =============================================================================

async def clear_old_container_on_droplet(droplet_ip: str, container_name: str, do_token: str) -> Dict[str, Any]:
    """Remove container from single droplet (Docker only, no DB)."""
    return await agent_client.remove_container(droplet_ip, container_name, do_token)


# =============================================================================
# Configure Nginx (matches pseudo code)
# =============================================================================

async def configure_nginx(droplet_ip: str, private_ips: List[str], host_port: int, 
                          domain: str, do_token: str) -> Dict[str, Any]:
    """Configure nginx on droplet."""
    return await agent_client.configure_nginx(droplet_ip, private_ips, host_port, domain, do_token)


# =============================================================================
# Main Deploy Function (matches pseudo code)
# =============================================================================

async def deploy(
    db, user_id: str, project_name: str, service_name: str, service_description: str,
    service_type: str, image: bytes, image_name: str, env_variables: List[str], env: str,
    do_token: str, cf_token: str, existing_droplet_ids: List[str] = None,
    new_droplets_nb: int = 0, new_droplets_region: str = 'lon1',
    new_droplets_size: str = 's-1vcpu-1gb', new_droplets_snapshot_id: str = None,
) -> AsyncIterator[str]:
    """
    Main deployment orchestration - follows pseudo code exactly.
    """
    deployment_id = None
    lock_id = None
    service_id = None
    stream = StreamContext()
    
    try:
        existing_droplet_ids = existing_droplet_ids or []
        if not existing_droplet_ids and new_droplets_nb == 0:
            raise Exception("No droplets specified")
        
        # Provision new droplets if needed
        new_droplets = []
        if new_droplets_nb > 0:
            stream(f'Provision {new_droplets_nb} new droplets in parallel, can take 1 minute...')
            yield sse_log(stream._logs[-1])
            from .provision import create_droplet
            tasks = [create_droplet(db, user_id, new_droplets_snapshot_id, 
                                   new_droplets_region, new_droplets_size, do_token)
                    for _ in range(new_droplets_nb)]
            new_droplets = await asyncio.gather(*tasks)
            stream(f'{new_droplets_nb} created.')
            yield sse_log(stream._logs[-1])
        
        # Create project if needed
        stream('creating project if needed...')
        yield sse_log(stream._logs[-1])
        project = await projects.get_by_name(db, user_id, project_name)
        if not project:
            project = await projects.create(db, {'workspace_id': user_id, 'name': project_name})
        stream('project handled.')
        yield sse_log(stream._logs[-1])
        
        # Create service if needed
        stream('creating service if needed...')
        yield sse_log(stream._logs[-1])
        service = await services.get_by_name(db, project['id'], service_name)
        if not service:
            service = await services.create(db, {
                'project_id': project['id'], 'name': service_name,
                'description': service_description, 'service_type': service_type,
            })
        service_id = service['id']
        stream('service handled.')
        yield sse_log(stream._logs[-1])
        
        # Acquire lock
        lock_id = await acquire_deploy_lock(service_id, env, timeout=600, holder=user_id)
        if not lock_id:
            raise Exception('Deployment already in progress')
        
        # Get target IPs
        stream('finding target ips...')
        yield sse_log(stream._logs[-1])
        existing_infos = [await droplets.get(db, did) for did in existing_droplet_ids]
        existing_infos = [d for d in existing_infos if d and d.get('ip')]
        
        all_droplets = existing_infos + [d for d in new_droplets if d and not d.get('error')]
        
        if not all_droplets:
            raise Exception("No valid droplets available")
        
        ids = [d['id'] for d in all_droplets]
        ips = [d['ip'] for d in all_droplets]
        private_ips = [d.get('private_ip') or d['ip'] for d in all_droplets]
        stream(f'target ips will be: {ips}')
        yield sse_log(stream._logs[-1])
        
        # Find version
        stream('finding version...')
        yield sse_log(stream._logs[-1])
        last_deployment = await deployments.get_latest(db, service_id, env, status='success')
        last_version = last_deployment['version'] if last_deployment else 0
        version = last_version + 1
        stream(f'new version will be v{version}.')
        yield sse_log(stream._logs[-1])
        
        # Container/image names
        last_container_name = get_container_name(user_id, project_name, service_name, env, last_version) if last_version > 0 else None
        container_name = get_container_name(user_id, project_name, service_name, env, version)
        final_image_name = image_name or get_image_name(user_id, project_name, service_name, env, version)
        host_port = get_host_port(user_id, project_name, service_name, env, version, service_type)
        container_port = get_container_port(service_type)
        stream(f'the container will be {container_name} and the image {final_image_name}.')
        yield sse_log(stream._logs[-1])
        
        # Parse env variables and inject stateful URLs
        env_dict = parse_env_variables(env_variables)
        if service_type in ('webservice', 'worker', 'schedule'):
            stateful_urls, warnings = await get_stateful_urls(db, project['id'], env, ids[0] if ids else None)
            for w in warnings:
                stream(f'Warning: {w}')
                yield sse_log(stream._logs[-1], 'warning')
            if stateful_urls:
                stream(f'auto-injected: {list(stateful_urls.keys())}')
                yield sse_log(stream._logs[-1])
                env_dict = {**stateful_urls, **env_dict}
        
        # Save deployment
        stream('saving deployment details in the database...')
        yield sse_log(stream._logs[-1])
        deployment = await deployments.create(db, {
            'service_id': service_id, 'version': version, 'env': env,
            'image_name': final_image_name, 'env_variables': env_dict, 'droplet_ids': ids,
            'is_rollback': image is None and image_name is not None,
            'status': 'pending', 'triggered_by': user_id, 'triggered_at': _now_iso(),
        })
        deployment_id = deployment['id']
        
        # Save container records
        for did in ids:
            await containers.upsert(db, {
                'container_name': container_name, 'droplet_id': did,
                'deployment_id': deployment_id, 'status': 'to be deployed', 'last_checked': _now_iso(),
            })
        stream('database ready')
        yield sse_log(stream._logs[-1])
        
        # Stateful: clean old containers BEFORE (expect downtime)
        if service_type not in ('webservice', 'worker', 'schedule') and last_version > 0:
            stream('cleaning the old containers, expect some downtime...')
            yield sse_log(stream._logs[-1])
            cleanup_results = await asyncio.gather(
                *[clear_old_container_on_droplet(ip, last_container_name, do_token) for ip in ips],
                return_exceptions=True
            )
            any_error = next((r for r in cleanup_results if isinstance(r, Exception) or (isinstance(r, dict) and r.get('error'))), None)
            if any_error:
                stream(f'could not clean all old containers: {any_error}.')
                yield sse_log(stream._logs[-1], 'error')
                raise Exception(f'could not clean all old containers: {any_error}')
            stream('old containers cleaned.')
            yield sse_log(stream._logs[-1])
        
        # Deploy in parallel
        stream('deploying in parallel...')
        yield sse_log(stream._logs[-1])
        deploy_tasks = [
            deploy_to(db, d['id'], d['ip'], deployment_id, container_name, final_image_name,
                     image, env_dict, container_port, host_port, do_token, stream)
            for d in all_droplets
        ]
        statuses = await asyncio.gather(*deploy_tasks)
        stream('deployment done.')
        yield sse_log(stream._logs[-1])
        
        # Check status
        stream('checking status...')
        yield sse_log(stream._logs[-1])
        success_count = sum(1 for s in statuses if s.get('status') == 'success')
        
        if success_count == len(ips):
            # All success
            stream('all containers are healthy.')
            yield sse_log(stream._logs[-1])
            
            if service_type == 'webservice':
                stream('switching the domain to point to the new containers (via nginx)...')
                yield sse_log(stream._logs[-1])
                domain = get_domain_name(user_id, project_name, service_name, env)
                nginx_results = await asyncio.gather(
                    *[configure_nginx(ip, private_ips, host_port, domain, do_token) for ip in ips],
                    return_exceptions=True
                )
                any_error = next((r for r in nginx_results if isinstance(r, Exception) or (isinstance(r, dict) and r.get('error'))), None)
                if any_error:
                    stream(f'domain switch failed: {any_error}')
                    yield sse_log(stream._logs[-1], 'error')
                    await deployments.update(db, deployment_id, {'status': 'switch_failed', 'error': str(any_error), 'log': stream.flush()})
                else:
                    stream('domain switched - new version is LIVE!')
                    yield sse_log(stream._logs[-1])
                    # Update Cloudflare (background)
                    from .dns import setup_multi_server
                    asyncio.create_task(setup_multi_server(cf_token, domain, ips))
            
            # Clean old containers (stateless)
            if service_type in ('webservice', 'worker', 'schedule') and last_version > 0:
                stream('cleaning the old containers...')
                yield sse_log(stream._logs[-1])
                cleanup_results = await asyncio.gather(
                    *[clear_old_container_on_droplet(ip, last_container_name, do_token) for ip in ips],
                    return_exceptions=True
                )
                any_error = next((r for r in cleanup_results if isinstance(r, Exception) or (isinstance(r, dict) and r.get('error'))), None)
                if any_error:
                    stream(f'could not clean all old containers: {any_error}.')
                    yield sse_log(stream._logs[-1], 'warning')
                else:
                    stream('old containers cleaned.')
                    yield sse_log(stream._logs[-1])
            
            await deployments.update(db, deployment_id, {'status': 'success', 'log': stream.flush()})
            stream('service deployed to all servers.')
            yield sse_log(stream._logs[-1])
            yield sse_complete(True, deployment_id)
            
        elif success_count == 0:
            # All failed
            first_error = next((s.get('error') for s in statuses if s.get('error')), 'All failed')
            await deployments.update(db, deployment_id, {'status': 'failed', 'error': first_error, 'log': stream.flush()})
            stream(f'deployment failed on all servers, with error such as {first_error}.')
            yield sse_log(stream._logs[-1], 'error')
            yield sse_complete(False, deployment_id, first_error)
            
        else:
            # Partial
            first_error = next((s.get('error') for s in statuses if s.get('error')), 'Partial failure')
            await deployments.update(db, deployment_id, {'status': 'partial', 'error': first_error, 'log': stream.flush()})
            stream(f'deployment failed on some servers, with error such as {first_error}.')
            yield sse_log(stream._logs[-1], 'warning')
            yield sse_complete(False, deployment_id, first_error)
    
    except Exception as e:
        error = str(e)
        stream(f'Error while deploying: {error}')
        yield sse_log(stream._logs[-1], 'error')
        if deployment_id:
            await deployments.update(db, deployment_id, {'status': 'failed', 'error': error, 'log': stream.flush()})
        yield sse_complete(False, deployment_id or '', error)
    
    finally:
        if lock_id and service_id:
            await release_deploy_lock(service_id, env, lock_id)


# =============================================================================
# Rollback (matches pseudo code)
# =============================================================================

async def rollback(
    db, user_id: str, service_id: str, target_version: int = None, env: str = 'prod',
    do_token: str = None, cf_token: str = None,
) -> AsyncIterator[str]:
    """Rollback to a previous version."""
    stream = StreamContext()
    
    try:
        stream('fetching service info...')
        yield sse_log(stream._logs[-1])
        service = await services.get(db, service_id)
        project = await projects.get(db, service['project_id'])
        stream(f'rolling back {project["name"]}/{service["name"]}')
        yield sse_log(stream._logs[-1])
        
        # Find current version
        stream('finding current version...')
        yield sse_log(stream._logs[-1])
        current = await deployments.get_latest(db, service_id, env, status='success')
        if not current:
            raise Exception('No successful deployment to rollback from')
        
        current_version = current['version']
        current_ids = current.get('droplet_ids', [])
        if isinstance(current_ids, str):
            current_ids = json.loads(current_ids)
        stream(f'current version is v{current_version} deployed on {len(current_ids)} servers.')
        yield sse_log(stream._logs[-1])
        
        # Find target version
        stream("finding target version deployment's details...")
        yield sse_log(stream._logs[-1])
        if target_version is None:
            target = await deployments.get_previous(db, service_id, env, current_version, status='success')
        else:
            target = await deployments.get_by_version(db, service_id, env, target_version)
        
        if not target:
            raise Exception('No previous version to rollback to')
        
        target_version = target['version']
        target_image_name = target['image_name']
        target_env_variables = target.get('env_variables', {})
        if isinstance(target_env_variables, str):
            target_env_variables = json.loads(target_env_variables)
        
        stream(f'will rollback to v{target_version} - deployed by {target.get("triggered_by")} on {target.get("triggered_at")}.')
        yield sse_log(stream._logs[-1])
        
        # Call deploy with image=None, image_name=target_image_name
        async for event in deploy(
            db, user_id, project['name'], service['name'], None, service['service_type'],
            image=None, image_name=target_image_name,
            env_variables=[f"{k}={v}" for k, v in target_env_variables.items()],
            env=env, do_token=do_token, cf_token=cf_token,
            existing_droplet_ids=current_ids,
        ):
            yield event
    
    except Exception as e:
        stream(f'Error: {e}')
        yield sse_log(stream._logs[-1], 'error')
        yield sse_complete(False, '', str(e))


# =============================================================================
# Scale (matches pseudo code)
# =============================================================================

async def scale(
    db, user_id: str, service_id: str, env: str, target_count: int,
    do_token: str, cf_token: str, region: str = 'lon1', size: str = 's-1vcpu-1gb',
    snapshot_id: str = None,
) -> AsyncIterator[str]:
    """Scale service to target_count droplets."""
    stream = StreamContext()
    
    try:
        service = await services.get(db, service_id)
        project = await projects.get(db, service['project_id'])
        
        current = await deployments.get_latest(db, service_id, env, status='success')
        if not current:
            raise Exception('No successful deployment to scale')
        
        current_ids = current.get('droplet_ids', [])
        if isinstance(current_ids, str):
            current_ids = json.loads(current_ids)
        current_count = len(current_ids)
        
        stream(f'scaling {project["name"]}/{service["name"]} from {current_count} to {target_count} droplets')
        yield sse_log(stream._logs[-1])
        
        if target_count == current_count:
            stream('already at target count, nothing to do.')
            yield sse_log(stream._logs[-1])
            yield sse_complete(True, current['id'])
            return
        
        if target_count > current_count:
            # SCALE UP
            new_count = target_count - current_count
            stream(f'scaling UP: adding {new_count} droplets')
            yield sse_log(stream._logs[-1])
            
            env_vars = current.get('env_variables', {})
            if isinstance(env_vars, str):
                env_vars = json.loads(env_vars)
            
            async for event in deploy(
                db, user_id, project['name'], service['name'], None, service['service_type'],
                image=None, image_name=current['image_name'],
                env_variables=[f"{k}={v}" for k, v in env_vars.items()],
                env=env, do_token=do_token, cf_token=cf_token,
                existing_droplet_ids=current_ids, new_droplets_nb=new_count,
                new_droplets_region=region, new_droplets_size=size, new_droplets_snapshot_id=snapshot_id,
            ):
                yield event
        
        else:
            # SCALE DOWN - LIFO
            remove_count = current_count - target_count
            stream(f'scaling DOWN: removing {remove_count} droplets')
            yield sse_log(stream._logs[-1])
            
            keep_ids = current_ids[:target_count]
            remove_ids = current_ids[target_count:]
            
            remove_infos = [await droplets.get(db, did) for did in remove_ids]
            remove_ips = [d['ip'] for d in remove_infos if d and d.get('ip')]
            
            container_name = get_container_name(user_id, project['name'], service['name'], env, current['version'])
            
            # Stop containers
            stream('stopping containers on removed droplets...')
            yield sse_log(stream._logs[-1])
            await asyncio.gather(
                *[clear_old_container_on_droplet(ip, container_name, do_token) for ip in remove_ips],
                return_exceptions=True
            )
            
            # Update deployment
            stream('updating deployment record...')
            yield sse_log(stream._logs[-1])
            await deployments.update(db, current['id'], {'droplet_ids': keep_ids})
            
            # Delete container records
            for did in remove_ids:
                await containers.delete_by_droplet_and_name(db, did, container_name)
            
            # Update nginx (webservice only)
            if service['service_type'] == 'webservice':
                stream('updating nginx on remaining droplets...')
                yield sse_log(stream._logs[-1])
                keep_infos = [await droplets.get(db, did) for did in keep_ids]
                keep_ips = [d['ip'] for d in keep_infos if d and d.get('ip')]
                keep_private_ips = [d.get('private_ip') or d['ip'] for d in keep_infos if d and d.get('ip')]
                
                host_port = get_host_port(user_id, project['name'], service['name'], env, current['version'], service['service_type'])
                domain = get_domain_name(user_id, project['name'], service['name'], env)
                
                await asyncio.gather(
                    *[configure_nginx(ip, keep_private_ips, host_port, domain, do_token) for ip in keep_ips],
                    return_exceptions=True
                )
            
            stream(f'scaled down to {target_count} droplets.')
            yield sse_log(stream._logs[-1])
            yield sse_complete(True, current['id'])
    
    except Exception as e:
        stream(f'Error: {e}')
        yield sse_log(stream._logs[-1], 'error')
        yield sse_complete(False, '', str(e))


# =============================================================================
# Delete Operations (match pseudo code)
# =============================================================================

async def delete_droplet(db, user_id: str, droplet_id: str, do_token: str, cf_token: str) -> AsyncIterator[str]:
    """Delete a droplet - always forceful."""
    stream = StreamContext()
    
    try:
        droplet = await droplets.get(db, droplet_id)
        if not droplet:
            raise Exception('Droplet not found')
        
        stream(f'deleting droplet {droplet["name"]} ({droplet.get("ip")})...')
        yield sse_log(stream._logs[-1])
        
        droplet_containers = await containers.list_for_droplet(db, droplet_id)
        
        if droplet_containers:
            stream(f'{len(droplet_containers)} containers will be destroyed.')
            yield sse_log(stream._logs[-1])
            
            affected_deps = set(c['deployment_id'] for c in droplet_containers if c.get('deployment_id'))
            
            for dep_id in affected_deps:
                dep = await deployments.get(db, dep_id)
                if not dep:
                    continue
                
                service = await services.get(db, dep['service_id'])
                if not service or service['service_type'] != 'webservice':
                    continue
                
                project = await projects.get(db, service['project_id'])
                domain = get_domain_name(user_id, project['name'], service['name'], dep['env'])
                
                dep_ids = dep.get('droplet_ids', [])
                if isinstance(dep_ids, str):
                    dep_ids = json.loads(dep_ids)
                remaining_ids = [d for d in dep_ids if d != droplet_id]
                
                if not remaining_ids:
                    stream(f'  no droplets remain for {domain}, removing DNS...')
                    yield sse_log(stream._logs[-1])
                    from .dns import remove_domain
                    await remove_domain(cf_token, domain)
                    continue
                
                # Update nginx on remaining
                remaining_infos = [await droplets.get(db, did) for did in remaining_ids]
                remaining_ips = [d['ip'] for d in remaining_infos if d]
                remaining_private = [d.get('private_ip') or d['ip'] for d in remaining_infos if d]
                host_port = get_host_port(user_id, project['name'], service['name'], dep['env'], dep['version'], service['service_type'])
                
                stream(f'  updating nginx on {len(remaining_ids)} droplets...')
                yield sse_log(stream._logs[-1])
                await asyncio.gather(
                    *[configure_nginx(ip, remaining_private, host_port, domain, do_token) for ip in remaining_ips],
                    return_exceptions=True
                )
                
                # Update DNS
                stream(f'  updating DNS for {domain}...')
                yield sse_log(stream._logs[-1])
                from .dns import setup_multi_server
                await setup_multi_server(cf_token, domain, remaining_ips)
            
            await containers.delete_by_droplet(db, droplet_id)
        
        stream('deleting from DigitalOcean...')
        yield sse_log(stream._logs[-1])
        from backend.cloud import AsyncDOClient
        async with AsyncDOClient(api_token=do_token) as client:
            await client.delete_droplet(droplet['do_droplet_id'], force=True)
        
        await droplets.delete(db, droplet_id)
        stream('droplet deleted.')
        yield sse_log(stream._logs[-1])
        yield sse_complete(True, droplet_id)
    
    except Exception as e:
        yield sse_log(f'Error: {e}', 'error')
        yield sse_complete(False, '', str(e))


async def delete_service(db, user_id: str, service_id: str, env: str = None, 
                         do_token: str = None, cf_token: str = None) -> AsyncIterator[str]:
    """Delete a service (all envs or specific env)."""
    stream = StreamContext()
    
    try:
        service = await services.get(db, service_id)
        if not service:
            raise Exception('Service not found')
        
        project = await projects.get(db, service['project_id'])
        
        stream(f'deleting service {project["name"]}/{service["name"]}' + (f' ({env})' if env else ' (all envs)'))
        yield sse_log(stream._logs[-1])
        
        service_deps = await deployments.list_for_service(db, service_id, env=env)
        
        if not service_deps:
            stream('no deployments found.')
            yield sse_log(stream._logs[-1])
            if not env:
                await services.delete(db, service_id)
                stream('service deleted.')
                yield sse_log(stream._logs[-1])
            yield sse_complete(True, service_id)
            return
        
        # Collect containers to stop
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
        
        # Stop containers
        stream(f'stopping {len(to_remove)} containers...')
        yield sse_log(stream._logs[-1])
        await asyncio.gather(
            *[clear_old_container_on_droplet(ip, cn, do_token) for ip, cn in to_remove],
            return_exceptions=True
        )
        
        # Remove DNS (webservice only)
        if service['service_type'] == 'webservice':
            envs_used = set(dep['env'] for dep in service_deps)
            domains = [get_domain_name(user_id, project['name'], service['name'], e) for e in envs_used]
            stream(f'removing DNS: {domains}')
            yield sse_log(stream._logs[-1])
            from .dns import remove_domain
            await asyncio.gather(*[remove_domain(cf_token, d) for d in domains], return_exceptions=True)
        
        # Clean DB
        await containers.delete_by_service(db, service_id, env=env)
        await deployments.delete_by_service(db, service_id, env=env)
        
        if not env:
            await services.delete(db, service_id)
            stream('service deleted.')
        else:
            stream(f'env {env} deleted.')
        yield sse_log(stream._logs[-1])
        yield sse_complete(True, service_id)
    
    except Exception as e:
        yield sse_log(f'Error: {e}', 'error')
        yield sse_complete(False, '', str(e))


async def delete_project(db, user_id: str, project_id: str, do_token: str, cf_token: str) -> AsyncIterator[str]:
    """Delete project and all services."""
    stream = StreamContext()
    
    try:
        project = await projects.get(db, project_id)
        if not project:
            raise Exception('Project not found')
        
        stream(f'deleting project {project["name"]}...')
        yield sse_log(stream._logs[-1])
        
        project_services = await services.list_for_project(db, project_id)
        
        for svc in project_services:
            async for event in delete_service(db, user_id, svc['id'], env=None, do_token=do_token, cf_token=cf_token):
                yield event
        
        await projects.delete(db, project_id)
        stream('project deleted.')
        yield sse_log(stream._logs[-1])
        yield sse_complete(True, project_id)
    
    except Exception as e:
        yield sse_log(f'Error: {e}', 'error')
        yield sse_complete(False, '', str(e))
