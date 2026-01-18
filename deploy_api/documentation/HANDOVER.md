# Deploy Infrastructure Project - Handover Document

## 🚨 RULE #1: LOGIC GOES IN INFRA, NOT API 🚨

```
┌─────────────────────────────────────────────────────────────────┐
│  BEFORE WRITING ANY CODE, ASK:                                  │
│  "Is this logic or routing?"                                    │
│                                                                 │
│  • Logic (validation, conversion, orchestration) → shared_libs/ │
│  • Routing (parse request, call service, return response) → API │
│                                                                 │
│  If you're writing more than 5 lines in API routes, STOP.       │
│  It probably belongs in shared_libs/.                           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Project Overview

Building a deployment platform (like Heroku/Railway) using DigitalOcean infrastructure. Provisions servers from snapshots, deploys via Docker.

---

## ⚠️ Critical Instructions for Claude

### 🧪 DEV PHASE MINDSET
- **We are in dev phase** - happy to delete all servers/snapshots and retest
- Give **proper fixes**, not workarounds for existing data
- Don't waste time on migration paths - clean slate is fine

### 📦 ALWAYS BUILD BEFORE ZIPPING
Before providing `deploy_api.zip`:
```powershell
cd deploy_api/frontend
npm run build
```
Then zip. The `static/` folder must contain fresh build.

### 🔄 THINK REUSABILITY
Before adding code, ask: "Could other services/projects use this?"
- Auth logic → `shared_libs/backend/auth/` ✅ (already done)
- DB utilities → `shared_libs/backend/app_kernel/`
- Cloud infra → `shared_libs/backend/infra/`

### User Environment
- **User is on Windows** - use PowerShell commands

### Version Bumping
When modifying `node_agent/agent_code.py`:
- Bump `AGENT_VERSION` in `agent_code.py`
- Bump `EXPECTED_AGENT_VERSION` in frontend
- **Recreate snapshot** after changes

### Snapshot Recreation Required
After changes to:
- `agent_code.py` - Node agent code
- `cloudinit.py` - Cloud-init scripts  
- `client.py` - Nginx default config (in `_get_default_nginx_conf()`)

---

## Folder Structure

```
Projects/
├── services/                          # Individual services
│   ├── deploy_api/                    # THIS PROJECT
│   │   ├── frontend/                  # Svelte source
│   │   │   ├── src/
│   │   │   │   ├── App.svelte
│   │   │   │   └── lib/
│   │   │   │       ├── components/
│   │   │   │       │   ├── deploy/
│   │   │   │       │   │   ├── Deploy.svelte
│   │   │   │       │   │   ├── Deployments.svelte
│   │   │   │       │   │   └── Infrastructure.svelte
│   │   │   │       │   └── ui/
│   │   │   │       ├── stores/
│   │   │   │       │   ├── app.js
│   │   │   │       │   ├── auth.js
│   │   │   │       │   └── toast.js
│   │   │   │       └── api/
│   │   │   │           └── client.js
│   │   │   ├── package.json
│   │   │   └── vite.config.js
│   │   ├── static/                    # Built frontend (served)
│   │   ├── src/
│   │   │   ├── routes/
│   │   │   │   └── infra_routes.py    # THIN routes
│   │   │   └── stores.py              # Database stores
│   │   ├── _gen/
│   │   │   ├── crud.py
│   │   │   └── db_schema.py
│   │   └── main.py
│   │
│   └── other_services/...             # Other services
│
└── shared_libs/                       # SHARED CODE (sibling to services)
    └── backend/
        ├── infra/                     # ALL DEPLOY LOGIC
        │   ├── cloud/
        │   │   ├── digitalocean/
        │   │   │   └── client.py      # DOClient
        │   │   ├── cloudflare/
        │   │   │   └── client.py      # CloudflareClient
        │   │   ├── snapshot_service.py
        │   │   └── cloudinit.py
        │   ├── deploy/
        │   │   ├── service.py         # DeploymentService
        │   │   └── generator.py       # Dockerfile generation
        │   ├── node_agent/
        │   │   ├── agent_code.py      # Flask app ON servers
        │   │   └── client.py          # NodeAgentClient
        │   └── networking/
        │       └── service.py         # NginxService
        │
        ├── auth/                      # Shared auth (used by all services)
        │   └── ...
        │
        └── app_kernel/                # Framework (DB, config, etc.)
            └── ...
```

---

## 🖥️ Svelte Frontend

### Building

```powershell
cd Projects/services/deploy_api/frontend
npm install           # First time only
npm run build         # Outputs to ../static/
```

### Key Stores

```javascript
// stores/app.js
export const servers = writable([])
export const snapshots = writable([])

// stores/auth.js  
export const auth = writable({ token: null, user: null })
export function getDoToken()
export function getCfToken()

