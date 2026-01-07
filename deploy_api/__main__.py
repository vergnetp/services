"""
Run deploy_api with: python -m deploy_api
"""

import uvicorn
from .config import get_settings

settings = get_settings()

if __name__ == "__main__":
    uvicorn.run(
        "deploy_api.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
