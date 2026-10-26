# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""ToolSystem Protocol — interface for the tool registry and execution.

Concrete implementation: src/tool_system/registry.py / build_tool.py.
The capabilities layer declares its own tool call/result shapes per the
Phase 1 import rule (no upstream imports).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

__all__ = [
    "ToolCall",
    "ToolContextProtocol",
    "ToolPermissionContextProtocol",
    "ToolProtocol",
    "ToolRegistryProtocol",
    "ToolResult",
    "ToolSystemProtocol",
]


class ToolCall(Protocol):
    """Call payload passed to tool dispatch (capabilities-local shape).

    Structurally compatible with Layer 1
    ``cloudagent_ext.tool_system.protocol.ToolCall``.
    """

    name: str
    input: dict[str, Any]
    tool_use_id: str | None


class ToolResult(Protocol):
    """Result returned by tool dispatch (capabilities-local shape).

    Structurally compatible with Layer 1
    ``cloudagent_ext.tool_system.protocol.ToolResult``.
    """

    name: str
    output: Any
    is_error: bool
    tool_use_id: str | None

    @property
    def data(self) -> Any: ...  # pragma: no cover


class ToolPermissionContextProtocol(Protocol):
    """Protocol for permission context passed to tool assembly/dispatch."""

    mode: str
    is_bypass_permissions_mode_available: bool
    should_avoid_permission_prompts: bool

    def blocks(self, tool_name: str) -> bool: ...  # pragma: no cover


class ToolProtocol(Protocol):
    """Protocol for a single tool definition."""

    name: str
    aliases: tuple[str, ...]

    def matches_name(self, name: str) -> bool: ...  # pragma: no cover


class ToolContextProtocol(Protocol):
    """Protocol for the execution context passed to tool dispatch."""

    workspace_root: Path | None
    cwd: Path | None
    plan_mode: bool
    permission_context: ToolPermissionContextProtocol | None


class ToolRegistryProtocol(Protocol):
    """Protocol for a registry of available tools."""

    def register(self, tool: ToolProtocol) -> None: ...  # pragma: no cover

    def unregister(self, name: str) -> bool: ...  # pragma: no cover

    def get(self, name: str) -> ToolProtocol | None: ...  # pragma: no cover

    def list_tools(self) -> list[ToolProtocol]: ...  # pragma: no cover

    def dispatch(self, call: ToolCall, context: ToolContextProtocol) -> ToolResult: ...  # pragma: no cover


class ToolSystemProtocol(Protocol):
    """Protocol for tool registry and tool execution.

    Provides: get_tools, find_tool_by_name, build_tool,
    assemble_tool_pool, dispatch.
    """

    def get_tools(self) -> list[ToolProtocol]: ...  # pragma: no cover

    def find_tool_by_name(self, name: str) -> ToolProtocol | None: ...  # pragma: no cover

    def build_tool(self, tool_def: dict[str, object]) -> ToolProtocol: ...  # pragma: no cover

    def assemble_tool_pool(
        self,
        registry: ToolRegistryProtocol,
        permission_context: ToolPermissionContextProtocol,
        mcp_tools: list[ToolProtocol] | None = None,
    ) -> list[ToolProtocol]: ...  # pragma: no cover

    def dispatch(self, call: ToolCall, context: ToolContextProtocol) -> ToolResult: ...  # pragma: no cover
