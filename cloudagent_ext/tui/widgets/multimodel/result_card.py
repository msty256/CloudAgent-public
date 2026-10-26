#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

from __future__ import annotations

from textual.widgets import Static


class ModelResultCard(Static):
    """A result card which can be rendered collapsed or expanded."""

    def set_result(self, state: object, *, selected: bool = False) -> None:
        duration = getattr(state, "duration_ms", None)
        seconds = "?" if duration is None else f"{duration / 1000:.1f}s"
        tokens = getattr(state, "tokens", {}).get("output", 0)
        slot, content = getattr(state, "slot"), getattr(state, "content")
        expanded = getattr(state, "expanded", False)
        prefix = "❯ " if selected else "  "
        text = f"{prefix}{slot} ({seconds}, {tokens} tok)\n"
        text += content if expanded else (content.splitlines()[0] if content else "等待输出…")
        self.update(text)
