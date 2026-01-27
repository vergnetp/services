"""
Naming conventions for droplets, containers, images, ports, domains.
"""

import re
import hashlib
import random
from typing import Dict, List, Tuple


ADJECTIVES = ["swift", "bright", "calm", "bold", "keen", "wise", "fair", "warm", "cool", "fresh"]
ANIMALS = ["falcon", "tiger", "eagle", "wolf", "hawk", "lion", "bear", "fox", "elk", "owl"]


def create_droplet_name() -> str:
    """Generate random droplet name: adjective-animal-NNN"""
    adj = random.choice(ADJECTIVES)
    animal = random.choice(ANIMALS)
    num = random.randint(100, 999)
    return f"{adj}-{animal}-{num}"


def create_vpc_name(user_id: str, region: str) -> str:
    """VPC name: {user6}_{region}"""
    user6 = user_id[:6] if len(user_id) >= 6 else user_id
    return f"{user6}_{region}"


def get_domain_name(user_id: str, project: str, service: str, env: str) -> str:
    """Domain: {user6}-{project}-{service}-{env}.digitalpixo.com"""
    user6 = user_id[:6] if len(user_id) >= 6 else user_id
    return f"{sanitize_name(user6)}-{sanitize_name(project)}-{sanitize_name(service)}-{sanitize_name(env)}.digitalpixo.com"


def get_container_name(user_id: str, project: str, service: str, env: str, version: int) -> str:
    """Container: {user6}_{project}_{service}_{env}_v{version}"""
    user6 = user_id[:6] if len(user_id) >= 6 else user_id
    return sanitize_container_name(f"{user6}_{project}_{service}_{env}_v{version}")


def get_image_name(user_id: str, project: str, service: str, env: str, version: int) -> str:
    """Image: {user6}-{project}-{service}-{env}-v{version}"""
    user6 = user_id[:6] if len(user_id) >= 6 else user_id
    return f"{sanitize_name(user6)}-{sanitize_name(project)}-{sanitize_name(service)}-{sanitize_name(env)}-v{version}"


def get_image_base_name(user_id: str, project: str, service: str, env: str) -> str:
    """Image base name without version (for cleanup)."""
    user6 = user_id[:6] if len(user_id) >= 6 else user_id
    return f"{sanitize_name(user6)}-{sanitize_name(project)}-{sanitize_name(service)}-{sanitize_name(env)}"


def get_container_port(service_type: str) -> int:
    """Fixed container ports per service type."""
    ports = {
        'webservice': 8000,
        'worker': 8000,
        'schedule': 8000,
        'redis': 6379,
        'postgres': 5432,
        'mysql': 3306,
        'mongodb': 27017,
    }
    return ports.get(service_type.lower(), 8000)


def get_host_port(user_id: str, project: str, service: str, env: str, version: int, service_type: str) -> int:
    """
    Host port allocation.
    - Stateful (redis, postgres, etc): fixed port based on hash (no version)
    - Stateless (webservice, worker): versioned port for blue-green
    """
    stateful_types = ('redis', 'postgres', 'mysql', 'mongodb')
    
    if service_type.lower() in stateful_types:
        key = f"{user_id}:{project}:{service}:{env}"
    else:
        key = f"{user_id}:{project}:{service}:{env}:v{version}"
    
    h = int(hashlib.md5(key.encode()).hexdigest(), 16)
    return 10000 + (h % 50000)  # Range: 10000-60000


def sanitize_name(name: str) -> str:
    """Sanitize for DNS/docker: lowercase, alphanumeric + hyphens."""
    name = name.lower()
    name = re.sub(r'[^a-z0-9-]', '-', name)
    name = re.sub(r'-+', '-', name)
    return name.strip('-')


def sanitize_container_name(name: str) -> str:
    """Sanitize for Docker container: lowercase, alphanumeric + underscores."""
    name = name.lower()
    name = re.sub(r'[^a-z0-9_]', '_', name)
    name = re.sub(r'_+', '_', name)
    return name.strip('_')


def parse_env_variables(env_list: List[str]) -> Dict[str, str]:
    """Parse ['KEY=value', ...] to {'KEY': 'value', ...}"""
    result = {}
    for item in env_list or []:
        if '=' in item:
            key, value = item.split('=', 1)
            result[key] = value
    return result
