#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""expose tools automatically as CLI slash commands.

Public API
----------
* :class:`DynamicCommandDiscovery` — scan a ``ToolRegistry`` for non-core
 tools and produce ``LocalCommand``s.
* :class:`DynamicToolCommand` — single-tool adapter; bind to REPL/TUI
 ``CommandContext`` for invocation.
* :func:`install_tool_subcommand` — register the ``cloudagent tool``
 CLI subcommand (idempotent).
* :func:`register_tool_commands` — register per-tool slash commands in
 a REPL/TUI ``CommandRegistry``.

Usage
-----
At REPL/TUI startup (after the runtime context is built)::

 from cloudagent_ext.cli.tool_cmd import register_tool_commands
 from cloudagent_ext.command_system.registry import CommandRegistry

 command_registry = CommandRegistry()
 register_tool_commands(command_registry, ctx.tool_registry)

From the CLI::

 cloudagent tool --list
 cloudagent tool detect_modality --path /data/sample.mp4
"""

from __future__ import annotations

from .command import DynamicToolCommand
from .discovery import DynamicCommandDiscovery
from .hooks import install_tool_subcommand, register_tool_commands
from . import core_filter, schema_parser

__all__ = [
    "DynamicCommandDiscovery",
    "DynamicToolCommand",
    "core_filter",
    "install_tool_subcommand",
    "register_tool_commands",
    "schema_parser",
]
