#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Downstream extensions for the orchestrator layer.

These patches live here per the project's decoupling mandate: behaviour that
modifies ``extensions/orchestrator/`` runtime behaviour must be implemented
in ``cloudagent_ext/`` via monkey-patch, registry, or hook — never by editing
``extensions/`` source files.

Currently houses:

- :func:`install_stale_registry_patch` — keeps the daemon's in-memory
  ``IssueRegistry`` in sync with the on-disk JSON so that operator actions
  (e.g. ``cloudagent orchestrator issue retry``) written via a separate
  CLI process become visible to the running daemon without a restart.
"""

from __future__ import annotations

from ._patch_stale_registry import install_stale_registry_patch

__all__ = ["install_stale_registry_patch"]
