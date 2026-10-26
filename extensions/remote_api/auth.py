#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Optional Bearer-token authentication for the remote API."""

from __future__ import annotations

import hmac
import os

from .errors import RemoteAPIError


def resolve_api_key(configured: str | None) -> str | None:
    """Resolve the configured API key.

    ``None`` means "read environment"; an empty string explicitly disables
    auth for tests and embedded callers.
    """

    if configured is not None:
        return configured or None
    return os.getenv("CLOUDAGENT_API_KEY") or os.getenv("API_SERVER_KEY") or None


def require_bearer_auth(api_key: str | None, authorization: str | None) -> None:
    """Validate a Bearer token when auth is enabled."""

    if not api_key:
        return
    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix):
        raise RemoteAPIError(401, "missing bearer token", code="unauthorized")
    token = authorization[len(prefix) :]
    if not hmac.compare_digest(token, api_key):
        raise RemoteAPIError(401, "invalid bearer token", code="unauthorized")
