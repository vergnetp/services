# =============================================================================
# src/service.py
# =============================================================================
"""
Deployment orchestration - calls node agent via HTTP for all container operations.
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
    get_container_port, get_host_port
)
from .utils import now_iso, parse_env_variables, is_stateful, is_webservice
from .stateful import get_stateful_urls
from .locks import acquire_deploy_lock, release_deploy_lock
from .sse_streaming import StreamContext, sse_complete, sse_log


# =============================================================================
# Deploy to Single Droplet
# =============================================================================

@retry_with_backoff(max_retries=2, base_delay=5.0, exceptions=(ConnectionError, TimeoutError, OSError))
async def _deploy_to(
    db, droplet_id: str, droplet_ip: str, deployment_id: str, container_name: str,
    image_name: str,
    # Source options
    source_type: str,  # 'image', 'build', 'existing'
    image: bytes = None,
    git_repos: List[Dict] = None,
    source_zips: Dict[str, bytes] = None,
    dockerfile_content: str = None,
    # Container config
    env_variables: Dict[str, str] = None,
    container_port: int = None,
    host_port: int = None,
    do_token: str = None,
    stream: StreamContext = None,
) -> Dict[str, Any]:
    """Deploy container to a single droplet."""
    try:
        stream(f'deploying to server {droplet_ip}...')
        
        # Handle source based on type
        if source_type == 'image':
            stream(f'   {droplet_ip} - uploading image...')
            result = await agent_client.upload_image(droplet_ip, image, image_name, do_token)
            if result.get('error'):
                raise Exception(f"Upload failed: {result['error']}")
            stream(f'   {droplet_ip} - image uploaded.')
        
        elif source_type == 'build':
            stream(f'   {droplet_ip} - building image...')
            result = await agent_client.build_image(
                droplet_ip, image_name, do_token,
                git_repos=git_repos,
                source_zips=source_zips,
                dockerfile_content=dockerfile_content
            )
            if result.get('status') == 'failed':
                raise Exception(f"Build failed: {result.get('error')}")
            stream(f'   {droplet_ip} - image built.')
        
        elif source_type == 'existing':
            stream(f'   {droplet_ip} - using existing image...')
        
        # Start container
        stream(f'   {droplet_ip} - starting container...')
        env_list = [f"{k}={v}" for k, v in env_variables.items()]
        result = await agent_client.start_container(
            droplet_ip, container_name, image_name, env_list, container_port, host_port, do_token
        )
        if result.get('error'):
            raise Exception(f"Start failed: {result['error']}")
        stream(f'   {droplet_ip} - container started.')
        
        # Health check
        status = await agent_client.health(droplet_ip, container_name, do_token)
        
        if status.get('status') == 'healthy':
            stream(f'deployed to server {droplet_ip}.')
            await containers.upsert(db, {
                'container_name': container_name, 'droplet_id': droplet_id,
                'deployment_id': deployment_id, 'status': 'running',
                'health_status': 'healthy', 'last_checked': now_iso(),
            })
            return {'status': 'success', 'error': None}
        else:
            error = status.get('reason', 'health check failed')
            stream(f'failed to deploy to server {droplet_ip}: {error}')
            await containers.upsert(db, {
                'container_name': container_name, 'droplet_id': droplet_id,
                'deployment_id': deployment_id, 'status': 'failed',
                'health_status': 'unhealthy', 'error': error, 'last_checked': now_iso(),
            })
            return {'status': 'failed', 'error': error}
    
    except Exception as e:
        error = str(e)
        stream(f'failed to deploy to server {droplet_ip}: {error}')
        await containers.upsert(db, {
            'container_name': container_name, 'droplet_id': droplet_id,
            'deployment_id': deployment_id, 'status': 'failed',
            'health_status': 'unhealthy', 'error': error, 'last_checked': now_iso(),
        })
        return {'status': 'failed', 'error': error}


# =============================================================================
# Main Deploy Service
# =============================================================================

async def deploy_service(
    db, user_id: str, project_name: str, service_name: str, service_description: str,
    service_type: str, env_variables: List[str], env: str,
    do_token: str, cf_token: str,
    # Source options (pick one or combine):
    image: bytes = None,                      # Pre-built image tar
    image_name: str = None,                   # For rollback (image already on droplet)
    git_repos: List[Dict] = None,             # [{'url', 'branch'?, 'token'?}]
    source_zips: Dict[str, bytes] = None,     # {'name': bytes}
    dockerfile_content: str = None,           # Required if no Dockerfile in source
    # Droplet options:
    existing_droplet_ids: List[str] = None,
    new_droplets_nb: int = 0,
    new_droplets_region: str = 'lon1',
    new_droplets_size: str = 's-1vcpu-1gb',
    new_droplets_snapshot_id: str = None,
) -> AsyncIterator[str]:
    """
    Main deployment orchestration.
    
    Source options:
    - image: Pre-built Docker image as tar bytes
    - image_name only: Rollback (image already exists on droplet)
    - git_repos + dockerfile_content: Build from git on droplet
    - source_zips + dockerfile_content: Build from zips on droplet
    - git_repos + source_zips: Mix both (all extracted as siblings)
    """
    deployment_id = None
    lock_id = None
    service_id = None
    stream = StreamContext()
    
    try:
        existing_droplet_ids = existing_droplet_ids or []
        if not existing_droplet_ids and new_droplets_nb == 0:
            raise Exception("No droplets specified")
        
        # Determine source type
        if image:
            source_type = 'image'
        elif git_repos or source_zips:
            source_type = 'build'
        elif image_name:
            source_type = 'existing'
        else:
            raise Exception('No source provided: need image, git_repos, source_zips, or image_name')
        
        # Provision new droplets if needed
        new_droplets = []
        if new_droplets_nb > 0:
            stream(f'Provisioning {new_droplets_nb} new droplets...')
            yield sse_log(stream._logs[-1])
            from .droplet import create_droplet
            tasks = [create_droplet(db, user_id, new_droplets_snapshot_id, 
                                   new_droplets_region, new_droplets_size, do_token)
                    for _ in range(new_droplets_nb)]
            new_droplets = await asyncio.gather(*tasks)
            stream(f'{new_droplets_nb} droplets created.')
            yield sse_log(stream._logs[-1])
        
        # Create project if needed
        stream('Setting up project...')
        yield sse_log(stream._logs[-1])
        project = await projects.get_by_name(db, user_id, project_name)
        if not project:
            project = await projects.create(db, {'workspace_id': user_id, 'name': project_name})
        
        # Create service if needed
        stream('Setting up service...')
        yield sse_log(stream._logs[-1])
        service = await services.get_by_name(db, project['id'], service_name)
        if not service:
            service = await services.create(db, {
                'project_id': project['id'], 'name': service_name,
                'description': service_description, 'service_type': service_type,
            })
        service_id = service['id']
        
        # Acquire lock
        lock_id = await acquire_deploy_lock(service_id, env, timeout=600, holder=user_id)
        if not lock_id:
            raise Exception('Deployment already in progress')
        
        # Get target droplets
        stream('Finding target servers...')
        yield sse_log(stream._logs[-1])
        existing_infos = [await droplets.get(db, did) for did in existing_droplet_ids]
        existing_infos = [d for d in existing_infos if d and d.get('ip')]
        
        all_droplets = existing_infos + [d for d in new_droplets if d and not d.get('error')]
        
        if not all_droplets:
            raise Exception("No valid droplets available")
        
        ids = [d['id'] for d in all_droplets]
        ips = [d['ip'] for d in all_droplets]
        private_ips = [d.get('private_ip') or d['ip'] for d in all_droplets]
        stream(f'Target servers: {ips}')
        yield sse_log(stream._logs[-1])
        
        # Find version
        stream('Finding version...')
        yield sse_log(stream._logs[-1])
        last_deployment = await deployments.get_latest(db, service_id, env, status='success')
        last_version = last_deployment['version'] if last_deployment else 0
        version = last_version + 1
        stream(f'New version: v{version}')
        yield sse_log(stream._logs[-1])
        
        # Container/image names
        last_container_name = get_container_name(user_id, project_name, service_name, env, last_version) if last_version > 0 else None
        container_name = get_container_name(user_id, project_name, service_name, env, version)
        
        # Use provided image_name or generate one
        if not image_name:
            image_name = get_image_name(user_id, project_name, service_name, env, version)
        
        container_port = get_container_port(service_type)
        host_port = get_host_port(user_id, project_name, service_name, env, version, service_type)
        
        # Parse env variables
        env_dict = parse_env_variables(env_variables)
        
        # Inject stateful URLs if needed
        if not is_stateful(service_type):
            stream('Resolving stateful URLs...')
            yield sse_log(stream._logs[-1])
            stateful_urls, warnings = await get_stateful_urls(db, project['id'], env)
            env_dict.update(stateful_urls)
            for w in warnings:
                stream(f'  Warning: {w}')
                yield sse_log(stream._logs[-1])
        
        # Create deployment record
        deployment = await deployments.create(db, {
            'service_id': service_id, 'env': env, 'version': version,
            'image_name': image_name, 'container_name': container_name,
            'env_variables': json.dumps(env_dict),
            'droplet_ids': json.dumps(ids),
            'status': 'deploying', 'triggered_by': user_id, 'triggered_at': now_iso(),
        })
        deployment_id = deployment['id']
        
        # Deploy to all droplets
        stream(f'Deploying to {len(all_droplets)} servers...')
        yield sse_log(stream._logs[-1])
        
        tasks = [
            _deploy_to(
                db, d['id'], d['ip'], deployment_id, container_name, image_name,
                source_type=source_type,
                image=image,
                git_repos=git_repos,
                source_zips=source_zips,
                dockerfile_content=dockerfile_content,
                env_variables=env_dict,
                container_port=container_port,
                host_port=host_port,
                do_token=do_token,
                stream=stream,
            )
            for d in all_droplets
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for r in results:
            if isinstance(r, dict) and r.get('error'):
                yield sse_log(f"Deploy error: {r['error']}", 'warning')
            elif isinstance(r, Exception):
                yield sse_log(f"Deploy exception: {r}", 'error')
        
        statuses = [r if isinstance(r, dict) else {'status': 'failed', 'error': str(r)} for r in results]
        success_count = sum(1 for s in statuses if s.get('status') == 'success')
        
        # Handle old containers
        if last_container_name and success_count > 0:
            stream('Removing old containers...')
            yield sse_log(stream._logs[-1])
            await asyncio.gather(
                *[agent_client.remove_container(d['ip'], last_container_name, do_token) for d in all_droplets],
                return_exceptions=True
            )
        
        # Configure nginx for webservices
        if is_webservice(service_type) and success_count > 0:
            stream('Configuring nginx...')
            yield sse_log(stream._logs[-1])
            domain = get_domain_name(user_id, project_name, service_name, env)
            await asyncio.gather(
                *[agent_client.configure_nginx(d['ip'], private_ips, host_port, domain, do_token) for d in all_droplets],
                return_exceptions=True
            )
            
            # Setup DNS
            stream('Configuring DNS...')
            yield sse_log(stream._logs[-1])
            from .dns import setup_multi_server
            await setup_multi_server(cf_token, domain, ips)
        
        # Final status
        if success_count == len(all_droplets):
            await deployments.update(db, deployment_id, {'status': 'success', 'log': stream.flush()})
            stream(f'Deployment complete: v{version} on {success_count} servers.')
            yield sse_log(stream._logs[-1])
            yield sse_complete(True, deployment_id)
        
        elif success_count == 0:
            first_error = next((s.get('error') for s in statuses if s.get('error')), 'All failed')
            await deployments.update(db, deployment_id, {'status': 'failed', 'error': first_error, 'log': stream.flush()})
            stream(f'Deployment failed: {first_error}')
            yield sse_log(stream._logs[-1], 'error')
            yield sse_complete(False, deployment_id, first_error)
        
        else:
            first_error = next((s.get('error') for s in statuses if s.get('error')), 'Partial failure')
            await deployments.update(db, deployment_id, {'status': 'partial', 'error': first_error, 'log': stream.flush()})
            stream(f'Deployment partial: {success_count}/{len(all_droplets)} succeeded.')
            yield sse_log(stream._logs[-1], 'warning')
            yield sse_complete(False, deployment_id, first_error)
    
    except Exception as e:
        error = str(e)
        stream(f'Error: {error}')
        yield sse_log(stream._logs[-1], 'error')
        if deployment_id:
            await deployments.update(db, deployment_id, {'status': 'failed', 'error': error, 'log': stream.flush()})
        yield sse_complete(False, deployment_id or '', error)
    
    finally:
        if lock_id and service_id:
            await release_deploy_lock(service_id, env, lock_id)


# =============================================================================
# Rollback
# =============================================================================

async def rollback_service(
    db, user_id: str, service_id: str, target_version: int = None, env: str = 'prod',
    do_token: str = None, cf_token: str = None,
) -> AsyncIterator[str]:
    """Rollback to a previous version."""
    stream = StreamContext()
    
    try:
        stream('Fetching service info...')
        yield sse_log(stream._logs[-1])
        service = await services.get(db, service_id)
        project = await projects.get(db, service['project_id'])
        stream(f'Rolling back {project["name"]}/{service["name"]}')
        yield sse_log(stream._logs[-1])
        
        # Find current version
        current = await deployments.get_latest(db, service_id, env, status='success')
        if not current:
            raise Exception('No successful deployment to rollback from')
        
        current_version = current['version']
        current_ids = current.get('droplet_ids', [])
        if isinstance(current_ids, str):
            current_ids = json.loads(current_ids)
        stream(f'Current: v{current_version} on {len(current_ids)} servers.')
        yield sse_log(stream._logs[-1])
        
        # Find target version
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
        
        stream(f'Rolling back to v{target_version}')
        yield sse_log(stream._logs[-1])
        
        # Deploy with existing image
        async for event in deploy_service(
            db, user_id, project['name'], service['name'], None, service['service_type'],
            env_variables=[f"{k}={v}" for k, v in target_env_variables.items()],
            env=env, do_token=do_token, cf_token=cf_token,
            image_name=target_image_name,
            existing_droplet_ids=current_ids,
        ):
            yield event
    
    except Exception as e:
        stream(f'Error: {e}')
        yield sse_log(stream._logs[-1], 'error')
        yield sse_complete(False, '', str(e))


# =============================================================================
# Delete Service
# =============================================================================

async def delete_service(db, user_id: str, service_id: str, env: str = None, 
                         do_token: str = None, cf_token: str = None) -> AsyncIterator[str]:
    """Delete a service (all envs or specific env)."""
    stream = StreamContext()
    
    try:
        service = await services.get(db, service_id)
        if not service:
            raise Exception('Service not found')
        
        project = await projects.get(db, service['project_id'])
        
        stream(f'Deleting {project["name"]}/{service["name"]}' + (f' ({env})' if env else ' (all envs)'))
        yield sse_log(stream._logs[-1])
        
        service_deps = await deployments.list_for_service(db, service_id, env=env)
        
        if not service_deps:
            stream('No deployments found.')
            yield sse_log(stream._logs[-1])
            if not env:
                await services.delete(db, service_id)
                stream('Service deleted.')
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
        stream(f'Stopping {len(to_remove)} containers...')
        yield sse_log(stream._logs[-1])
        await asyncio.gather(
            *[agent_client.remove_container(ip, cn, do_token) for ip, cn in to_remove],
            return_exceptions=True
        )
        
        # Remove DNS (webservice only)
        if is_webservice(service.get('service_type', '')):
            envs_used = set(dep['env'] for dep in service_deps)
            domains = [get_domain_name(user_id, project['name'], service['name'], e) for e in envs_used]
            stream(f'Removing DNS: {domains}')
            yield sse_log(stream._logs[-1])
            from .dns import remove_domain
            await asyncio.gather(*[remove_domain(cf_token, d) for d in domains], return_exceptions=True)
        
        # Clean DB
        await containers.delete_by_service(db, service_id, env=env)
        await deployments.delete_by_service(db, service_id, env=env)
        
        if not env:
            await services.delete(db, service_id)
            stream('Service deleted.')
        else:
            stream(f'Environment {env} deleted.')
        yield sse_log(stream._logs[-1])
        yield sse_complete(True, service_id)
    
    except Exception as e:
        yield sse_log(f'Error: {e}', 'error')
        yield sse_complete(False, '', str(e))

