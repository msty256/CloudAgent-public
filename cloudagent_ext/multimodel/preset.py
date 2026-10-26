#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Built-in model-group templates."""

from __future__ import annotations

from .config import GroupConfig, SlotConfig

PRESETS: dict[str, GroupConfig] = {
    "quick-compare": GroupConfig(
        "parallel",
        (
            SlotConfig("sonnet", "anthropic", "claude-sonnet-4-6"),
            SlotConfig("gpt4o", "openai", "gpt-4o"),
            SlotConfig("deepseek", "deepseek", "deepseek-v4-flash"),
        ),
        aggregator="passthrough",
    ),
    "high-reliability": GroupConfig(
        "voting",
        (
            SlotConfig("sonnet", "anthropic", "claude-sonnet-4-6", weight=2),
            SlotConfig("gpt4o", "openai", "gpt-4o"),
            SlotConfig("deepseek", "deepseek", "deepseek-v4-flash"),
        ),
        aggregator="majority",
        min_votes=2,
    ),
    "budget-safe": GroupConfig(
        "fallback",
        (
            SlotConfig("primary", "deepseek", "deepseek-v4-flash"),
            SlotConfig("fallback1", "openai", "gpt-4o"),
            SlotConfig("fallback2", "anthropic", "claude-sonnet-4-6"),
        ),
    ),
}


def get_preset(name: str) -> GroupConfig:
    try:
        return PRESETS[name]
    except KeyError as exc:
        raise KeyError(f"unknown preset '{name}'") from exc
