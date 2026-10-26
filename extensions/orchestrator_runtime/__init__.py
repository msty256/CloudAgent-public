#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""In-tree orchestrator runtime: protocols and cloudagent adapters.

Ships as a monorepo package, not a separate PyPI distribution. When
``ORCHESTRATOR_USE_RUNTIME=1``, callers may take the adapter path;
otherwise they keep using ``extensions.orchestrator`` directly.
"""

from __future__ import annotations

__version__ = "0.1.0a0"

# Package marker only until cloudagent_compat is the default import path.
# See ``extensions.orchestrator_runtime.adapters.cloudagent_compat``.

__all__ = ["__version__"]
