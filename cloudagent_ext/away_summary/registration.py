#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Command registration for Away Summary."""

from __future__ import annotations

import logging
from typing import Any

from cloudagent_ext.away_summary.config import (  # pylint: disable=no-name-in-module
    load_away_summary_config,
)

from .command import build_recap_command

logger = logging.getLogger(__name__)


def register_away_summary_commands(registry: Any | None = None) -> None:
    """Register /recap when enabled.

    This is intentionally separate from the Away Summary service/controller so
    future removal of the slash command can leave automatic summaries intact.
    """

    from cloudagent_ext.command_system.registry import get_command_registry

    reg = registry or get_command_registry()
    if not load_away_summary_config().recap_command_enabled:
        try:
            reg.unregister("recap")
        except Exception:
            logger.debug("Away Summary command unregister failed", exc_info=True)
        return

    reg.register(build_recap_command())
