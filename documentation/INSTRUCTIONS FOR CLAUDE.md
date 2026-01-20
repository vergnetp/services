# Instructions for Claude - Deploy Infrastructure Project

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

### 📦 BEFORE PROVIDING deploy_api.zip (MANDATORY CHECKLIST)

**⚠️ DO ALL STEPS IN ORDER - NO SKIPPING!**

| Step | Command/Action | Verify |
|------|----------------|--------|
| 1 | `date -u +"%Y-%m-%d %H:%M UTC"` | Get timestamp (e.g., `2026-01-20 12:39 UTC`) |
| 2 | Update `config.py`: `DEPLOY_API_VERSION = "..."` | ✓ |
| 3 | Update `App.svelte`: `BUILD_VERSION = '...'` | ✓ |
| 4 | `cd frontend && npm run build` | Must see "built in X.XXs" |
| 5 | **VERIFY:** `ls -la static/assets/` | Check JS file timestamp is NOW |
| 6 | `zip -r deploy_api.zip deploy_api ...` | Create zip |
| 7 | **VERIFY:** `unzip -p deploy_api.zip deploy_api/config.py \| grep VERSION` | Confirm version in zip |

**Common mistakes to avoid:**
- ❌ Updating versions but not running `npm run build`
- ❌ Running build but zipping old files (forgot to re-zip after build)
- ❌ Zipping before build completes

**One-liner for steps 4-7:**
```bash
cd /home/claude/work/deploy_api/frontend && npm run build && \
cd /home/claude/work && rm -f /mnt/user-data/outputs/deploy_api.zip && \
zip -r /mnt/user-data/outputs/deploy_api.zip deploy_api -x "*.pyc" -x "*__pycache__*" -x "*.git*" -x "*node_modules*" -x "*.svelte-kit*" && \
echo "=== VERIFY ===" && unzip -p /mnt/user-data/outputs/deploy_api.zip deploy_api/config.py | grep VERSION
```

### 🔄 THINK REUSABILITY
Before adding code, ask: "Could other services/projects use this?"
- Auth logic → `shared_libs/backend/auth/` ✅ (already done)
- DB utilities → `shared_libs/backend/app_kernel/`
- Cloud infra → `shared_libs/backend/infra/`
- **UI Components** → `shared_libs/frontend/` ✅ (already done)

### Phil's Environment
- **Phil is on Windows** - use PowerShell commands when giving instructions to Phil

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
├── package.json                       # NPM WORKSPACE ROOT
│                                      # { "workspaces": ["shared_libs/frontend", "services/*/frontend"] }
│
├── shared_libs/
│   ├── frontend/                      # @myorg/ui - SHARED SVELTE COMPONENTS
│   │   ├── package.json               # name: "@myorg/ui"
│   │   ├── README.md
│   │   └── src/
│   │       ├── index.js               # Main exports
│   │       ├── components/
│   │       │   ├── Auth.svelte        # Configurable auth (presets, social, SSO)
│   │       │   ├── Header.svelte
│   │       │   ├── Button.svelte
│   │       │   ├── Badge.svelte
│   │       │   ├── Card.svelte
│   │       │   ├── Modal.svelte
│   │       │   ├── Tabs.svelte
│   │       │   ├── ToastContainer.svelte
│   │       │   └── ThemeToggle.svelte
│   │       ├── stores/
│   │       │   ├── auth.js            # Shared auth store
│   │       │   ├── toast.js           # Toast notifications
│   │       │   └── theme.js           # Dark/light mode
│   │       ├── api/
│   │       │   └── client.js          # Configurable API client
│   │       ├── presets/
│   │       │   └── index.js           # Auth presets: internal, b2b, b2c, developer
│   │       └── styles/
│   │           └── base.css           # Theme variables (override --primary etc.)
│   │
│   └── backend/
│       ├── infra/                     # ALL DEPLOY LOGIC
│       │   ├── cloud/
│       │   │   ├── digitalocean/
│       │   │   │   └── client.py
│       │   │   ├── cloudflare/
│       │   │   │   └── client.py
│       │   │   ├── snapshot_service.py
│       │   │   └── cloudinit.py
│       │   ├── deploy/
│       │   │   ├── service.py
│       │   │   └── generator.py
│       │   ├── node_agent/
│       │   │   ├── agent_code.py
│       │   │   └── client.py
│       │   └── networking/
│       │       └── service.py
│       │
│       ├── auth/                      # Shared auth (used by all services)
│       │   └── ...
│       │
│       └── app_kernel/                # Framework (DB, config, etc.)
│           └── ...
│
└── services/
    └── deploy_api/                    # THIS PROJECT
        ├── frontend/
        │   ├── package.json           # deps: { "@myorg/ui": "file:../../../shared_libs/frontend" }
        │   ├── vite.config.js
        │   └── src/
        │       ├── App.svelte         # Imports from @myorg/ui
        │       ├── app.css            # Theme overrides (optional)
        │       ├── main.js
        │       └── lib/
        │           ├── components/    # APP-SPECIFIC components only
        │           │   ├── deploy/
        │           │   │   ├── Deploy.svelte
        │           │   │   └── Deployments.svelte
        │           │   ├── infra/
        │           │   │   └── Infrastructure.svelte
        │           │   └── ui/
        │           │       └── ScopeBar.svelte   # App-specific
        │           ├── stores/
        │           │   ├── app.js     # App-specific stores
        │           │   ├── auth.js    # Re-exports @myorg/ui + DO/CF tokens
        │           │   └── toast.js   # Re-exports @myorg/ui
        │           └── api/
        │               └── client.js  # Extended with DO token injection
        ├── static/                    # Built frontend (served)
        ├── src/
        │   ├── routes/
        │   └── stores.py
        ├── _gen/
        └── main.py
