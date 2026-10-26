#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Fast-path ``cloudagent session migrate`` CLI command.

P5-H: register the ``session`` subcommand so operators can run::

    cloudagent session migrate --from-3-file [--all] [--remove-legacy] [SESSION_ID]

Subcommand dispatch is handled by :mod:`cloudagent_ext.cli.subcommand_registry`
via the ``@register`` decorator. The actual migration logic lives in
``src/services/session_migrate.py`` so this module is purely a thin
CLI surface.
"""

from __future__ import annotations

import sys

from cloudagent_ext.cli.subcommand_registry import register

from cloudagent_ext.services.session_migrate import handle_session_migrate_cli


@register("session")
def run_session_command(args: list[str]) -> int:
    """Dispatch ``session`` sub-subcommands (currently only ``migrate``)."""
    if not args:
        print(
            "usage: cloudagent session migrate --from-3-file [--all] [--remove-legacy] [SESSION_ID]",
            file=sys.stderr,
        )
        return 2

    subcommand = args[0]
    rest = args[1:]

    if subcommand == "migrate":
        return handle_session_migrate_cli(rest)

    print(f"Unknown session command: {subcommand}", file=sys.stderr)
    print(
        "usage: cloudagent session migrate --from-3-file [--all] [--remove-legacy] [SESSION_ID]",
        file=sys.stderr,
    )
    return 2


__all__ = ["run_session_command"]
