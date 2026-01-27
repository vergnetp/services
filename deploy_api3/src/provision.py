"""
Droplet and snapshot provisioning.
"""

import asyncio
from typing import Optional, Dict, Any, List

from .stores import droplets, snapshots
from .naming import create_droplet_name, create_vpc_name


async def ensure_vpc(do_client, vpc_name: str, region: str) -> str:
    """Create VPC if it doesn't exist, return vpc_uuid."""
    existing_vpcs = await do_client.list_vpcs()
    
    for vpc in existing_vpcs:
        if vpc.get('name') == vpc_name and vpc.get('region') == region:
            return vpc['id']
    
    vpc = await do_client.create_vpc(name=vpc_name, region=region, ip_range="10.10.0.0/16")
    return vpc['id']


async def create_droplet(
    db,
    user_id: str,
    snapshot_id: str,
    region: str,
    size: str,
    do_token: str,
    name: str = None,
) -> Dict[str, Any]:
    """Create a new droplet in VPC."""
    from backend.cloud import AsyncDOClient
    
    async with AsyncDOClient(api_token=do_token) as client:
        vpc_name = create_vpc_name(user_id, region)
        vpc_uuid = await ensure_vpc(client, vpc_name, region)
        
        droplet_name = name or create_droplet_name()
        
        # Get snapshot DO ID
        snap = await snapshots.get(db, snapshot_id)
        if not snap:
            return {'error': f'Snapshot {snapshot_id} not found'}
        
        do_snapshot_id = snap.get('do_snapshot_id')
        
        # Create droplet
        result = await client.create_droplet(
            name=droplet_name,
            region=region,
            size=size,
            image=do_snapshot_id,
            vpc_uuid=vpc_uuid,
            tags=[f"user:{user_id}"],
        )
        
        # Wait for IP
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
            return {'error': 'Timeout waiting for droplet IP'}
        
        # Save to DB
        droplet = await droplets.create(db, {
            'workspace_id': user_id,
            'name': droplet_name,
            'do_droplet_id': str(do_droplet_id),
            'region': region,
            'size': size,
            'ip': ip,
            'private_ip': private_ip,
            'vpc_uuid': vpc_uuid,
            'snapshot_id': snapshot_id,
            'health_status': 'healthy',
        })
        
        return droplet


async def provision_droplets(
    db,
    user_id: str,
    do_token: str,
    count: int,
    region: str,
    size: str,
    snapshot_id: str,
) -> List[Dict[str, Any]]:
    """Provision multiple droplets in parallel."""
    tasks = [
        create_droplet(db, user_id, snapshot_id, region, size, do_token)
        for _ in range(count)
    ]
    return await asyncio.gather(*tasks)


async def create_snapshot_from_droplet(
    db,
    workspace_id: str,
    do_token: str,
    droplet_id: str,
    name: str,
    set_as_base: bool = False,
) -> Dict[str, Any]:
    """Create snapshot from existing droplet."""
    from backend.cloud import AsyncDOClient
    
    droplet = await droplets.get(db, droplet_id)
    if not droplet:
        return {'error': 'Droplet not found'}
    
    async with AsyncDOClient(api_token=do_token) as client:
        result = await client.create_snapshot(
            droplet_id=droplet['do_droplet_id'],
            name=name,
        )
        
        snapshot = await snapshots.create(db, {
            'workspace_id': workspace_id,
            'name': name,
            'do_snapshot_id': str(result['id']),
            'region': droplet['region'],
            'is_base': set_as_base,
        })
        
        if set_as_base:
            await snapshots.clear_base_flag(db, workspace_id, exclude_id=snapshot['id'])
        
        return snapshot


async def list_snapshots(db, workspace_id: str, region: str = None) -> List[Dict[str, Any]]:
    """List snapshots for workspace."""
    return await snapshots.list_for_workspace(db, workspace_id, region=region)


async def set_base_snapshot(db, snapshot_id: str) -> Dict[str, Any]:
    """Set a snapshot as the base snapshot."""
    snap = await snapshots.get(db, snapshot_id)
    if not snap:
        return {'error': 'Snapshot not found'}
    
    await snapshots.clear_base_flag(db, snap['workspace_id'], exclude_id=snapshot_id)
    return await snapshots.update(db, snapshot_id, {'is_base': True})


async def delete_snapshot(db, snapshot_id: str, do_token: str) -> Dict[str, Any]:
    """Delete a snapshot."""
    from backend.cloud import AsyncDOClient
    
    snap = await snapshots.get(db, snapshot_id)
    if not snap:
        return {'error': 'Snapshot not found'}
    
    async with AsyncDOClient(api_token=do_token) as client:
        await client.delete_snapshot(snap['do_snapshot_id'])
    
    await snapshots.delete(db, snapshot_id)
    return {'deleted': snapshot_id}
