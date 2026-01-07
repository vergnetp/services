#!/bin/bash
# Build deploy_api Docker image
#
# Usage (from projects/ directory):
#   ./services/deploy_api/build.sh
#
# Or from services/deploy_api/:
#   ./build.sh

set -e

# Find the projects root (parent of services/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Check if we're in services/deploy_api or projects/
if [[ -d "$SCRIPT_DIR/../../shared_libs" ]]; then
    # We're in services/deploy_api/
    PROJECTS_ROOT="$SCRIPT_DIR/../.."
elif [[ -d "$SCRIPT_DIR/shared_libs" ]]; then
    # We're in projects/
    PROJECTS_ROOT="$SCRIPT_DIR"
else
    echo "Error: Cannot find shared_libs. Run from projects/ or services/deploy_api/"
    exit 1
fi

cd "$PROJECTS_ROOT"

echo "Building deploy-api from: $(pwd)"
echo "  - services/deploy_api/"
echo "  - shared_libs/"

docker build \
    -f services/deploy_api/Dockerfile \
    -t deploy-api:latest \
    .

echo ""
echo "✅ Build complete: deploy-api:latest"
echo ""
echo "Run with:"
echo "  docker run -p 8000:8000 -e DO_TOKEN=xxx deploy-api:latest"
