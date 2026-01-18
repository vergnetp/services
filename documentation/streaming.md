\\# Streaming Infrastructure







Real-time event delivery for FastAPI applications.







---







\\## Overview







The streaming module provides two distinct patterns for different use cases:







| Pattern | Use Case | Latency | Worker Blocking |



|---------|----------|---------|-----------------|



| \\\*\\\*Direct Streaming\\\*\\\* | LLM tokens, chat responses | Lowest (~0ms overhead) | Yes (but async) |



| \\\*\\\*Queue-based Streaming\\\*\\\* | Deployments, long tasks | +1-5ms per event | No |







---







\\## Module Location







```



shared\\\_libs/backend/



â”œâ”€â”€ streaming/                    â† Core module (NEW)



â”‚   â”œâ”€â”€ events.py                # StreamEvent dataclass



â”‚   â”œâ”€â”€ leases.py                # StreamLeaseLimiter (rate limiting)



â”‚   â”œâ”€â”€ lifecycle.py             # stream\\\_lease() context manager



â”‚   â”œâ”€â”€ channels.py              # Redis Pub/Sub (sync + async)



â”‚   â”œâ”€â”€ context.py               # StreamContext (for workers)



â”‚   â”œâ”€â”€ sse.py                   # FastAPI SSE helpers



â”‚   â”œâ”€â”€ storage.py               # OpenSearch persistence (optional)



â”‚   â””â”€â”€ README.md



â”‚



â”œâ”€â”€ infra/streaming/             â† Backward-compatible wrapper



â”‚   â””â”€â”€ \\\_\\\_init\\\_\\\_.py              # SSEEmitter, DeploymentEmitter



â”‚



â””â”€â”€ app\\\_kernel/                  â† Re-exports stream\\\_lease



\&nbsp;   â””â”€â”€ \\\_\\\_init\\\_\\\_.py



```







---







\\## Two Streaming Patterns Explained







\\### 1. Direct Streaming (LLM/Chat)







\\\*\\\*How it works:\\\*\\\*



```



Client â†â”€â”€SSEâ”€â”€â† FastAPI Worker â†â”€â”€asyncâ”€â”€â† LLM API



\&nbsp;                    â”‚



\&nbsp;                    â””â”€â”€ Worker is "occupied" but not blocked



\&nbsp;                        (async I/O allows other requests)



```







\\\*\\\*Characteristics:\\\*\\\*



\\- FastAPI worker handles the stream directly



\\- No Redis hop between tokens (lowest latency)



\\- Worker is occupied for duration of stream (30-120 seconds typical)



\\- Limited by number of FastAPI workers (default: 40)







\\\*\\\*Use when:\\\*\\\*



\\- Low latency is critical (every millisecond matters)



\\- Streaming tokens from LLM APIs



\\- Short-to-medium duration streams







\\\*\\\*Code:\\\*\\\*



```python



from streaming import stream\\\_lease, StreamLimitExceeded







@router.post("/chat/stream")



async def chat\\\_stream(request: ChatRequest, user: UserIdentity = Depends(get\\\_current\\\_user)):



\&nbsp;   try:



\&nbsp;       async with stream\\\_lease(str(user.id)) as lease:



\&nbsp;           async def generate():



\&nbsp;               async for token in llm\\\_client.stream(request.prompt):



\&nbsp;                   yield f"data: {json.dumps({'token': token})}\\\\n\\\\n"



\&nbsp;               yield f"data: {json.dumps({'done': True})}\\\\n\\\\n"



\&nbsp;           



\&nbsp;           return StreamingResponse(generate(), media\\\_type="text/event-stream")



\&nbsp;   except StreamLimitExceeded:



\&nbsp;       raise HTTPException(429, "Too many concurrent streams")



```







---







\\### 2. Queue-based Streaming (Deployments/Long Tasks)







\\\*\\\*How it works:\\\*\\\*



