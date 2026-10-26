#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Workflow mode — discriminate and extract workflow structure from source."""

from __future__ import annotations

import logging
from pathlib import Path

from .discriminator import WorkflowDiscriminator
from .extractors.models import WorkflowGraph
from .extractors.registry import ExtractorRegistry
from .models import DiscriminationResult, THRESHOLD_FWA
from .scan_context import SourceScanContext

logger = logging.getLogger(__name__)


def extract_workflow(
    source_dir: str | Path,
    disc: DiscriminationResult,
    *,
    extractor: str | None = None,
    interactive: bool = False,
    out_dir: str | Path | None = None,
) -> WorkflowGraph | None:
    """Run extraction when mode is hybrid or fwa.

    Parameters
    ----------
    source_dir:
        Path to the source code directory.
    disc:
        Discrimination result.
    extractor:
        Optional override for extractor name.
    interactive:
        When True and extraction yields no graph, generate TODO
        completion templates regardless of mode.
    out_dir:
        Where to write the TODO templates (only used when
        ``interactive=True``).
    """
    if disc.mode not in ("hybrid", "fwa"):
        if interactive:
            logger.info(
                "Mode is %s for %s; generating interactive completion templates",
                disc.mode,
                source_dir,
            )
            from .completions import generate_completion_todo, generate_completion_yaml_stub

            generate_completion_todo(disc, source_dir, out_path=out_dir)
            generate_completion_yaml_stub(disc, source_dir, out_path=out_dir)
        return None

    path = Path(source_dir)
    scan = disc.scan or SourceScanContext.build(path)
    ext = ExtractorRegistry.get_extractor(
        path,
        name=extractor or disc.recommended_extractor,
        scan=scan,
        mode=disc.mode,
        allow_coarse=disc.total_score >= THRESHOLD_FWA and not disc.forced,
    )
    graph = ext.extract(path)
    if graph.is_empty():
        if interactive:
            logger.info(
                "Workflow extraction empty for %s; generating interactive completion templates",
                path,
            )
            from .completions import generate_completion_todo, generate_completion_yaml_stub

            generate_completion_todo(disc, path, out_path=out_dir)
            generate_completion_yaml_stub(disc, path, out_path=out_dir)
            # Return an empty graph so the caller knows extraction failed,
            # but the templates have been written.
            return None
        logger.warning("Workflow extraction empty for %s; falling back to SDK-only output", path)
        return None
    return graph


def discriminate_and_extract(
    source_dir: str | Path,
    *,
    force_mode: str | None = None,
    extractor: str | None = None,
    interactive: bool = False,
    out_dir: str | Path | None = None,
) -> tuple[DiscriminationResult, WorkflowGraph | None]:
    path = Path(source_dir)
    scan = SourceScanContext.build(path)
    disc = WorkflowDiscriminator(path, scan=scan).discriminate(force_mode=force_mode)
    graph = extract_workflow(
        path,
        disc,
        extractor=extractor,
        interactive=interactive,
        out_dir=out_dir,
    )
    return disc, graph
