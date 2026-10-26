#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Buddy notification helpers + date gates + trigger highlights.
The React hook ``useBuddyNotification`` itself stays deferred (Class C1
in ``my-docs/get-parity-by-folder/buddy-gap-analysis.md`` §3.3) — Python
has no notification context outside Textual yet, and the rainbow
renderer needs a Textual host.
The dead ``"external" === 'ant'`` branch is dropped here: Python has
no equivalent build-substitution facility. See gap-analysis §2.4.
"""

from __future__ import annotations

import re
from datetime import datetime

from cloudagent_ext.buddy.feature import is_buddy_enabled


def is_buddy_teaser_window() -> bool:
    """Whether today falls inside the April 1-7 2026 teaser window.
    Local date, not UTC — mirrors.
    The teaser window is a 24h rolling sweep across timezones (avoids
    a UTC-midnight spike on soul-gen load).
    """
    d = datetime.now()
    return d.year == 2026 and d.month == 4 and d.day <= 7


def is_buddy_live() -> bool:
    """Whether the buddy feature is live (post April 1 2026).
    """
    d = datetime.now()
    return d.year > 2026 or (d.year == 2026 and d.month >= 4)


_BUDDY_TRIGGER_RE = re.compile(r"/buddy\b")


def find_buddy_trigger_positions(text: str) -> list[dict[str, int]]:
    """Return character ranges where ``/buddy`` appears (word-bounded).
    ``{"start": int, "end": int}`` dicts so callers can apply highlight
    styling to those character ranges in a future PromptInput widget.
    """
    if not is_buddy_enabled():
        return []
    return [{"start": m.start(), "end": m.end()} for m in _BUDDY_TRIGGER_RE.finditer(text)]


__all__ = [
    "find_buddy_trigger_positions",
    "is_buddy_live",
    "is_buddy_teaser_window",
]