```

---

## 🖥️ Frontend Architecture

### NPM Workspaces

Root `package.json`:
```json
{
  "private": true,
  "workspaces": [
    "shared_libs/frontend",
    "services/*/frontend"
  ]
}
```

### Building (Claude)

```bash
# Extract uploads
unzip deploy_api.zip -d /home/claude/output/services/
unzip shared_libs_frontend.zip -d /home/claude/output/shared_libs/

# Setup workspace (needed for @myorg/ui linking)
cd /home/claude/output
cat > package.json << 'EOF'
{"private":true,"workspaces":["shared_libs/frontend","services/*/frontend"]}
EOF

# Install and build
npm install
cd services/deploy_api/frontend
npm run build

# Zip full deploy_api
cd /home/claude/output/services
zip -r /mnt/user-data/outputs/deploy_api.zip deploy_api
```

### Importing Shared Components

```svelte
<script>
  // Shared UI from @myorg/ui
  import { 
    Auth, Header, Button, Card, Modal, Tabs, ToastContainer,
    authStore, isAuthenticated, isAdmin,
    toasts, api,
    presets
  } from '@myorg/ui'
  import '@myorg/ui/styles/base.css'
  import './app.css'  // Local theme overrides
  
  // App-specific
  import Infrastructure from './lib/components/infra/Infrastructure.svelte'
</script>

<Auth 
  title="Deploy Dashboard"
  {...presets.internal}
  on:success={handleAuth}
/>
```

### Auth Presets

| Preset | Signup | Social | SSO | Use Case |
|--------|--------|--------|-----|----------|
| `internal` | ❌ | ❌ | ❌ | Admin panels, internal tools |
| `b2b` | ✅ | Google, Microsoft | ✅ | SaaS, enterprise apps |
| `b2c` | ✅ | Google, Apple, Facebook | ❌ | Consumer apps |
| `developer` | ✅ | GitHub, Google | ❌ | API/developer portals |

```svelte
<!-- Internal tool -->
<Auth {...presets.internal} />

<!-- B2B with custom SSO -->
<Auth {...withPreset('b2b', { ssoButtonText: 'Sign in with Okta' })} />

<!-- B2C with social -->
<Auth {...presets.b2c} />
```

### Theming

Override CSS variables in `app.css`:

```css
/* Purple theme (deploy_api default) */
:root {
  --primary: #6d5cff;
  --primary2: #2d7dff;
}

/* Teal theme (different app) */
:root {
  --primary: #14b8a6;
  --primary2: #06b6d4;
}
```

### App-Specific Auth Extensions

`deploy_api/frontend/src/lib/stores/auth.js`:
```javascript
// Re-export shared auth
export { authStore, isAuthenticated, isAdmin } from '@myorg/ui'

// App-specific: DigitalOcean token
export function getDoToken() {
  return getCustomToken('do_token_local')
}
export function setDoToken(token) {
  setCustomToken('do_token_local', token, 30)
}
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

## What Phil Tests After Receiving Files

(Claude can't test live deployments - Phil does this after extracting zips)

1. **Recreate snapshot** if agent/cloudinit/client.py changed
2. **Test deploy**: Upload code → Deploy → Check domain
3. **Test rollback**: Deployments tab → Rollback
4. **Verify HTTPS**: Domain works with SSL

---

## Files to Ask Phil

When starting work, ask Phil to upload:

| File | When needed |
|------|-------------|
| `deploy_api.zip` | Any deploy_api work |
| `infra.zip` | Backend infra/deploy logic changes |
| `shared_libs_frontend.zip` | **Always if touching frontend** (needed for @myorg/ui imports) |

## Files Claude Provides

After making changes, **only zip what was modified**:

| Provide | When |
|---------|------|
| `deploy_api.zip` | Any deploy_api changes (always build frontend first) |
| `infra.zip` | Backend infra/deploy logic changes |
| `shared_libs_frontend.zip` | Shared UI component changes |

---

## Current State

### TODO 🔧
- Auto-scaling
- Docker image cleanup on servers