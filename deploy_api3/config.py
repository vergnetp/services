"""Configuration."""
import os

class Settings:
    node_agent_port = int(os.environ.get('NODE_AGENT_PORT', 9999))
    database_path = os.environ.get('DATABASE_PATH', './data/deploy.db')

settings = Settings()
