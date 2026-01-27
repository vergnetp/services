# app_kernel

A stable, reusable application kernel for backend services.

## Overview

`app_kernel` provides runtime infrastructure that can be reused across multiple backend services (agentic or not). It handles auth, jobs, streaming safety, database connections, and observability so you don't re-implement them every time.

**Philosophy:**
- **Kernel provides:** mechanisms + invariants
- **Apps provide:** meaning + business logic
- Kernel is domain-agnostic
- All configuration is immutable after initialization

**Rule of thumb:** If it changes weekly or is product-specific, it does NOT belong in `app_kernel`.

## Installation
```python
# In your shared_libs or requirements
from shared_libs.backend.app_kernel import create_service, ServiceConfig
```

## 🚀 Quick Start (Easiest Way)

Create a complete service in **~30 lines** using `create_service`:
```python
from fastapi import APIRouter, Depends
from shared_libs.backend.app_kernel import create_service, ServiceConfig, get_current_user, db_connection

# Your business logic
router = APIRouter(prefix="/widgets", tags=["widgets"])

@router.post("")
async def create_widget(data: dict, user=Depends(get_current_user), db=Depends(db_connection)):
    return await db.save_entity("widgets", {"owner": user.id, **data})

@router.get("")
async def list_widgets(user=Depends(get_current_user), db=Depends(db_connection)):
    return await db.find_entities("widgets", where_clause="[owner] = ?", params=(user.id,))

# Create the app - that's it!
app = create_service(
    name="widget_service",
    routers=[router],
    config=ServiceConfig.from_env(),  # Uses JWT_SECRET, REDIS_URL, DATABASE_NAME env vars
)
```

**What you get for free:**
- ✅ JWT authentication (`/api/v1/auth/login`, `/api/v1/auth/register`)
- ✅ Database connection pool (inject via `Depends(db_connection)`)
- ✅ CORS (configured or `*`)
- ✅ Security headers
- ✅ Request ID tracking
- ✅ Structured logging
- ✅ Metrics endpoint (`/metrics`)
- ✅ Health endpoints (`/healthz`, `/readyz`)
- ✅ Rate limiting (if `REDIS_URL` set)
- ✅ Background jobs (if `REDIS_URL` set)
- ✅ Error handling

## Database Connection

The kernel manages database connections. **Never use `DatabaseManager.connect()` directly in apps.**

### In Routes (FastAPI Dependency)
```python
from fastapi import Depends
from shared_libs.backend.app_kernel import db_connection, get_current_user

@router.get("/users/{user_id}")
async def get_user(user_id: str, db=Depends(db_connection)):
    return await db.get_entity("users", user_id)

@router.post("/users")
async def create_user(data: dict, db=Depends(db_connection)):
    return await db.save_entity("users", data)

@router.get("/users")
async def list_users(db=Depends(db_connection)):
    return await db.find_entities("users", order_by="[created_at] DESC", limit=100)
```

### In Workers/Scripts (Context Manager)
```python
from shared_libs.backend.app_kernel import get_db_connection

async def process_job(payload: dict):
    async with get_db_connection() as db:
        item = await db.get_entity("items", payload["item_id"])
        item["processed"] = True
        await db.save_entity("items", item)
```

### In Service Functions (Pass db as Parameter)

For functions called from routes, pass the `db` connection as a parameter:
```python
# src/service.py
async def deploy_service(db, user_id: str, project_name: str, ...):
    project = await db.get_entity("projects", project_id)
    await db.save_entity("deployments", {...})

# routes.py
@router.post("/deploy")
async def deploy(req: DeployRequest, user=Depends(get_current_user), db=Depends(db_connection)):
    return await deploy_service(db, user.id, req.project_name, ...)
```

### Database Configuration

Configure in `ServiceConfig` (NOT scattered across routes):
```python
config = ServiceConfig(
    # SQLite (default)
    database_name="./data/myapp.db",
    database_type="sqlite",
    
    # Or PostgreSQL
    database_name="myapp",
    database_type="postgres",
    database_host="localhost",
    database_port=5432,
    database_user="postgres",
    database_password="secret",
    
    # Or MySQL
    database_name="myapp",
    database_type="mysql",
    database_host="localhost",
    database_port=3306,
    database_user="root",
    database_password="secret",
)
```

Or use environment variables:
```bash
DATABASE_NAME=./data/myapp.db
DATABASE_TYPE=sqlite
# Or for postgres:
DATABASE_NAME=myapp
DATABASE_TYPE=postgres
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_USER=postgres
DATABASE_PASSWORD=secret
```

