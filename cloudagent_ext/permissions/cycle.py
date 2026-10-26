#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Permission-mode cycling for the Shift+Tab keybinding.
reference has an Anthropic-internal ``USER_TYPE === 'ant'`` branch and a
``TRANSCRIPT_CLASSIFIER``-gated ``auto`` cycle target.
Cycle order (with ``bypassPermissions`` enabled):
    ``default → acceptEdits → plan → bypassPermissions → auto → default``
The ``bypassPermissions → auto`` step is guarded by:func:`can_cycle_to_auto`
so it only appears when the environment is safe (no protected directory, no
recent dangerous-operation denials). When unavailable, the cycle wraps
``bypassPermissions → default`` directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from cloudagent_ext.permissions.types import PermissionMode, PermissionUpdateSetMode, ToolPermissionContext

# ---------------------------------------------------------------------------
# Cycle order — the single source of truth for mode switching.
#
# The cycle is a *ring*: each press of Shift+Tab advances to the next mode in
# ``CYCLE_ORDER``, skipping any mode that is not currently available, and wraps
# from the last entry back to ``default``. Availability is evaluated per call,
# so one unavailable mode no longer truncates the whole cycle (the pre-ring
# table returned ``default`` as soon as a guarded edge was blocked, which made
# ``dontAsk`` / ``auto`` / ``bypassPermissions`` unreachable for users who had
# not authorised bypass).
#
# Downstream extensions can override a single successor via
# ``register_cycle_step()``; overrides win over the ring.
# ---------------------------------------------------------------------------

CYCLE_ORDER: tuple[PermissionMode, ...] = (
    "default",
    "acceptEdits",
    "plan",
    "dontAsk",
    "auto",
    "bypassPermissions",
)

# Downstream overrides: mode → its forced successor. Consulted before the ring
# so an extension can pin a transition (upstream parity for
# ``register_cycle_step``). Targets are NOT availability-filtered — the
# extension asked for that edge explicitly.
_CYCLE_OVERRIDES: dict[str, PermissionMode] = {}

# Derived view for readers that still inspect the historical table shape.
# Do NOT mutate — the ring (``CYCLE_ORDER``) is authoritative.
_CYCLE_TABLE: list[tuple[str, str]] = [
    (CYCLE_ORDER[i], CYCLE_ORDER[(i + 1) % len(CYCLE_ORDER)]) for i in range(len(CYCLE_ORDER))
]


def register_cycle_step(source: str, target: str, *, after: str | None = None) -> None:
    """Override the successor of ``source`` in the Shift+Tab cycle.

    Args:
        source: The mode to transition *from*.
        target: The mode to transition *to*.
        after: Deprecated and ignored. It used to control list position in the
            old static table; the ring defines ordering now, so only the
            ``source → target`` override matters.

    Example:
        # Force bypassPermissions → dontAsk (bypasses the ring's wrap)
        register_cycle_step("bypassPermissions", "dontAsk")

    Note:
        A mode has exactly one Shift+Tab successor, so registering the same
        ``source`` twice keeps the last target. The target should be a mode in
        :data:`CYCLE_ORDER`; otherwise that mode may lose its path back to
        ``default``. Callers own that risk.
    """
    _CYCLE_OVERRIDES[source] = cast(PermissionMode, target)


def _is_mode_available(target: PermissionMode, context: ToolPermissionContext) -> bool:
    """Whether the cycle may land on *target* right now.

    ``bypassPermissions`` keeps its existing authorisation source (CLI flag /
    settings); ``auto`` keeps the safety hook but *without* the danger-history
    gate — Shift+Tab is an explicit user action, and the history check reads a
    process-global denial tracker, which would make ``auto`` vanish silently
    from the cycle after three denied writes. Other modes are always available.
    """

    if target == "bypassPermissions":
        return bool(context.is_bypass_permissions_mode_available)
    if target == "auto":
        return can_cycle_to_auto(
            context,
            check_protected_directory=True,
            check_danger_history=False,
        )
    return True