// stores/toast.js
export const toasts = { success(), error(), info() }
```

### API Client

```javascript
import { api } from '../api/client.js'
const data = await api('GET', '/infra/servers')
```

### SSE Streams

```javascript
const res = await fetch(`/api/v1/infra/deploy?${params}`, {
  method: 'POST',
  body: JSON.stringify(payload)
})
const reader = res.body.getReader()
// Read and parse SSE...
```

---

## 📦 Database Schema (Normalized)

SQLite with normalized schema (`data/deploy.db`):

- `projects` - Workspace-level grouping
- `services` - Deployable units within projects
- `droplets` - Server inventory
- `service_droplets` - Which servers run which services
- `deployments` - Deployment history

### Store Classes

```python
from deploy_api.src.stores import (
    ProjectStore, ServiceStore, DropletStore,
    ServiceDropletStore, DeploymentStore
)
```

---

## 📝 Rollback with Tagged Images

Every deployment tags the image:
```
{image_base}:deploy_{deployment_id[:8]}
```

Example: `vergnetp/ai-agents:deploy_4bd0ed9b`

Rollback uses tagged image (exact version), not latest.

---

## 🛡️ Droplet Safety

`MANAGED_TAG = "deployed-via-api"` protects personal droplets:
- Only managed droplets listed/deployed to
- Delete refuses unmanaged unless `force=True`

---

## API Endpoints

### Deployment
- `POST /infra/deploy` - Main deploy (SSE)
- `GET /infra/deployments/history` - List
- `POST /infra/deployments/rollback` - Rollback (SSE)

### Infrastructure
- `GET /infra/servers` - List servers
- `POST /infra/servers/provision` - Create
- `GET /infra/snapshots` - List snapshots

### Config
- `GET /infra/deploy-configs` - List saved
- `POST /infra/deploy-configs` - Save

---

## Testing Checklist

1. **Recreate snapshot** if agent/cloudinit/client.py changed
2. **Build frontend**: `cd frontend && npm run build`
3. **Test deploy**: Upload code → Deploy → Check domain
4. **Test rollback**: Deployments tab → Rollback
5. **Verify HTTPS**: Domain works with SSL

---

## Files to Provide

1. `HANDOVER.md` - This document
2. `deploy_api.zip` → `Projects/services/deploy_api/` (WITH built static/)
3. `infra.zip` → `Projects/shared_libs/backend/infra/`

---

## Current State

### Working ✅
- Snapshot creation/provisioning
- Multi-server deployment (code/git/image)
- Svelte dashboard with tabs
- Deployment history + rollback
- Config save/load
- Domain setup with Cloudflare DNS
- HTTPS via nginx with origin certs
- Server list refreshes after deploy

### Recent Fixes
- Nginx `server_names_hash_bucket_size 128` in default config
- Rollback uses tagged images `{base}:deploy_{id[:8]}`
- User lookup uses entity API
- Ports format fixed for rollback

### TODO 🔧
- Auto-scaling
- Docker image cleanup on servers

---

## 🚀 Performance Monitoring

**Goal**: This API may be sold to clients. Always endeavour to understand why calls are slow and improve runtime.

### Request Metrics Infrastructure

The `app_kernel.observability.request_metrics` module captures rich metadata for every request:

```
Request → Middleware captures metadata → job_queue.enqueue() (non-blocking)
                                                ↓
                                        Worker stores to:
                                        1. DB (hot data, fast queries)
                                        2. OpenSearch (cold data, analytics)
```

**Captured data**:
- Request: method, path, query_params, request_id
- Response: status_code, error details
- Timing: server_latency_ms
- Client: real IP (behind CF/nginx), user_agent, referer
- Auth: user_id, workspace_id
- Geo: country (from CF-IPCountry)
- Partitioning: timestamp, year, month, day, hour

### Real IP Extraction (CF → nginx → app)

```python
from app_kernel.observability import get_real_ip

# Priority: CF-Connecting-IP → X-Real-IP → X-Forwarded-For[0] → client.host
real_ip = get_real_ip(request)
```

### Profiling Slow Routes

Use the profiler decorator to identify bottlenecks:

```python
from app_kernel import profiled_function

@router.get("/servers")
@profiled_function(is_entry=True)
async def list_servers(...):
    ...

@profiled_function()
def expensive_operation():
    ...
```

The decorator logs timing stats when the entry function completes.

### Querying Request Metrics

```python
from app_kernel.observability import RequestMetricsStore

store = RequestMetricsStore()

# Recent requests
metrics = await store.get_recent(limit=100, path_prefix="/api/v1/infra")

# Aggregated stats (last 24h)
stats = await store.get_stats(hours=24)
# Returns: total_requests, avg_latency_ms, slow_endpoints, error_endpoints

# Find slow requests (>1000ms)
slow = await store.get_recent(min_latency_ms=1000)
```

### API Endpoints (admin only)

- `GET /metrics/requests` - List recent requests
- `GET /metrics/requests/stats` - Aggregated statistics  
- `GET /metrics/requests/slow` - Slow requests (>1s)
- `GET /metrics/requests/errors` - Error requests (4xx/5xx)

### Environment Variables (OpenSearch - optional)

```
OPENSEARCH_HOST=localhost
OPENSEARCH_PORT=9200
OPENSEARCH_USE_SSL=false
OPENSEARCH_AUTH_TYPE=none|basic|aws
OPENSEARCH_USERNAME=
OPENSEARCH_PASSWORD=
```