```



Client â†â”€â”€SSEâ”€â”€â† FastAPI Worker â†â”€â”€Redis Pub/Subâ”€â”€â† Background Worker



\&nbsp;                    â”‚                                    â”‚



\&nbsp;                    â””â”€â”€ Returns immediately              â””â”€â”€ Does actual work



\&nbsp;                        (just subscribes to Redis)           (can take minutes)



```







\\\*\\\*Characteristics:\\\*\\\*



\\- FastAPI worker returns immediately (just subscribes to Redis)



\\- Actual work happens in background worker



\\- Events delivered via Redis Pub/Sub



\\- +1-5ms latency per event (acceptable for deployments)







\\\*\\\*Use when:\\\*\\\*



\\- Long-running operations (minutes)



\\- Don't want to block FastAPI workers



\\- Need to scale workers independently







\\\*\\\*Code:\\\*\\\*



```python



from streaming import StreamContext, sse\\\_response



from job\\\_queue import QueueManager







@router.post("/deploy")



async def deploy(request: DeployRequest, user: UserIdentity = Depends(get\\\_current\\\_user)):



\&nbsp;   ctx = StreamContext.create(



\&nbsp;       workspace\\\_id=str(user.id),



\&nbsp;       project=request.project,



\&nbsp;       env=request.environment,



\&nbsp;       service=request.service,



\&nbsp;   )



\&nbsp;   



\&nbsp;   # Enqueue to background worker (returns immediately)



\&nbsp;   queue\\\_manager.enqueue(



\&nbsp;       entity={"stream\\\_ctx": ctx.to\\\_dict(), "config": request.dict()},



\&nbsp;       processor="infra.deploy.service.deploy\\\_task",



\&nbsp;   )



\&nbsp;   



\&nbsp;   # Return SSE (subscribes to Redis, doesn't block)



\&nbsp;   return await sse\\\_response(ctx.channel\\\_id)











\\# In background worker



def deploy\\\_task(entity: dict):



\&nbsp;   ctx = StreamContext.from\\\_dict(entity\\\["stream\\\_ctx"])



\&nbsp;   



\&nbsp;   ctx.log("ðŸš€ Starting deployment...")



\&nbsp;   ctx.progress(10, step="building")



\&nbsp;   # ... long work ...



\&nbsp;   ctx.complete(success=True, deployment\\\_id="abc123")



```







---







\\## Requirements







\\### Redis (Required for production)







| Feature | Without Redis | With Redis |



|---------|---------------|------------|



| Lease limiting | In-memory (single process only) | Distributed (all workers) |



| Queue-based streaming | âŒ Not available | âœ… Works |



| Direct streaming | âœ… Works (no rate limiting across workers) | âœ… Works with distributed rate limiting |







\\\*\\\*Redis URL:\\\*\\\*



```bash



REDIS\\\_URL=redis://localhost:6379/0



```







\\\*\\\*What happens without Redis:\\\*\\\*



\\- `StreamLeaseLimiter` falls back to in-memory (per-process)



\\- Rate limits won't be shared across FastAPI workers



\\- Queue-based streaming won't work at all



\\- Direct streaming still works (just no cross-worker rate limiting)







---







\\### Background Workers (Required for queue-based streaming)







\\\*\\\*What they do:\\\*\\\*



\\- Process jobs from Redis queue



\\- Publish events to Redis Pub/Sub



\\- Run independently of FastAPI







\\\*\\\*How many workers?\\\*\\\*







| Scenario | Workers | Notes |



|----------|---------|-------|



| Dev/testing | 1 | Single process is fine |



| Small production | 2-4 | On same server as app |



| Medium production | 4-8 | Can be on separate server |



| High throughput | 8-16+ | Dedicated worker server(s) |







\\\*\\\*Rule of thumb:\\\*\\\* Start with 2-4 workers, monitor queue depth, scale up if jobs wait too long.







\\\*\\\*Where to deploy workers:\\\*\\\*







| Option | Pros | Cons |



|--------|------|------|



| Same server as FastAPI | Simple, low latency | Competes for resources |



| Dedicated worker server | Isolated, scalable | More infrastructure |



