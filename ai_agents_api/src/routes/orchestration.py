"""
Multi-agent orchestration endpoints.

Patterns:
- Parallel: Run multiple agents concurrently on same input
- Supervisor: Plan → Delegate → Synthesize 
- Pipeline: Sequential agent chain
- Debate: Multi-round discussion with consensus detection

All endpoints support SSE streaming.
"""

import json
import asyncio
import time
import uuid
from datetime import datetime, timezone
from typing import Optional, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from ..deps import get_db, AgentStore, Agent, get_agent_provider
from ..auth import get_current_user, CurrentUser
from ..schemas import (
    ParallelRequest, ParallelResponse,
    SupervisorRequest, SupervisorResponse,
    PipelineRequest, PipelineResponse,
    DebateRequest, DebateResponse,
    AgentResultSchema, DebateMessage,
    OrchestrationRunResponse, OrchestrationPattern,
    ErrorResponse,
)
from ...config import get_settings

router = APIRouter(prefix="/orchestration", tags=["orchestration"])


# =============================================================================
# Helpers
# =============================================================================

def _get_api_key(provider: str, settings) -> str:
    if provider == "anthropic":
        return settings.anthropic_api_key
    if provider == "groq":
        return settings.groq_api_key
    if provider == "ollama":
        return None
    return settings.openai_api_key


async def _load_agents(
    agent_ids: list[str],
    db,
    user: CurrentUser,
    settings,
) -> dict[str, Agent]:
    """Load multiple agents by ID."""
    store = AgentStore(db)
    agents = {}
    
    for agent_id in agent_ids:
        agent_data = await store.get(agent_id, user=user)
        if not agent_data:
            raise HTTPException(
                status_code=404,
                detail=f"Agent not found: {agent_id}"
            )
        
        provider_name = agent_data.get("provider", "openai")
        model = agent_data.get("model", "gpt-4")
        
        cached_provider = get_agent_provider(
            provider_name,
            model,
            api_key_fn=lambda p: _get_api_key(p, settings),
        )
        
        agent = await Agent.from_store(
            agent_id=agent_id,
            conn=db,
            provider=cached_provider,
        )
        agents[agent_id] = agent
    
    return agents


async def _run_agent(
    agent: Agent,
    message: str,
    timeout: float,
) -> AgentResultSchema:
    """Run a single agent with timeout."""
    start = time.time()
    
    try:
        response = await asyncio.wait_for(
            agent.chat(message),
            timeout=timeout
        )
        
        duration_ms = int((time.time() - start) * 1000)
        
        return AgentResultSchema(
            agent_id=agent.agent_id,
            agent_name=agent.name,
            content=response.content,
            success=True,
            duration_ms=duration_ms,
            cost=response.cost,
            usage=response.usage,
        )
    except asyncio.TimeoutError:
        return AgentResultSchema(
            agent_id=agent.agent_id,
            agent_name=agent.name,
            content="",
            success=False,
            error=f"Timeout after {timeout}s",
            duration_ms=int((time.time() - start) * 1000),
        )
    except Exception as e:
        return AgentResultSchema(
            agent_id=agent.agent_id,
            agent_name=agent.name,
            content="",
            success=False,
            error=str(e),
            duration_ms=int((time.time() - start) * 1000),
        )


def _format_combined(results: list[AgentResultSchema], format: str) -> str:
    """Format multiple results into combined output."""
    if format == "xml":
        parts = []
        for r in results:
            if r.success:
                parts.append(f"<agent name=\"{r.agent_name}\">\n{r.content}\n</agent>")
        return "\n\n".join(parts)
    elif format == "labeled":
        parts = []
        for r in results:
            if r.success:
                parts.append(f"**{r.agent_name}:**\n{r.content}")
        return "\n\n---\n\n".join(parts)
    else:  # numbered
        parts = []
        for i, r in enumerate(results, 1):
            if r.success:
                parts.append(f"{i}. [{r.agent_name}]\n{r.content}")
        return "\n\n".join(parts)


