# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""PermissionContext Protocol — minimal boundary for SOP permission checks.

Mirrors the field subset the SOP converter (``sop_exploration_guard``)
consumes today; the default adapter wraps
``cloudagent_ext.permissions.types.ToolPermissionContext``. Field aliases
per ``docs/DECOUPLE_SOP_CONVERTER_PLAN.md`` §3.3: ``mode``,
``is_bypass`` (upstream ``is_bypass_permissions_mode_available``),
``should_avoid_prompts`` (upstream ``should_avoid_permission_prompts``),
``blocks(tool_name)`` predicate.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["PermissionContextProtocol"]


PermissionModeLiteral = str


@runtime_checkable
class PermissionContextProtocol(Protocol):
    """Minimal contract for an SOP-visible permission context.

    Implementations MUST expose ``mode`` (permission mode literal),
    ``is_bypass`` (bypassPermissions selectable), ``should_avoid_prompts``
    (no interactive prompts), and ``blocks(tool_name)`` (always-deny check).
    """

    mode: PermissionModeLiteral
    is_bypass: bool
    should_avoid_prompts: bool

    def blocks(self, tool_name: str) -> bool: ...
