#!/usr/bin/env python3
# coding=utf-8

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

from extensions.sop_converter.core.runtime_paths import (
    is_wsl_runtime,
    wsl_path_to_windows_path,
    windows_path_to_wsl_path,
    normalize_runtime_path,
)

__all__ = [
    "is_wsl_runtime",
    "wsl_path_to_windows_path",
    "windows_path_to_wsl_path",
    "normalize_runtime_path",
]

from extensions.sop_converter.core import runtime_paths as _impl

for _name, _value in vars(_impl).items():
    if _name.startswith("_") and not _name.startswith("__"):
        globals()[_name] = _value
del _name, _value, _impl
