#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""GATE/DECISION enrichment for overview workflow stages."""

from __future__ import annotations

from extensions.sop_converter.runtime.agent_md_writer import WorkflowStage

from ..capability.models import StageAgentMap
from ..extractors.models import WorkflowGraph


def control_flow_markdown(graph: WorkflowGraph) -> str:
    if not graph.gates and not graph.decisions:
        return ""

    lines = ["## 控制流说明", ""]
    if graph.gates:
        lines.append("### GATE 阶段")
        for sid, gate in sorted(graph.gates.items()):
            stage = next((s for s in graph.stages if s.id == sid), None)
            label = stage.label if stage else str(sid)
            lines.append(f"- Stage {sid} ({label}): 完成后需审批（模式: {gate.approval_mode}）")
        lines.append("")

    if graph.decisions:
        lines.append("### DECISION 分支")
        for sid, decision in sorted(graph.decisions.items()):
            if not decision.outcomes:
                continue
            for outcome, spec in decision.outcomes.items():
                rb = f", rollback→{spec.rollback_to}" if spec.rollback_to else ""
                mt = f", max_times={spec.max_times}" if spec.max_times else ""
                lines.append(f"- Stage {sid}: outcome `{outcome}` → Stage {spec.next_stage}{rb}{mt}")
        lines.append("")

    return "\n".join(lines)


def enrich_workflow_stages(
    graph: WorkflowGraph,
    agent_map: StageAgentMap,
    base_stages: list[WorkflowStage],
) -> list[WorkflowStage]:
    """Augment WorkflowStage descriptions with GATE/DECISION hints."""
    control_md = control_flow_markdown(graph)
    if not control_md:
        return base_stages

    enriched: list[WorkflowStage] = []
    for ws in base_stages:
        extra = ""
        stage = next((s for s in graph.stages if s.label == ws.name or s.id == ws.order), None)
        if stage:
            if stage.id in graph.gates:
                extra += f" [GATE:{graph.gates[stage.id].approval_mode}]"
            if stage.id in graph.decisions and graph.decisions[stage.id].outcomes:
                extra += " [DECISION]"
        desc = ws.description + extra if extra else ws.description
        agent = ws.responsible_agent
        if stage:
            profile = agent_map.profile_for_stage(stage.id)
            if profile and profile.mapped_agent:
                agent = profile.mapped_agent
        enriched.append(
            WorkflowStage(
                name=ws.name,
                order=ws.order,
                description=desc,
                responsible_agent=agent,
                depends_on=ws.depends_on,
                output_type=ws.output_type,
            )
        )
    return enriched