### Schema Initialization

Provide a `schema_init` function to create tables on startup:
```python
async def init_schema(db):
    """Called once on startup."""
    await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE,
            name TEXT,
            created_at TEXT
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS widgets (
            id TEXT PRIMARY KEY,
            owner TEXT,
            name TEXT,
            created_at TEXT
        )
    """)

app = create_service(
    name="myapp",
    routers=[router],
    schema_init=init_schema,  # <-- Pass your schema function
    config=ServiceConfig.from_env(),
)
```

## With Background Jobs
```python
from shared_libs.backend.app_kernel import create_service, ServiceConfig, get_job_client, get_db_connection

# Task handler (runs in worker process)
async def process_order(payload, ctx):
    order_id = payload["order_id"]
    
    # Use get_db_connection in workers
    async with get_db_connection() as db:
        order = await db.get_entity("orders", order_id)
        order["status"] = "processed"
        await db.save_entity("orders", order)
    
    return {"status": "done"}

# Route that enqueues work
router = APIRouter(prefix="/orders")

@router.post("")
async def create_order(data: dict, user=Depends(get_current_user), db=Depends(db_connection)):
    order = await db.save_entity("orders", {"user_id": user.id, "status": "pending", **data})
    
    client = get_job_client()
    result = await client.enqueue("process_order", {"order_id": order["id"]}, user_id=user.id)
    
    return {"order_id": order["id"], "job_id": result.job_id}

# Create app with tasks
app = create_service(
    name="order_service",
    routers=[router],
    tasks={"process_order": process_order},  # Register task handlers
    config=ServiceConfig.from_env(),
)
```

## ServiceConfig Options
```python
config = ServiceConfig(
    # Auth
    jwt_secret="your-secret",      # Required for production
    jwt_expiry_hours=24,
    auth_enabled=True,
    allow_self_signup=False,
    
    # Database (kernel manages connection pool)
    database_name="./data/myapp.db",
    database_type="sqlite",  # or "postgres", "mysql"
    
    # Redis (enables jobs, rate limiting)
    redis_url="redis://localhost:6379",
    
    # CORS
    cors_origins=["http://localhost:3000"],
    
    # Rate limiting
    rate_limit_requests=100,
    rate_limit_window=60,
    
    # Debug
    debug=False,
)

# Or load from environment variables
config = ServiceConfig.from_env()  # Reads JWT_SECRET, REDIS_URL, DATABASE_NAME, etc.
```

## Advanced: Manual Initialization

For more control, use `init_app_kernel` directly:
```python
from fastapi import FastAPI
from shared_libs.backend.app_kernel import init_app_kernel, KernelSettings, JobRegistry
from shared_libs.backend.app_kernel.settings import AuthSettings, RedisSettings

app = FastAPI()

# 1. Create job registry and register tasks
registry = JobRegistry()

@registry.task("process_document")
async def process_document(payload, ctx):
    doc_id = payload["doc_id"]
    # Process the document...
    return {"status": "done"}

# 2. Configure settings (frozen after creation)
settings = KernelSettings(
    auth=AuthSettings(token_secret=os.environ["JWT_SECRET"]),
    redis=RedisSettings(url=os.environ["REDIS_URL"]),
)

# 3. Initialize kernel (for API process)
init_app_kernel(app, settings, registry)

# NOTE: Workers run as SEPARATE PROCESSES - see "Running Workers" section
```

## Auto-Mounted Routes

The kernel automatically mounts common routes based on `FeatureSettings`. **No manual `include_router` needed.**

### Defaults (safe for production)

| Feature | Default | Endpoint |
|---------|---------|----------|
| Health | ✅ ON | `GET /healthz`, `GET /readyz` |
| Metrics | ✅ ON (admin-protected) | `GET /metrics` |
| Auth routes | ✅ ON (if local auth) | `/auth/login`, `/auth/me`, `/auth/refresh` |
| Self-signup | ❌ OFF | `/auth/register` (disabled) |
| Audit routes | ❌ OFF | `GET /audit` |

### Configuration
```python
from shared_libs.backend.app_kernel import KernelSettings, FeatureSettings

settings = KernelSettings(
    features=FeatureSettings(
        # Health endpoints (always safe, no auth)
        enable_health_routes=True,
        health_path="/healthz",
        ready_path="/readyz",
        
        # Metrics (protected by default)
        enable_metrics=True,
        metrics_path="/metrics",
        protect_metrics="admin",  # "admin", "internal", or "none"
        
        # Auth routes (for local auth mode)
        enable_auth_routes=True,
        auth_mode="local",        # "local", "apikey", or "external"
        allow_self_signup=False,  # IMPORTANT: disabled by default
        auth_prefix="/auth",
        
        # Audit (admin only, optional)
        enable_audit_routes=False,
    ),
)
```

