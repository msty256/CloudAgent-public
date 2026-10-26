#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Small settings writer for ``settings.intent_forecast``."""

from __future__ import annotations

from typing import Any


def update_intent_forecast_settings(updates: dict[str, Any]) -> None:
    """Persist Intent Forecast settings to the user/global config.

    The settings loader reads extension settings from the nested
    ``settings`` section in ``~/.cloudagent/config.json``. Keep this writer
    intentionally narrow so ``/forecast on|off`` does not serialize merged
    project/local config back into the global file.
    """

    from cloudagent_ext.config import _get_default_manager  # pylint: disable=no-name-in-module
    from cloudagent_ext.settings.settings import invalidate_settings_cache  # pylint: disable=no-name-in-module

    mgr = _get_default_manager()
    cfg = mgr.load_global()
    settings = cfg.get("settings")
    if not isinstance(settings, dict):
        settings = {}
    section = settings.get("intent_forecast")
    if not isinstance(section, dict):
        section = {}
    section.update(updates)
    settings["intent_forecast"] = section
    cfg["settings"] = settings
    mgr.save_global(cfg)
    invalidate_settings_cache()
