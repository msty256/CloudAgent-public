#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Resolve workflow artifacts inside a POS bundle directory."""

from __future__ import annotations

import logging
from pathlib import Path

from .bundle_manifest import read_bundle_manifest

logger = logging.getLogger(__name__)


def bundle_dir_from_workflow_yaml(workflow_yaml: Path) -> Path:
    return workflow_yaml.resolve().parent


def resolve_bundle_workflow_yaml(bundle_path: Path) -> Path | None:
    """Return ``workflow.yaml`` for *bundle_path* if present."""
    bundle_path = bundle_path.resolve()
    manifest = read_bundle_manifest(bundle_path)
    if manifest is not None and manifest.workflow_yaml:
        candidate = bundle_path / manifest.workflow_yaml
        if candidate.is_file():
            return candidate

    direct = bundle_path / "workflow.yaml"
    if direct.is_file():
        return direct
    return None


def discover_workflow_yaml(workspace: Path) -> Path | None:
    """Find the first workflow bundle under ``workspace/.cloudagent/*/``."""
    workspace = workspace.resolve()
    cloudagent_root = workspace / ".cloudagent"
    if not cloudagent_root.is_dir():
        return None

    candidates: list[Path] = []
    for child in sorted(cloudagent_root.iterdir()):
        if not child.is_dir():
            continue
        wf = resolve_bundle_workflow_yaml(child)
        if wf is not None:
            candidates.append(wf)

    if not candidates:
        return None
    if len(candidates) > 1:
        logger.info(
            "Multiple workflow bundles found under %s; using %s",
            cloudagent_root,
            candidates[0],
        )
    return candidates[0]


def workflow_artifacts_enabled(
    *,
    has_mapped_stages: bool,
    workflow_mode: str | None,
) -> bool:
    """Whether workflow artifacts should be emitted."""
    if has_mapped_stages:
        return True
    return workflow_mode in ("fwa", "hybrid")
