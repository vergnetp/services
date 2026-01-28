"""
Project operations - uses typed entities.
"""

from typing import AsyncIterator

from .stores import projects, services
from .service import delete_service
from .sse_streaming import StreamContext, sse_complete, sse_log


async def delete_project(
    db, user_id: str, project_id: str, do_token: str, cf_token: str
) -> AsyncIterator[str]:
    """Delete project and all services."""
    stream = StreamContext()
    
    try:
        project = await projects.get(db, project_id)
        if not project:
            raise Exception('Project not found')
        
        stream(f'deleting project {project.name}...')
        yield sse_log(stream._logs[-1])
        
        project_services = await services.list_for_project(db, project_id)
        
        for svc in project_services:
            async for event in delete_service(
                db, user_id, svc.id, env=None, 
                do_token=do_token, cf_token=cf_token
            ):
                yield event
        
        await projects.delete(db, project_id)
        stream('project deleted.')
        yield sse_log(stream._logs[-1])
        yield sse_complete(True, project_id)
    
    except Exception as e:
        yield sse_log(f'Error: {e}', 'error')
        yield sse_complete(False, '', str(e))
