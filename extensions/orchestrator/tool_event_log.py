# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Tool-event audit log data contract (F-45).
Per-tool decision rows persisted to
``~/.cloudagent/tool-events/{run_id}/events.ndjson`` by
``AgentRunner._append_tool_event_log`` (extensions/orchestrator/agent_runner.py).
Schema (8 fields, fixed order — keeps `tail`/`grep` greppable):
    ts: float — time.time() at write moment
    tool: str — event.tool_name (Bash, Read, Edit, …)
    params: dict — event.params (full, not redacted — see F-45 决定 #7)
    approved: bool — event._approved (True/False); None only if
                                ApprovalPolicy skipped (shouldn't happen in
                                orchestrator headless mode post F-45 wiring)
    deny_reason: str|None — event._deny_reason (None on approve)
    permission_mode: str — session_context["permission_mode"]
                                (bypassPermissions / dontAsk / acceptEdits /
                                default / plan / auto / bubble)
    turn: int — session.turn_count at the moment of the call
    session_run_id: str — session.run_id (the directory name)
Serialised as one JSON object per line (NDJSON). Append-only, no overwrite,
no schema version field (callers must add a reader-side guard if they ever
rev the schema — see F-45 决定 #5 for forward compat with report_writer).
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

_JSON_SCALAR_TYPES = (str, int, float, bool)


def _json_safe(value: Any) -> Any:
    """Preserve JSON values and redact objects that would stringify data."""
    if value is None or isinstance(value, _JSON_SCALAR_TYPES):
        return value
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            sanitized[str(key)] = _json_safe(item)
        return sanitized
    if isinstance(value, (list, tuple)):
        return list(map(_json_safe, value))
    return "[REDACTED]"


@dataclass(frozen=True)
class ToolEventLog:
    """One row in events.ndjson."""

    tool: str
    params: dict[str, Any]
    approved: bool | None
    deny_reason: str | None
    permission_mode: str
    turn: int
    session_run_id: str
    ts: float = field(default_factory=time.time)
    # Spawn-attribution fields (all optional; omitted from the row when
    # unset so existing consumers see byte-identical rows):
    # * ``tool_use_id`` — provider call id, links a tool's call row to
    # its result row.
    # * ``kind`` — "call" (default, implicit) or "agent_result": a
    # supplemental row written when an Agent tool RETURNS, carrying
    # the spawned child's id (unknown at call time). Redundant with
    # the call row on purpose — if either row is lost the visualizer
    # can still reconstruct the spawn.
    # * ``agent_id`` — the spawned sub-agent's id (agent_result rows).
    tool_use_id: str | None = None
    kind: str = "call"
    agent_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "ts": self.ts,
            "tool": self.tool,
            "params": _json_safe(self.params),
            "approved": self.approved,
            "deny_reason": self.deny_reason,
            "permission_mode": self.permission_mode,
            "turn": self.turn,
            "session_run_id": self.session_run_id,
        }
        if self.tool_use_id:
            row["tool_use_id"] = self.tool_use_id
        if self.kind != "call":
            row["kind"] = self.kind
        if self.agent_id:
            row["agent_id"] = self.agent_id
        return row

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)
