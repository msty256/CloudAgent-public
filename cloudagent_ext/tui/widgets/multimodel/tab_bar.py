#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static


class ModelTabBar(Static):
    """Compact model selector for the streaming phase."""

    def set_tabs(self, slots: list[str], selected: int) -> None:
        out = Text()
        for index, slot in enumerate(slots):
            if index:
                out.append("  │  ", style="dim")
            out.append(slot, style="bold cyan" if index == selected else "")
        self.update(out)