### Environment Variable Overrides
```bash
KERNEL_ENABLE_HEALTH=true
KERNEL_ENABLE_METRICS=true
KERNEL_PROTECT_METRICS=admin
KERNEL_ENABLE_AUTH=true
KERNEL_AUTH_MODE=local
KERNEL_ALLOW_SIGNUP=false
KERNEL_ENABLE_AUDIT=false
```

### Health Checks

Configure custom health checks for `/readyz`:
```python
from shared_libs.backend.app_kernel import get_db_connection

async def check_db() -> tuple[bool, str]:
    try:
        async with get_db_connection() as db:
            await db.execute("SELECT 1")
        return True, "database connected"
    except Exception as e:
        return False, f"database error: {e}"

async def check_redis() -> tuple[bool, str]:
    try:
        await redis.ping()
        return True, "redis connected"
    except Exception as e:
        return False, f"redis error: {e}"

app = create_service(
    name="myapp",
    routers=[router],
    health_checks=[check_db, check_redis],
    config=ServiceConfig.from_env(),
)
```

## Running Workers

**Workers are separate processes, not part of FastAPI startup.**

The kernel provides worker code; your deployment decides how to run workers.
```python
# worker_main.py - Run this as a separate process
import asyncio
from shared_libs.backend.app_kernel.jobs import get_worker_manager

async def main():
    manager = get_worker_manager()
    await manager.start()
    
    # Block until shutdown signal
    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        await manager.stop()

if __name__ == "__main__":
    # Must call init_app_kernel first to configure
    from myapp import create_app_config
    create_app_config()  # Sets up kernel
    
    asyncio.run(main())
```

Deployment options:
- Separate container/process
- Supervisor/systemd managed
- Kubernetes separate deployment
- Never inside FastAPI lifecycle

## Module Structure
```
app_kernel/
├── app.py              # init_app_kernel(...)
├── bootstrap.py        # create_service(...) - simplified creation
├── settings.py         # KernelSettings configuration
├── auth/
│   ├── deps.py         # FastAPI dependencies (get_current_user, etc.)
│   ├── models.py       # UserIdentity, TokenPayload
│   └── utils.py        # Token/password utilities
├── db/
│   └── session.py      # db_connection, get_db_connection, get_db_manager
├── jobs/
│   ├── client.py       # Enqueue wrapper
│   ├── worker.py       # Worker loop
│   └── registry.py     # Task registry interface
├── streaming/
│   ├── leases.py       # StreamLeaseLimiter (Redis)
│   └── lifecycle.py    # stream_lease context manager
├── reliability/
│   ├── ratelimit.py    # Rate limiting
│   └── idempotency.py  # Request deduplication
└── observability/
    ├── logging.py      # Structured logging
    ├── metrics.py      # Metrics collection
    └── audit.py        # Audit trail
```

## Configuration

All settings are **frozen (immutable)** after creation. No per-request or runtime mutation is allowed.

### KernelSettings
```python
from shared_libs.backend.app_kernel import KernelSettings
from shared_libs.backend.app_kernel.settings import (
    RedisSettings,
    AuthSettings,
    JobSettings,
    StreamingSettings,
    ObservabilitySettings,
    ReliabilitySettings,
)

settings = KernelSettings(
    # Redis connection
    redis=RedisSettings(
        url="redis://localhost:6379",
        key_prefix="myapp:",
    ),
    
    # Authentication
    auth=AuthSettings(
        token_secret="your-secret-key",
        access_token_expires_minutes=15,
        refresh_token_expires_days=30,
    ),
    
    # Job queue
    jobs=JobSettings(
        worker_count=4,
        thread_pool_size=8,
        max_attempts=3,  # Advisory default, not enforced by kernel
    ),
    
    # Streaming limits
    streaming=StreamingSettings(
        max_concurrent_per_user=5,
        lease_ttl_seconds=180,
    ),
    
    # Logging/metrics
    observability=ObservabilitySettings(
        service_name="my-service",
        log_level="INFO",
    ),
    
    # Rate limiting
    reliability=ReliabilitySettings(
        rate_limit_requests=100,
        rate_limit_window_seconds=60,
    ),
)
```

## Authentication

