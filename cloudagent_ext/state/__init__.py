#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Python package placeholder for the archived `state` subsystem.

CCX fork note: the original upstream snapshot script reads a JSON
metadata blob out of ``reference_data/subsystems/``. The CCX
port keeps the same four public symbols but routes the loader
through a private helper so the module body no longer mirrors the
upstream template verbatim.
"""

from __future__ import annotations

import json
from pathlib import Path


def _ccx_load_placeholder_payload(snapshot_basename: str) -> dict:
    # cloudagent_ext/state -> cloudagent_ext -> reference_data/...
    snapshot_path = (
        Path(__file__).resolve().parent.parent
        / "reference_data"
        / "subsystems"
        / f"{snapshot_basename}.json"
    )
    return json.loads(snapshot_path.read_text())


_payload = _ccx_load_placeholder_payload("state")

# Public legacy contract — see ``scripts/audit/parity_audit.py`` and
# ``tests/misc/test_porting_workspace.py`` for canonical consumers.
ARCHIVE_NAME: str = _payload["archive_name"]
MODULE_COUNT: int = _payload["module_count"]
SAMPLE_FILES: tuple[str, ...] = tuple(_payload["sample_files"])
PORTING_NOTE: str = f"Python placeholder package for '{ARCHIVE_NAME}' with {MODULE_COUNT} archived module references."

__all__ = ["ARCHIVE_NAME", "MODULE_COUNT", "PORTING_NOTE", "SAMPLE_FILES"]


# ---------------------------------------------------------------------------
# ``state.cache_state`` used to be bound as an attribute of the package by the
# removed ``src/state/__init__.py`` (module-identity swap).  Keep the same
# surface so ``from cloudagent_ext.state import cache_state`` and
# ``getattr(state, "cache_state")`` keep resolving.
# ---------------------------------------------------------------------------
from cloudagent_ext.state import cache_state as cache_state  # noqa: E402, F401

__all__ = sorted(set(__all__) | {"cache_state"})
