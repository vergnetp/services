# Streaming Infrastructure

Real-time event delivery for FastAPI applications.

---

## Overview

The streaming module provides two distinct patterns for different use cases:

| Pattern | Use Case | Latency | Worker Blocking |
|---------|----------|---------|-----------------|
| **Direct Streaming** | LLM tokens, chat responses | Lowest (~0ms overhead) | Yes (but async) |
| **Queue-based Streaming** | Deployments, long tasks | +1-5ms per event | No |

---

## Module Location

```
shared_libs/backend/
├── streaming/                    ← Core module (NEW)
│   ├── events.py                # StreamEvent dataclass
│   ├── leases.py                # StreamLeaseLimiter (rate limiting)
│   ├── lifecycle.py             # stream_lease() context manager
│   ├── channels.py              # Redis Pub/Sub (sync + async)
│   ├── context.py               # StreamContext (for workers)
│   ├── sse.py                   # FastAPI SSE helpers
│   ├── storage.py               # OpenSearch persistence (optional)
│   └── README.md
│
├── infra/streaming/             ← Backward-compatible wrapper
│   └── __init__.py              # SSEEmitter, DeploymentEmitter
│
└── app_kernel/                  ← Re-exports stream_lease
    └── __init__.py
```

---

## Two Streaming Patterns Explained

### 1. Direct Streaming (LLM/Chat)

**How it works:**
```
Client ←──SSE──← FastAPI Worker ←──async──← LLM API
                     │
                     └── Worker is "occupied" but not blocked
                         (async I/O allows other requests)
```

**Characteristics:**
- FastAPI worker handles the stream directly
- No Redis hop between tokens (lowest latency)
- Worker is occupied for duration of stream (30-120 seconds typical)
- Limited by number of FastAPI workers (default: 40)

**Use when:**
- Low latency is critical (every millisecond matters)
- Streaming tokens from LLM APIs
- Short-to-medium duration streams

**Code:**
```python
from streaming import stream_lease, StreamLimitExceeded

@router.post("/chat/stream")
async def chat_stream(request: ChatRequest, user: UserIdentity = Depends(get_current_user)):
    try:
        async with stream_lease(str(user.id)) as lease:
            async def generate():
                async for token in llm_client.stream(request.prompt):
                    yield f"data: {json.dumps({'token': token})}\n\n"
                yield f"data: {json.dumps({'done': True})}\n\n"
            
            return StreamingResponse(generate(), media_type="text/event-stream")
    except StreamLimitExceeded:
        raise HTTPException(429, "Too many concurrent streams")
```

---

### 2. Queue-based Streaming (Deployments/Long Tasks)

**How it works (with Redis):**
```
Client ←──SSE──← FastAPI Worker ←──Redis Pub/Sub──← Background Thread
                     │                                    │
                     └── Returns immediately              └── Does actual work
                         (just subscribes to Redis)           (can take minutes)
```

**Fallback (without Redis):**
```
Client ←──SSE──← FastAPI Worker ←──in-memory queue──← Background Thread
                     │                                    │
                     └── BLOCKED polling queue            └── Does actual work
                         (1 of 40 workers occupied)
```

**Characteristics:**
- FastAPI worker returns immediately (just subscribes to Redis)
- Actual work happens in background worker
- Events delivered via Redis Pub/Sub
- +1-5ms latency per event (acceptable for deployments)

**Use when:**
- Long-running operations (minutes)
- Don't want to block FastAPI workers
- Need to scale workers independently

**Code (with automatic fallback):**
```python
from infra.streaming import DeploymentEmitter, sse_response

@router.post("/deploy")
async def deploy(request: DeployRequest, user: UserIdentity = Depends(get_current_user)):
    emitter = DeploymentEmitter()
    
    # This works with OR without Redis:
    # - With Redis: non-blocking, subscribes to Pub/Sub
    # - Without Redis: blocking fallback, polls in-memory queue
    return await sse_response(emitter, deploy_worker, request.dict())


def deploy_worker(config: dict, emitter: DeploymentEmitter):
    """Runs in background thread."""
    emitter.log("🚀 Starting deployment...")
    emitter.progress(10, step="building")
    # ... long work ...
    emitter.complete(success=True, deployment_id="abc123")
```

---

## Requirements

### Redis (Required for production)

