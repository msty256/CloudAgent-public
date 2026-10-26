#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Rich Text highlighting for ultraplan trigger keywords."""

from __future__ import annotations

from typing import Any

from rich.text import Text

from cloudagent_ext.services.ultraplan.keyword_detector import TriggerHit


RAINBOW_STYLES: tuple[str, ...] = ("red", "yellow", "green", "cyan", "blue", "magenta")


def highlight_triggers(
    text: str,
    hits: list[TriggerHit],
    *,
    palette: tuple[str, ...] = RAINBOW_STYLES,
    fallback: str | None = None,
) -> Text:
    rendered = Text(text)
    if not hits:
        return rendered
    for hit in hits:
        if fallback:
            rendered.stylize(fallback, hit.start, hit.end)
            continue
        for offset, index in enumerate(range(hit.start, hit.end)):
            rendered.stylize(palette[offset % len(palette)], index, index + 1)
    return rendered


def should_render_rainbow(stream: Any) -> bool:
    isatty = getattr(stream, "isatty", None)
    return bool(callable(isatty) and isatty())
