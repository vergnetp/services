"""
Health monitoring & healing - matches pseudo code exactly.
Calls node agent via HTTP for health checks.
"""

import logging
from typing import Dict, Any
from datetime import datetime, timezone

from . import agent_client
from .stores import droplets, containers

logger = logging.getLogger(__name__)

MAX_CONTAINER_RESTARTS = 3
MAX_DROPLET_REBOOTS = 2


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# =============================================================================
# Main Health Check Loop (matches pseudo code)
# =============================================================================

async def check_health_all(db, do_token: str):
    """
    Main health check loop. Called by background worker.
    Checks ALL droplets (healthy, unreachable, problematic - all of them).
    """
    all_droplets = await droplets.list_active(db)
    
    for droplet in all_droplets:
        try:
            await check_droplet_health(db, droplet, do_token)
        except Exception as e:
            logger.error(f"Error checking droplet {droplet.get('name')}: {e}")


async def check_droplet_health(db, droplet: Dict[str, Any], do_token: str):
    """
    Check droplet reachability and all its containers.
    Triggers healing if needed.
    """
    ip = droplet.get('ip')
    if not ip:
        return
    
    # 1. Check if agent is reachable
    try:
        resp = await agent_client.ping(ip, do_token)
        agent_ok = resp.get('status') == 'ok'
    except Exception:
        agent_ok = False
    
    if not agent_ok:
        await handle_droplet_unreachable(db, droplet, do_token)
        return
    
    # 2. Agent OK - reset ALL failure state
    if droplet.get('failure_count', 0) > 0 or droplet.get('health_status') != 'healthy':
        await droplets.update(db, droplet['id'], {
            'health_status': 'healthy',
            'failure_count': 0,
            'problematic_reason': None,
            'flagged_at': None,
            'last_checked': _now_iso(),
        })
    
    # 3. Check all containers on this droplet
    droplet_containers = await containers.list_for_droplet(db, droplet['id'])
    
    for container in droplet_containers:
        await check_container_health(db, droplet, container, do_token)


async def check_container_health(db, droplet: Dict[str, Any], container: Dict[str, Any], do_token: str):
    """
    Check single container health via node agent.
    Agent returns: {'status': 'healthy|unhealthy|degraded', 'reason': '...', 'details': [...]}
    """
    ip = droplet.get('ip')
    container_name = container.get('container_name')
    
    try:
        # Call agent's /containers/{name}/status endpoint
        status = await agent_client.container_status(ip, container_name, do_token)
    except Exception:
        status = None
    
    if not status or status.get('error') == 'not_found':
        await mark_container_unhealthy(db, container, 'not_found')
        return
    
    state = status.get('state')
    health = status.get('health_status', 'none')
    
    if state != 'running':
        await mark_container_unhealthy(db, container, f'state:{state}')
        await heal_container(db, droplet, container, do_token)
        return
    
    if health == 'unhealthy':
        await mark_container_unhealthy(db, container, 'health_check_failed')
        await heal_container(db, droplet, container, do_token)
        return
    
    # Healthy - reset failure count
    if container.get('failure_count', 0) > 0 or container.get('health_status') != 'healthy':
        await containers.update(db, container['id'], {
            'health_status': 'healthy',
            'failure_count': 0,
            'last_healthy_at': _now_iso(),
            'last_checked': _now_iso(),
        })


async def mark_container_unhealthy(db, container: Dict[str, Any], reason: str):
    """Record container failure."""
    await containers.update(db, container['id'], {
        'health_status': 'unhealthy',
        'failure_count': container.get('failure_count', 0) + 1,
        'last_failure_at': _now_iso(),
        'last_failure_reason': reason,
        'last_checked': _now_iso(),
    })
    logger.warning(f"Container {container.get('container_name')} unhealthy: {reason}")


# =============================================================================
# Healing (matches pseudo code)
# =============================================================================

