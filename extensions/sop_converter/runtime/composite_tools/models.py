#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Data models for composite tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class CompositeStage:
    """A single stage within a composite tool workflow."""

    name: str
    description: str
    agent_ref: str | None = None
    expected_duration_s: int = 30


@dataclass
class CompositeToolSpec:
    """Specification for a composite (macro) tool.

    A composite tool is registered as an ``AgentToolSpec`` (so the agent can
    invoke it) **and** can emit a ``workflow.yaml`` sidecar for the orchestrator.

    ``call_impl`` / ``call_type`` may be set to make the tool
    executable (e.g. ``invoke-existing-agent``).  When unset, the default
    stage-echo behaviour is preserved for backwards compatibility.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    stages: list[CompositeStage] = field(default_factory=list)
    tags: tuple[str, ...] = field(default_factory=lambda: ("composite", "macro"))
    aliases: tuple[str, ...] = field(default_factory=tuple)
    call_type: Literal["bash", "http", "python", "workflow"] | None = None
    call_impl: str | dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    query_arg: str = "query"
    extra_metadata: dict = field(default_factory=dict)
    # Executable workflow specification. ``Any`` avoids a dependency
    # cycle between the registry model and the runtime model.
    workflow_spec: Any | None = None
