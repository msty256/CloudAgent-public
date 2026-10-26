#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Scoped configuration discovery, mutation, and runtime integration."""

from .contract import (
    ConfigurationFieldSpec,
    configuration_json_schema,
    get_configuration_contract,
    get_configuration_field,
    infer_configuration_domain,
    managed_configuration_route,
    register_settings_extension,
    validate_configuration_document,
)

from .service import (
    ConfigDomain,
    ConfigMutationRequest,
    ConfigMutationResult,
    ConfigOperation,
    ConfigScope,
    ConfigurationError,
    ConfigurationSnapshot,
    apply_configuration_snapshot,
    get_configuration_snapshot,
    invalidate_configuration,
    mutate_configuration,
    set_effort,
)

__all__ = [
    "ConfigDomain",
    "ConfigMutationRequest",
    "ConfigMutationResult",
    "ConfigOperation",
    "ConfigScope",
    "ConfigurationError",
    "ConfigurationFieldSpec",
    "ConfigurationSnapshot",
    "apply_configuration_snapshot",
    "configuration_json_schema",
    "get_configuration_contract",
    "get_configuration_field",
    "get_configuration_snapshot",
    "infer_configuration_domain",
    "invalidate_configuration",
    "mutate_configuration",
    "managed_configuration_route",
    "register_settings_extension",
    "set_effort",
    "validate_configuration_document",
]
