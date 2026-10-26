#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Fast-path telemetry CLI command."""

from __future__ import annotations

from cloudagent_ext.cli.subcommand_registry import register


@register("telemetry")
def run_telemetry_command(args: list[str]) -> int:
    from telemetry.cli import main

    return main(args)
