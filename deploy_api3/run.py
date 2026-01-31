#!/usr/bin/env python3
"""Entry point that ensures proper Python path setup."""
import sys
from pathlib import Path

# Add parent directory to path so deploy_api3 is importable as a package
app_dir = Path(__file__).parent.parent
if str(app_dir) not in sys.path:
    sys.path.insert(0, str(app_dir))

# Now import and run the app
from deploy_api3.main import app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
