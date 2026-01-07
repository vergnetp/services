# Deploy Infrastructure Project - Handover Document

## 🚨 RULE #1: LOGIC GOES IN INFRA, NOT API 🚨

```
┌─────────────────────────────────────────────────────────────────┐
│  BEFORE WRITING ANY CODE, ASK:                                  │
│  "Is this logic or routing?"                                    │
│                                                                 │
│  • Logic (validation, conversion, orchestration) → infra/      │
│  • Routing (parse request, call service, return response) → API │
│                                                                 │
│  If you're writing more than 5 lines in API routes, STOP.       │
│  It probably belongs in infra/.                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Examples:**
- Zip→tar conversion? → `infra/deploy/service.py`
- Multi-server orchestration? → `infra/deploy/service.py`  
- Dockerfile generation? → `infra/deploy/generator.py`
- API key derivation? → `infra/cloud/__init__.py`

**API route should look like:**
```python
@router.post("/deploy")
async def deploy(req: DeployRequest, user = Depends(get_current_user)):
    service = DeploymentService(token, key)
    result = await service.deploy(config)
    return result
```

---

## Project Overview

Building a deployment platform (like a simplified Heroku/Railway) using DigitalOcean infrastructure. The system provisions servers from pre-built snapshots and deploys applications via Docker.

## Architecture

See **RULE #1** above. The pattern is:

```
Frontend (thin)     →  API (thin)           →  Infra (ALL LOGIC)
─────────────────────────────────────────────────────────────────
Collect form data      Route + validate        DeploymentService
Call endpoint          Call service            - _ensure_tar()
Display results        Return response         - provision_servers()
                                               - build_and_deploy()
```

## ⚠️ Instructions for Claude

### 🚨 REMEMBER RULE #1
Before writing code: **Logic → infra/, Routing → API**. Read the top of this document.

### User Environment
- **User is on Windows** - give PowerShell commands, not bash
- Example: `curl.exe` not `curl`, or use `Invoke-WebRequest`

### Version Bumping
When modifying `node_agent/agent_code.py`, ALWAYS bump both:
- `AGENT_VERSION` in `agent_code.py` (line ~10)
- `EXPECTED_AGENT_VERSION` in `index.html` (in State section)

These must match. Version mismatch = stale snapshot.

### Zips
Always give back full updated zips. User simply replaces without checking contents.

### Snapshot Recreation Required
After changes to:
- `agent_code.py` - Node agent code baked into snapshot
- `cloudinit.py` - Cloud-init scripts run during snapshot creation

### Emergency SSH Access
`EMERGENCY_ADMIN_IPS` in `cloudinit.py` allows SSH for debugging. IP is location-dependent - update when Phil changes location (France ↔ London) and recreate snapshot.

### Don't Duplicate Logic
If code/git/image deploys share logic, use ONE function with a parameter, not three copies. Example:
```python
# GOOD: Single function handles all source types
async def deploy(config: DeployConfig):
    servers = await collect_servers(config)
    await wait_for_agents(servers)
    if config.source_type == 'git':
        await clone_repo(servers[0])  # Only difference
    await build_and_run(servers, config)

# BAD: Duplicated code for each source type
if source_type == 'code':
    # 100 lines of deploy logic
elif source_type == 'git':
    # Same 100 lines with minor changes
```

## Folder Structure

```
Projects/
├── services/
│   └── deploy_api/
│       ├── src/routes/
│       │   └── infra_routes.py       # THIN - calls DeploymentService
│       ├── static/
│       │   └── index.html            # THIN - form + SSE display
│       └── main.py
│
└── shared_libs/backend/
    ├── infra/                        # ALL LOGIC HERE
    │   ├── cloud/
    │   │   ├── digitalocean/
    │   │   │   └── client.py         # DOClient
    │   │   ├── snapshot_service.py   # SnapshotService
    │   │   └── cloudinit.py          # Cloud-init generation
    │   ├── deploy/
    │   │   ├── service.py            # DeploymentService (multi-server)
    │   │   ├── generator.py          # Dockerfile generation
    │   │   └── local.py              # LocalDeployer, RemoteDeployer
    │   ├── node_agent/
    │   │   ├── agent_code.py         # Flask app ON servers
    │   │   └── client.py             # NodeAgentClient (async)
    │   ├── docker/
    │   ├── ssh/
    │   └── utils/
    │       └── naming.py             # generate_friendly_name()
    ├── app_kernel/
    ├── auth/
    └── ...