| Multiple servers | High availability | Complexity |







\\\*\\\*Starting workers:\\\*\\\*







```python



\\# worker.py



from job\\\_queue import QueueWorker, QueueConfig







config = QueueConfig(redis\\\_url=os.getenv("REDIS\\\_URL"))



worker = QueueWorker(config, max\\\_workers=4)







\\# Register processors



config.operations\\\_registry\\\["infra.deploy.service.deploy\\\_task"] = deploy\\\_task







\\# Run



asyncio.run(worker.start())



```







```bash



\\# Run 4 worker processes



python -m worker \\\&



python -m worker \\\&



python -m worker \\\&



python -m worker \\\&



```







\\\*\\\*What happens without workers:\\\*\\\*



\\- Jobs sit in Redis queue forever



\\- SSE response subscribes but never receives events



\\- Client sees infinite loading/ping events



\\- Eventually times out







---







\\## Initialization







\\### FastAPI App Startup







```python



from streaming import init\\\_streaming



from job\\\_queue import QueueRedisConfig



import os







@app.on\\\_event("startup")



async def startup():



\&nbsp;   redis\\\_url = os.getenv("REDIS\\\_URL")



\&nbsp;   



\&nbsp;   if redis\\\_url:



\&nbsp;       redis\\\_config = QueueRedisConfig(url=redis\\\_url)



\&nbsp;       init\\\_streaming(



\&nbsp;           redis\\\_config,



\&nbsp;           enable\\\_storage=bool(os.getenv("OPENSEARCH\\\_HOST")),  # Optional



\&nbsp;       )



\&nbsp;   else:



\&nbsp;       # Dev mode: in-memory lease limiting, no queue-based streaming



\&nbsp;       from streaming import init\\\_lease\\\_limiter



\&nbsp;       init\\\_lease\\\_limiter(use\\\_memory=True)



```







\\### What `init\\\_streaming()` does:







1\\. Initializes `StreamLeaseLimiter` with Redis



2\\. Initializes `SyncStreamChannel` and `AsyncStreamChannel`



3\\. Optionally initializes `OpenSearchEventStorage`







---







\\## Configuration







\\### Lease Limiting







```python



from streaming import StreamLeaseConfig, init\\\_lease\\\_limiter







config = StreamLeaseConfig(



\&nbsp;   limit=5,              # Max concurrent streams per user



\&nbsp;   ttl\\\_seconds=180,      # Lease auto-expires (crash recovery)



\&nbsp;   key\\\_namespace="stream\\\_leases",



)







init\\\_lease\\\_limiter(redis\\\_config, config)



```







\\### Channels







```python



from streaming import ChannelConfig, init\\\_channels







config = ChannelConfig(



\&nbsp;   key\\\_prefix="stream:",     # Redis channel prefix



\&nbsp;   subscribe\\\_timeout=1.0,    # Poll interval



\&nbsp;   ping\\\_interval=15.0,       # Keepalive ping



\&nbsp;   max\\\_idle\\\_time=300.0,      # Close after 5 min idle



)







init\\\_channels(redis\\\_config, config)



```







\\### Event Storage (Optional)







```python



from streaming import init\\\_event\\\_storage







init\\\_event\\\_storage(



\&nbsp;   host=os.getenv("OPENSEARCH\\\_HOST", "localhost"),



\&nbsp;   port=int(os.getenv("OPENSEARCH\\\_PORT", "9200")),



\&nbsp;   index\\\_prefix="stream\\\_events",



)



```







Or via environment variables:



```bash



OPENSEARCH\\\_HOST=localhost



OPENSEARCH\\\_PORT=9200



OPENSEARCH\\\_USE\\\_SSL=false



OPENSEARCH\\\_AUTH\\\_TYPE=none  # none, basic, aws



```







---







\\## Comparison: Tracing/Logs vs LLM Streaming







| Aspect | Tracing/Logs | LLM Streaming |



|--------|--------------|---------------|



| \\\*\\\*Purpose\\\*\\\* | Debug, audit, analytics | User-facing response |



