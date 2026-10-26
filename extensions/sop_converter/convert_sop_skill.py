#!/usr/bin/env python3
# coding=utf-8

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

from extensions.sop_converter.runtime.convert_sop_skill import (
    logger,
    convert_sop_to_agent,
    get_prompt_for_command,
)

__all__ = [
    "logger",
    "convert_sop_to_agent",
    "get_prompt_for_command",
]

from extensions.sop_converter.runtime import convert_sop_skill as _impl

for _name, _value in vars(_impl).items():
    if _name.startswith("_") and not _name.startswith("__"):
        globals()[_name] = _value
del _name, _value, _impl