```

## Key Components

### DeploymentService (infra/deploy/service.py)

Central orchestrator for all deployments. Handles:
- Multi-server deployments (parallel)
- Server provisioning from snapshots
- Agent health checks
- Three source types:
  - **CODE**: Upload tar → Build → Run
  - **GIT**: Clone → Build → Run  
  - **IMAGE**: Pull → Run (skips build)

```python
from shared_libs.backend.infra.deploy import DeploymentService, MultiDeployConfig, DeploySource

service = DeploymentService(do_token="...", agent_key="...", log=print)

result = await service.deploy(MultiDeployConfig(
    name="myapp",
    port=8000,
    source_type=DeploySource.GIT,
    git_url="https://github.com/user/repo",
    server_ips=["1.2.3.4", "5.6.7.8"],  # Deploy to multiple
    new_server_count=2,                  # Also provision 2 new
    snapshot_id="12345",
    region="lon1",
))
```

### Deploy Endpoint

Single endpoint handles all deploy types:

```
POST /api/v1/infra/deploy?do_token=XXX

{
    "name": "myapp",
    "port": 8000,
    "env_vars": {"KEY": "value"},
    "environment": "prod",
    "tags": ["api", "v2"],
    
    "source_type": "code" | "git" | "image",
    
    // For code:
    "code_tar_b64": "base64...",
    "dockerfile": "FROM python:3.11...",
    
    // For git:
    "git_url": "https://github.com/...",
    "git_branch": "main",
    "git_token": "ghp_...",
    
    // For image:
    "image": "nginx:latest",
    
    // Infrastructure:
    "server_ips": ["1.2.3.4"],
    "new_server_count": 0,
    "snapshot_id": "123",
    "region": "lon1",
    "size": "s-1vcpu-1gb"
}
```

Returns SSE stream:
```
data: {"type": "log", "message": "🚀 Deploying..."}
data: {"type": "log", "message": "✅ Server ready"}
data: {"type": "done", "success": true, "servers": [...]}
```

### Frontend (Thin)

Just collects form data and displays SSE:

```javascript
async function startDeployment(event) {
    // 1. Collect form data into payload object
    const payload = {
        name: document.getElementById('deploy-name').value,
        source_type: getSelectedSourceType(),
        server_ips: getSelectedServers().map(s => s.ip),
        // ... etc
    };
    
    // 2. Call unified endpoint
    const response = await fetch(`${API_BASE}/infra/deploy/unified?do_token=${token}`, {
        method: 'POST',
        body: JSON.stringify(payload)
    });
    
    // 3. Read SSE stream and display logs
    const reader = response.body.getReader();
    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        // Parse SSE and call log() function
    }
}
```

## Snapshots

Pre-built DigitalOcean images with Docker + node_agent installed.

- **Base snapshot**: `base-docker-ubuntu` - Docker, node_agent, basic tools
- **Custom snapshots**: Built FROM base, add specific packages

### Node Agent

Flask API on every server (port 9999). Handles all Docker operations.

**No SSH** - all operations via node_agent HTTP API.

### API Key Generation

Deterministic from DO token + user ID:
```python
def generate_node_agent_key(do_token: str, user_id: str) -> str:
    import hashlib, hmac
    message = f"node-agent:{user_id}"
    return hmac.new(do_token.encode(), message.encode(), hashlib.sha256).hexdigest()[:32]
```

**CRITICAL**: Always use `str(user.id)` - type mismatch causes key mismatch.

## Client-Side State Management

Dashboard uses React-style state pattern:

```javascript
// Single source of truth
const state = {
    infraServers: [],  // All servers with image info
    // ...
};

// Load once
async function loadServersForDeploy() {
    state.infraServers = await api('GET', '/infra/servers');
    renderServerList();
}

// Filter client-side (instant, no API calls)
function renderServerList() {
    const snapshotId = getSelectedSnapshot();
    const region = getSelectedRegion();
    
    const filtered = state.infraServers.filter(s => {
        if (snapshotId && s.image?.id != snapshotId) return false;
        if (region && s.region != region) return false;
        return true;
    });
    
    // Update DOM
}

