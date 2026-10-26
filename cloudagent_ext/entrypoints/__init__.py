#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Lazy entrypoint exports for legacy and current UI launchers."""

from __future__ import annotations

from importlib import import_module

_LAZY_NAMES = {
    "HeadlessOptions": ("cloudagent_ext.entrypoints.headless", "HeadlessOptions"),
    "run_headless": ("cloudagent_ext.entrypoints.headless", "run_headless"),
    "TUIOptions": ("cloudagent_ext.entrypoints.tui", "TUIOptions"),
    "run_tui": ("cloudagent_ext.entrypoints.tui", "run_tui"),
    "should_use_tui": ("cloudagent_ext.entrypoints.tui", "should_use_tui"),
    "launch_ink_tui": ("cloudagent_ext.entrypoints.tui_launcher", "launch_ink_tui"),
    "run_tui_launcher": ("cloudagent_ext.entrypoints.tui_launcher", "run_tui_launcher"),
}


def __getattr__(name: str):
    try:
        module_name, attribute = _LAZY_NAMES[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value


__all__ = list(_LAZY_NAMES)
