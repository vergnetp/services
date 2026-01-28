"""Droplet and snapshot provisioning."""

import asyncio
from typing import Dict, Any, List

from .stores import droplets, snapshots
from .naming import create_droplet_name, create_vpc_name


async def ensure_vpc(do_client, vpc_name: str, region: str) -> str:
    """Create VPC if not exists, return vpc_uuid."""
    existing = await do_client.list_vpcs()
    for vpc in existing:
        if vpc.get('name') == vpc_name and vpc.get('region') == region:
            return vpc['id']
    vpc = await do_client.create_vpc(name=vpc_name, region=region, ip_range="10.10.0.0/16")
    return vpc['id']


async def create_droplet(db, user_id: str, snapshot_id: str, region: str, size: str, do_token: str, name: str = None) -> Dict[str, Any]:
    """Create a new droplet in VPC."""
    from backend.cloud import AsyncDOClient
    
    async with AsyncDOClient(api_token=do_token) as client:
        vpc_name = create_vpc_name(user_id, region)
        vpc_uuid = await ensure_vpc(client, vpc_name, region)
        
        droplet_name = name or create_droplet_name()
        
        snap = await snapshots.get(db, snapshot_id)
        if not snap:
            return {'error': f'Snapshot {snapshot_id} not found'}
        
        result = await client.create_droplet(
            name=droplet_name, region=region, size=size,
            image=snap.get('do_snapshot_id'), vpc_uuid=vpc_uuid,
            tags=[f"user:{user_id}"],
        )
        
        do_droplet_id = result['id']
        ip = None
        private_ip = None
        
        for _ in range(30):
            await asyncio.sleep(2)
            info = await client.get_droplet(do_droplet_id)
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
