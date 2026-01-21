"""
Admin routes for telemetry and monitoring.

These routes are only accessible to admin users (defined in ADMIN_EMAILS).
Supports viewing telemetry from ANY service (via service_name filter).
"""

import os
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from shared_libs.backend.app_kernel.auth import get_current_user, UserIdentity


# Admin configuration
ADMIN_EMAILS = [e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "vergnetp@yahoo.fr").split(",")]


def is_admin(email: str) -> bool:
    """Check if email is an admin."""
    return email and email.strip().lower() in ADMIN_EMAILS


router = APIRouter(prefix="/admin", tags=["admin"])


# =============================================================================
# Dependencies
# =============================================================================

async def require_admin(user: UserIdentity = Depends(get_current_user)) -> UserIdentity:
    """
    Dependency to ensure user is admin.
    Raises 403 if user is not an admin.
    """
    email = getattr(user, 'email', None)
    if not is_admin(email):
        raise HTTPException(403, "Admin access required")
    return user


def get_trace_store():
    """Get the trace store instance from app_kernel."""
    try:
        from shared_libs.backend.app_kernel import get_trace_store as kernel_get_trace_store
        return kernel_get_trace_store()
    except ImportError:
        return None


def get_current_service_name():
    """Get current service name from app_kernel."""
    try:
        from shared_libs.backend.app_kernel import get_traced_service_name
        return get_traced_service_name() or "unknown"
    except ImportError:
        return "unknown"


# =============================================================================
# Response Models
# =============================================================================

class TraceOverview(BaseModel):
    """Overview statistics for telemetry."""
    total_requests: int
    avg_latency_ms: float
    max_latency_ms: float
    p95_latency_ms: float
    error_count: int
    error_rate: float
    slow_count: int
    slow_endpoints: List[Dict[str, Any]]
    error_endpoints: List[Dict[str, Any]]


class SpanInfo(BaseModel):
    """Span information for drill-down."""
    name: str
    kind: str
    duration_ms: Optional[float] = None
    status: Optional[str] = None
    attributes: Dict[str, Any] = {}
    error: Optional[str] = None
    error_type: Optional[str] = None
    children: List['SpanInfo'] = []


class TraceDetail(BaseModel):
    """Detailed trace with spans."""
    request_id: str
    service_name: Optional[str] = None
    method: Optional[str] = None
    path: Optional[str] = None
    status_code: Optional[int] = None
    duration_ms: Optional[float] = None
    user_id: Optional[str] = None
    has_errors: bool = False
    timestamp: Optional[str] = None
    spans: List[SpanInfo] = []


class TraceSummary(BaseModel):
    """Summary of a trace for listing."""
    request_id: str
    service_name: Optional[str] = None
    method: Optional[str] = None
    path: Optional[str] = None
    status_code: Optional[int] = None
    duration_ms: Optional[float] = None
    user_id: Optional[str] = None
    timestamp: Optional[str] = None
    span_count: int = 0
    has_errors: bool = False


# =============================================================================
# Routes
# =============================================================================

@router.get("/telemetry/check")
async def check_admin_access(
    user = Depends(require_admin)
):
    """Check if current user has admin access."""
    return {
        "is_admin": True,
        "email": getattr(user, 'email', None),
        "current_service": get_current_service_name(),
    }


@router.get("/telemetry/services")
async def list_services(
    user = Depends(require_admin),
):
    """
    List all services that have recorded traces.
    
    Use this to populate a service filter dropdown.
    """
    store = get_trace_store()
    if not store:
        return {"services": [], "current": get_current_service_name()}
    
    try:
        services = store.get_services()
    except Exception:
        services = []
    
    return {
        "services": services,
        "current": get_current_service_name(),
    }


@router.get("/telemetry/overview", response_model=TraceOverview)
async def get_telemetry_overview(
    service_name: Optional[str] = Query(None, description="Filter by service name"),
    hours: int = Query(24, description="Look back period in hours"),
    path_prefix: Optional[str] = Query(None, description="Filter by path prefix"),
    user = Depends(require_admin),
):
    """
    Get overview statistics for telemetry.
    
    Returns aggregated stats like request count, latency percentiles,
    error rates, and slow endpoints.
    """
    store = get_trace_store()
    if not store:
        raise HTTPException(503, "Trace store not available")
    
    since = datetime.utcnow() - timedelta(hours=hours)
    
    stats = store.get_stats(since=since, path_prefix=path_prefix, service_name=service_name)
    return TraceOverview(
        total_requests=stats.get("total_requests", 0),
        avg_latency_ms=stats.get("avg_latency_ms", 0),
        max_latency_ms=stats.get("max_latency_ms", 0),
        p95_latency_ms=stats.get("p95_latency_ms", 0),
        error_count=stats.get("error_count", 0),
        error_rate=stats.get("error_rate", 0),
        slow_count=stats.get("slow_count", 0),
        slow_endpoints=stats.get("slow_endpoints", []),
        error_endpoints=stats.get("error_endpoints", []),
    )


