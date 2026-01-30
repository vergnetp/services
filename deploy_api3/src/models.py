"""
Entity models for deploy_api.

Now using schema-first approach with @entity decorators (see schemas.py).

These dataclasses provide:
- Validation (constructor checks required fields)
- Defaults (built into the class)
- Documentation (AI/humans read the class)
- IDE autocomplete
- Database schema (via @entity decorators)

Usage:
    # Validate and use
    project = Project(**data)
    print(project.name)
    
    # Convert to dict for database
    from dataclasses import asdict
    await db.save_entity("projects", asdict(project))
    
    # Or use stores
    from src.stores import projects
    project = await projects.create(db, data)
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any
import json

# Import schema classes (with @entity decorators) from root schemas.py
from ..schemas import (
    Project,
    Service,
    Deployment,
    Droplet,
    Container,
    Snapshot,
)


# =============================================================================
# Helper functions (backward compatibility)
# =============================================================================

def from_dict(cls, data: Dict[str, Any]):
    """Create entity from dict, handling only known fields."""
    if data is None:
        return None
    known_fields = {f.name for f in cls.__dataclass_fields__.values()}
    filtered = {k: v for k, v in data.items() if k in known_fields}
    return cls(**filtered)


# Add from_dict class method to all entities for backward compatibility
Project.from_dict = classmethod(lambda cls, data: from_dict(cls, data))
Service.from_dict = classmethod(lambda cls, data: from_dict(cls, data))
Deployment.from_dict = classmethod(lambda cls, data: from_dict(cls, data))
Droplet.from_dict = classmethod(lambda cls, data: from_dict(cls, data))
Container.from_dict = classmethod(lambda cls, data: from_dict(cls, data))
Snapshot.from_dict = classmethod(lambda cls, data: from_dict(cls, data))


# Add helper properties to Deployment
@property
def env_vars_dict(self) -> Dict[str, str]:
    """Parse env_variables JSON to dict."""
    if not self.env_variables:
        return {}
    try:
        return json.loads(self.env_variables)
    except:
        return {}

@property
def droplet_ids_list(self) -> List[str]:
    """Parse droplet_ids JSON to list."""
    if not self.droplet_ids:
        return []
    try:
        return json.loads(self.droplet_ids)
    except:
        return []

Deployment.env_vars_dict = env_vars_dict
Deployment.droplet_ids_list = droplet_ids_list


__all__ = [
    "Project",
    "Service",
    "Deployment",
    "Droplet",
    "Container",
    "Snapshot",
    "from_dict",
]

