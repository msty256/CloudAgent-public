#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Diagnostics primitives (§18).

This package houses the freeze-detection watchdog (Layer 1) and its
dump / resolution helpers. Nothing in here modifies behaviour of the
canonical query / agent loop — every consumer is opt-in via
``CLOUDAGENT_FREEZE_DIAG=1`` (real-time enable) or an explicit ``start()``
call.

Layer 0 quick fixes (P108-A Permission/AskUser auto-deny, P108-B
headless future budget, P108-C tool timeout) live with their owning
modules (``cloudagent_ext/tui/agent_bridge.py``,
``extensions/api/query.py``); Layer 2 hard timeouts and Layer 3
auto-recovery live in ``extensions/api/query.py`` and
``cloudagent_ext/query/agent_loop_compat.py``. Layer 4 diagnostics CLI
(:mod:`cloudagent_ext.cli.diag_cmd`) wraps this package.
"""

from .freeze_config import (
    DEFAULT_FREEZE_SETTINGS,
    FreezeSettings,
    dump_path,
    env_var_for,
    resolve_freeze_settings,
)
from .freeze_detector import (
    DEFAULT_FREEZE_CHECK_INTERVAL_S,
    DEFAULT_FREEZE_DIAG_ENV,
    FreezeDetector,
    FreezeDump,
    ThreadStackFrame,
)
from .recovery import (
    RecoveryAction,
    RecoverySpec,
    describe,
    recovery_actions,
)

__all__ = [
    "DEFAULT_FREEZE_SETTINGS",
    "DEFAULT_FREEZE_CHECK_INTERVAL_S",
    "DEFAULT_FREEZE_DIAG_ENV",
    "FreezeDetector",
    "FreezeDump",
    "FreezeSettings",
    "RecoveryAction",
    "RecoverySpec",
    "ThreadStackFrame",
    "describe",
    "dump_path",
    "env_var_for",
    "recovery_actions",
    "resolve_freeze_settings",
]
