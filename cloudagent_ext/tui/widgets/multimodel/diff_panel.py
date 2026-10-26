#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

from __future__ import annotations

from textual.widgets import Static


class MultiModelDiffPanel(Static):
    def set_diff(self, left_slot: str, right_slot: str, lines: list[str]) -> None:
        self.update(f"── Diff 模式: {left_slot} vs {right_slot} ──\n" + "\n".join(lines))
