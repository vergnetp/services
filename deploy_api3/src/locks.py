"""Deployment locking to prevent concurrent deploys."""

import asyncio
import uuid
from typing import Optional, Dict, Any
from datetime import datetime, timezone, timedelta

_locks: Dict[str, Dict[str, Any]] = {}
_lock_mutex = asyncio.Lock()


def _lock_key(service_id: str, env: str) -> str:
    return f"{service_id}:{env}"


async def acquire_deploy_lock(service_id: str, env: str, timeout: int = 300, holder: str = None) -> Optional[str]:
    """Acquire lock. Returns lock_id if acquired, None if already locked."""
    key = _lock_key(service_id, env)
    now = datetime.now(timezone.utc)
    
    async with _lock_mutex:
        existing = _locks.get(key)
        if existing and existing['expires_at'] > now:
            return None
        
        lock_id = holder or str(uuid.uuid4())
        _locks[key] = {
            'lock_id': lock_id,
            'expires_at': now + timedelta(seconds=timeout),
        }
        return lock_id


async def release_deploy_lock(service_id: str, env: str, lock_id: str) -> bool:
    """Release lock."""
    key = _lock_key(service_id, env)
    async with _lock_mutex:
        existing = _locks.get(key)
        if not existing or existing['lock_id'] != lock_id:
            return False
        del _locks[key]
        return True
