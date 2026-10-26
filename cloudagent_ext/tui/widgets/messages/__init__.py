#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Transcript row widgets.
Each widget is a self-contained Textual ``Widget`` representing one row
in the scrollable transcript. Rows correspond roughly 1-to-1 with the
components under in the ink
reference implementation:
*:class:`BaseRow` — shared padding / header plumbing.
*:class:`UserTextMessage` — the ``❯`` user-turn row.
*:class:`AssistantTextMessage` — live-streaming assistant text that
  finalises to Markdown at end-of-turn.
*:class:`AssistantToolUseMessage` — the pre-run announcement for a
  tool call; its body is a
  :class:`src.tui.widgets.tool_activity.ToolActivity` subclass that
  transitions through ``requested → running → done / error``.
*:class:`ToolResultRow` — terminal summary row shown when a
  tool result comes back (used for non-grouped paths).
*:class:`SystemMessage` — muted system/error notifications.
"""

from .base import BaseRow, SystemMessage
from .user_text import UserTextMessage
from .assistant_text import AssistantTextMessage
from .assistant_tool_use import AssistantToolUseMessage
from .assistant_advisor import AssistantAdvisorMessage
from .tool_result import ToolResultRow

__all__ = [
    "BaseRow",
    "SystemMessage",
    "UserTextMessage",
    "AssistantTextMessage",
    "AssistantToolUseMessage",
    "AssistantAdvisorMessage",
    "ToolResultRow",
]
