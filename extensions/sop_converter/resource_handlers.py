#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

from extensions.sop_converter.core.resource_handlers import (
    RESOURCE_TYPE_UNREGISTERED,
    ResourceHandler,
    ResourceHandlerError,
    ensure_builtin_handlers,
    get_resource_handler,
    normalize_resource_type,
    register_resource_handler,
    registered_resource_types,
    require_resource_handler,
)

__all__ = [
    "RESOURCE_TYPE_UNREGISTERED",
    "ResourceHandler",
    "ResourceHandlerError",
    "ensure_builtin_handlers",
    "get_resource_handler",
    "normalize_resource_type",
    "register_resource_handler",
    "registered_resource_types",
    "require_resource_handler",
]

from extensions.sop_converter.core import resource_handlers as _impl

for _name, _value in vars(_impl).items():
    if _name.startswith("_") and not _name.startswith("__"):
        globals()[_name] = _value
del _name, _value, _impl
