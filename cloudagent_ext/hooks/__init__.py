#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Hook system — PreToolUse, PostToolUse, Stop, Notification, PostSampling hook execution runtime.
"""

from __future__ import annotations

from .config_manager import HookConfigManager
from .hook_types import (
    AGENT_HOOK_TIMEOUT_MS,
    ALL_HOOK_EVENTS,
    HTTP_HOOK_TIMEOUT_MS,
    TOOL_HOOK_EXECUTION_TIMEOUT_MS,
    HookConfig,
    HookEvent,
    HookProgress,
    HookResult,
    HookSource,
    HookType,
    NotificationHookInput,
    PostSamplingHookInput,
    PostToolUseHookInput,
    PreToolUseHookInput,
    ShellType,
    StopHookInput,
    UserPromptSubmitHookInput,
)
from .registry import (
    AsyncHookRegistry,
    RegisteredHook,
    get_global_hook_registry,
    reset_global_hook_registry,
)
from .shell_invocation import (
    DEFAULT_HOOK_SHELL,
    SHELL_TYPES,
    build_powershell_args,
    find_powershell_path,
)

__all__ = [
    "AGENT_HOOK_TIMEOUT_MS",
    "ALL_HOOK_EVENTS",
    "DEFAULT_HOOK_SHELL",
    "HTTP_HOOK_TIMEOUT_MS",
    "SHELL_TYPES",
    "TOOL_HOOK_EXECUTION_TIMEOUT_MS",
    "AsyncHookRegistry",
    "HookConfig",
    "HookConfigManager",
    "HookEvent",
    "HookProgress",
    "HookResult",
    "HookSource",
    "HookType",
    "NotificationHookInput",
    "PostSamplingHookInput",
    "PostToolUseHookInput",
    "PreToolUseHookInput",
    "RegisteredHook",
    "ShellType",
    "StopHookInput",
    "UserPromptSubmitHookInput",
    "build_powershell_args",
    "find_powershell_path",
    "get_global_hook_registry",
    "reset_global_hook_registry",
]
