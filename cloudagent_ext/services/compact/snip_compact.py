#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""
Layer 2: Snip compact — stub matching 
The implementation is a stub that returns null (not implemented).
We match that behavior here to avoid aggressively trimming tool results
that the model may need to reference later in the conversation.
"""

from __future__ import annotations

from cloudagent_ext.types.messages import Message  # pylint: disable=no-name-in-module

SNIPPED_MARKER = "[Snipped: tool result too old]"
DEFAULT_KEEP_RECENT = 10


def snip_compact(
    messages: list[Message],
    keep_recent: int = DEFAULT_KEEP_RECENT,
) -> tuple[list[Message], int]:
    return list(messages), 0
