#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Helpers for external-agent REPL debugging."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Mapping, TextIO


_TRUTHY = {"1", "true", "yes", "on"}
_FALSEY = {"", "0", "false", "no", "off"}


def agent_debug_enabled(environ: Mapping[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    raw = str(env.get("CLOUDAGENT_AGENT_DEBUG", "")).strip().lower()
    if raw in _TRUTHY:
        return True
    if raw in _FALSEY:
        return False
    return False


def resolve_repl_history_file(
    environ: Mapping[str, str] | None = None,
    *,
    home: Path | None = None,
) -> Path:
    env = os.environ if environ is None else environ
    explicit = str(env.get("CLOUDAGENT_HISTORY_FILE", "")).strip()
    if explicit:
        return Path(explicit).expanduser()

    home_path = Path.home() if home is None else home
    if not agent_debug_enabled(env):
        return home_path / ".cloudagent" / "history"

    debug_dir = str(env.get("CLOUDAGENT_AGENT_DEBUG_DIR", "")).strip()
    base = Path(debug_dir).expanduser() if debug_dir else Path(tempfile.gettempdir()) / "cloudagent-agent-debug"
    return base / "history"


def resolve_agent_debug_dir(environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    debug_dir = str(env.get("CLOUDAGENT_AGENT_DEBUG_DIR", "")).strip()
    if debug_dir:
        return Path(debug_dir).expanduser()
    return Path(tempfile.gettempdir()) / "cloudagent-agent-debug"


def apply_agent_debug_environment(
    environ: dict[str, str] | None = None,
    *,
    debug_dir: Path | None = None,
) -> dict[str, str]:
    env = os.environ if environ is None else environ
    base = debug_dir if debug_dir is not None else resolve_agent_debug_dir(env)

    env["CLOUDAGENT_AGENT_DEBUG"] = "1"
    env["CLOUDAGENT_AGENT_DEBUG_DIR"] = str(base)
    env["CLOUDAGENT_HOME"] = str(base)
    env["CLOUDAGENT_HISTORY_FILE"] = str(base / "history")
    env["CLOUDAGENT_SESSIONS_DIR"] = str(base / "sessions")
    env["CLOUDAGENT_TELEMETRY_STORAGE_DIR"] = str(base / "telemetry")
    return env


def emit_agent_debug_marker(
    name: str,
    payload: Mapping[str, object] | None = None,
    *,
    stream: TextIO | None = None,
    environ: Mapping[str, str] | None = None,
) -> None:
    if not agent_debug_enabled(environ):
        return

    target = sys.stderr if stream is None else stream
    body = json.dumps(dict(payload or {}), sort_keys=True, separators=(",", ":"))
    target.write(f"CLOUDAGENT_AGENT_DEBUG::{name}::{body}\n")
    target.flush()
