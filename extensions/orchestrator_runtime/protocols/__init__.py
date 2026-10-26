#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Orchestrator runtime protocols (no implementations).

Protocols here must not import ``cloudagent_ext.*``, ``src.*``, or
``extensions.orchestrator.*``.
"""

from __future__ import annotations

from .agent_runtime import AgentRuntime, SessionContext
from .backend import BackendUnavailable, OrchestratordBackend
from .coordinator import CoordinatorContextProvider
from .diagnostics import DiagnosticsProbe, HeartbeatState, HeartbeatStatus
from .git_backend import FileStatusLike, GitBackend
from .im_channel import ImChannel, ImCommandRouter, ImInbound, ImOutbound
from .intent_focus import FocusArea, IntentFocus, IssueLike
from .messages import (
    AgentEvent,
    AgentEventType,
    PhaseComplete,
    SessionComplete,
    TextDelta,
    ToolCallEvent,
    ToolResultEvent,
)
from .provider import LLMProvider
from .session_storage import ConversationLike, SessionMeta, SessionStorage
from .workspace_tooling import ToolContextLike, WorkspaceTooling

__all__ = [
    "AgentEvent",
    "AgentEventType",
    "AgentRuntime",
    "BackendUnavailable",
    "ConversationLike",
    "CoordinatorContextProvider",
    "DiagnosticsProbe",
    "FileStatusLike",
    "FocusArea",
    "GitBackend",
    "HeartbeatState",
    "HeartbeatStatus",
    "ImChannel",
    "ImCommandRouter",
    "ImInbound",
    "ImOutbound",
    "IntentFocus",
    "IssueLike",
    "LLMProvider",
    "OrchestratordBackend",
    "PhaseComplete",
    "SessionComplete",
    "SessionContext",
    "SessionMeta",
    "SessionStorage",
    "TextDelta",
    "ToolCallEvent",
    "ToolContextLike",
    "ToolResultEvent",
    "WorkspaceTooling",
]
