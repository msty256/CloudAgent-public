#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""User-scope provider/model preference persistence."""

from __future__ import annotations

from cloudagent_ext.cli.model_cmd.registry import ModelRegistry
from cloudagent_ext.cli.model_cmd.errors import UnsupportedScopeError as ModelUnsupportedScopeError
from cloudagent_ext.cli.provider_cmd.errors import (
    UnsupportedScopeError as ProviderUnsupportedScopeError,
)


class ModelStore:
    """Persist default provider and provider default model preferences."""

    def __init__(self, registry: ModelRegistry | None = None) -> None:
        self.registry = registry or ModelRegistry()

    def set_default_provider(self, provider: str, *, scope: str = "user") -> None:
        if scope != "user":
            raise ProviderUnsupportedScopeError(scope)
        provider = self.registry.validate_provider(provider)
        from cloudagent_ext.config import set_default_provider

        set_default_provider(provider)

    def unset_default_provider(self, *, scope: str = "user") -> str:
        if scope != "user":
            raise ProviderUnsupportedScopeError(scope)
        provider = "anthropic"
        self.set_default_provider(provider, scope=scope)
        return provider

    def set_default_model(
        self,
        provider: str,
        model: str,
        *,
        scope: str = "user",
        allow_unknown: bool = False,
    ) -> None:
        if scope != "user":
            raise ModelUnsupportedScopeError(scope)
        provider = self.registry.validate_provider(provider)
        if not allow_unknown:
            self.registry.validate_model(model, provider)

        from cloudagent_ext.config import get_provider_config, set_api_key
        from cloudagent_ext.providers import PROVIDER_INFO

        try:
            current = get_provider_config(provider)
            api_key = current.get("api_key", "")
            base_url = current.get("base_url")
        except ValueError:
            current = None
            api_key = ""
            base_url = None
        if not base_url:
            base_url = PROVIDER_INFO[provider]["default_base_url"]
        set_api_key(
            provider,
            api_key=api_key,
            base_url=base_url,
            default_model=model,
        )

    def set_default_model_persist_unknown(
        self,
        provider: str,
        model: str,
        *,
        scope: str = "user",
    ) -> None:
        """Persist *model* as the default for *provider* even when it is
        not in :class:`ModelRegistry`'s built-in list.  ``config.json``'s
        ``models`` list is updated by ``set_api_key`` so the next session
        can still resolve the model without re-warning.
        """
        self.set_default_model(provider, model, scope=scope, allow_unknown=True)