### FastAPI Dependencies
```python
from fastapi import Depends
from shared_libs.backend.app_kernel import get_current_user, require_admin, UserIdentity

@app.get("/profile")
async def get_profile(user: UserIdentity = Depends(get_current_user)):
    return {"id": user.id, "email": user.email}

@app.post("/admin/action")
async def admin_action(user: UserIdentity = Depends(require_admin)):
    return {"admin_id": user.id}
```

### Token Utilities
```python
from shared_libs.backend.app_kernel.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

# Hash password
hashed = hash_password("user-password")

# Verify password
is_valid = verify_password("user-password", hashed)

# Create tokens
access = create_access_token(user, secret, expires_delta=timedelta(minutes=15))
refresh = create_refresh_token(user, secret, expires_delta=timedelta(days=30))
```

## Jobs

### Registering Tasks

Registry metadata (`timeout`, `max_attempts`) is **advisory only**. The kernel does not act as a scheduler - it dispatches work to registered processors and fails fast on unknown task names.
```python
from shared_libs.backend.app_kernel.jobs import JobRegistry, JobContext

registry = JobRegistry()

@registry.task("send_email", timeout=30.0, max_attempts=3)
async def send_email(payload: dict, ctx: JobContext) -> dict:
    email = payload["email"]
    subject = payload["subject"]
    
    # ctx contains job metadata
    print(f"Job {ctx.job_id}, attempt {ctx.attempt}/{ctx.max_attempts}")
    
    # Send email...
    return {"sent": True}

# Or register manually
registry.register("process_file", process_file_handler)
```

### Enqueueing Jobs
```python
from shared_libs.backend.app_kernel.jobs import get_job_client

client = get_job_client()

# Simple enqueue
result = await client.enqueue(
    "send_email",
    {"email": "user@example.com", "subject": "Hello"},
)

# With options
result = await client.enqueue(
    "process_document",
    {"doc_id": "123"},
    priority="high",
    user_id=current_user.id,
    timeout=60.0,
    max_attempts=5,
)

# Batch enqueue
results = await client.enqueue_many(
    "send_notification",
    [{"user_id": "1"}, {"user_id": "2"}, {"user_id": "3"}],
    priority="low",
)
```

## Streaming

### Safe Streaming with Leases
```python
from shared_libs.backend.app_kernel import stream_lease, StreamLimitExceeded
from fastapi import HTTPException

@app.post("/chat/stream")
async def stream_chat(user: UserIdentity = Depends(get_current_user)):
    try:
        async with stream_lease(user.id) as lease:
            async for chunk in generate_response():
                yield chunk
                
                # Optional: refresh for long streams
                if should_refresh:
                    lease.refresh()
                    
    except StreamLimitExceeded:
        raise HTTPException(429, "Too many concurrent streams")
```

## Complete Example
```python
# main.py
import os
from pathlib import Path
from fastapi import APIRouter, Depends

from shared_libs.backend.app_kernel import (
    create_service, 
    ServiceConfig, 
    get_current_user, 
    db_connection,
    get_db_connection,
    get_job_client,
)

SERVICE_DIR = Path(__file__).parent

# =============================================================================
# Schema
# =============================================================================

async def init_schema(db):
    await db.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            workspace_id TEXT,
            name TEXT NOT NULL,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_projects_workspace ON projects(workspace_id)")

# =============================================================================
# Tasks (for background jobs)
# =============================================================================

async def process_project(payload, ctx):
    async with get_db_connection() as db:
        project = await db.get_entity("projects", payload["project_id"])
        # Do processing...
        project["processed"] = True
        await db.save_entity("projects", project)
    return {"status": "done"}

# =============================================================================
# Routes
# =============================================================================

router = APIRouter(prefix="/projects", tags=["projects"])

@router.get("")
async def list_projects(user=Depends(get_current_user), db=Depends(db_connection)):
    return await db.find_entities(
        "projects", 
        where_clause="[workspace_id] = ?", 
        params=(user.id,),
        order_by="[created_at] DESC"
    )

@router.post("")
async def create_project(data: dict, user=Depends(get_current_user), db=Depends(db_connection)):
    project = await db.save_entity("projects", {
        "workspace_id": user.id,
        "name": data["name"],
    })
    
    # Optionally enqueue background work
    client = get_job_client()
    await client.enqueue("process_project", {"project_id": project["id"]})
    
    return project

@router.get("/{project_id}")
async def get_project(project_id: str, db=Depends(db_connection)):
    return await db.get_entity("projects", project_id)

# =============================================================================
# App
# =============================================================================

def _build_config() -> ServiceConfig:
    data_dir = SERVICE_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    
    return ServiceConfig(
        jwt_secret=os.environ.get("JWT_SECRET", "dev-secret"),
        database_name=str(data_dir / "app.db"),
        database_type="sqlite",
        redis_url=os.environ.get("REDIS_URL", ""),
    )

app = create_service(
    name="my_service",
    routers=[router],
    tasks={"process_project": process_project},
    schema_init=init_schema,
    config=_build_config(),
)
```

