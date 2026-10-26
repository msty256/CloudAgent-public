#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Public Python API for CloudAgent."""
# pylint: disable=undefined-all-variable

__all__ = [
    "OrchestrationSubsystem",
    "QueryConfig",
    "QueryRunner",
    "QueryEvent",
]


def __getattr__(name: str):
    if name == "OrchestrationSubsystem":
        from .orchestration import OrchestrationSubsystem

        return OrchestrationSubsystem
    if name in {"QueryConfig", "QueryRunner", "QueryEvent"}:
        from .query import QueryConfig, QueryEvent, QueryRunner

        values = {
            "QueryConfig": QueryConfig,
            "QueryRunner": QueryRunner,
            "QueryEvent": QueryEvent,
        }
        return values[name]
    raise AttributeError(name)
