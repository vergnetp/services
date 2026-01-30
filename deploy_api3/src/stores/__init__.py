# src/stores/__init__.py
"""
Database stores - custom queries + entity re-exports.

Entities defined in schemas.py have built-in CRUD:
  Project.get(), Project.create(), Project.update(), Project.find()

Stores add custom queries:
  projects.get_by_name(), projects.list_for_workspace()
"""

from . import projects, services, deployments, droplets, containers, snapshots

__all__ = [
    "projects",
    "services", 
    "deployments",
    "droplets",
    "containers",
    "snapshots",
]
