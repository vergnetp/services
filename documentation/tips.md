Architecture \& Streaming



Direct streaming (FastAPI workers) - Use for important/business operations (LLM tokens, chat, deployments). Workers are "occupied" but not blocked (async I/O). Limited to ~40 concurrent but fine for most use cases.

Redis queue streaming - Use for fire-and-forget operations (logs, telemetry, background cleanup). +1-5ms latency per event.

Rule may be broken for heavy CPU processing that would actually block the event loop - those should go to workers.



Node Agent Authentication



API key = HMAC-SHA256(do\_token, "node-agent:") - No user\_id involved

Key is deterministic - same DO token always produces same key

Snapshot creates key from DO token at creation time

If snapshot was created with different key logic → must recreate snapshot



Code Organization (RULE #1)



Logic goes in shared\_libs/infra/, routes are thin wrappers

Routes should: parse request → call infra service → return response

Routes should NOT: generate keys, do validation logic, orchestrate operations

If writing >5 lines in a route, it probably belongs in shared\_libs/

NodeAgentClient accepts do\_token, generates key internally - routes don't touch keys



Database Schema (SQLite Quirks)



PRAGMA table\_info() returns (cid, name, type, ...) where cid is index 0

Must detect SQLite format and use row\[1] for name, row\[2] for type

History tables must filter reserved fields (version, history\_timestamp, etc.) to avoid duplicates when main table has a version column



Dev Phase Mindset



Clean slate is fine - delete DB, recreate snapshots

Proper fixes over workarounds

No migration scripts needed in dev

