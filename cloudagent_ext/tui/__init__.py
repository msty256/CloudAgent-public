#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Downstream TUI extensions — lazy proxy for circular-safety.

Eager imports avoided to break the circular chain:
  __init__ → .app → .screens.* → ..app → ...
"""

# pylint: disable=E0603
__all__ = [
    "CloudAgentTUI",
    "AdvisorEventMessage",
    "AgentRunFinished",
    "AgentRunStarted",
    "AssistantChunk",
    "AssistantMessage",
    "ToolEventMessage",
]

_NAME_TO_MODULE = {
    "CloudAgentTUI": "cloudagent_ext.tui.app",
    "AdvisorEventMessage": "cloudagent_ext.tui.messages",
    "AgentRunFinished": "cloudagent_ext.tui.messages",
    "AgentRunStarted": "cloudagent_ext.tui.messages",
    "AssistantChunk": "cloudagent_ext.tui.messages",
    "AssistantMessage": "cloudagent_ext.tui.messages",
    "ToolEventMessage": "cloudagent_ext.tui.messages",
}


def __getattr__(name: str):
    module_name = _NAME_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    mod = importlib.import_module(module_name)
    val = getattr(mod, name)
    globals()[name] = val
    return val
