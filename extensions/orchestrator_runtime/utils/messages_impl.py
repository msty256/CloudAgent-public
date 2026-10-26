#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Orchestrator-local message and content-block helpers.

Extracts the lazy ``cloudagent_ext.types.{messages,content_blocks}``
imports used by AgentRunner, keeping the original dataclass shape.

Must not import ``cloudagent_ext.*``. This is a copy-down, not a proxy.
Only the symbols AgentRunner uses are copied: ``TextBlock`` /
``ToolUseBlock`` / ``ToolResultBlock``, plus ``create_user_message`` /
``create_assistant_message``. Canonical sources remain
``cloudagent_ext/types/content_blocks.py`` and ``messages.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, TypeAlias
from uuid import uuid4


# ─── Content blocks (mirrors cloudagent_ext.types.content_blocks) ───────────


@dataclass
class TextBlock:
    text: str = ""
    type: Literal["text"] = "text"


@dataclass
class ToolUseBlock:
    id: str = ""
    name: str = ""
    input: dict[str, Any] = field(default_factory=dict)
    type: Literal["tool_use"] = "tool_use"


@dataclass
class ToolResultBlock:
    tool_use_id: str = ""
    content: str | list[Any] = ""
    is_error: bool = False
    type: Literal["tool_result"] = "tool_result"
    metadata: dict[str, Any] = field(default_factory=dict)
    duration_ms: int | None = None


MessageContent: TypeAlias = str | list[Any]


# ─── Message factories (mirrors cloudagent_ext.types.messages) ──────────────


def _now_iso() -> str:
    return datetime.now().isoformat()


def _new_uuid() -> str:
    return str(uuid4())


def create_user_message(content: MessageContent, **kwargs: Any) -> dict[str, Any]:
    """Build a user message dict aligned with ``create_user_message``.

    Only the fields AgentRunner actually uses; not a full clone.
    """
    return {
        "role": "user",
        "content": content,
        "type": "user",
        "uuid": _new_uuid(),
        "timestamp": _now_iso(),
        **kwargs,
    }


def create_assistant_message(content: MessageContent, **kwargs: Any) -> dict[str, Any]:
    """Build an assistant message dict aligned with ``create_assistant_message``."""
    return {
        "role": "assistant",
        "content": content,
        "type": "assistant",
        "uuid": _new_uuid(),
        "timestamp": _now_iso(),
        **kwargs,
    }


def message_from_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Rebuild a message dict from wire format (pass-through fields).

    AgentRunner uses this once in ``_save_json_snapshot`` after the
    caller has already validated the payload. Not a full port of
    ``cloudagent_ext.types.messages.message_from_dict``.
    """
    return {
        "role": data.get("role", "user"),
        "content": data.get("content", ""),
        "type": data.get("type", data.get("role", "user")),
        "uuid": data.get("uuid") or _new_uuid(),
        "timestamp": data.get("timestamp") or _now_iso(),
        **{
            k: v
            for k, v in data.items()
            if k
            not in {
                "role",
                "content",
                "type",
                "uuid",
                "timestamp",
            }
        },
    }


__all__ = [
    "MessageContent",
    "TextBlock",
    "ToolUseBlock",
    "ToolResultBlock",
    "create_user_message",
    "create_assistant_message",
    "message_from_dict",
]
