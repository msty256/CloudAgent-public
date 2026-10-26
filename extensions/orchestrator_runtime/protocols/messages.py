#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Agent stream event dataclasses.

Events yielded by ``AgentRuntime.stream()`` and ``resume()``. Each
event is ``@dataclass(slots=True)``. ``AgentEvent`` is a sum type
discriminated by ``type``.

Must not import ``cloudagent_ext.*`` / ``src.*`` / ``extensions.orchestrator.*``.
Shapes are compatible with ``extensions.api`` stream events so adapters
can map 1-1 later.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(slots=True)
class TextDelta:
    """Streamed agent text chunk.

    Attributes:
        text: chunk UTF-8 text
        seq: monotonically increasing per-stream sequence (optional)
    """

    text: str
    seq: int = 0


@dataclass(slots=True)
class ToolCallEvent:
    """Agent requests to call a tool.

    Mirrors ``extensions.api.query.ToolCallEvent`` shape (structurally).

    Attributes:
        tool_name: registered tool name (e.g. ``"bash"``)
        tool_input: tool-specific input kwargs (JSON-serializable preferred)
        call_id: opaque correlation id used to match with ``ToolResultEvent``
    """

    tool_name: str
    tool_input: dict[str, Any]
    call_id: str


@dataclass(slots=True)
class ToolResultEvent:
    """Tool execution finished; pairs with ``ToolCallEvent.call_id``.

    Attributes:
        call_id: correlation id from the originating ``ToolCallEvent``
        output: tool-defined result; type depends on the tool
        is_error: ``True`` if tool reported an error (non-zero exit, exception)
    """

    call_id: str
    output: Any
    is_error: bool = False


@dataclass(slots=True)
class PhaseComplete:
    """A logical phase of the agent loop completed (e.g. end-of-turn).

    Attributes:
        phase: human-readable phase name (e.g. ``"turn1"``, ``"summarize"``)
        cost: cumulative cost in USD (or None if unknown)
        turn_count: number of LLM turns used so far
    """

    phase: str
    cost: float = 0.0
    turn_count: int = 0


@dataclass(slots=True)
class SessionComplete:
    """Terminal event — single instance per ``stream()`` invocation.

    Attributes:
        reason: one of ``"completed"``, ``"resumed"``, ``"cancelled"``,
            ``"error"``, ``"budget_exceeded"``
        final_text: last assistant text (may be empty)
    """

    reason: str
    final_text: str = ""


# ---------------------------------------------------------------------------
# Sum-type container: AgentEvent = (type, payload)
# ---------------------------------------------------------------------------

AgentEventType = Literal[
    "text_delta",
    "tool_call",
    "tool_result",
    "phase_complete",
    "session_complete",
]


@dataclass(slots=True)
class AgentEvent:
    """Sum-type wrapper for ``AgentRuntime.stream()`` yields.

    Discriminate by ``type`` and ``isinstance(payload, ...)``:

        event = AgentEvent(...)
        if event.type == "text_delta":
            assert isinstance(event.payload, TextDelta)
            ...

    Phase 0/1 keeps the wrapper minimal; Phase 3 will plug AgentRunner to emit
    these consistently.
    """

    type: AgentEventType
    payload: Any


__all__ = [
    "AgentEvent",
    "AgentEventType",
    "PhaseComplete",
    "SessionComplete",
    "TextDelta",
    "ToolCallEvent",
    "ToolResultEvent",
]
