#!/usr/bin/env python3
# coding=utf-8

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

from extensions.sop_converter.runtime.bundle_context import (
    logger,
    SOP_CONVERTER_SPEC_SOURCES,
    SOP_BUNDLE_SPEC_SOURCES,
    is_sop_converter_spec_source,
    BundleContext,
    set_active_bundle,
    get_active_bundle,
    build_bundle_context,
    apply_sdk_source_working_directory,
    collect_tool_names_from_skills,
    collect_tool_names_from_bundle_specs,
    is_pos_converter_tool,
    filter_tools_for_bundle,
    load_bundle_persisted_tools,
    ensure_bundle_tools_registered,
    prune_registry_to_bundle,
    activate_bundle_isolation,
    load_bundle_macro_routes,
)

__all__ = [
    "logger",
    "SOP_CONVERTER_SPEC_SOURCES",
    "SOP_BUNDLE_SPEC_SOURCES",
    "is_sop_converter_spec_source",
    "BundleContext",
    "set_active_bundle",
    "get_active_bundle",
    "build_bundle_context",
    "apply_sdk_source_working_directory",
    "collect_tool_names_from_skills",
    "collect_tool_names_from_bundle_specs",
    "is_pos_converter_tool",
    "filter_tools_for_bundle",
    "load_bundle_persisted_tools",
    "ensure_bundle_tools_registered",
    "prune_registry_to_bundle",
    "activate_bundle_isolation",
    "load_bundle_macro_routes",
]

from extensions.sop_converter.runtime import bundle_context as _impl

for _name, _value in vars(_impl).items():
    if _name.startswith("_") and not _name.startswith("__"):
        globals()[_name] = _value
del _name, _value, _impl
