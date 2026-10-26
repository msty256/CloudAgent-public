#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

from extensions.sop_converter.runtime.task_guide import (
    build_operation_index,
    is_entry_point,
    generate_task_guide_markdown,
    append_task_guide_to_skill_body,
    format_flat_skill_markdown,
)

__all__ = [
    "build_operation_index",
    "is_entry_point",
    "generate_task_guide_markdown",
    "append_task_guide_to_skill_body",
    "format_flat_skill_markdown",
]

from extensions.sop_converter.runtime import task_guide as _impl

for _name, _value in vars(_impl).items():
    if _name.startswith("_") and not _name.startswith("__"):
        globals()[_name] = _value
del _name, _value, _impl