| \\\*\\\*Latency tolerance\\\*\\\* | High (seconds OK) | Low (ms matters) |



| \\\*\\\*Volume\\\*\\\* | High (every request) | Lower (active chats) |



| \\\*\\\*Delivery\\\*\\\* | Best-effort | Must reach client |



| \\\*\\\*Storage\\\*\\\* | OpenSearch/files | Usually not stored |



| \\\*\\\*Pattern\\\*\\\* | Fire-and-forget | Direct streaming |







\\\*\\\*Tracing/Logs flow:\\\*\\\*



```



App â†’ log.info() â†’ Redis Queue â†’ Worker â†’ OpenSearch



\&nbsp;                       â†“



\&nbsp;             (async, can be delayed)



```







\\\*\\\*LLM Streaming flow:\\\*\\\*



```



App â†’ llm.stream() â†’ FastAPI â†’ SSE â†’ Client



\&nbsp;                       â†“



\&nbsp;             (sync path, no queue)



```







---







\\## Architecture Decision Guide







```



â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”



â”‚  Do you need real-time delivery to the client?          â”‚



â”‚                                                         â”‚



â”‚  YES â†’ Is latency critical (< 10ms per event)?          â”‚



â”‚        â”‚                                                â”‚



â”‚        â”œâ”€â”€ YES â†’ Use Direct Streaming                   â”‚



â”‚        â”‚         (LLM tokens, chat)                     â”‚



â”‚        â”‚                                                â”‚



â”‚        â””â”€â”€ NO  â†’ Use Queue-based Streaming              â”‚



â”‚                  (deployments, long tasks)              â”‚



â”‚                                                         â”‚



â”‚  NO  â†’ Use regular logging/tracing                      â”‚



â”‚        (fire-and-forget to OpenSearch)                  â”‚



â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜



```







---







\\## Scaling Guidelines







\\### 1000 Concurrent Users







| Component | Recommendation |



|-----------|----------------|



| FastAPI workers | 40 (default uvicorn) |



| Redis | 1 instance, 2GB RAM |



| Background workers | 4-8 processes |



| Max concurrent direct streams | ~200 (5 per user Ã— 40 active) |



| Max queue-based streams | ~1000 (limited by Redis Pub/Sub) |







\\### Bottleneck Analysis







| Pattern | Bottleneck | Solution |



|---------|------------|----------|



| Direct streaming | FastAPI workers | More workers, or switch to queue-based |



| Queue-based | Background workers | More worker processes |



| Both | Redis | Redis cluster or separate instances |







---







\\## Failure Modes







| Failure | Direct Streaming | Queue-based Streaming |



|---------|------------------|----------------------|



| Redis down | Falls back to in-memory rate limiting | âŒ Doesn't work |



| Worker down | N/A | Jobs queue up, SSE times out |



| FastAPI restart | Streams interrupted | Streams interrupted (worker continues) |



| Client disconnect | Worker finishes anyway | Worker finishes anyway |







---







\\## Quick Reference







```python



\\# Direct streaming (LLM)



from streaming import stream\\\_lease, StreamLimitExceeded







async with stream\\\_lease(user\\\_id) as lease:



\&nbsp;   async for token in llm.stream():



\&nbsp;       yield token



\&nbsp;       if should\\\_refresh:



\&nbsp;           await lease.refresh\\\_async()







\\# Queue-based streaming (deployments)



from streaming import StreamContext, sse\\\_response







ctx = StreamContext.create(workspace\\\_id=user\\\_id, project="myapp")



queue\\\_manager.enqueue(entity={"ctx": ctx.to\\\_dict()}, processor=task)



return await sse\\\_response(ctx.channel\\\_id)







\\# In worker



def task(entity):



\&nbsp;   ctx = StreamContext.from\\\_dict(entity\\\["ctx"])



\&nbsp;   ctx.log("Working...")



\&nbsp;   ctx.progress(50)



\&nbsp;   ctx.complete(success=True)



```