@router.get("/telemetry/requests", response_model=List[TraceSummary])
async def list_requests(
    service_name: Optional[str] = Query(None, description="Filter by service name"),
    path_prefix: Optional[str] = Query(None, description="Filter by path prefix"),
    min_duration_ms: Optional[float] = Query(None, description="Minimum duration"),
    status_code: Optional[int] = Query(None, description="Filter by exact status code"),
    status_class: Optional[str] = Query(None, description="Filter by status class (2xx, 4xx, 5xx)"),
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    hours: Optional[int] = Query(24, description="Look back period in hours"),
    limit: int = Query(100, le=500, description="Max results"),
    offset: int = Query(0, description="Offset for pagination"),
    user = Depends(require_admin),
):
    """
    List request traces with filtering.
    
    Use this to find specific requests or browse recent activity.
    Can filter by service_name to view telemetry from any service.
    """
    store = get_trace_store()
    if not store:
        return []
    
    since = datetime.utcnow() - timedelta(hours=hours) if hours else None
    
    traces = store.query(
        service_name=service_name,
        path_prefix=path_prefix,
        min_duration_ms=min_duration_ms,
        status_code=status_code,
        status_class=status_class,
        user_id=user_id,
        since=since,
        limit=limit,
        offset=offset,
    )
    
    return [
        TraceSummary(
            request_id=t["request_id"],
            service_name=t.get("service_name"),
            method=t.get("method"),
            path=t.get("path"),
            status_code=t.get("status_code"),
            duration_ms=t.get("duration_ms"),
            user_id=t.get("user_id"),
            timestamp=t.get("timestamp"),
            span_count=t.get("span_count", len(t.get("spans", []))),
            has_errors=t.get("has_errors", False),
        )
        for t in traces
    ]


@router.get("/telemetry/requests/{request_id}", response_model=TraceDetail)
async def get_request_detail(
    request_id: str,
    user = Depends(require_admin),
):
    """
    Get detailed trace with all spans for drill-down.
    
    Use this to analyze exactly what happened during a request,
    including all HTTP calls, their timing, and any errors.
    """
    store = get_trace_store()
    if not store:
        raise HTTPException(503, "Trace store not available")
    
    trace = store.get(request_id)
    
    if not trace:
        raise HTTPException(404, f"Trace {request_id} not found")
    
    def dict_to_span_info(span_dict: Dict[str, Any]) -> SpanInfo:
        """Convert span dict to SpanInfo model."""
        attrs = span_dict.get("attributes", {})
        if isinstance(attrs, dict) and "custom" in attrs:
            # Flatten custom attributes
            flat_attrs = {k: v for k, v in attrs.items() if k != "custom"}
            flat_attrs.update(attrs.get("custom", {}))
            attrs = flat_attrs
        
        return SpanInfo(
            name=span_dict.get("name", "unknown"),
            kind=span_dict.get("kind", "internal"),
            duration_ms=span_dict.get("duration_ms"),
            status=span_dict.get("status"),
            attributes=attrs if isinstance(attrs, dict) else {},
            error=attrs.get("error_message") if isinstance(attrs, dict) else None,
            error_type=attrs.get("error_type") if isinstance(attrs, dict) else None,
            children=[dict_to_span_info(c) for c in span_dict.get("children", [])],
        )
    
    spans = trace.get("spans", [])
    
    return TraceDetail(
        request_id=trace["request_id"],
        service_name=trace.get("service_name"),
        method=trace.get("method"),
        path=trace.get("path"),
        status_code=trace.get("status_code"),
        duration_ms=trace.get("duration_ms"),
        user_id=trace.get("user_id"),
        has_errors=trace.get("has_errors", False),
        timestamp=trace.get("timestamp"),
        spans=[dict_to_span_info(s) for s in spans],
    )


