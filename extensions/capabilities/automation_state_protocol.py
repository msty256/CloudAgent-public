# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Automation-state protocols for the orchestrator and its observers.

* :class:`AutomationStateReporter` — pull model: answers
  ``automation_state()`` with a JSON-serialisable snapshot.
* :class:`AutomationStateObserver` — push model: receives
  ``on_automation_state(snapshot)`` callbacks (e.g. Feishu activity sink).
* :class:`AutomationStateSource` — combined pull + subscribe contract
  (e.g. orchestrator ``status_dashboard.StatusDashboard``).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

__all__ = [
    "AutomationStateObserver",
    "AutomationStateReporter",
    "AutomationStateSource",
]


@runtime_checkable
class AutomationStateReporter(Protocol):
    def automation_state(self) -> dict[str, Any]:
        """Return a JSON-serialisable automation state snapshot."""


@runtime_checkable
class AutomationStateObserver(Protocol):
    """Push-mode consumer; must be cheap and idempotent (may be called rapidly)."""

    def on_automation_state(self, snapshot: dict[str, Any]) -> None:
        """Receive a fresh automation-state snapshot from a source."""


@runtime_checkable
class AutomationStateSource(Protocol):
    """An automation-state object supporting both pull and subscribe."""

    def automation_state(self) -> dict[str, Any]:
        """Return the current snapshot."""

    def subscribe(self, observer: AutomationStateObserver) -> None:
        """Register ``observer`` to receive future snapshots."""
