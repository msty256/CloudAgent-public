"""Query package — lazy proxy to avoid init cycles across the
src/ ↔ cloudagent_ext/ facade split.

The package re-exports symbols from sibling submodules. When those
siblings themselves transitively import from this package (which
they do, e.g. ``from src.query.query import ...`` inside
``cloudagent_ext.query.engine``), an eager ``from .X import Y`` here
triggers a circular import during module load. The lazy proxy
defers the real submodule imports until the first attribute access,
which is after the importing module has finished its top-level
definitions.
"""

from __future__ import annotations

import importlib

__all__ = [
    'QueryConfig',
    'QueryEngine',
    'QueryEngineConfig',
    'QueryParams',
    'QueryState',
    'StreamEvent',
    'Terminal',
    'Transition',
    'build_query_config',
    'query',
]


def __getattr__(name: str):
    if name in {'QueryConfig', 'build_query_config'}:
        return getattr(importlib.import_module('cloudagent_ext.query.config'), name)
    if name in {'QueryEngine', 'QueryEngineConfig'}:
        return getattr(importlib.import_module('cloudagent_ext.query.engine'), name)
    if name in {'QueryParams', 'StreamEvent', 'query'}:
        return getattr(importlib.import_module('cloudagent_ext.query.query'), name)
    if name in {'QueryState', 'Terminal', 'Transition'}:
        return getattr(importlib.import_module('cloudagent_ext.query.transitions'), name)
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
