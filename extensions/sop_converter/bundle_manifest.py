#!/usr/bin/env python3
# coding=utf-8

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

from extensions.sop_converter.core.bundle_manifest import (
    logger,
    BUNDLE_MANIFEST_NAME,
    BundleManifest,
    manifest_path_for_bundle,
    write_bundle_manifest,
    read_bundle_manifest,
    resolve_sdk_source_dir,
)

__all__ = [
    "logger",
    "BUNDLE_MANIFEST_NAME",
    "BundleManifest",
    "manifest_path_for_bundle",
    "write_bundle_manifest",
    "read_bundle_manifest",
    "resolve_sdk_source_dir",
]

from extensions.sop_converter.core import bundle_manifest as _impl

for _name, _value in vars(_impl).items():
    if _name.startswith("_") and not _name.startswith("__"):
        globals()[_name] = _value
del _name, _value, _impl
