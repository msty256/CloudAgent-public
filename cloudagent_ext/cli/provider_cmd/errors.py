#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Provider command errors."""

from __future__ import annotations


class ProviderCommandError(Exception):
    """Base class for provider command failures."""


class UnknownProviderError(ProviderCommandError):
    def __init__(self, provider: str) -> None:
        super().__init__(f"Unknown provider: {provider}")


class NotConfiguredError(ProviderCommandError):
    def __init__(self, provider: str) -> None:
        super().__init__(f"Provider is not configured: {provider}")


class UnsupportedScopeError(ProviderCommandError):
    def __init__(self, scope: str) -> None:
        super().__init__(f"Unsupported scope: {scope}. Only user scope is supported.")
