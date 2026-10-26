#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Shared stage dispatch tables for Python and CLI bridge generators."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..capability.arc_mapper import arc_stage_impl_rel_path, is_executor_module_path
from ..capability.models import ExecutionMode, StageAgentMap
from ..extractors.pattern import resolve_pipeline_dir
from ..extractors.models import WorkflowGraph


def resolve_stage_module_path(stage, source_dir: Path) -> str | None:
    """Return repo-relative path to a stage implementation module, if any."""
    source_dir = Path(source_dir).resolve()
    pipeline_dir = resolve_pipeline_dir(source_dir)
    if pipeline_dir is not None and stage.entry_function:
        impl_rel = arc_stage_impl_rel_path(source_dir, pipeline_dir, stage)
        if impl_rel and not is_executor_module_path(impl_rel):
            return impl_rel

    if stage.file_path and not (
        pipeline_dir is not None and stage.entry_function and is_executor_module_path(stage.file_path)
    ):
        return stage.file_path.replace("\\", "/")
    for sub in ("stage_impls", "stages", "pipeline"):
        candidate = source_dir / sub / f"{stage.name.replace('-', '_')}.py"
        if candidate.is_file():
            return candidate.relative_to(source_dir).as_posix()
        candidate = source_dir / sub / f"{stage.name}.py"
        if candidate.is_file():
            return candidate.relative_to(source_dir).as_posix()
    return None


def build_bridge_tables(
    graph: WorkflowGraph,
    agent_map: StageAgentMap,
    source_dir: Path,
) -> tuple[dict[int, dict[str, Any]], dict[int, list[str]]] | None:
    """Build ``(stage_dispatch, stage_outputs)`` for wrapper/hybrid stages only."""
    source_dir = Path(source_dir).resolve()
    stage_dispatch: dict[int, dict[str, Any]] = {}
    stage_outputs: dict[int, list[str]] = {}

    for stage in graph.stages:
        profile = agent_map.profile_for_stage(stage.id)
        if not profile:
            continue
        if profile.execution_mode not in (ExecutionMode.WRAPPER, ExecutionMode.HYBRID):
            continue

        rel_path = resolve_stage_module_path(stage, source_dir)
        entry_function = profile.entry_function
        if not entry_function and stage.entry_function:
            entry_function = stage.entry_function
        stage_dispatch[stage.id] = {
            "module_path": rel_path or stage.file_path,
            "entry_function": entry_function or stage.name.replace("-", "_"),
            "stage_name": stage.name,
        }
        contract = graph.contracts.get(stage.id)
        if contract:
            stage_outputs[stage.id] = list(contract.output_files)

    if not stage_dispatch:
        return None
    return stage_dispatch, stage_outputs