Run with:
```bash
JWT_SECRET=xxx uvicorn main:app --reload
```

Then hit `http://localhost:8000/docs` 🎉

---

## API Reference

<div style="background-color:#f8f9fa; border:1px solid #ddd; padding: 16px; border-radius: 8px; margin-bottom: 24px;margin-top: 24px;">

### Database Functions

| Function | Usage | Description |
|----------|-------|-------------|
| `db_connection` | `db=Depends(db_connection)` | FastAPI dependency - use in routes |
| `get_db_connection()` | `async with get_db_connection() as db:` | Context manager - use in workers/scripts |
| `get_db_manager()` | `manager = get_db_manager()` | Get underlying DatabaseManager (rarely needed) |
| `init_db_session(...)` | Called by kernel | Initialize connection pool (internal) |
| `close_db()` | Called by kernel | Close connections on shutdown (internal) |

**⚠️ NEVER use `DatabaseManager.connect()` directly in apps. The kernel manages the connection pool.**

</div>

<div style="background-color:#f8f9fa; border:1px solid #ddd; padding: 16px; border-radius: 8px; margin-bottom: 24px;margin-top: 24px;">

### class `ServiceConfig`

Configuration for `create_service()` with sensible defaults.

<details>
<summary><strong>Public Methods</strong></summary>

| Decorators | Method | Args | Returns | Category | Description |
|------------|--------|------|---------|----------|-------------|
| `@classmethod` | `from_env` | `prefix: str=""` | `ServiceConfig` | Factory | Load config from environment variables. |

</details>

<br>

<details>
<summary><strong>Attributes</strong></summary>

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `jwt_secret` | `str` | `"dev-secret-change-me"` | JWT signing secret (required for production) |
| `jwt_expiry_hours` | `int` | `24` | Access token expiry |
| `auth_enabled` | `bool` | `True` | Enable authentication |
| `allow_self_signup` | `bool` | `False` | Allow `/auth/register` |
| `database_name` | `str` | `None` | Database name or file path |
| `database_type` | `str` | `"sqlite"` | `"sqlite"`, `"postgres"`, or `"mysql"` |
| `database_host` | `str` | `"localhost"` | Database host |
| `database_port` | `int` | `None` | Database port (None = default for type) |
| `database_user` | `str` | `None` | Database user |
| `database_password` | `str` | `None` | Database password |
| `redis_url` | `str` | `None` | Redis URL (enables jobs, rate limiting) |
| `cors_origins` | `List[str]` | `["*"]` | CORS allowed origins |
| `rate_limit_requests` | `int` | `100` | Rate limit requests per window |
| `rate_limit_window` | `int` | `60` | Rate limit window in seconds |
| `debug` | `bool` | `False` | Enable debug mode |

</details>

</div>

<div style="background-color:#f8f9fa; border:1px solid #ddd; padding: 16px; border-radius: 8px; margin-bottom: 24px;margin-top: 24px;">

### function `create_service`

Create a production-ready FastAPI service with all kernel features.
```python
app = create_service(
    name="my_service",
    routers=[router],
    tasks={"task_name": handler},
    schema_init=init_schema,
    config=ServiceConfig.from_env(),
    health_checks=[check_db],
)
```

<details>
<summary><strong>Parameters</strong></summary>

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | `str` | Yes | Service name |
| `routers` | `List[APIRouter]` | Yes | FastAPI routers to mount |
| `config` | `ServiceConfig` | No | Configuration (defaults to `ServiceConfig()`) |
| `tasks` | `Dict[str, Callable]` | No | Background task handlers |
| `schema_init` | `Callable[[db], Awaitable]` | No | Database schema initializer |
| `health_checks` | `List[Callable]` | No | Custom health check functions |
| `on_startup` | `Callable` | No | Additional startup hook |
| `on_shutdown` | `Callable` | No | Additional shutdown hook |
| `version` | `str` | No | API version (default: `"1.0.0"`) |
| `description` | `str` | No | API description |

</details>

</div>