"""
Stateful service URL injection with dependency warnings.
"""

import json
from typing import Dict, List, Tuple, Optional

from .stores import services, deployments, droplets
from .naming import get_container_port


def build_url(service_type: str, host: str, port: int, service_name: str) -> str:
    """Build connection URL per service type."""
    templates = {
        'redis': 'redis://{host}:{port}/0',
        'postgres': 'postgresql://postgres:postgres@{host}:{port}/{name}',
        'mysql': 'mysql://root:root@{host}:{port}/{name}',
        'mongodb': 'mongodb://{host}:{port}/{name}',
    }
    template = templates.get(service_type, '{type}://{host}:{port}')
    return template.format(host=host, port=port, name=service_name, type=service_type)


def get_env_var_name(service_type: str, service_name: str) -> str:
    """redis, redis -> REDIS_URL; redis, cache -> REDIS_CACHE_URL"""
    base = {'redis': 'REDIS', 'postgres': 'DATABASE', 'mysql': 'DATABASE', 'mongodb': 'MONGODB'}.get(service_type, service_type.upper())
    
    if service_name.lower() == service_type.lower():
        return f'{base}_URL'
    
    name_lower = service_name.lower()
    type_lower = service_type.lower()
    
    if name_lower.startswith(type_lower + '-') or name_lower.startswith(type_lower + '_'):
        suffix = service_name[len(service_type) + 1:]
    else:
        suffix = service_name
    
    return f"{base}_{suffix.upper().replace('-', '_')}_URL"


async def get_stateful_urls(db, project_id: str, env: str, target_droplet_id: Optional[str] = None) -> Tuple[Dict[str, str], List[str]]:
    """Get connection URLs for all stateful services. Returns (urls, warnings)."""
    urls = {}
    warnings = []
    
    project_services = await services.list_for_project(db, project_id)
    stateful_types = ('redis', 'postgres', 'mysql', 'mongodb')
    
    for svc in project_services:
        svc_type = svc.get('service_type', '').lower()
        if svc_type not in stateful_types:
            continue
        
        svc_name = svc['name']
        env_var = get_env_var_name(svc_type, svc_name)
        
        dep = await deployments.get_latest(db, svc['id'], env, status='success')
        if not dep:
            warnings.append(f"{svc_name} ({svc_type}) not deployed - {env_var} not injected")
            continue
        
        droplet_ids = dep.get('droplet_ids', [])
        if isinstance(droplet_ids, str):
            droplet_ids = json.loads(droplet_ids)
        
        if not droplet_ids:
            warnings.append(f"{svc_name} ({svc_type}) has no droplets - {env_var} not injected")
            continue
        
        droplet = await droplets.get(db, droplet_ids[0])
        if not droplet:
            warnings.append(f"{svc_name} ({svc_type}) droplet not found - {env_var} not injected")
            continue
        
        if target_droplet_id and droplet['id'] == target_droplet_id:
            host = 'localhost'
        else:
            host = droplet.get('private_ip') or droplet.get('ip') or 'localhost'
        
        port = get_container_port(svc_type)
        url = build_url(svc_type, host, port, svc_name)
        urls[env_var] = url
    
    return urls, warnings
