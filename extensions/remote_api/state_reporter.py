#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

from __future__ import annotations

# Pylint cannot infer dynamically exposed cloudagent_ext subpackages.
# pylint: disable=no-name-in-module

from typing import Any

from cloudagent_ext.services.proactive import get_default_controller


class ProactiveAutomationStateReporter:
    def automation_state(self) -> dict[str, Any]:
        return get_default_controller().state.to_dict()


def current_automation_state() -> dict[str, Any]:
    return ProactiveAutomationStateReporter().automation_state()


def set_proactive_focus(level: str) -> dict[str, Any]:
    ctrl = get_default_controller()
    ctrl.set_focus(level)  # type: ignore[arg-type]
    return ctrl.state.to_dict()


__all__ = [
    "ProactiveAutomationStateReporter",
    "current_automation_state",
    "set_proactive_focus",
]
