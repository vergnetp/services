FROM python:3.11-slim
WORKDIR /app
# Copy shared_libs
COPY shared_libs/ ./shared_libs/
# Copy main service
COPY deploy_api/ ./deploy_api/
# Install dependencies
RUN pip install --no-cache-dir -r deploy_api/requirements.txt
EXPOSE 8000
CMD ["uvicorn", "deploy_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
