#!/usr/bin/env python3
# coding=utf-8

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Macro definition and routing data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class MacroRoute:
    """Direct route for macro tool recall.

    MacroRoute is independent of PriorityRoute. It can actively recall
    a target tool that would not otherwise appear in normal ToolSearch results.
    """

    phrases: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    negative_keywords: list[str] = field(default_factory=list)
    target_tool: str = ""
    match_mode: Literal["exact", "all", "any"] = "all"
    selection: Literal["exclusive", "prefer"] = "prefer"
    priority: int = 100
    verified: bool = False
    enabled: bool = True
    # Narrow retrieval intent and the atomic tools shadowed by this
    # macro.  These are deliberately separate from lifecycle groups,
    # which may contain several actions (for example create + invoke).
    intent_key: str = ""
    covered_tools: list[str] = field(default_factory=list)
    unavailable_policy: Literal["restore-covered"] = "restore-covered"
    # Resolution order: session > bundle > builtin (builtin safety exclusives protected)
    scope: Literal["session", "bundle", "builtin"] = "bundle"


@dataclass
class MacroDefinition:
    """Persistent macro definition with routing and provenance."""

    version: int = 1
    name: str = ""
    description: str = ""
    scope: Literal["bundle", "session", "builtin"] = "bundle"
    enabled: bool = True
    workflow: dict = field(default_factory=dict)
    routing: MacroRoute = field(default_factory=MacroRoute)
    provenance: dict = field(default_factory=dict)