def get_next_permission_mode(context: ToolPermissionContext) -> PermissionMode:
    """Return the next mode when the user presses Shift+Tab.

    Walks :data:`CYCLE_ORDER` forward from the current mode and returns the
    first *available* candidate, wrapping around to ``default``. An unavailable
    mode is skipped rather than truncating the cycle, so ``dontAsk`` / ``auto``
    stay reachable when ``bypassPermissions`` is not authorised.

    Modes outside the ring (``bubble`` — internal sub-agent escalation — and
    any unknown value) fall through to ``default`` so Shift+Tab never strands
    the user. Registered :func:`register_cycle_step` overrides win over the
    ring.
    """

    mode = context.mode

    override = _CYCLE_OVERRIDES.get(mode)
    if override is not None:
        return override

    if mode not in CYCLE_ORDER:
        return "default"

    start = CYCLE_ORDER.index(mode)
    # len(CYCLE_ORDER) steps always reaches "default" (never filtered), so the
    # loop is guaranteed to return; the trailing return is defensive only.
    for step in range(1, len(CYCLE_ORDER) + 1):
        candidate = CYCLE_ORDER[(start + step) % len(CYCLE_ORDER)]
        if _is_mode_available(candidate, context):
            return candidate
    return "default"


def cycle_permission_mode(
    context: ToolPermissionContext,
) -> tuple[PermissionMode, ToolPermissionContext]:
    """Compute the next mode and return the (mode, updated_context) pair.
    .
    The updated context is produced via:func:`apply_permission_update` with
    a ``setMode`` update so any future hooks that observe context updates fire
    consistently.
    """
    next_mode = get_next_permission_mode(context)
    from cloudagent_ext.permissions.updates import apply_permission_update

    next_context = apply_permission_update(
        context,
        PermissionUpdateSetMode(
            type="setMode",
            destination="session",
            mode=next_mode,
        ),
    )
    return next_mode, next_context


PROTECTED_DIRECTORIES: tuple[str, ...] = (
    ".git",
    ".vscode",
    ".cloudagent",
    ".idea",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
)


def _is_in_protected_directory(cwd: str | Path | None) -> bool:
    """Check if current working directory is inside a protected location."""
    if cwd is None:
        return False
    cwd_path = Path(cwd).resolve()
    for protected in PROTECTED_DIRECTORIES:
        if protected in cwd_path.parts:
            return True
        protected_path = cwd_path / protected
        if protected_path.exists():
            return True
    return False


def _has_recent_dangerous_operations(
    denial_tracker: Any | None = None,
) -> bool:
    """Check if there have been recent denied dangerous operations."""
    if denial_tracker is None:
        try:
            from cloudagent_ext.permissions.check import get_denial_tracker

            denial_tracker = get_denial_tracker()
        except Exception:
            return False
    dangerous_tools = ("Bash", "Write", "Edit")
    for tool in dangerous_tools:
        if denial_tracker.get_denial_count(tool) >= 3:
            return True
    return False


def can_cycle_to_auto(
    context: ToolPermissionContext,
    *,
    check_protected_directory: bool = True,
    check_danger_history: bool = True,
) -> bool:
    """Check if auto mode is available and safe to activate.
    Auto mode is not part of the Shift+Tab cycle because it requires
    explicit activation and safety checks. This function validates:
    1. Current permission configuration allows auto mode
    2. Not operating in a protected directory (.git,.vscode, etc.)
    3. No recent dangerous operation denials
    Args:
        context: Current permission context
        check_protected_directory: Whether to check for protected dirs
        check_danger_history: Whether to check denial history
    Returns:
        True if auto mode can be safely activated
    """
    if context.mode == "auto":
        return True
    if check_protected_directory:
        cwd = getattr(context, "cwd", None)
        if _is_in_protected_directory(cwd):
            return False
    if check_danger_history:
        if _has_recent_dangerous_operations():
            return False
    return True


def get_auto_mode_availability_reason(
    context: ToolPermissionContext,
) -> str | None:
    """Return human-readable reason why auto mode is unavailable.
    Args:
        context: Current permission context
    Returns:
        None if auto mode is available, otherwise the blocking reason
    """
    if context.mode == "auto":
        return None
    cwd = getattr(context, "cwd", None)
    if _is_in_protected_directory(cwd):
        return "Working directory is inside a protected location (.git, .vscode, etc.)"
    if _has_recent_dangerous_operations():
        return "Recent dangerous operations were denied (auto mode paused for safety)"
    return None


__all__ = [
    "CYCLE_ORDER",
    "PROTECTED_DIRECTORIES",
    "can_cycle_to_auto",
    "cycle_permission_mode",
    "get_auto_mode_availability_reason",
    "get_next_permission_mode",
    "register_cycle_step",
]
