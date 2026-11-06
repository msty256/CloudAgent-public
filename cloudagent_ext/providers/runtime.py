#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Runtime provider construction helpers."""

from __future__ import annotations

import os

# fix: importing the package (not just ``factory``) triggers
# ``cloudagent_ext/providers/__init__.py``, which registers the
# cancel-latency-fixed ``CloudagentAnthropicProvider`` /
# ``CloudagentMinimaxProvider`` overrides via
# ``_EXTRA_PROVIDER_CLASSES``. Without this side-effect import,
# ``get_provider_class("anthropic")`` falls through to the bare
# upstream ``AnthropicProvider``, which iterates
# ``stream.text_stream`` on the main thread — its only cancellation
# mechanism is ``response.close()`` (advisory on Linux/Winsock and
# silently a no-op for the ``_transport`` access in our
# ``_close_transport_safely`` helper because ``httpx.Response``
# doesn't expose ``_transport``), so a Ctrl+C waits the full platform
# socket timeout (~60s) instead of the ~100ms the worker-thread
# poll in ``drain_text_stream_with_abort_poll`` provides.
#
# Importing here is safe because every provider-build call site goes
# through ``build_provider_from_config`` / ``create_provider``, and
# this module sits at the top of that dependency chain. ``factory``
# already imports cleanly from this module (no circular reference),
# so the chain is: caller -> ``runtime`` -> factory + package
# ``__init__`` -> ``register_provider`` populates
# ``_EXTRA_PROVIDER_CLASSES``.
import cloudagent_ext.providers  # noqa: F401  -- side-effect import

from cloudagent_ext.auth.codex_oauth import CodexAuthError, resolve_codex_runtime_credentials
from cloudagent_ext.config import get_provider_config
from cloudagent_ext.providers.factory import create_provider

from cloudagent_ext.providers.base import BaseProvider

OAUTH_PROVIDERS = {"openai-codex"}


def _workbuddy_has_local_session(provider_name: str) -> bool:
    """Whether a WorkBuddy route can authenticate from this machine.

    WorkBuddy issues no API keys: the credential is the sign-in the WorkBuddy
    desktop app already wrote locally (see ``providers/workbuddy_provider.py``).
    Kept beside the gate it relaxes so the two cannot drift.
    """
    try:
        from cloudagent_ext.providers.workbuddy_provider import discover_workbuddy_credentials

        region = "global" if provider_name.endswith("-global") else "cn"
        return bool(discover_workbuddy_credentials(region))
    except Exception:  # noqa: BLE001 - probing must never be fatal here
        return False


def build_provider_from_config(provider_name: str, model: str | None = None) -> BaseProvider:
    try:
        provider_cfg = get_provider_config(provider_name)
    except ValueError:
        provider_cfg = {}
    selected_model = model or provider_cfg.get("default_model")

    if provider_name == "openai-codex":
        try:
            credentials = resolve_codex_runtime_credentials()
        except CodexAuthError as exc:
            raise RuntimeError(
                f"OpenAI Codex is not authenticated. Run `cloudagent login` and select openai-codex. ({exc})"
            ) from exc
        return create_provider(
            provider_name,
            api_key=credentials.api_key,
            base_url=provider_cfg.get("base_url") or credentials.base_url,
            model=selected_model,
        )

    # Resolve API key: config first, then env var / keychain fallback.
    if not provider_cfg.get("api_key"):
        from cloudagent_ext.auth.auth import load_api_key

        api_key = load_api_key(provider_name)
        if not api_key and provider_cfg:
            if provider_name.startswith("workbuddy"):
                # `cloudagent login` cannot mint a WorkBuddy key — say what
                # actually unblocks the user instead of pointing at it.
                if not _workbuddy_has_local_session(provider_name):
                    raise RuntimeError(
                        f"WorkBuddy ({provider_name}) has no sign-in on this machine. "
                        "Sign in with the WorkBuddy desktop app (or with the "
                        "dsh-connect-workbuddy plugin) so a credential exists locally; "
                        "WorkBuddy does not issue API keys."
                    )
            else:
                raise RuntimeError(
                    f"API key for provider '{provider_name}' is not configured. "
                    "Run `cloudagent login` to set it up, or set the "
                    f"{provider_name.upper()}_API_KEY environment variable."
                )
    else:
        api_key = provider_cfg["api_key"]

    # Resolve base_url: config first, then env var fallback.
    base_url = provider_cfg.get("base_url")
    if not base_url:
        env_base = os.environ.get(f"{provider_name.upper()}_BASE_URL")
        if env_base:
            base_url = env_base

    return create_provider(
        provider_name,
        api_key=api_key,
        base_url=base_url,
        model=selected_model,
    )
