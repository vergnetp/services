"""
Naming conventions for droplets, containers, images, ports, domains.
"""

import re
import hashlib
import random
from typing import Dict, List

ADJECTIVES = ["swift", "bright", "calm", "bold", "keen", "wise", "fair", "warm", "cool", "fresh"]
ANIMALS = ["falcon", "tiger", "eagle", "wolf", "hawk", "lion", "bear", "fox", "elk", "owl"]

USER_LENGTH = 6

def create_droplet_name() -> str:
    """Auto-generate with adjective-animal."""
    adj = random.choice(ADJECTIVES)
    animal = random.choice(ANIMALS)    
    return f"{adj}-{animal}"

def get_snapshot_base_name():
    return f'base_snapshot'

def create_vpc_name(user_id: str, region: str) -> str:
    """VPC name unique per user+region."""
    return f'{user_id[:USER_LENGTH]}_{region}'


def get_domain_name(user_id: str, project: str, service: str, env: str) -> str:
    """Domain: {user6}-{project}-{service}-{env}.digitalpixo.com"""
    return f"{sanitize(user_id[:USER_LENGTH])}-{sanitize(project)}-{sanitize(service)}-{sanitize(env)}.digitalpixo.com"


def get_container_name(user_id: str, project: str, service: str, env: str, version: int) -> str:
    """Container: {user6}_{project}_{service}_{env}_{version}"""
    return sanitize_container(f'{user_id[:USER_LENGTH]}_{project}_{service}_{env}_{version}')


def get_image_name(user_id: str, project: str, service: str, env: str, version: int) -> str:
    """Image: {user6}-{project}-{service}-{env}-{version}"""
    return f"{sanitize(user_id[:USER_LENGTH])}-{sanitize(project)}-{sanitize(service)}-{sanitize(env)}-{version}"


def get_container_port(service_type: str) -> int:
    """Fixed per service type."""
    return {
        'webservice': 8000, 'worker': 8000, 'schedule': 8000,
        'redis': 6379, 'postgres': 5432, 'mysql': 3306, 'mongodb': 27017,
    }.get(service_type.lower(), 8000)


def get_host_port(user_id: str, project: str, service: str, env: str, version: int, service_type: str = 'webservice') -> int:
    """
    Host port allocation.
    - Webservice: versioned for blue-green
    - Stateful: fixed (same port always)
    """
    if service_type.lower() in ('redis', 'postgres', 'mysql', 'mongodb'):
        key = f"{user_id}:{project}:{service}:{env}"
    else:
        key = f"{user_id}:{project}:{service}:{env}:v{version}"
    
    h = int(hashlib.md5(key.encode()).hexdigest(), 16)
    return 10000 + (h % 50000)


def sanitize(s: str) -> str:
    """DNS/docker safe: lowercase, alphanumeric + hyphens."""
    s = s.lower()
    s = re.sub(r'[^a-z0-9-]', '-', s)
    s = re.sub(r'-+', '-', s)
    return s.strip('-')


def sanitize_container(s: str) -> str:
    """Docker container safe: lowercase, alphanumeric + underscores."""
    s = s.lower()
    s = re.sub(r'[^a-z0-9_]', '_', s)
    s = re.sub(r'_+', '_', s)
    return s.strip('_')

