"""Droplet and snapshot provisioning."""

import asyncio
import json
from typing import Dict, Any, AsyncIterator

from shared_libs.backend.cloud import AsyncDOClient

from .stores import projects, services, deployments, droplets, containers, snapshots
from . import agent_client
from .naming import (
    get_domain_name, get_host_port
)
from .utils import  is_webservice
from .naming import create_droplet_name, create_vpc_name
from .sse_streaming import StreamContext, sse_complete, sse_log

async def _ensure_vpc(do_client, vpc_name: str, region: str) -> str:
    """Create VPC if not exists, return vpc_uuid."""
    existing = await do_client.list_vpcs()
    for vpc in existing:
        if vpc.get('name') == vpc_name and vpc.get('region') == region:
            return vpc['id']
    vpc = await do_client.create_vpc(name=vpc_name, region=region, ip_range="10.10.0.0/16")
    return vpc['id']


async def create_droplet(db, user_id: str, snapshot_id: str, region: str, size: str, do_token: str, name: str = None) -> Dict[str, Any]:
    """Create a new droplet in VPC."""    
    
    async with AsyncDOClient(api_token=do_token) as doClient:
        vpc_name = create_vpc_name(user_id, region)
        vpc_uuid = await _ensure_vpc(doClient, vpc_name, region)
        
        droplet_name = name or create_droplet_name()
        
        snap = await snapshots.get(db, snapshot_id)
        if not snap:
            return {'error': f'Snapshot {snapshot_id} not found'}
        
        result = await doClient.create_droplet(
            name=droplet_name, region=region, size=size,
            image=snap.get('do_snapshot_id'), vpc_uuid=vpc_uuid,
            tags=[f"user:{user_id}"],
        )
        
        do_droplet_id = result['id']
        ip = None
        private_ip = None
        
        for _ in range(30):
            await asyncio.sleep(2)
            info = await doClient.get_droplet(do_droplet_id)
            networks = info.get('networks', {})
            for net in networks.get('v4', []):
                if net.get('type') == 'public':
                    ip = net.get('ip_address')
                elif net.get('type') == 'private':
                    private_ip = net.get('ip_address')
            if ip:
                break
        
        if not ip:
            return {'error': 'Timeout waiting for IP'}
        
        droplet = await droplets.create(db, {
            'workspace_id': user_id, 'name': droplet_name,
            'do_droplet_id': str(do_droplet_id), 'region': region,
            'size': size, 'ip': ip, 'private_ip': private_ip,
            'vpc_uuid': vpc_uuid, 'snapshot_id': snapshot_id,
            'health_status': 'healthy',
        })
        
        return droplet


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
                if not service or not is_webservice(service.get('service_type','')):
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
                    *[agent_client.configure_nginx(ip, remaining_private, host_port, domain, do_token) for ip in remaining_ips],
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
        async with AsyncDOClient(api_token=do_token) as client:
            await client.delete_droplet(droplet['do_droplet_id'], force=True)
        
        await droplets.delete(db, droplet_id)
        stream('droplet deleted.')
        yield sse_log(stream._logs[-1])
        yield sse_complete(True, droplet_id)
    
    except Exception as e:
        yield sse_log(f'Error: {e}', 'error')
        yield sse_complete(False, '', str(e))

