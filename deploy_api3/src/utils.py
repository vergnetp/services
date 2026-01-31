"""
Utility functions.
"""

from typing import Dict, List
from datetime import datetime, timezone


# Tag used to identify droplets created by deploy_api
DEPLOY_API_TAG = 'deploy-api'


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_env_variables(env_list: List[str]) -> Dict[str, str]:
    """['KEY=value', ...] -> {'KEY': 'value', ...}"""
    result = {}
    for item in env_list or []:
        if '=' in item:
            key, value = item.split('=', 1)
            result[key] = value
    return result


def is_stateful(service_type: str) -> bool:
    """Everything that is not a webservice, worker or scheduled task is deemed stateful"""
    return service_type not in ('webservice', 'worker', 'schedule')


def is_webservice(service_type: str) -> bool:
    """Everything that is a webservice"""
    return service_type == 'webservice'


async def get_is_managed(db, snapshot_id: str) -> bool:
    """
    Check if a snapshot is in managed mode.
    
    Managed mode = snapshot was created with same DO token as deploy_api server.
    In managed mode, agents only listen on VPC IP for security.
    
    Args:
        db: Database connection
        snapshot_id: Snapshot ID to check
        
    Returns:
        True if managed mode, False otherwise
    """
    if not snapshot_id:
        return False
    
    from .stores import snapshots
    snap = await snapshots.get(db, snapshot_id)
    if not snap:
        return False
    
    return getattr(snap, 'is_managed', False)


async def get_agent_ip_for_droplet(db, droplet) -> str:
    """
    Get the IP to use for agent calls based on managed mode.
    
    In managed mode (same DO account), use public IP but agent is protected
    by firewall allowing only VPC + ADMIN_IPs.
    In customer mode (different DO account), agent listens on public IP.
    
    Args:
        db: Database connection
        droplet: Droplet entity or dict with ip, private_ip, and snapshot_id
    
    Returns:
        IP address to use for agent calls (always public IP)
    """
    # Always use public IP - firewall handles access control
    if isinstance(droplet, dict):
        return droplet.get('ip')
    else:
        return getattr(droplet, 'ip', None)


async def list_do_droplets_by_tag(do_token: str, tag: str = None) -> List[Dict]:
    """
    List droplets from DigitalOcean API filtered by tag.
    
    Args:
        do_token: DigitalOcean API token
        tag: Tag to filter by (defaults to DEPLOY_API_TAG)
        
    Returns:
        List of droplet dicts from DO API
    """
    from shared_libs.backend.cloud import AsyncDOClient
    
    tag = tag or DEPLOY_API_TAG
    
    async with AsyncDOClient(api_token=do_token) as client:
        # DO API supports filtering by tag
        droplets = await client.list_droplets(tag_name=tag)
        return [
            {
                'id': d.id,
                'name': d.name,
                'ip': d.ip,
                'private_ip': d.private_ip,
                'status': d.status,
                'region': d.region,
                'size': d.size_slug,
                'tags': d.tags,
                'created_at': d.created_at,
            }
            for d in droplets
        ]