@router.get("/telemetry/slow", response_model=List[TraceSummary])
async def get_slow_requests(
    service_name: Optional[str] = Query(None, description="Filter by service name"),
    threshold_ms: float = Query(1000, description="Slow threshold in ms"),
    hours: int = Query(24, description="Look back period in hours"),
    limit: int = Query(50, le=200, description="Max results"),
    user = Depends(require_admin),
):
    """
    Get slow requests (above threshold).
    
    Default threshold is 1000ms (1 second).
    """
    store = get_trace_store()
    if not store:
        return []
    
    since = datetime.utcnow() - timedelta(hours=hours)
    
    traces = store.query(
        service_name=service_name,
        min_duration_ms=threshold_ms,
        since=since,
        limit=limit,
    )
    
    return [
        TraceSummary(
            request_id=t["request_id"],
            service_name=t.get("service_name"),
            method=t.get("method"),
            path=t.get("path"),
            status_code=t.get("status_code"),
            duration_ms=t.get("duration_ms"),
            user_id=t.get("user_id"),
            timestamp=t.get("timestamp"),
            span_count=t.get("span_count", len(t.get("spans", []))),
            has_errors=t.get("has_errors", False),
        )
        for t in traces
    ]


@router.get("/telemetry/errors", response_model=List[TraceSummary])
async def get_error_requests(
    service_name: Optional[str] = Query(None, description="Filter by service name"),
    status_class: str = Query("5xx", description="Error class (4xx or 5xx)"),
    hours: int = Query(24, description="Look back period in hours"),
    limit: int = Query(50, le=200, description="Max results"),
    user = Depends(require_admin),
):
    """
    Get requests that resulted in errors (4xx or 5xx).
    """
    if status_class not in ("4xx", "5xx"):
        raise HTTPException(400, "status_class must be '4xx' or '5xx'")
    
    store = get_trace_store()
    if not store:
        return []
    
    since = datetime.utcnow() - timedelta(hours=hours)
    
    traces = store.query(
        service_name=service_name,
        status_class=status_class,
        since=since,
        limit=limit,
    )
    
    return [
        TraceSummary(
            request_id=t["request_id"],
            service_name=t.get("service_name"),
            method=t.get("method"),
            path=t.get("path"),
            status_code=t.get("status_code"),
            duration_ms=t.get("duration_ms"),
            user_id=t.get("user_id"),
            timestamp=t.get("timestamp"),
            span_count=t.get("span_count", len(t.get("spans", []))),
            has_errors=t.get("has_errors", False),
        )
        for t in traces
    ]


@router.post("/telemetry/cleanup")
async def cleanup_old_traces(
    days: int = Query(7, description="Delete traces older than this many days"),
    user = Depends(require_admin),
):
    """
    Clean up old traces to save disk space.
    
    By default, deletes traces older than 7 days.
    """
    store = get_trace_store()
    if not store:
        raise HTTPException(503, "Trace store not available")
    
    deleted = store.cleanup(older_than=timedelta(days=days))
    
    return {
        "deleted": deleted,
        "message": f"Deleted {deleted} traces older than {days} days",
    }


# =============================================================================
# Admin Info
# =============================================================================

@router.get("/info")
async def get_admin_info(
    user = Depends(require_admin),
):
    """Get admin-only system information."""
    import sys
    import platform
    
    return {
        "admin_emails": ADMIN_EMAILS,
        "current_service": get_current_service_name(),
        "python_version": sys.version,
        "platform": platform.platform(),
        "user": {
            "email": getattr(user, 'email', None),
            "id": str(getattr(user, 'id', None)),
        },
    }


# Update the SpanInfo model to support recursion
SpanInfo.model_rebuild()


# =============================================================================
# Backend Logs (In-Memory Buffer)
# =============================================================================

import logging
from collections import deque
from threading import Lock

# In-memory log buffer
_log_buffer: deque = deque(maxlen=1000)  # Keep last 1000 entries
_log_lock = Lock()


class MemoryLogHandler(logging.Handler):
    """Handler that stores log records in memory for admin viewing."""
    
    def emit(self, record):
        try:
            msg = self.format(record)
            with _log_lock:
                _log_buffer.append({
                    "timestamp": datetime.fromtimestamp(record.created).isoformat(),
                    "level": record.levelname,
                    "logger": record.name,
                    "message": msg,
                    "module": record.module,
                    "funcName": record.funcName,
                    "lineno": record.lineno,
                })
        except Exception:
            pass


def setup_memory_logging():
    """Attach memory handler to root logger."""
    handler = MemoryLogHandler()
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logging.getLogger().addHandler(handler)
    # Also add to uvicorn loggers
    for logger_name in ['uvicorn', 'uvicorn.access', 'uvicorn.error', 'fastapi']:
        logging.getLogger(logger_name).addHandler(handler)