async def heal_container(db, droplet: Dict[str, Any], container: Dict[str, Any], do_token: str):
    """
    Attempt to restart unhealthy container.
    If too many failures, flag droplet as problematic.
    """
    if container.get('failure_count', 0) >= MAX_CONTAINER_RESTARTS:
        logger.warning(f"Container {container.get('container_name')} failed {container.get('failure_count')} times, flagging droplet")
        await flag_droplet_problematic(db, droplet, f"container {container.get('container_name')} keeps failing")
        return
    
    logger.info(f"Restarting container {container.get('container_name')} on {droplet.get('ip')}")
    
    try:
        await agent_client.restart_container(droplet.get('ip'), container.get('container_name'), do_token)
        await containers.update(db, container['id'], {'last_restart_at': _now_iso()})
    except Exception as e:
        logger.error(f"Failed to restart container: {e}")


async def handle_droplet_unreachable(db, droplet: Dict[str, Any], do_token: str):
    """
    Droplet agent not responding. Increment failure count, maybe reboot.
    """
    new_count = droplet.get('failure_count', 0) + 1
    
    await droplets.update(db, droplet['id'], {
        'health_status': 'unreachable',
        'failure_count': new_count,
        'last_failure_at': _now_iso(),
    })
    
    if new_count > MAX_DROPLET_REBOOTS:
        await flag_droplet_problematic(db, droplet, 'unreachable after reboots')
        return
    
    logger.warning(f"Droplet {droplet.get('name')} unreachable (attempt {new_count}), rebooting...")
    await heal_droplet(db, droplet, do_token)


async def heal_droplet(db, droplet: Dict[str, Any], do_token: str):
    """Reboot droplet via DigitalOcean API."""
    try:
        from backend.cloud import AsyncDOClient
        async with AsyncDOClient(api_token=do_token) as client:
            await client.reboot_droplet(droplet['do_droplet_id'])
        
        await droplets.update(db, droplet['id'], {'last_reboot_at': _now_iso()})
        logger.info(f"Reboot initiated for {droplet.get('name')}")
    except Exception as e:
        logger.error(f"Failed to reboot droplet: {e}")
        await flag_droplet_problematic(db, droplet, f'reboot failed: {e}')


async def flag_droplet_problematic(db, droplet: Dict[str, Any], reason: str):
    """Mark droplet as needing manual intervention."""
    await droplets.update(db, droplet['id'], {
        'health_status': 'problematic',
        'problematic_reason': reason,
        'flagged_at': _now_iso(),
    })
    logger.error(f"DROPLET FLAGGED: {droplet.get('name')} - {reason}")
    # TODO: send alert (email, slack, etc.)


# =============================================================================
# Dashboard Functions
# =============================================================================

async def get_health_overview(db) -> Dict[str, Any]:
    """Get health overview for dashboard."""
    all_droplets = await droplets.list_active(db)
    all_containers = await containers.list_active(db)
    
    droplet_stats = {'healthy': 0, 'unhealthy': 0, 'unreachable': 0, 'problematic': 0}
    container_stats = {'healthy': 0, 'unhealthy': 0, 'degraded': 0, 'unknown': 0}
    
    for d in all_droplets:
        status = d.get('health_status', 'unknown')
        if status in droplet_stats:
            droplet_stats[status] += 1
    
    for c in all_containers:
        status = c.get('health_status', 'unknown')
        if status in container_stats:
            container_stats[status] += 1
        else:
            container_stats['unknown'] += 1
    
    return {
        'droplets': droplet_stats,
        'containers': container_stats,
        'problematic_droplets': [d for d in all_droplets if d.get('health_status') == 'problematic'],
        'unhealthy_containers': [c for c in all_containers if c.get('health_status') == 'unhealthy'],
    }


async def clear_problematic_flag(db, droplet_id: str) -> Dict[str, Any]:
    """Clear problematic flag after manual intervention."""
    droplet = await droplets.get(db, droplet_id)
    if not droplet:
        return {'error': 'Droplet not found'}
    
    await droplets.update(db, droplet_id, {
        'health_status': 'healthy',
        'failure_count': 0,
        'problematic_reason': None,
        'flagged_at': None,
    })
    
    return {'status': 'cleared', 'droplet': droplet['name']}
