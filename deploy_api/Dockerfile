# Dockerfile for deploy_api
# 
# Build from projects/ directory:
#   docker build -f services/deploy_api/Dockerfile -t deploy-api .
#
# Or from anywhere with context path:
#   docker build -f /path/to/Dockerfile -t deploy-api /path/to/projects/

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY services/deploy_api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared_libs (must be in build context)
COPY shared_libs /app/shared_libs

# Copy deploy_api application (flat structure)
COPY services/deploy_api /app/deploy_api
# Remove build files from app directory
RUN rm -f /app/deploy_api/Dockerfile /app/deploy_api/requirements.txt /app/deploy_api/build.sh /app/deploy_api/.dockerignore

# Set Python path so shared_libs imports work
ENV PYTHONPATH=/app

# Default JWT_SECRET for easier testing (override in production!)
ENV JWT_SECRET=change-me-in-production-default-secret

# Create data directory for SQLite
RUN mkdir -p /app/deploy_api/data

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run with uvicorn (production settings)
CMD ["uvicorn", "deploy_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