# Initialize on module load
setup_memory_logging()


class LogEntry(BaseModel):
    timestamp: str
    level: str
    logger: str
    message: str
    module: Optional[str] = None
    funcName: Optional[str] = None
    lineno: Optional[int] = None


@router.get("/logs", response_model=List[LogEntry])
async def get_backend_logs(
    user: UserIdentity = Depends(require_admin),
    level: Optional[str] = Query(None, description="Filter by level: DEBUG, INFO, WARNING, ERROR"),
    search: Optional[str] = Query(None, description="Search in message"),
    limit: int = Query(200, ge=1, le=1000),
):
    """
    Get recent backend logs from memory buffer.
    
    Useful for debugging deployment issues without SSH access.
    """
    with _log_lock:
        logs = list(_log_buffer)
    
    # Reverse to show newest first
    logs = logs[::-1]
    
    # Filter by level
    if level:
        level_upper = level.upper()
        logs = [l for l in logs if l["level"] == level_upper]
    
    # Filter by search term
    if search:
        search_lower = search.lower()
        logs = [l for l in logs if search_lower in l["message"].lower()]
    
    return logs[:limit]


@router.delete("/logs")
async def clear_backend_logs(user: UserIdentity = Depends(require_admin)):
    """Clear the in-memory log buffer."""
    with _log_lock:
        _log_buffer.clear()
    return {"status": "cleared"}


# =============================================================================
# Database Admin (Dev Phase)
# =============================================================================

from fastapi import UploadFile, File
from fastapi.responses import FileResponse
from pathlib import Path as FilePath


def _get_db_path() -> FilePath:
    """Get database path from settings."""
    from deploy_api.config import get_settings
    settings = get_settings()
    return FilePath(settings.database_path).resolve()


@router.get("/db/download")
async def download_database(user: UserIdentity = Depends(require_admin)):
    """
    Download the current SQLite database file.
    
    Useful for backing up or syncing db between local and server.
    """
    db_path = _get_db_path()
    
    if not db_path.exists():
        raise HTTPException(404, f"Database not found at {db_path}")
    
    if not db_path.suffix == ".db":
        raise HTTPException(400, "Only SQLite databases (.db) are supported")
    
    return FileResponse(
        path=str(db_path),
        filename=db_path.name,
        media_type="application/octet-stream",
    )


@router.post("/db/upload")
async def upload_database(
    file: UploadFile = File(...),
    user: UserIdentity = Depends(require_admin),
):
    """
    Upload and replace the SQLite database file.
    
    WARNING: This replaces the entire database! Make sure to download
    the current one first if needed.
    
    After upload, you should restart the service for connections to refresh.
    """
    db_path = _get_db_path()
    
    # Validate file
    if not file.filename.endswith(".db"):
        raise HTTPException(400, "File must be a .db SQLite database")
    
    # Read uploaded file
    content = await file.read()
    
    if len(content) < 100:
        raise HTTPException(400, "File too small to be a valid SQLite database")
    
    # Check SQLite header magic
    if content[:16] != b'SQLite format 3\x00':
        raise HTTPException(400, "Invalid SQLite database file (bad header)")
    
    # Ensure directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Backup current db if exists
    backup_path = None
    if db_path.exists():
        backup_path = db_path.with_suffix(".db.backup")
        import shutil
        shutil.copy2(db_path, backup_path)
    
    # Write new database
    try:
        with open(db_path, "wb") as f:
            f.write(content)
        
        return {
            "status": "success",
            "message": f"Database uploaded to {db_path}",
            "size_bytes": len(content),
            "backup_created": str(backup_path) if backup_path else None,
            "note": "Restart the service for connections to refresh",
        }
    except Exception as e:
        # Restore backup on failure
        if backup_path and backup_path.exists():
            import shutil
            shutil.copy2(backup_path, db_path)
        raise HTTPException(500, f"Failed to write database: {e}")


@router.get("/db/info")
async def get_database_info(user: UserIdentity = Depends(require_admin)):
    """Get information about the current database."""
    db_path = _get_db_path()
    
    info = {
        "path": str(db_path),
        "exists": db_path.exists(),
        "size_bytes": None,
        "size_human": None,
        "modified": None,
    }
    
    if db_path.exists():
        stat = db_path.stat()
        info["size_bytes"] = stat.st_size
        info["size_human"] = _format_size(stat.st_size)
        info["modified"] = datetime.fromtimestamp(stat.st_mtime).isoformat()
    
    return info


def _format_size(size_bytes: int) -> str:
    """Format bytes as human readable string."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"
