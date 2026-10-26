#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

from extensions.sop_converter.runtime.sop_routing import (
    looks_like_direct_sdk_execution,
    requested_agent_types_in_prompt,
    list_domain_agent_types,
    check_bundle_agent_delegation,
    refresh_domain_agent_sop_prompts,
)

__all__ = [
    "looks_like_direct_sdk_execution",
    "requested_agent_types_in_prompt",
    "list_domain_agent_types",
    "check_bundle_agent_delegation",
    "refresh_domain_agent_sop_prompts",
]

from extensions.sop_converter.runtime import sop_routing as _impl

for _name, _value in vars(_impl).items():
    if _name.startswith("_") and not _name.startswith("__"):
        globals()[_name] = _value
del _name, _value, _impl
