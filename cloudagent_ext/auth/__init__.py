#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Canonical public surface for :mod:`cloudagent_ext.auth`."""

from __future__ import annotations

import importlib
from typing import Any

_SYMBOLS_BY_MODULE: dict[str, tuple[str, ...]] = {
    "cloudagent_ext.auth.auth": (
        "ApiKeyInfo",
        "ApiKeySource",
        "get_api_key_source",
        "load_api_key",
        "validate_api_key",
    ),
    "cloudagent_ext.auth.aws": ("AwsAuth",),
    "cloudagent_ext.auth.gemini": ("GeminiAuth",),
    "cloudagent_ext.auth.oauth": ("OAuthFlow", "OAuthTokens"),
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
