# Node Agent

Flask app that runs ON each droplet. Gets embedded into snapshot via cloud-init.

## Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/ping` | Agent health check |
| POST | `/upload?name=xxx` | Upload Docker image (stream body) |
| POST | `/start_container` | Start a container |
| POST | `/remove_container?container_name=xxx` | Stop and remove container |
| GET | `/health?container_name=xxx` | Health check with log parsing + TCP ping |
| GET | `/containers/<name>/status` | Get container status |
| POST | `/containers/<name>/restart` | Restart container |
| POST | `/configure_nginx` | Configure nginx upstream |

## Health Check Flow

1. Parse docker logs for errors (up to 5)
2. Check if container is running (docker inspect)
3. Get host port and TCP ping
4. Return status:
   - `unhealthy` - not running
   - `unhealthy` - running but TCP ping times out
   - `degraded` - running but has errors in logs
   - `healthy` - all good

## Embedding in Snapshot

```python
# Read agent code
with open("node_agent/agent.py") as f:
    agent_code = f.read()

# Embed in cloud-init user_data when creating snapshot
user_data = f"""
#cloud-config
write_files:
  - path: /opt/node_agent/agent.py
    content: |
      {agent_code}
runcmd:
  - pip install flask
  - cd /opt/node_agent && nohup python agent.py &
"""
```

## Authentication

Uses API key derived from DO token:
```python
import hmac, hashlib
api_key = hmac.new(do_token.encode(), b"node-agent:", hashlib.sha256).hexdigest()
```

Agent expects `X-API-Key` header on all requests.
