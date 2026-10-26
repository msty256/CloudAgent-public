#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Canonical public surface for :mod:`cloudagent_ext.buddy`."""

from __future__ import annotations

import importlib
from typing import Any

_SYMBOLS_BY_MODULE: dict[str, tuple[str, ...]] = {
    "cloudagent_ext.buddy.feature": ("is_buddy_enabled",),
    "cloudagent_ext.buddy.prompt": (
        "build_companion_intro_attachment",
        "companion_intro_text",
        "format_companion_intro_attachments",
    ),
}
_SYMBOL_MODULES = {symbol: module_name for module_name, symbols in _SYMBOLS_BY_MODULE.items() for symbol in symbols}

__all__ = list(_SYMBOL_MODULES)


def __getattr__(name: str) -> Any:
    try:
        module_name = _SYMBOL_MODULES[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(importlib.import_module(module_name), name)
    globals()[name] = value
    return value
