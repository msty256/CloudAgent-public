#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Index helpers for session summaries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_summary(session_id: str, *, sessions_dir: Path | None = None) -> dict[str, Any] | None:
    from cloudagent_ext.services.session_storage import resolve_sessions_dir

    base = sessions_dir if sessions_dir is not None else resolve_sessions_dir()
    path = Path(base) / session_id / "summary.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(data, dict) and int(data.get("schema_version", 0)) >= 1:
        return data
    return None