| Feature | Without Redis | With Redis |
|---------|---------------|------------|
| Lease limiting | In-memory (single process only) | Distributed (all workers) |
| Queue-based streaming | **Fallback**: blocks 1 worker | ✅ Non-blocking |
| Direct streaming | ✅ Works (no cross-worker rate limiting) | ✅ Works with distributed rate limiting |

**Redis URL:**
```bash
REDIS_URL=redis://localhost:6379/0
```

**What happens without Redis:**
- `StreamLeaseLimiter` falls back to in-memory (per-process)
- Rate limits won't be shared across FastAPI workers
- **Streaming still works** but blocks 1 of 40 FastAPI workers per stream
- Warning logged: `⚠️ STREAMING FALLBACK: Redis not available...`

**Fallback behavior:**
```
With Redis (recommended):
  FastAPI → enqueue job → return SSE (subscribes to Redis) → Worker publishes → Client sees logs
  Result: Worker freed immediately, can handle other requests

Without Redis (fallback):
  FastAPI → run in thread → poll in-memory queue → Client sees logs  
  Result: Worker blocked for duration of stream (30s-5min), but user still sees logs
```

This means: **No Redis = limited to ~40 concurrent deploys**, but nothing breaks.

---

### Background Workers (Optional - for Redis mode only)

**What they do:**
- Process jobs from Redis queue
- Publish events to Redis Pub/Sub
- Run independently of FastAPI

**When needed:**
- Required if using `StreamContext` + `job_queue.enqueue()` pattern
- NOT required if using `SSEEmitter` + `sse_response(emitter, worker_func)` pattern

**How many workers?**

| Scenario | Workers | Notes |
|----------|---------|-------|
| Dev/testing | 1 | Single process is fine |
| Small production | 2-4 | On same server as app |
| Medium production | 4-8 | Can be on separate server |
| High throughput | 8-16+ | Dedicated worker server(s) |

**Rule of thumb:** Start with 2-4 workers, monitor queue depth, scale up if jobs wait too long.

**Where to deploy workers:**

| Option | Pros | Cons |
|--------|------|------|
| Same server as FastAPI | Simple, low latency | Competes for resources |
| Dedicated worker server | Isolated, scalable | More infrastructure |
| Multiple servers | High availability | Complexity |

**Starting workers:**

```python
# worker.py
from job_queue import QueueWorker, QueueConfig

config = QueueConfig(redis_url=os.getenv("REDIS_URL"))
worker = QueueWorker(config, max_workers=4)

# Register processors
config.operations_registry["infra.deploy.service.deploy_task"] = deploy_task

# Run
asyncio.run(worker.start())
```

```bash
# Run 4 worker processes
python -m worker &
python -m worker &
python -m worker &
python -m worker &
```

**What happens without workers (if using SSEEmitter pattern):**
- **Nothing breaks** - fallback runs work in thread
- Just limited to ~40 concurrent streams

**What happens without workers (if using StreamContext + job_queue pattern):**
- Jobs sit in Redis queue forever
- SSE response subscribes but never receives events
- Client sees infinite loading/ping events
- Eventually times out

---

## Initialization

### FastAPI App Startup

```python
from streaming import init_streaming
from job_queue import QueueRedisConfig
import os

@app.on_event("startup")
async def startup():
    redis_url = os.getenv("REDIS_URL")
    
    if redis_url:
        # Production: Redis-backed streaming
        redis_config = QueueRedisConfig(url=redis_url)
        init_streaming(
            redis_config,
            enable_storage=bool(os.getenv("OPENSEARCH_HOST")),
        )
    # else: fallback mode is automatic (no init needed)
```

### What `init_streaming()` does:

1. Initializes `StreamLeaseLimiter` with Redis
2. Initializes `SyncStreamChannel` and `AsyncStreamChannel`
3. Optionally initializes `OpenSearchEventStorage`

**If not called:** Fallback mode kicks in automatically when you use `SSEEmitter` + `sse_response(emitter, worker_func)`.

---

## Configuration

### Lease Limiting

```python
from streaming import StreamLeaseConfig, init_lease_limiter

config = StreamLeaseConfig(
    limit=5,              # Max concurrent streams per user
    ttl_seconds=180,      # Lease auto-expires (crash recovery)
    key_namespace="stream_leases",
)

init_lease_limiter(redis_config, config)
```

