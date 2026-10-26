#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""CloudagentSessionStorage — concrete ``SessionStorage`` Protocol adapter.

Thin wrapper over ``cloudagent_ext.services.session_storage.SessionStorage``
so agent_runner does not construct the upstream class directly.

``save`` / ``load`` / ``list_sessions`` / ``session_dir`` each build a
fresh upstream instance. ``Conversation`` uses the upstream constructor;
the orchestrator ``ConversationLike`` protocol matches
``messages`` / ``provider`` / ``model``. The adapter holds no state.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from extensions.orchestrator_runtime.protocols.session_storage import (
    ConversationLike,
    SessionMeta,
    SessionStorage,
)


class CloudagentSessionStorage(SessionStorage):
    """Forward to ``cloudagent_ext.services.session_storage.SessionStorage``."""

    def _resolve_dir(self) -> Path:
        """Lazy upstream import — adapters may import upstream."""
        from cloudagent_ext.services.session_storage import resolve_sessions_dir

        return resolve_sessions_dir()

    def _upstream(self, session_id: str | None = None) -> Any:
        """Construct a fresh upstream ``SessionStorage`` handle."""
        from cloudagent_ext.services.session_storage import SessionStorage as _Upstream

        return _Upstream(session_id=session_id)

    def save(self, session_id: str, conversation: ConversationLike) -> None:
        storage = self._upstream(session_id)
        # ``Conversation`` is structurally compatible: messages / provider / model.
        # Upstream SessionStorage writes transcript via ``write_message`` /
        # ``write_raw``; we adapt by iterating ``conversation.messages`` (a
        # list of message dicts / dataclasses).
        for msg in conversation.messages:
            storage.write_raw(msg if isinstance(msg, dict) else _msg_to_dict(msg))

    def load(self, session_id: str) -> ConversationLike | None:
        storage = self._upstream(session_id)
        try:
            metadata = storage.get_metadata()
        except FileNotFoundError:
            return None
        if metadata is None:
            return None
        messages = storage.read_messages() if storage._session_dir.exists() else []
        return _ConversationAdapter(messages=messages, provider=None, model=None)

    def list_sessions(
        self,
        workspace: Path | None = None,
    ) -> list[SessionMeta]:
        from cloudagent_ext.services.session_storage import SessionStorage as _Upstream

        upstream = _Upstream()
        # Upstream ``list_sessions(workspace=...)`` returns a list of dicts
        # with session metadata; we adapt to ``SessionMeta`` Protocol.
        # source list_sessions signature differs
        # pylint: disable=E1123
        raw = upstream.list_sessions(workspace=workspace)
        result: list[SessionMeta] = []
        for entry in raw:
            if isinstance(entry, dict):
                result.append(_SessionMetaAdapter(**entry))
        return result

    def session_dir(self) -> Path:
        return self._resolve_dir()


# ─── Conversions (structurally match upstream, but defined locally to avoid
#     importing the upstream types — Protocol module stays upstream-free).


def _msg_to_dict(msg: Any) -> dict[str, Any]:
    if isinstance(msg, dict):
        return msg
    out: dict[str, Any] = {}
    for field in ("role", "content", "type", "uuid", "timestamp"):
        if hasattr(msg, field):
            out[field] = getattr(msg, field)
    return out


class _ConversationAdapter:
    """Minimal Conversation-like adapter wrapping a list of message dicts."""

    def __init__(
        self,
        messages: list[Any],
        provider: str | None,
        model: str | None,
    ) -> None:
        self.messages = messages
        self.provider = provider
        self.model = model


class _SessionMetaAdapter:
    """Minimal SessionMeta adapter wrapping a dict from ``list_sessions``."""

    def __init__(self, session_id: str, workspace: Path, created_at: str) -> None:
        self.session_id = session_id
        self.workspace = workspace
        self.created_at = created_at


__all__ = ["CloudagentSessionStorage"]
