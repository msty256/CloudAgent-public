#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""IntentFocus protocol.

Given an issue and a workspace path, return the files/regions the
orchestrator should edit first. Default implementation is copied from
``cloudagent_ext.intent_forecast.focus.compute_workspace_focuses``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(slots=True)
class IssueLike(Protocol):
    """Structural type for an issue to compute focuses for. Attributes
    are compatible with ``extensions.orchestrator.issue.Issue``.
    """

    issue_id: str
    title: str
    body: str


@dataclass(slots=True)
class FocusArea:
    """One focus area in a workspace.

    Attributes:
        path: file path relative to workspace root
        rationale: human-readable reasoning
        confidence: 0.0..1.0
    """

    path: str
    rationale: str
    confidence: float = 1.0


@runtime_checkable
class IntentFocus(Protocol):
    """Workspace focus computation."""

    def compute_workspace_focuses(
        self,
        workspace: Path,
        issue: IssueLike,
    ) -> list[FocusArea]: ...


__all__ = ["FocusArea", "IntentFocus", "IssueLike"]
