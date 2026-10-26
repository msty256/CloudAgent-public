#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""SessionStorage protocol.

Persist agent sessions and restore them across restarts. A Cloudagent
backend can wrap ``cloudagent_ext.services.session_storage.SessionStorage``.
"""

from __future__ import annotations
# pylint: disable=W2301

from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SessionMeta(Protocol):
    """Structural metadata for a persisted session."""

    session_id: str
    workspace: Path
    created_at: str  # ISO-8601


@runtime_checkable
class ConversationLike(Protocol):
    """Structural type for a serializable conversation.

    Compatible with ``cloudagent_ext.agent.conversation.Conversation``:
    ``messages``, ``provider``, ``model`` are accessible as attributes.
    """

    messages: list[Any]
    provider: str | None
    model: str | None


class SessionStorage(Protocol):
    """Persist + recover agent sessions across orchestrator restarts."""

    def save(self, session_id: str, conversation: ConversationLike) -> None: ...

    def load(self, session_id: str) -> ConversationLike | None: ...

    def list_sessions(
        self,
        workspace: Path | None = None,
    ) -> list[SessionMeta]: ...

    def session_dir(self) -> Path:
        """Return the canonical sessions directory (e.g. ``~/.codex/sessions/``)."""
        ...


__all__ = ["ConversationLike", "SessionMeta", "SessionStorage"]
