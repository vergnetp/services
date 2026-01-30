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
    
    In managed mode (same DO account), agent only listens on VPC IP.
    In customer mode (different DO account), agent listens on public IP.
    
    Args:
        db: Database connection
        droplet: Droplet entity or dict with ip, private_ip, and snapshot_id
    
    Returns:
        IP address to use for agent calls
    """
    # Get snapshot_id from droplet (handles both entity and dict)
    if isinstance(droplet, dict):
        snapshot_id = droplet.get('snapshot_id')
        private_ip = droplet.get('private_ip')
        public_ip = droplet.get('ip')
    else:
        snapshot_id = getattr(droplet, 'snapshot_id', None)
        private_ip = getattr(droplet, 'private_ip', None)
        public_ip = getattr(droplet, 'ip', None)
    
    is_managed = await get_is_managed(db, snapshot_id)
    
    if is_managed:
        # Use VPC IP (fallback to public if no private IP)
        return private_ip or public_ip
    else:
        # Use public IP
        return public_ip


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
