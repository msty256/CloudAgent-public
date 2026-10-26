# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""ToolAuthoring Protocol — interface for SOP-convertible tool authoring.

Aggregates the persistence / spec / validation / factory / registration
surface the SOP converter borrows from ``cloudagent_ext.agent.tool_authoring``
(``persistence``, ``spec``, ``validators``, ``factory``, ``registry_ext``).
Only the methods the SOP converter calls today are surfaced.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

__all__ = [
    "AgentToolSpecProtocol",
    "ToolAuthoringProtocol",
    "ValidationError",
]


@runtime_checkable
class AgentToolSpecProtocol(Protocol):
    """Minimal contract for an ``AgentToolSpec``-shaped value.

    Mirrors ``cloudagent_ext.agent.tool_authoring.spec.AgentToolSpec``;
    implementations may add fields beyond those listed here.
    """

    name: str
    description: str
    input_schema: dict
    call_type: str
    call_impl: Any
    tags: tuple[str, ...]
    aliases: tuple[str, ...]
    source: str
    bundle_id: Optional[str]
    stateful_wrapper: bool
    output_schema: Optional[dict]


class ValidationError(Exception):
    """Raised by :meth:`ToolAuthoringProtocol.validate_spec` on bad specs.

    Mirrors ``cloudagent_ext.agent.tool_authoring.validators.ValidationError``
    so existing callers keep working through an adapter.
    """


@runtime_checkable
class ToolAuthoringProtocol(Protocol):
    """Aggregate boundary for the SOP converter's tool-authoring needs.

    The default implementation lives in
    ``extensions/sop_converter/adapters/tool_authoring_adapter.py``
    (Phase 3+); for now the Protocol is ``@runtime_checkable`` documentation.
    """

    # --- persistence (cloudagent_ext.agent.tool_authoring.persistence) ---
    TOOL_DIR: Path

    def bundle_tool_dir(self, bundle_path: Path) -> Path: ...

    def scripts_dir_for(self, tool_dir: Path) -> Path: ...

    def save_spec(self, spec: AgentToolSpecProtocol, *, tool_dir: Optional[Path] = None) -> None: ...

    def list_persisted_specs(self, tool_dir: Optional[Path] = None) -> list[Any]: ...

    def iter_bundle_tool_dirs(self, bundle_path: Path) -> list[Path]: ...

    def create_spec(self, **kwargs: Any) -> Any:
        """Create a concrete tool spec, duck-compatible with ``AgentToolSpecProtocol``."""

    # --- validation (cloudagent_ext.agent.tool_authoring.validators) ---
    def validate_spec(self, spec: AgentToolSpecProtocol) -> None: ...

    # --- factory / registration ---
    # ``create_and_validate`` returns the runtime ``Tool`` instance — typed as
    # ``Any`` because the SOP converter only registers it via ``add_tool``.
    def create_and_validate(self, spec: AgentToolSpecProtocol) -> Any: ...

    def add_tool(self, tool: Any) -> None: ...
