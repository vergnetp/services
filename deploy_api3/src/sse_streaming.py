"""
sse streaming 
"""

import json
from typing import List
from datetime import datetime, timezone


class StreamContext:
    def __init__(self):
        self._logs: List[str] = []
    
    def __call__(self, msg: str):
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self._logs.append(f"[{ts}] {msg}")
    
    def flush(self) -> str:
        return "\n".join(self._logs)


def sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"

def sse_log(message: str, level: str = "info") -> str:
    return sse_event("log", {"message": message, "level": level})

def sse_complete(success: bool, deployment_id: str, error: str = None) -> str:
    return sse_event("complete", {"success": success, "deployment_id": deployment_id, "error": error})