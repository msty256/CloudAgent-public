#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Register a bridge script as an AgentToolSpec."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def bridge_tool_name(project_name: str) -> str:
    """Kebab-case execute-stage tool name (aligned with stage agent templates)."""
    kebab = project_name.replace("_", "-").lower()
    return f"{kebab}-execute-stage"


def register_bridge_tool(
    tool_name: str,
    bridge_script: Path,
    *,
    description: str = "Execute a single workflow stage via generated bridge",
    persist: bool = True,
    bundle_dir: Path | None = None,
) -> str | None:
    """Create bash-callable tool spec for the bridge script."""
    from cloudagent_ext.agent.tool_authoring.persistence import (
        TOOL_DIR,
        bundle_tool_dir,
        save_spec,
        scripts_dir_for,
    )
    from cloudagent_ext.agent.tool_authoring.spec import AgentToolSpec
    from cloudagent_ext.agent.tool_authoring.validators import (
        ValidationError,
        validate_spec,
    )

    script_path = bridge_script.resolve()
    if not script_path.is_file():
        logger.warning("Bridge script not found: %s", script_path)
        return None

    bundle_path = bundle_dir.resolve() if bundle_dir is not None else None
    tool_dir = bundle_tool_dir(bundle_path) if bundle_path is not None else None
    scripts_dir = scripts_dir_for(tool_dir) if tool_dir is not None else scripts_dir_for(TOOL_DIR)
    scripts_dir.mkdir(parents=True, exist_ok=True)

    dest = scripts_dir / script_path.name
    if dest.resolve() != script_path:
        dest.write_text(script_path.read_text(encoding="utf-8"), encoding="utf-8")

    call_impl = f'python3 "{dest}" --stage-id {{stage_id}} --project-dir {{project_dir}}'
    input_schema = {
        "type": "object",
        "properties": {
            "stage_id": {
                "type": "integer",
                "description": "Workflow stage id (1=TOPIC_INIT, 2=PROBLEM_DECOMPOSE, ...)",
            },
            "project_dir": {
                "type": "string",
                "description": "Pipeline run workspace directory (alias: run_dir)",
            },
            "run_dir": {
                "type": "string",
                "description": "Alias for project_dir — pipeline run workspace",
            },
        },
        "required": ["stage_id"],
    }

    spec = AgentToolSpec(
        name=tool_name,
        description=description,
        input_schema=input_schema,
        call_type="bash",
        call_impl=call_impl,
        tags=("workflow", "bridge"),
        source="sop-converter",
        bundle_id=bundle_dir.name if bundle_dir else None,
    )

    try:
        validate_spec(spec)
    except ValidationError as exc:
        logger.warning("Bridge tool spec validation failed: %s", exc)
        return None

    if persist:
        save_spec(spec, tool_dir=tool_dir)
    return spec.name
