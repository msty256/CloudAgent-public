#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Downstream CLI extensions."""


def __getattr__(name: str):
    """Expose the legacy CLI compatibility surface (``_legacy_surface``).

    Resolved lazily: importing it runs the keychain/MDM prefetch handles that
    the old ``src.cli`` module spun up at import time, which must not happen
    for every ordinary ``cloudagent_ext.cli`` import.
    """
    import importlib

    # NB: import by name -- writing `from cloudagent_ext.cli import _legacy_surface`
    # would re-enter this __getattr__ and recurse.
    _legacy_surface = importlib.import_module("cloudagent_ext.cli._legacy_surface")
    try:
        return getattr(_legacy_surface, name)
    except AttributeError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
