# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Extension tool registration.

Registers 二开 tools that are not part of upstream's ALL_STATIC_TOOLS.
Called by ``src/tool_system/defaults.py:build_default_registry``.
"""

from __future__ import annotations

from cloudagent_ext.goal.tools import make_goal_model_tools
from cloudagent_ext.tool_system.build_tool import Tool
from cloudagent_ext.tool_system.tools.bg_session import BgSessionTool
from cloudagent_ext.tool_system.tools.create_agent_tool import make_create_agent_tool
from cloudagent_ext.tool_system.tools.lodestone import LodestoneTool
from cloudagent_ext.tool_system.tools.progress_report import ProgressReportTool
from cloudagent_ext.tool_system.tools.task_directives import TaskDirectivesTool
from cloudagent_ext.tool_system.tools.task_inspect import TaskInspectTool
from extensions.sop_converter.runtime.macros.register_tool import (
    PromoteMacroWorkflowTool,
    RegisterMacroFromTraceTool,
    RegisterMacroWorkflowTool,
)

EXTENSION_TOOLS: list[Tool] = [
    *make_goal_model_tools(),
    ProgressReportTool,
    TaskDirectivesTool,
    TaskInspectTool,
    make_create_agent_tool(),
    # Agent-facing background session query/control.
    # Tool self-gates on CLOUDAGENT_BG_SESSIONS (returns {disabled: true}
    # when off), so unconditional registration is safe.
    BgSessionTool,
    # Deep-link anchor parser + resolver.
    # Self-gates on ``LODESTONE=off`` (renderer falls back to plain
    # text), so unconditional registration is safe.
    LodestoneTool,
    # Session macro register / from-trace / promote
    # (capability-gated; confirm wired by TUI/REPL).
    RegisterMacroWorkflowTool,
    RegisterMacroFromTraceTool,
    PromoteMacroWorkflowTool,
]

# Chrome browser automation — seven ``chrome_*`` tools
# registered when the optional chrome service module is importable.
# The chrome controller depends on Playwright / Pillow / the MCP
# SDK as optional dependencies; the tools themselves are built
# unconditionally and degrade gracefully to a ``NullChromeController``
# that surfaces an install-hint error on every call.
try:
    from cloudagent_ext.services.chrome import build_chrome_tools

    EXTENSION_TOOLS.extend(build_chrome_tools())
except Exception:  # noqa: BLE001 — defensive, never break tool registration  # nosec B110
    # If the chrome module can't be imported (e.g. mid-refactor
    # or a partial install), the rest of the extension tools
    # still register. The chrome public API is loaded lazily by
    # ``build_chrome_controller`` at first use.
    pass

__all__ = [
    "EXTENSION_TOOLS",
]
