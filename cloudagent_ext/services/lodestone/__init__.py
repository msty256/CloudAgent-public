#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""LODESTONE: unified deep-link anchor layer for CloudAgent.

LODESTONE recognises ``path:line[:column]`` / git refs / tracker issues /
function symbols that appear in any agent output, REPL panel or markdown
document and converts them into navigable URLs targeting the user's IDE,
the git remote, or the configured tracker.

This package is the core (Layer 1) implementation. Public surface:

- ``models``     : data classes (LodestoneAnchor / AnchorTarget / context)
- ``parser``     : tokenise text and classify anchors
- ``targets``    : built-in target registry (vscode / cursor / idea / …)
- ``resolver``   : pick the right target given context + user preference
- ``renderer``   : text / markdown / OSC 8 rendering
- ``fingerprint``: workspace detection (git remote, host platform)
- ``config``     : default config + persistence
- ``service``    : one-stop ``LodestoneService`` facade

Concrete consumers: ``cloudagent_ext.command_system.lodestone_commands``
provides ``/link`` sub-commands; ``cloudagent_ext.tool_system.tools.lodestone``
exposes a ``LodestoneTool`` for agent-driven rendering.
"""

from __future__ import annotations

from .models import (
    AnchorContext,
    AnchorKind,
    AnchorTarget,
    AnchorTargetRegistry,
    LodestoneAnchor,
    LodestoneConfig,
    RenderedAnchor,
    Sink,
)
from .service import LodestoneService, get_lodestone_service, reset_default_service

__all__ = [
    "AnchorContext",
    "AnchorKind",
    "AnchorTarget",
    "AnchorTargetRegistry",
    "LodestoneAnchor",
    "LodestoneConfig",
    "LodestoneService",
    "RenderedAnchor",
    "Sink",
    "get_lodestone_service",
    "reset_default_service",
]
