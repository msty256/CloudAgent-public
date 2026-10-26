#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""The single LKB feature flag with a host-optional fallback."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

PLAN_GRAPH_FEATURE_NAME = "LKB_PLAN_GRAPH"


# LKB provides a minimal FeatureRegistry with environment variables and defaults.
# Dependency, mutex, and persistence features are intentionally outside its scope.
@dataclass
class _LkbFeatureFlag:
    name: str
    default: bool = False


@dataclass
class _LkbRegistry:
    _flags: dict[str, _LkbFeatureFlag] = field(default_factory=dict)

    def register(self, flag: _LkbFeatureFlag) -> None:
        self._flags[flag.name] = flag

    def is_enabled(self, name: str) -> bool:
        flag = self._flags.get(name)
        if flag is None:
            return False
        env_val = os.environ.get(f"LKB_FEATURE_{name}")
        if env_val is not None:
            return env_val.lower() in ("1", "true", "yes")
        return flag.default


_LKB_REGISTRY = _LkbRegistry()
for _flag in (_LkbFeatureFlag(PLAN_GRAPH_FEATURE_NAME, default=False),):
    _LKB_REGISTRY.register(_flag)


def _try_cloudagent_feature_gate():
    """Use the optional CloudAgent feature gate when running inside that host."""
    try:
        from cloudagent_ext.feature_gate import get_registry, register_defaults

        register_defaults()
        return get_registry()
    except ImportError:
        return None


def is_plan_graph_enabled() -> bool:
    """Return whether the persistent Plan Graph owns Task-v2 state."""
    feature_registry = _try_cloudagent_feature_gate()
    if feature_registry is not None:
        return feature_registry.is_enabled(PLAN_GRAPH_FEATURE_NAME)
    return _LKB_REGISTRY.is_enabled(PLAN_GRAPH_FEATURE_NAME)


__all__ = ["PLAN_GRAPH_FEATURE_NAME", "is_plan_graph_enabled"]
