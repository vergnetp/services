"""
scaling operations
"""

import json
import asyncio
from typing import AsyncIterator

from .stores import projects, services, deployments, droplets, containers
from . import agent_client
from .naming import (
    get_domain_name, get_container_name, get_host_port
)
from .service import deploy_service
from .utils import is_webservice
from .sse_streaming import StreamContext, sse_complete, sse_log


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
            
            async for event in deploy_service(
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
                *[agent_client.remove_container(ip, container_name, do_token) for ip in remove_ips],
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
            if is_webservice(service.get('service_type','')):
                stream('updating nginx on remaining droplets...')
                yield sse_log(stream._logs[-1])
                keep_infos = [await droplets.get(db, did) for did in keep_ids]
                keep_ips = [d['ip'] for d in keep_infos if d and d.get('ip')]
                keep_private_ips = [d.get('private_ip') or d['ip'] for d in keep_infos if d and d.get('ip')]
                
                host_port = get_host_port(user_id, project['name'], service['name'], env, current['version'], service['service_type'])
                domain = get_domain_name(user_id, project['name'], service['name'], env)
                
                await asyncio.gather(
                    *[agent_client.configure_nginx(ip, keep_private_ips, host_port, domain, do_token) for ip in keep_ips],
                    return_exceptions=True
                )
            
            stream(f'scaled down to {target_count} droplets.')
            yield sse_log(stream._logs[-1])
            yield sse_complete(True, current['id'])
    
    except Exception as e:
        stream(f'Error: {e}')
        yield sse_log(stream._logs[-1], 'error')
        yield sse_complete(False, '', str(e))

