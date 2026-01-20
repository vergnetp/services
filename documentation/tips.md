# Tips & Key Learnings

## Architecture & Streaming

- **Direct streaming** (FastAPI workers) - Use for important/business operations (LLM tokens, chat, deployments). Workers are "occupied" but not blocked (async I/O). Limited to ~40 concurrent but fine for most use cases.
- **Redis queue streaming** - Use for fire-and-forget operations (logs, telemetry, background cleanup). +1-5ms latency per event.
- Rule may be broken for heavy CPU processing that would actually block the event loop - those should go to workers.

## Node Agent Authentication

- API key = `HMAC-SHA256(do_token, "node-agent:")` - No user_id involved
- Key is deterministic - same DO token always produces same key
- Snapshot creates key from DO token at creation time
- If snapshot was created with different key logic → must recreate snapshot

## Code Organization (RULE #1)

- Logic goes in `shared_libs/infra/`, routes are thin wrappers
- Routes should: parse request → call infra service → return response
- Routes should NOT: generate keys, do validation logic, orchestrate operations
- If writing >5 lines in a route, it probably belongs in `shared_libs/`
- `NodeAgentClient` accepts `do_token`, generates key internally - routes don't touch keys

## Database Schema (SQLite Quirks)

- `PRAGMA table_info()` returns `(cid, name, type, ...)` where cid is index 0
- Must detect SQLite format and use `row[1]` for name, `row[2]` for type
- History tables must filter reserved fields (version, history_timestamp, etc.) to avoid duplicates when main table has a version column

## Multi-Redis / Stateful Service Injection

### Service-Name-Based Environment Variables

When deploying services, stateful services (Redis, Postgres, etc.) in the same project are auto-discovered and injected as environment variables:

| Service Name | Environment Variable |
|--------------|---------------------|
| `redis` | `REDIS_URL` |
| `redis-business` | `REDIS_BUSINESS_URL` |
| `redis-logs` | `REDIS_LOGS_URL` |
| `postgres` | `DATABASE_URL` (backward compat) |
| `postgres-analytics` | `DATABASE_ANALYTICS_URL` |

**Naming Rules:**
- Default names (`redis`, `postgres`) → Standard env vars (`REDIS_URL`, `DATABASE_URL`)
- Custom names with suffix (`redis-xxx`) → `REDIS_XXX_URL`
- Dashes become underscores, uppercase

### Project-Scoped Discovery

- Stateful services are discovered **within the same project only**
- No workspace-wide injection (avoids ambiguity with multiple instances)
- Logic in `infra/deploy/injection.py` → `get_env_var_prefix()`

### Multiple Redis Instances - Architecture Benefits

Using multiple Redis instances (vs. named queues in one Redis):
- Each instance gets its own `QueueManager` with independent circuit breaker
- Physical/process isolation
- Independent scaling and resource allocation  
- If one Redis crashes, others unaffected
- No code-level named queue complexity

**Usage Pattern:**
```python
import os
from job_queue import QueueManager

main_queue = QueueManager(redis_url=os.getenv("REDIS_URL"))
logs_queue = QueueManager(redis_url=os.getenv("REDIS_LOGS_URL"))
```

## Dev Phase Mindset

- Clean slate is fine - delete DB, recreate snapshots
- Proper fixes over workarounds
- No migration scripts needed in dev
