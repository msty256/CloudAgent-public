#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Spec-1 negative assertions for the removed legacy ``Goal`` tool."""

from __future__ import annotations

import importlib

import pytest

from cloudagent_ext.tool_system.defaults import build_default_registry


def test_legacy_goal_tool_module_is_removed():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("cloudagent_ext.goal.tool")


def test_default_tool_registry_does_not_register_legacy_goal_tool():
    registry = build_default_registry(include_user_tools=False, load_agent_tools=False)

    assert registry.get("Goal") is None
    assert all(tool.name != "Goal" for tool in registry.list_tools())


def test_extension_tool_bundle_does_not_include_legacy_goal_tool():
    from extensions.tool_system_ext.registration import EXTENSION_TOOLS

    assert all(tool.name != "Goal" for tool in EXTENSION_TOOLS)
