"""
App-specific settings for deploy_api.

Infrastructure config (database, auth, email, etc.) is in manifest.yaml.
This file only contains app-specific settings not covered by the kernel.

.env hierarchy (lowest → highest priority):
  1. shared_libs/.env              (shared defaults)
  2. shared_libs/services/.env     (all services)  
  3. shared_libs/services/deploy_api/.env  (this service)
  4. Environment variables         (always win)

Note: Loaded here for worker.py, and also by create_service() for the API.
      (load_env_hierarchy is idempotent - safe to call multiple times)
"""

# =============================================================================
# BUILD TIMESTAMP - Auto-generated when Claude creates deploy_api.zip
# =============================================================================
DEPLOY_API_VERSION = "2026-01-20 20:58 UTC"
# =============================================================================

import os
from pathlib import Path
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

from shared_libs.backend.app_kernel import load_env_hierarchy


# Service directory (where this file lives)
SERVICE_DIR = Path(__file__).parent

# Load .env hierarchy (for worker.py - API also loads via create_service)
load_env_hierarchy(__file__)


class AppSettings(BaseSettings):
    """App-specific settings (not in manifest.yaml)."""
    
    model_config = SettingsConfigDict(
        env_prefix="DEPLOY_",
        extra="ignore",
    )
    
    # Server (uvicorn)
    host: str = "0.0.0.0"
    port: int = 8000
    
    # App-specific
    encryption_key: Optional[str] = None  # For credential encryption
    
    # Cloudflare Origin Certificate (for HTTPS domains)
    # Can be set via env vars or loaded from files
    origin_cert: Optional[str] = None  # PEM content
    origin_key: Optional[str] = None   # PEM content
    origin_cert_path: Optional[str] = None  # Path to cert file
    origin_key_path: Optional[str] = None   # Path to key file
    
    def get_origin_cert(self) -> Optional[str]:
        """Get origin certificate content (from env or file)."""
        if self.origin_cert:
            return self.origin_cert
        if self.origin_cert_path and Path(self.origin_cert_path).exists():
            return Path(self.origin_cert_path).read_text()
        # Try default path relative to infra folder
        default_path = SERVICE_DIR.parent / "infra" / "certificate.pem"
        if default_path.exists():
            return default_path.read_text()
        return None
    
    def get_origin_key(self) -> Optional[str]:
        """Get origin certificate key (from env or file)."""
        if self.origin_key:
            return self.origin_key
        if self.origin_key_path and Path(self.origin_key_path).exists():
            return Path(self.origin_key_path).read_text()
        # Try default path relative to infra folder
        default_path = SERVICE_DIR.parent / "infra" / "certificate.key"
        if default_path.exists():
            return default_path.read_text()
        return None


@lru_cache
def get_app_settings() -> AppSettings:
    """Get cached app settings instance."""
    return AppSettings()


def get_manifest_path() -> str:
    """Get path to manifest.yaml."""
    return str(SERVICE_DIR / "manifest.yaml")


# =============================================================================
# Combined settings for worker (reads from manifest + env)
# =============================================================================

class Settings(BaseSettings):
    """Combined settings from manifest.yaml and environment.
    
    Used by worker.py which needs database settings.
    """
    
    model_config = SettingsConfigDict(
        extra="ignore",
    )
    
    # Redis
    redis_url: str = "redis://localhost:6379/0"
    redis_key_prefix: str = "deploy:"
    
    # Database (from manifest or env)
    # Path is relative to working directory, matching manifest
    database_path: str = "./data/deploy.db"
    database_type: str = "sqlite"
    database_host: str = "localhost"
    database_port: int = 5432
    database_user: Optional[str] = None
    database_password: Optional[str] = None


@lru_cache
def get_settings() -> Settings:
    """Get settings, loading from manifest.yaml if available."""
    import yaml
    import re
    
    manifest_path = get_manifest_path()
    
    # Start with defaults
    settings_dict = {}
    
    # Load from manifest if exists
    if Path(manifest_path).exists():
        with open(manifest_path) as f:
            content = f.read()
        
        # Interpolate ${VAR} and ${VAR:-default}
        def interpolate(match):
            var_name = match.group(1)
            default = match.group(2)
            return os.environ.get(var_name, default if default is not None else "")
        
        content = re.sub(r'\$\{([^}:]+)(?::-([^}]*))?\}', interpolate, content)
        manifest = yaml.safe_load(content)
        
        # Extract database settings (use `or` to handle empty interpolated values)
        db = manifest.get("database", {})
        settings_dict["database_type"] = db.get("type") or "sqlite"
        settings_dict["database_path"] = db.get("path") or "./data/deploy.db"
        settings_dict["database_host"] = db.get("host") or "localhost"
        settings_dict["database_port"] = db.get("port") or 5432
        settings_dict["database_user"] = db.get("user") or None
        settings_dict["database_password"] = db.get("password") or None
        
        # Extract redis settings (env var takes priority)
        redis = manifest.get("redis", {})
        settings_dict["redis_url"] = os.environ.get("REDIS_URL") or redis.get("url") or "redis://localhost:6379/0"
        settings_dict["redis_key_prefix"] = redis.get("key_prefix") or "deploy:"
    
    return Settings(**settings_dict)
