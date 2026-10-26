#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Feature-gate helpers for upstream-compatible goals."""

from __future__ import annotations

from cloudagent_ext.feature_gate import FeatureFlag, get_registry

GOALS_FEATURE = "goals"


def ensure_goals_feature_registered() -> None:
    """Register the goals gate if a fresh registry does not have it yet."""
    registry = get_registry()
    if registry.get_flag(GOALS_FEATURE) is None:
        registry.register(
            FeatureFlag(
                name=GOALS_FEATURE,
                default=True,
                description="Enable upstream-compatible /goal mode",
            )
        )


def goal_enabled() -> bool:
    """Return whether the upstream-compatible goal surface is enabled."""
    ensure_goals_feature_registered()
    return get_registry().is_enabled(GOALS_FEATURE)


__all__ = ["GOALS_FEATURE", "ensure_goals_feature_registered", "goal_enabled"]
