#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Pure display formatters — Python port.
Used by the REPL spinner (and any future caller) to render durations and
token counts in the same compact form as the TypeScript Ink reference UI:
``12s`` / ``1m 30s`` for time, ``900`` / ``1.2k`` / ``1.0m`` for counts.
Behaviour matches the reference closely enough that the two
implementations produce byte-identical output for the spinner row.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from datetime import datetime


def format_duration(
    ms: float,
    *,
    hide_trailing_zeros: bool = False,
    most_significant_only: bool = False,
) -> str:
    """Render a millisecond duration the same way ``formatDuration`` in
     does.
    """

    if ms < 60_000:
        if ms == 0:
            return "0s"
        if ms < 1:
            return f"{ms / 1000:.1f}s"
        return f"{int(math.floor(ms / 1000))}s"

    days = int(math.floor(ms / 86_400_000))
    hours = int(math.floor((ms % 86_400_000) / 3_600_000))
    minutes = int(math.floor((ms % 3_600_000) / 60_000))
    # Match JS ``Math.round`` (round-half-up) rather than Python's
    # banker's rounding so 0.5s ticks land identically across the two
    # implementations.
    seconds = int(math.floor((ms % 60_000) / 1000 + 0.5))

    # Carry rounded seconds (e.g. 59.5s → 60s → 1m).
    if seconds == 60:
        seconds = 0
        minutes += 1
    if minutes == 60:
        minutes = 0
        hours += 1
    if hours == 24:
        hours = 0
        days += 1

    if most_significant_only:
        if days > 0:
            return f"{days}d"
        if hours > 0:
            return f"{hours}h"
        if minutes > 0:
            return f"{minutes}m"
        return f"{seconds}s"

    hide = hide_trailing_zeros

    if days > 0:
        if hide and hours == 0 and minutes == 0:
            return f"{days}d"
        if hide and minutes == 0:
            return f"{days}d {hours}h"
        return f"{days}d {hours}h {minutes}m"
    if hours > 0:
        if hide and minutes == 0 and seconds == 0:
            return f"{hours}h"
        if hide and seconds == 0:
            return f"{hours}h {minutes}m"
        return f"{hours}h {minutes}m {seconds}s"
    if minutes > 0:
        if hide and seconds == 0:
            return f"{minutes}m"
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def format_number(n: float) -> str:
    """Compact-notation number formatter matching ``formatNumber``.
    Examples: ``900`` → ``"900"``, ``1321`` → ``"1.3k"``, ``1_000`` →
    ``"1.0k"``, ``1_500_000`` → ``"1.5m"``.
    """

    if n < 1000:
        # path: Intl.NumberFormat compact with no minimum fraction
        # digits collapses < 1000 values to bare integers.
        return str(int(n))
    if n < 1_000_000:
        return f"{n / 1000:.1f}k"
    if n < 1_000_000_000:
        return f"{n / 1_000_000:.1f}m"
    return f"{n / 1_000_000_000:.1f}b"


def format_tokens(count: int) -> str:

    return format_number(count).replace(".0", "")


def format_clock_time(value: datetime | None = None) -> str:
    """Lower-case 12-hour clock stamp such as ``Sep 30 1:05am``.
    Replaces the POSIX-only ``strftime("%b %d %-I:%M%p")`` idiom: the
    ``%-I`` *(no-pad hour)* directive is a glibc extension and raises
    ``ValueError: Invalid format string`` on Windows, which silently broke
    cron prompt wrapping and the REPL status line there. This builds the
    same output from portable directives only, so the day stays zero-padded
    and only the hour loses its leading zero.
    """
    from datetime import datetime as _datetime

    now = value if value is not None else _datetime.now()
    hour12 = now.hour % 12 or 12
    meridiem = "am" if now.hour < 12 else "pm"
    return f"{now.strftime('%b %d').lower()} {hour12}:{now.minute:02d}{meridiem}"
