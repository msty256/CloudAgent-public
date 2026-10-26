#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Single feature-gate chokepoint for multi-model dispatch."""

from __future__ import annotations


def is_multimodel_enabled() -> bool:
    from cloudagent_ext.feature_gate import get_registry  # pylint: disable=no-name-in-module

    return get_registry().is_enabled("MULTIMODEL")


def require_multimodel_enabled() -> None:
    if not is_multimodel_enabled():
        raise RuntimeError("Multi-model mode is disabled. Enable it with `cloudagent feature set MULTIMODEL --on`.")


def disabled_message() -> str:
    return "Multi-model mode is disabled. Enable it with `cloudagent feature set MULTIMODEL --on`."


__all__ = ["disabled_message", "is_multimodel_enabled", "require_multimodel_enabled"]