async def _save_run(
    db,
    user_id: str,
    workspace_id: Optional[str],
    pattern: str,
    agent_ids: list[str],
    message: str,
    config: dict,
    results: dict,
    total_cost: float,
    duration_ms: int,
) -> str:
    """Save orchestration run to database."""
    run_id = str(uuid.uuid4())
    
    await db.save_entity("orchestration_runs", {
        "id": run_id,
        "workspace_id": workspace_id,
        "user_id": user_id,
        "pattern": pattern,
        "agent_ids": json.dumps(agent_ids),
        "input_message": message,
        "config": json.dumps(config),
        "results": json.dumps(results),
        "total_cost": total_cost,
        "duration_ms": duration_ms,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    
    return run_id


# =============================================================================
# Parallel Execution
# =============================================================================

@router.post("/parallel", response_model=ParallelResponse)
async def run_parallel(
    data: ParallelRequest,
    stream: bool = False,
    current_user: CurrentUser = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Run multiple agents in parallel on the same input.
    
    All agents receive the same message and run concurrently.
    Results are collected and formatted according to result_format.
    """
    if stream:
        return await _stream_parallel(data, current_user, db)
    
    settings = get_settings()
    start = time.time()
    
    # Load all agents
    agents = await _load_agents(data.agent_ids, db, current_user, settings)
    
    # Run in parallel
    tasks = [
        _run_agent(agent, data.message, data.timeout)
        for agent in agents.values()
    ]
    
    if data.fail_fast:
        # Stop on first failure
        results = []
        for coro in asyncio.as_completed(tasks):
            result = await coro
            results.append(result)
            if not result.success:
                # Cancel remaining
                for t in tasks:
                    if hasattr(t, 'cancel'):
                        t.cancel()
                break
    else:
        results = await asyncio.gather(*tasks)
    
    # Order results by original agent_ids order
    ordered_results = []
    for agent_id in data.agent_ids:
        for r in results:
            if r.agent_id == agent_id:
                ordered_results.append(r)
                break
    
    total_duration = int((time.time() - start) * 1000)
    total_cost = sum(r.cost for r in ordered_results)
    successful = sum(1 for r in ordered_results if r.success)
    
    response = ParallelResponse(
        results=ordered_results,
        successful=successful,
        failed=len(ordered_results) - successful,
        combined_output=_format_combined(ordered_results, data.result_format),
        total_duration_ms=total_duration,
        total_cost=total_cost,
    )
    
    # Save run
    await _save_run(
        db, current_user.id, None, "parallel",
        data.agent_ids, data.message,
        {"timeout": data.timeout, "fail_fast": data.fail_fast, "result_format": data.result_format},
        response.model_dump(),
        total_cost, total_duration,
    )
    
    return response


async def _stream_parallel(
    data: ParallelRequest,
    user: CurrentUser,
    db,
) -> StreamingResponse:
    """Stream parallel execution results."""
    
    async def generate() -> AsyncGenerator[str, None]:
        settings = get_settings()
        start = time.time()
        
        try:
            agents = await _load_agents(data.agent_ids, db, user, settings)
        except HTTPException as e:
            yield f"data: {json.dumps({'type': 'error', 'error': e.detail})}\n\n"
            return
        
        yield f"data: {json.dumps({'type': 'start', 'agent_count': len(agents)})}\n\n"
        
        results = []
        tasks = {
            asyncio.create_task(_run_agent(agent, data.message, data.timeout)): agent_id
            for agent_id, agent in agents.items()
        }
        
        for coro in asyncio.as_completed(tasks.keys()):
            result = await coro
            results.append(result)
            
            yield f"data: {json.dumps({'type': 'agent_result', 'result': result.model_dump()})}\n\n"
            
            if data.fail_fast and not result.success:
                break
        
        total_duration = int((time.time() - start) * 1000)
        total_cost = sum(r.cost for r in results)
        
        yield f"data: {json.dumps({'type': 'done', 'total_duration_ms': total_duration, 'total_cost': total_cost})}\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream")


# =============================================================================
# Supervisor Pattern
# =============================================================================

@router.post("/supervisor", response_model=SupervisorResponse)
async def run_supervisor(
    data: SupervisorRequest,
    stream: bool = False,
    current_user: CurrentUser = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Supervisor pattern: Plan → Delegate → Synthesize.
    
    1. Planner analyzes task and creates execution plan
    2. Workers execute their assigned tasks (parallel or sequential)
    3. Synthesizer combines results into final output
    """
    if stream:
        return await _stream_supervisor(data, current_user, db)
    
    settings = get_settings()
    start = time.time()
    
    # Load worker agents
    workers = await _load_agents(data.agent_ids, db, current_user, settings)
    worker_names = {aid: agents.name for aid, agents in workers.items()}
    
    # Create planner prompt
    worker_list = "\n".join([f"- {name} (id: {aid})" for aid, name in worker_names.items()])
    planner_prompt = f"""You are a task planner. Analyze the user's request and create a plan.

Available workers:
{worker_list}

Based on the mode "{data.mode.value}":
- "all": Use all workers
- "selective": Choose the best workers for this task  
- "sequential": Assign tasks to be done in order

Respond with a JSON object:
{{
    "plan": "Brief description of the plan",
    "tasks": [
        {{"worker_id": "<agent_id>", "task": "<specific task for this worker>"}}
    ]
}}

Only output the JSON, no other text."""

    # Get planner agent (use first worker's provider for simplicity)
    first_worker = list(workers.values())[0]
    
    # Create a simple chat for planning
    plan_response = await first_worker.provider.chat(
        messages=[
            {"role": "system", "content": planner_prompt},
            {"role": "user", "content": data.message}
        ],
        temperature=0.3,
    )
    
    # Parse plan
    try:
        plan_text = plan_response.content
        # Extract JSON from response
        if "```json" in plan_text:
            plan_text = plan_text.split("```json")[1].split("```")[0]
        elif "```" in plan_text:
            plan_text = plan_text.split("```")[1].split("```")[0]
        
        plan_data = json.loads(plan_text.strip())
        plan_description = plan_data.get("plan", "No plan description")
        tasks = plan_data.get("tasks", [])
    except (json.JSONDecodeError, KeyError):
        # Fallback: use all workers with the original message
        plan_description = "Using all workers (plan parsing failed)"
        tasks = [{"worker_id": aid, "task": data.message} for aid in data.agent_ids]
    
    # Execute tasks
    worker_results = []
    
    if data.mode.value == "sequential":
        # Sequential execution
        context = data.message
        for task_info in tasks:
            worker_id = task_info.get("worker_id")
            task = task_info.get("task", context)
            
            if worker_id in workers:
                result = await _run_agent(workers[worker_id], task, 60.0)
                worker_results.append(result)
                if result.success:
                    context = result.content  # Pass to next
    else:
        # Parallel execution
        parallel_tasks = []
        for task_info in tasks:
            worker_id = task_info.get("worker_id")
            task = task_info.get("task", data.message)
            
            if worker_id in workers:
                parallel_tasks.append(_run_agent(workers[worker_id], task, 60.0))
        
        if parallel_tasks:
            worker_results = list(await asyncio.gather(*parallel_tasks))
    
    # Synthesize results
    synthesis_context = "\n\n".join([
        f"[{r.agent_name}]: {r.content}" 
        for r in worker_results if r.success
    ])
    
    synthesis_prompt = f"""Synthesize the following worker outputs into a coherent final response.

Original request: {data.message}

Worker outputs:
{synthesis_context}

Provide a comprehensive synthesis that addresses the original request."""

    synthesis_response = await first_worker.provider.chat(
        messages=[
            {"role": "system", "content": "You are a synthesizer. Combine multiple perspectives into a coherent response."},
            {"role": "user", "content": synthesis_prompt}
        ],
        temperature=0.5,
    )
    
    total_duration = int((time.time() - start) * 1000)
    total_cost = sum(r.cost for r in worker_results) + plan_response.cost + synthesis_response.cost
    
    response = SupervisorResponse(
        plan=plan_description,
        worker_results=worker_results,
        synthesis=synthesis_response.content,
        iterations=1,
        total_duration_ms=total_duration,
        total_cost=total_cost,
    )
    
    # Save run
    await _save_run(
        db, current_user.id, None, "supervisor",
        data.agent_ids, data.message,
        {"mode": data.mode.value, "max_iterations": data.max_iterations},
        response.model_dump(),
        total_cost, total_duration,
    )
    
    return response


async def _stream_supervisor(
    data: SupervisorRequest,
    user: CurrentUser,
    db,
) -> StreamingResponse:
    """Stream supervisor execution."""
    
    async def generate() -> AsyncGenerator[str, None]:
        settings = get_settings()
        start = time.time()
        
        try:
            workers = await _load_agents(data.agent_ids, db, user, settings)
        except HTTPException as e:
            yield f"data: {json.dumps({'type': 'error', 'error': e.detail})}\n\n"
            return
        
        yield f"data: {json.dumps({'type': 'phase', 'phase': 'planning'})}\n\n"
        
        # Planning phase
        worker_names = {aid: agent.name for aid, agent in workers.items()}
        worker_list = "\n".join([f"- {name} (id: {aid})" for aid, name in worker_names.items()])
        
        planner_prompt = f"""Analyze the request and create a plan.
Available workers: {worker_list}
Mode: {data.mode.value}
Respond with JSON: {{"plan": "...", "tasks": [{{"worker_id": "...", "task": "..."}}]}}"""

        first_worker = list(workers.values())[0]
        plan_response = await first_worker.provider.chat(
            messages=[
                {"role": "system", "content": planner_prompt},
                {"role": "user", "content": data.message}
            ],
            temperature=0.3,
        )
        
        try:
            plan_text = plan_response.content
            if "```json" in plan_text:
                plan_text = plan_text.split("```json")[1].split("```")[0]
            plan_data = json.loads(plan_text.strip())
            plan_description = plan_data.get("plan", "No plan")
            tasks = plan_data.get("tasks", [])
        except:
            plan_description = "Using all workers"
            tasks = [{"worker_id": aid, "task": data.message} for aid in data.agent_ids]
        
        yield f"data: {json.dumps({'type': 'plan', 'plan': plan_description, 'tasks': tasks})}\n\n"
        
        # Execution phase
        yield f"data: {json.dumps({'type': 'phase', 'phase': 'executing'})}\n\n"
        
        worker_results = []
        for task_info in tasks:
            worker_id = task_info.get("worker_id")
            task = task_info.get("task", data.message)
            
            if worker_id in workers:
                result = await _run_agent(workers[worker_id], task, 60.0)
                worker_results.append(result)
                yield f"data: {json.dumps({'type': 'worker_result', 'result': result.model_dump()})}\n\n"
        
        # Synthesis phase
        yield f"data: {json.dumps({'type': 'phase', 'phase': 'synthesizing'})}\n\n"
        
        synthesis_context = "\n\n".join([
            f"[{r.agent_name}]: {r.content}" for r in worker_results if r.success
        ])
        
        synthesis_response = await first_worker.provider.chat(
            messages=[
                {"role": "system", "content": "Synthesize the worker outputs into a coherent response."},
                {"role": "user", "content": f"Original: {data.message}\n\nOutputs:\n{synthesis_context}"}
            ],
            temperature=0.5,
        )
        
        total_duration = int((time.time() - start) * 1000)
        total_cost = sum(r.cost for r in worker_results) + plan_response.cost + synthesis_response.cost
        
        yield f"data: {json.dumps({'type': 'synthesis', 'content': synthesis_response.content})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'total_duration_ms': total_duration, 'total_cost': total_cost})}\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream")


# =============================================================================
# Pipeline
# =============================================================================

@router.post("/pipeline", response_model=PipelineResponse)
async def run_pipeline(
    data: PipelineRequest,
    stream: bool = False,
    current_user: CurrentUser = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Sequential agent pipeline.
    
    Each agent's output becomes the next agent's input.
    Optional transformers can modify the output between steps.
    """
    if stream:
        return await _stream_pipeline(data, current_user, db)
    
    settings = get_settings()
    start = time.time()
    
    agents = await _load_agents(data.agent_ids, db, current_user, settings)
    
    steps = []
    current_input = data.message
    
    for i, agent_id in enumerate(data.agent_ids):
        agent = agents[agent_id]
        
        result = await _run_agent(agent, current_input, 60.0)
        steps.append(result)
        
        if not result.success:
            if data.stop_on_error:
                break
            continue
        
        # Apply transformer if defined for this step
        if str(i) in data.transformers:
            transform_instruction = data.transformers[str(i)]
            # Simple transform: prepend instruction
            current_input = f"{transform_instruction}\n\nInput:\n{result.content}"
        else:
            current_input = result.content
    
    total_duration = int((time.time() - start) * 1000)
    total_cost = sum(s.cost for s in steps)
    final_output = steps[-1].content if steps and steps[-1].success else ""
    
    response = PipelineResponse(
        steps=steps,
        final_output=final_output,
        completed_steps=sum(1 for s in steps if s.success),
        total_steps=len(data.agent_ids),
        total_duration_ms=total_duration,
        total_cost=total_cost,
    )
    
    await _save_run(
        db, current_user.id, None, "pipeline",
        data.agent_ids, data.message,
        {"transformers": data.transformers, "stop_on_error": data.stop_on_error},
        response.model_dump(),
        total_cost, total_duration,
    )
    
    return response


async def _stream_pipeline(
    data: PipelineRequest,
    user: CurrentUser,
    db,
) -> StreamingResponse:
    """Stream pipeline execution."""
    
    async def generate() -> AsyncGenerator[str, None]:
        settings = get_settings()
        start = time.time()
        
        try:
            agents = await _load_agents(data.agent_ids, db, user, settings)
        except HTTPException as e:
            yield f"data: {json.dumps({'type': 'error', 'error': e.detail})}\n\n"
            return
        
        yield f"data: {json.dumps({'type': 'start', 'total_steps': len(data.agent_ids)})}\n\n"
        
        current_input = data.message
        steps = []
        
        for i, agent_id in enumerate(data.agent_ids):
            agent = agents[agent_id]
            
            yield f"data: {json.dumps({'type': 'step_start', 'step': i, 'agent_name': agent.name})}\n\n"
            
            result = await _run_agent(agent, current_input, 60.0)
            steps.append(result)
            
            yield f"data: {json.dumps({'type': 'step_result', 'step': i, 'result': result.model_dump()})}\n\n"
            
            if not result.success and data.stop_on_error:
                break
            
            if result.success:
                if str(i) in data.transformers:
                    current_input = f"{data.transformers[str(i)]}\n\nInput:\n{result.content}"
                else:
                    current_input = result.content
        
        total_duration = int((time.time() - start) * 1000)
        total_cost = sum(s.cost for s in steps)
        
        yield f"data: {json.dumps({'type': 'done', 'total_duration_ms': total_duration, 'total_cost': total_cost})}\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream")


# =============================================================================
# Debate
# =============================================================================

@router.post("/debate", response_model=DebateResponse)
async def run_debate(
    data: DebateRequest,
    stream: bool = False,
    current_user: CurrentUser = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Multi-agent debate with consensus detection.
    
    Agents discuss the topic across multiple rounds.
    A moderator can synthesize conclusions and detect consensus.
    """
    if stream:
        return await _stream_debate(data, current_user, db)
    
    settings = get_settings()
    start = time.time()
    
    agents = await _load_agents(data.agent_ids, db, current_user, settings)
    
    transcript = []
    total_cost = 0.0
    
    # Build debate context
    debate_context = f"Topic: {data.message}\n\n"
    
    for round_num in range(1, data.rounds + 1):
        round_messages = []
        
        if data.parallel_responses:
            # All agents respond in parallel
            tasks = []
            for agent_id, agent in agents.items():
                prompt = f"{debate_context}Round {round_num}: Share your perspective on this topic. Consider previous points if any."
                tasks.append((agent_id, agent, _run_agent(agent, prompt, 60.0)))
            
            results = await asyncio.gather(*[t[2] for t in tasks])
            
            for (agent_id, agent, _), result in zip(tasks, results):
                if result.success:
                    msg = DebateMessage(
                        round=round_num,
                        agent_id=agent_id,
                        agent_name=agent.name,
                        content=result.content,
                    )
                    transcript.append(msg)
                    round_messages.append(f"[{agent.name}]: {result.content}")
                    total_cost += result.cost
        else:
            # Sequential responses
            for agent_id, agent in agents.items():
                prompt = f"{debate_context}Round {round_num}: Share your perspective. Consider previous points."
                result = await _run_agent(agent, prompt, 60.0)
                
                if result.success:
                    msg = DebateMessage(
                        round=round_num,
                        agent_id=agent_id,
                        agent_name=agent.name,
                        content=result.content,
                    )
                    transcript.append(msg)
                    round_messages.append(f"[{agent.name}]: {result.content}")
                    debate_context += f"\n{agent.name}: {result.content}\n"
                    total_cost += result.cost
        
        # Update context for next round
        debate_context += f"\n--- Round {round_num} ---\n" + "\n".join(round_messages) + "\n"
    
    # Generate conclusion
    first_agent = list(agents.values())[0]
    conclusion_prompt = f"""Based on this debate, provide a conclusion.

{debate_context}

Summarize:
1. Key points of agreement
2. Key points of disagreement  
3. Overall conclusion

Also indicate if consensus was reached (true/false)."""

    conclusion_response = await first_agent.provider.chat(
        messages=[
            {"role": "system", "content": "You are a debate moderator. Summarize debates objectively."},
            {"role": "user", "content": conclusion_prompt}
        ],
        temperature=0.5,
    )
    
    total_cost += conclusion_response.cost
    
    # Simple consensus detection
    conclusion_lower = conclusion_response.content.lower()
    consensus = "consensus" in conclusion_lower and ("reached" in conclusion_lower or "achieved" in conclusion_lower)
    
    total_duration = int((time.time() - start) * 1000)
    
    response = DebateResponse(
        transcript=transcript,
        conclusion=conclusion_response.content,
        consensus_reached=consensus,
        rounds_completed=data.rounds,
        total_duration_ms=total_duration,
        total_cost=total_cost,
    )
    
    await _save_run(
        db, current_user.id, None, "debate",
        data.agent_ids, data.message,
        {"rounds": data.rounds, "parallel_responses": data.parallel_responses},
        response.model_dump(),
        total_cost, total_duration,
    )
    
    return response


async def _stream_debate(
    data: DebateRequest,
    user: CurrentUser,
    db,
) -> StreamingResponse:
    """Stream debate execution."""
    
    async def generate() -> AsyncGenerator[str, None]:
        settings = get_settings()
        start = time.time()
        
        try:
            agents = await _load_agents(data.agent_ids, db, user, settings)
        except HTTPException as e:
            yield f"data: {json.dumps({'type': 'error', 'error': e.detail})}\n\n"
            return
        
        yield f"data: {json.dumps({'type': 'start', 'rounds': data.rounds, 'agents': [a.name for a in agents.values()]})}\n\n"
        
        transcript = []
        total_cost = 0.0
        debate_context = f"Topic: {data.message}\n\n"
        
        for round_num in range(1, data.rounds + 1):
            yield f"data: {json.dumps({'type': 'round_start', 'round': round_num})}\n\n"
            
            round_messages = []
            
            for agent_id, agent in agents.items():
                prompt = f"{debate_context}Round {round_num}: Share your perspective."
                result = await _run_agent(agent, prompt, 60.0)
                
                if result.success:
                    msg = DebateMessage(
                        round=round_num,
                        agent_id=agent_id,
                        agent_name=agent.name,
                        content=result.content,
                    )
                    transcript.append(msg)
                    round_messages.append(f"[{agent.name}]: {result.content}")
                    total_cost += result.cost
                    
                    yield f"data: {json.dumps({'type': 'message', 'message': msg.model_dump()})}\n\n"
            
            debate_context += f"\n--- Round {round_num} ---\n" + "\n".join(round_messages) + "\n"
            
            yield f"data: {json.dumps({'type': 'round_end', 'round': round_num})}\n\n"
        
        # Conclusion
        yield f"data: {json.dumps({'type': 'phase', 'phase': 'conclusion'})}\n\n"
        
        first_agent = list(agents.values())[0]
        conclusion_response = await first_agent.provider.chat(
            messages=[
                {"role": "system", "content": "Summarize the debate objectively."},
                {"role": "user", "content": f"Summarize this debate:\n{debate_context}"}
            ],
            temperature=0.5,
        )
        
        total_cost += conclusion_response.cost
        total_duration = int((time.time() - start) * 1000)
        
        yield f"data: {json.dumps({'type': 'conclusion', 'content': conclusion_response.content})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'total_duration_ms': total_duration, 'total_cost': total_cost})}\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream")


# =============================================================================
# History
# =============================================================================

@router.get("/runs", response_model=list[OrchestrationRunResponse])
async def list_runs(
    pattern: Optional[str] = None,
    limit: int = 20,
    current_user: CurrentUser = Depends(get_current_user),
    db=Depends(get_db),
):
    """List orchestration runs for the current user."""
    where = "[user_id] = ?"
    params = [current_user.id]
    
    if pattern:
        where += " AND [pattern] = ?"
        params.append(pattern)
    
    runs = await db.find_entities(
        "orchestration_runs",
        where_clause=where,
        params=tuple(params),
        order_by="created_at DESC",
        limit=limit,
    )
    
    result = []
    for run in (runs or []):
        result.append(OrchestrationRunResponse(
            id=run["id"],
            workspace_id=run.get("workspace_id"),
            user_id=run["user_id"],
            pattern=OrchestrationPattern(run["pattern"]),
            agent_ids=json.loads(run.get("agent_ids", "[]")),
            input_message=run.get("input_message", ""),
            config=json.loads(run.get("config", "{}")),
            results=json.loads(run.get("results", "{}")),
            total_cost=run.get("total_cost", 0.0),
            duration_ms=run.get("duration_ms", 0),
            created_at=run.get("created_at"),
        ))
    
    return result


@router.get("/runs/{run_id}", response_model=OrchestrationRunResponse)
async def get_run(
    run_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db=Depends(get_db),
):
    """Get a specific orchestration run."""
    run = await db.get_entity("orchestration_runs", run_id)
    
    if not run or run.get("user_id") != current_user.id:
        raise HTTPException(status_code=404, detail="Run not found")
    
    return OrchestrationRunResponse(
        id=run["id"],
        workspace_id=run.get("workspace_id"),
        user_id=run["user_id"],
        pattern=OrchestrationPattern(run["pattern"]),
        agent_ids=json.loads(run.get("agent_ids", "[]")),
        input_message=run.get("input_message", ""),
        config=json.loads(run.get("config", "{}")),
        results=json.loads(run.get("results", "{}")),
        total_cost=run.get("total_cost", 0.0),
        duration_ms=run.get("duration_ms", 0),
        created_at=run.get("created_at"),
    )
