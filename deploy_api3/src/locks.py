"""
Deployment locking to prevent concurrent deploys to same service/env.
"""

import asyncio
import uuid
from typing import Optional, Dict, Any
from datetime import datetime, timezone, timedelta


_locks: Dict[str, Dict[str, Any]] = {}
_lock_mutex = asyncio.Lock()


def _lock_key(service_id: str, env: str) -> str:
    return f"{service_id}:{env}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def acquire_deploy_lock(
    service_id: str,
    env: str,
    timeout: int = 300,
    holder: str = None,
) -> Optional[str]:
    """
    Acquire deployment lock. Returns lock_id if acquired, None if already locked.
    Lock auto-expires after timeout seconds.
    """
    key = _lock_key(service_id, env)
    lock_id = holder or str(uuid.uuid4())
    expires_at = _now() + timedelta(seconds=timeout)
    
    async with _lock_mutex:
        existing = _locks.get(key)
        if existing and existing['expires_at'] > _now():
            return None
        
        _locks[key] = {
            'lock_id': lock_id,
            'service_id': service_id,
            'env': env,
            'acquired_at': _now().isoformat(),
            'expires_at': expires_at,
        }
        return lock_id


async def release_deploy_lock(service_id: str, env: str, lock_id: str) -> bool:
    """Release deployment lock. Returns True if released."""
    key = _lock_key(service_id, env)
    
    async with _lock_mutex:
        existing = _locks.get(key)
        if not existing or existing['lock_id'] != lock_id:
            return False
        del _locks[key]
        return True


async def get_lock_info(service_id: str, env: str) -> Optional[Dict[str, Any]]:
    """Get info about current lock, if any."""
    key = _lock_key(service_id, env)
    
    async with _lock_mutex:
        existing = _locks.get(key)
        if not existing or existing['expires_at'] <= _now():
            if existing:
                del _locks[key]
            return None
        
        return {
            'service_id': service_id,
            'env': env,
            'acquired_at': existing['acquired_at'],
            'expires_in': (existing['expires_at'] - _now()).seconds,
        }
