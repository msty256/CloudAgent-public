#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Registration hooks.

This module glues to the two existing command surfaces:

1. **CLI argv level** (:mod:`cloudagent_ext.cli.subcommand_registry`):
 A single ``tool`` subcommand is registered that dispatches to any
 discoverable tool by name. See :mod:`cloudagent_ext.cli.tool_cmd.runtime`.

2. **REPL/TUI level** (:mod:`cloudagent_ext.command_system.registry`):
 Individual :class:`LocalCommand` objects are registered for each
 discoverable tool, so the user can invoke ``/detect_modality …`` in
 the REPL. See :func:`register_tool_commands` below.

The CLI hook is wired from ``subcommand_registry.load_builtin_subcommands``
(per the spec §1.6). The REPL/TUI hook is exposed as a public
function and called from the REPL/TUI startup code in the same place
``register_runtime_commands`` is called.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from . import discovery

if TYPE_CHECKING:
    from cloudagent_ext.command_system.registry import CommandRegistry
    from cloudagent_ext.tool_system.registry import ToolRegistry

log = logging.getLogger(__name__)

_INSTALLED = False


def install_tool_subcommand() -> None:
    """Register the ``tool`` CLI subcommand in ``subcommand_registry``.

    Idempotent — calling more than once is a no-op. Wired from
    :func:`cloudagent_ext.cli.subcommand_registry.load_builtin_subcommands`
    per spec §1.6.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    from cloudagent_ext.cli.subcommand_registry import register

    @register("tool")
    def _tool_subcommand(args: list[str]) -> int:
        from .runtime import run_tool_subcommand

        return run_tool_subcommand(args)

    _INSTALLED = True
    log.debug("installed 'tool' CLI subcommand")


def register_tool_commands(
    command_registry: "CommandRegistry | None",
    tool_registry: "ToolRegistry | None" = None,
) -> int:
    """Register dynamic tool commands in *command_registry*.

    Returns the number of commands actually registered (after skipping
    name collisions and core tools). A *None* registry is treated as a
    no-op — call sites that pass ``None`` (e.g. "register globally") get
    a zero count, which matches the pattern used by
    :func:`register_runtime_commands` for the global registry.
    """
    if command_registry is None:
        return 0

    if tool_registry is None:
        # Lazy import: avoid pulling the heavy tool graph for callers
        # that only want a no-op registration. Tests typically pass
        # an explicit registry; production callers can pass the
        # runtime's ``ctx.tool_registry``.
        from cloudagent_ext.tool_system.defaults import build_default_registry

        tool_registry = build_default_registry()

    disc = discovery.DynamicCommandDiscovery(tool_registry)
    registered = 0
    for local_cmd in disc.discover():
        # Skip if a command with this name is already registered (e.g.
        # by a skill, plugin, or agent command). is purely
        # additive — it never overwrites an existing handler.
        try:
            if command_registry.has(local_cmd.name):
                log.debug(
                    "skipping %r — already registered in command registry",
                    local_cmd.name,
                )
                continue
        except Exception:  # noqa: BLE001  # nosec B110
            pass  # Diagnostics are best-effort and must not affect the monitored operation.
        try:
            command_registry.register(local_cmd)
        except Exception as exc:  # noqa: BLE001
            log.debug("failed to register %r: %s", local_cmd.name, exc)
            continue
        registered += 1
    return registered
