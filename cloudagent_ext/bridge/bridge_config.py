#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Shared bridge auth/URL resolution.
Consolidates the ``CLAUDE_BRIDGE_*`` internal-only dev overrides that were
previously copy-pasted across the bridge subsystem. Two layers:
* ``*_override()`` returns the env var if set, else ``None``.
* The non-``_override`` wrapper falls through to the real OAuth store /
  config.
Per refactoring plan §0.1 Q6 + §2 item 9: the OAuth fallthrough (
``getClaudeAIOAuthTokens()?.accessToken``) is **not yet ported in the
Python build**. ``get_bridge_access_token`` returns ``None`` on
fallthrough (callers treat as "not logged in"). ``get_bridge_base_url``
returns ``_DEFAULT_PRODUCTION_BASE_URL`` (matches production
``getOauthConfig().BASE_API_URL`` after the GA OAuth config was finalized
— Anthropic's production API host). When Phase 2 lands the real OAuth
helpers, the fallthroughs will switch to the keychain reader; callers
see no API change.
Originally lived at
``src/bridge/bridge_config.py``; moved to ``cloudagent_ext/`` during the single-layering
refactor. The ``src/`` compatibility facade was removed along with it,
so import the ``cloudagent_ext`` path directly.
"""

from __future__ import annotations

import os

_DEFAULT_PRODUCTION_BASE_URL = "https://api.anthropic.com"
"""Fallback when no override AND no Phase 2 OAuth config is available.
 function reads from an OAuth config object populated at startup; the
Python port lands the constant inline until that config layer is ported.
"""


def get_bridge_token_override() -> str | None:
    """Dev override: ``CLAUDE_BRIDGE_OAUTH_TOKEN``, else ``None``.
    Empty string is treated as unset (matches the ``|| undefined``).
    """
    value = os.environ.get("CLAUDE_BRIDGE_OAUTH_TOKEN")
    return value or None


def get_bridge_base_url_override() -> str | None:
    """Dev override: ``CLAUDE_BRIDGE_BASE_URL``, else ``None``.
    """
    value = os.environ.get("CLAUDE_BRIDGE_BASE_URL")
    return value or None


def get_bridge_access_token() -> str | None:
    """Access token for bridge API calls.
    Returns the dev override if set, else ``None`` (Phase 2 will swap
    this fallthrough for the OAuth keychain read).
    """
    return get_bridge_token_override()


def get_bridge_base_url() -> str:
    """Base URL for bridge API calls.
    returns a non-``None`` URL. Returns the dev override if set, else the
    production base URL constant.
    """
    return get_bridge_base_url_override() or _DEFAULT_PRODUCTION_BASE_URL


__all__ = [
    "get_bridge_access_token",
    "get_bridge_base_url",
    "get_bridge_base_url_override",
    "get_bridge_token_override",
]