// Dropdown changes just re-render
function onSnapshotChange() { renderServerList(); }
function onRegionChange() { renderServerList(); }
```

## Bugs Fixed

### Path Permissions
Node agent requires trailing slash: `/app/` not `/app`

### AgentResponse Handling
```python
# Wrong: result.get("status")
# Right: result.success, result.data.get("key")
```

### Multi-Server Deploy
Both code and git deploys now deploy to ALL selected servers, not just the first one.

### Zip to Tar Conversion
Handle directories properly with `zipfile.ZipInfo.is_dir()` and `tarfile.DIRTYPE`.

## Current State

### Working ✅
- Base snapshot creation with streaming logs
- Custom snapshot building
- Snapshot transfer to all regions
- Server provisioning
- Multi-server deployment (code, git, image)
- Dashboard with client-side server filtering
- Unified deploy endpoint with SSE streaming

### TODO 🔧

> **Migration from `original_infra.zip`** - mature codebase with features to port:
> - nginx config generation (reverse proxy, SSL)
> - Zero-downtime deployments
> - Auto-scaling
> - Multi-service projects
> - Scheduled tasks
> - Health monitoring with auto-recovery

1. **Domain/SSL support** - nginx config exists but not wired up
2. **Deployment management** - list, logs, stop/restart
3. **Multiple apps per server**

## Files to Provide

1. `HANDOVER.md` - This document (read first)
2. `deploy_api.zip` → `Projects/services/deploy_api/`
3. `infra.zip` → `Projects/shared_libs/backend/infra/`
4. `original_infra.zip` - (Optional) Reference for feature migration

## Critical Rules

### DO NOT MODIFY working streaming endpoints:
- `init_setup_stream` - Base snapshot creation
- `build_image_stream` - Custom snapshot building

### Before changes:
1. State which functions/lines will be modified
2. State what will NOT be touched
3. Wait for approval

### SSE Pattern
```python
msg_queue = queue.Queue()

def worker():
    msg_queue.put(event)
    msg_queue.put({'type': '__END__'})

thread = threading.Thread(target=worker, daemon=True)
thread.start()

def generate():
    while True:
        event = msg_queue.get(timeout=1)
        if event.get('type') == '__END__':
            break
        yield f"data: {json.dumps(event)}\n\n"

return StreamingResponse(generate(), media_type="text/event-stream")
```

## API Endpoints

### Setup
- `GET /infra/setup/status` - Check base snapshot exists
- `POST /infra/setup/init/stream` - Create base snapshot (SSE)

### Snapshots
- `GET /infra/snapshots` - List
- `POST /infra/images/build/stream` - Build custom (SSE)
- `POST /infra/snapshots/{id}/transfer-all` - Transfer regions
- `DELETE /infra/snapshots/{id}` - Delete

### Servers
- `GET /infra/servers` - List (includes image info for filtering)
- `POST /infra/servers/provision` - Provision new
- `DELETE /infra/servers/{id}` - Delete

### Deployment
- `POST /infra/deploy` - **Main endpoint** (SSE) - handles code/git/image
- `POST /infra/deploy/single` - Quick single-server image deploy (no SSE)
- `POST /infra/deploy/upload` - Upload code to server

### Node Agent (proxy)
- `GET /infra/agent/health?server_ip=X`
- `POST /infra/agent/{ip}/build`
- `POST /infra/agent/{ip}/containers/run`
- `POST /infra/agent/{ip}/pull`
- `POST /infra/agent/{ip}/git/clone`

## Testing Checklist

1. **Recreate snapshot** if node_agent changed
2. **Test all 3 source types**: code, git, image
3. **Test multi-server**: select 2+ servers, verify both deployed
4. **Health check via Dashboard**: Infrastructure tab → 🩺 Health button on server
5. **Manual agent test (PowerShell)**:
   ```powershell
   # Get your API key first from dashboard Settings → Show Credentials
   curl.exe -H "X-API-Key: YOUR_FULL_KEY" http://SERVER_IP:9999/ping
   curl.exe -H "X-API-Key: YOUR_FULL_KEY" http://SERVER_IP:9999/health
   ```