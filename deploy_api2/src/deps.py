"""
FastAPI dependencies for deploy_api.

Provides:
- Database connection
- Current user (from JWT)
- DO/CF tokens (from headers)
"""

from typing import Optional
from contextlib import asynccontextmanager
from fastapi import Depends, Header, HTTPException, Request

from backend.app_kernel.db import db_connection, get_db_connection
from backend.app_kernel.auth import get_current_user, UserIdentity

__all__ = [
    "db_connection",
    "get_db_connection",
    "get_current_user",
    "get_do_token",
    "get_cf_token",
    "require_do_token",
    "require_cf_token",
]


# =============================================================================
# Token extraction from headers
# =============================================================================

async def get_do_token(
    x_do_token: Optional[str] = Header(None, alias="X-DO-Token"),
) -> Optional[str]:
    """Get DigitalOcean token from header (optional)."""
    return x_do_token


async def get_cf_token(
    x_cf_token: Optional[str] = Header(None, alias="X-CF-Token"),
) -> Optional[str]:
    """Get Cloudflare token from header (optional)."""
    return x_cf_token


async def require_do_token(
    token: Optional[str] = Depends(get_do_token),
) -> str:
    """Require DigitalOcean token."""
    if not token:
        raise HTTPException(
            status_code=400,
            detail="DigitalOcean token required. Set X-DO-Token header.",
        )
    return token


async def require_cf_token(
    token: Optional[str] = Depends(get_cf_token),
) -> str:
    """Require Cloudflare token."""
    if not token:
        raise HTTPException(
            status_code=400,
            detail="Cloudflare token required. Set X-CF-Token header.",
        )
    return token


# =============================================================================
# Combined dependencies
# =============================================================================

async def get_tokens(
    do_token: Optional[str] = Depends(get_do_token),
    cf_token: Optional[str] = Depends(get_cf_token),
) -> dict:
    """Get both tokens as a dict."""
    return {
        "do_token": do_token,
        "cf_token": cf_token,
    }


async def require_tokens(
    do_token: str = Depends(require_do_token),
    cf_token: str = Depends(require_cf_token),
) -> dict:
    """Require both tokens."""
    return {
        "do_token": do_token,
        "cf_token": cf_token,
    }