### Channels

```python
from streaming import ChannelConfig, init_channels

config = ChannelConfig(
    key_prefix="stream:",     # Redis channel prefix
    subscribe_timeout=1.0,    # Poll interval
    ping_interval=15.0,       # Keepalive ping
    max_idle_time=300.0,      # Close after 5 min idle
)

init_channels(redis_config, config)
```

### Event Storage (Optional)

```python
from streaming import init_event_storage

init_event_storage(
    host=os.getenv("OPENSEARCH_HOST", "localhost"),
    port=int(os.getenv("OPENSEARCH_PORT", "9200")),
    index_prefix="stream_events",
)
```

Or via environment variables:
```bash
OPENSEARCH_HOST=localhost
OPENSEARCH_PORT=9200
OPENSEARCH_USE_SSL=false
OPENSEARCH_AUTH_TYPE=none  # none, basic, aws
```

---

## Comparison: Tracing/Logs vs LLM Streaming

| Aspect | Tracing/Logs | LLM Streaming |
|--------|--------------|---------------|
| **Purpose** | Debug, audit, analytics | User-facing response |
| **Latency tolerance** | High (seconds OK) | Low (ms matters) |
| **Volume** | High (every request) | Lower (active chats) |
| **Delivery** | Best-effort | Must reach client |
| **Storage** | OpenSearch/files | Usually not stored |
| **Pattern** | Fire-and-forget | Direct streaming |

**Tracing/Logs flow:**
```
App → log.info() → Redis Queue → Worker → OpenSearch
                        ↓
              (async, can be delayed)
```

**LLM Streaming flow:**
```
App → llm.stream() → FastAPI → SSE → Client
                        ↓
              (sync path, no queue)
```

---

## Architecture Decision Guide

```
┌─────────────────────────────────────────────────────────┐
│  Do you need real-time delivery to the client?          │
│                                                         │
│  YES → Is latency critical (< 10ms per event)?          │
│        │                                                │
│        ├── YES → Use Direct Streaming                   │
│        │         (LLM tokens, chat)                     │
│        │                                                │
│        └── NO  → Use Queue-based Streaming              │
│                  (deployments, long tasks)              │
│                  • With Redis: non-blocking             │
│                  • Without Redis: fallback (blocking)   │
│                                                         │
│  NO  → Use regular logging/tracing                      │
│        (fire-and-forget to OpenSearch)                  │
└─────────────────────────────────────────────────────────┘
```

---

## Scaling Guidelines

### 1000 Concurrent Users

| Component | With Redis | Without Redis (fallback) |
|-----------|------------|--------------------------|
| FastAPI workers | 40 (default uvicorn) | 40 (same) |
| Redis | 1 instance, 2GB RAM | Not needed |
| Background workers | 4-8 processes | Not needed |
| Max concurrent streams | ~1000 | **~40** (limited by workers) |

### Bottleneck Analysis

| Pattern | Bottleneck | Solution |
|---------|------------|----------|
| Direct streaming | FastAPI workers | More workers, or switch to queue-based |
| Queue-based (Redis) | Background workers | More worker processes |
| Queue-based (fallback) | **FastAPI workers** | Add Redis! |
| Both | Redis | Redis cluster or separate instances |

---

## Failure Modes

| Failure | Direct Streaming | Queue-based Streaming |
|---------|------------------|----------------------|
| Redis down | Falls back to in-memory rate limiting | **Falls back to blocking mode** (logs warning) |
| Worker down | N/A | Jobs queue up, SSE times out |
| FastAPI restart | Streams interrupted | Streams interrupted (worker continues) |
| Client disconnect | Worker finishes anyway | Worker finishes anyway |

---

## Quick Reference

```python
# Direct streaming (LLM) - always works
from streaming import stream_lease, StreamLimitExceeded

async with stream_lease(user_id) as lease:
    async for token in llm.stream():
        yield token
        if should_refresh:
            await lease.refresh_async()

# Queue-based streaming (deployments) - with automatic fallback
from infra.streaming import DeploymentEmitter, sse_response

emitter = DeploymentEmitter()
return await sse_response(emitter, deploy_worker, config)

def deploy_worker(config, emitter):
    emitter.log("Working...")
    emitter.progress(50)
    emitter.complete(success=True)
```