"""
Deploy API configuration.
"""

import os
from pathlib import Path
from dataclasses import dataclass

# Service directory
SERVICE_DIR = Path(__file__).parent

# Version
DEPLOY_API_VERSION = "2026-01-27 00:09 UTC"


@dataclass(frozen=True)
class Settings:
    """Application settings from environment."""
    
    # Database
    database_path: str = os.getenv("DATABASE_PATH") or str(SERVICE_DIR / "data" / "deploy.db")
    database_type: str = "sqlite"
    
    # Redis (optional)
    redis_url: str = os.getenv("REDIS_URL", "")
    
    # Auth
    jwt_secret: str = os.getenv("JWT_SECRET", "dev-secret-change-in-production")
    
    # DigitalOcean (user provides their own token)
    # Not stored here - passed via request headers
    
    # Cloudflare (user provides their own token)
    # Not stored here - passed via request headers
    
    # Node agent
    node_agent_port: int = 9999
    
    # Admin emails (comma-separated)
    admin_emails: str = os.getenv("ADMIN_EMAILS", "")
    
    # Domain for generated subdomains
    base_domain: str = os.getenv("BASE_DOMAIN", "digitalpixo.com")
    
    @property
    def database_name(self) -> str:
        """Extract database name from path."""
        return Path(self.database_path).stem
    
    def ensure_data_dir(self):
        """Create data directory if needed."""
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
    
    def is_admin(self, email: str) -> bool:
        """Check if email is an admin."""
        if not self.admin_emails:
            return False
        admins = [e.strip().lower() for e in self.admin_emails.split(",")]
        return email.lower() in admins


settings = Settings()
