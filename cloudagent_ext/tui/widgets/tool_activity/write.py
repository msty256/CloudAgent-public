#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Write tool activity — shows target file and operation kind."""

from __future__ import annotations

from typing import Any

from rich.text import Text

from .base import ToolActivity


class WriteActivity(ToolActivity):
    def inflight_text(self) -> Text:
        path = self.tool_input.get("file_path") or self.tool_input.get("filePath") or ""
        return Text(f"write {path}" if path else "write …", style="dim")

    def result_body(self, output: Any, *, is_error: bool) -> Any | None:
        if not isinstance(output, dict):
            return None
        path = output.get("filePath") or output.get("file_path") or ""
        op = output.get("type") or ""
        summary = f"{op} · {path}".strip(" ·")
        if not summary:
            return None
        return Text(summary, style="red" if is_error else "green")
