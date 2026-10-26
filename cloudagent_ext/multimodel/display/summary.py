#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Summary and headless serializers for multi-model display results."""

from __future__ import annotations

import json
from typing import Iterable

from .protocol import ModelDisplayState


class SummaryBuilder:
    @staticmethod
    def build_text(results: Iterable[ModelDisplayState]) -> str:
        blocks: list[str] = []
        for result in results:
            seconds = "?" if result.duration_ms is None else f"{result.duration_ms / 1000:.1f}s"
            tokens = result.tokens.get("output", 0)
            blocks.append(f"───── {result.slot} ({seconds}, {tokens} tok) ─────\n{result.content}")
        return "\n\n".join(blocks)

    @staticmethod
    def build_json(results: Iterable[ModelDisplayState], *, strategy: str = "parallel") -> str:
        return json.dumps(
            {"multimodel": True, "strategy": strategy, "results": [result.to_dict() for result in results]},
            ensure_ascii=False,
        )
