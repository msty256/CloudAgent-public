#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Optional stage-scoped skill markdown generation."""

from __future__ import annotations

from pathlib import Path

from ..extractors.models import ExtractedStage, WorkflowGraph
from .artifact_semantics import format_io_contract_markdown


def stage_skill_body(stage: ExtractedStage, graph: WorkflowGraph) -> str:
    contract = graph.contracts.get(stage.id)
    lines = [
        f"# Skill: {stage.name}",
        "",
        stage.description or f"Stage {stage.label} operations.",
        "",
    ]
    io_section = format_io_contract_markdown(contract)
    if io_section:
        lines.append(io_section)
    return "\n".join(lines)


def write_stage_skill(
    stage: ExtractedStage,
    graph: WorkflowGraph,
    output_dir: Path,
    *,
    tools: list[str] | None = None,
) -> Path | None:
    """Write optional stage-scoped SKILL.md under .atomcode/skills/."""
    skill_name = f"{stage.name}-skill"
    skill_dir = output_dir / ".atomcode" / "skills" / skill_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / "SKILL.md"
    lines = [
        "---",
        f"name: {skill_name}",
        f"description: Stage skill for {stage.label}",
        "user-invocable: true",
    ]
    if tools:
        lines.append("allowed-tools:")
        for tool in tools:
            lines.append(f"  - {tool}")
    if (output_dir / ".cloudagent" / "tool-dependencies.yaml").exists():
        lines.append("lifecycle-deps: .cloudagent/tool-dependencies.yaml")
    lines.append("---\n")
    frontmatter = "\n".join(lines) + "\n"
    path.write_text(frontmatter + stage_skill_body(stage, graph), encoding="utf-8")
    return path
