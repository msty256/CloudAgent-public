#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Command registration for Intent Forecast."""

from __future__ import annotations

from typing import Any

from cloudagent_ext.intent_forecast.command import build_forecast_command


def register_intent_forecast_commands(registry: Any | None = None) -> None:
    from cloudagent_ext.command_system.registry import get_command_registry

    reg = registry or get_command_registry()
    reg.register(build_forecast_command())
