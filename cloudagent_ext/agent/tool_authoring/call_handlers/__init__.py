#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Call handlers for agent-created tools."""

from .bash import (
    BashCallError,
    execute_bash,
    parse_sop_wrapper_stdout,
    resolve_bundle_venv_environment,
)
from .http import HttpCallError, execute_http
from .python import PythonCallError, execute_python
from .sdk_wrapper import (
    SdkWrapperCallError,
    execute_sdk_wrapper_in_process,
    parse_sdk_wrapper_cli_options,
    parse_sdk_wrapper_call_impl,
    should_use_in_process_sdk_wrapper,
    wrapper_uses_instance_cache,
)

__all__ = [
    "BashCallError",
    "execute_bash",
    "parse_sop_wrapper_stdout",
    "resolve_bundle_venv_environment",
    "HttpCallError",
    "execute_http",
    "PythonCallError",
    "execute_python",
    "SdkWrapperCallError",
    "execute_sdk_wrapper_in_process",
    "parse_sdk_wrapper_cli_options",
    "parse_sdk_wrapper_call_impl",
    "should_use_in_process_sdk_wrapper",
    "wrapper_uses_instance_cache",
]
