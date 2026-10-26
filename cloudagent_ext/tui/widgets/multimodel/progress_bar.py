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


class ModelProgressBars(Static):
    def set_progress(self, states: list[object], selected: int) -> None:
        out = Text()
        for index, state in enumerate(states):
            percent = getattr(state, "progress_percent", 0)
            fill = "█" * round(percent / 5) + "░" * (20 - round(percent / 5))
            marker = "●" if index == selected else "○"
            out.append(
                f"{marker} {getattr(state, 'slot')}  {fill} {percent}%\n", style="cyan" if index == selected else "dim"
            )
        self.update(out)
