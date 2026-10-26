"""HTTP header builder for OAuth-authenticated requests.
. The rest of the file (the
teleport API client) is out of scope for the bridge orchestrator port.
Used by, ``archiveBridgeSession``,
``updateBridgeSessionTitle``, and the v1 to build the
standard ``Authorization`` + ``anthropic-version`` + ``Content-Type``
header set for OAuth-authed requests.
"""

from __future__ import annotations


ANTHROPIC_VERSION = '2023-06-01'
"""Anthropic API version header value.
Mirrors hardcoded ``'anthropic-version': '2023-06-01'`` used across
the codebase. Centralized here to match 's pattern of building it
into ``getOAuthHeaders``.
"""


def get_oauth_headers(access_token: str) -> dict[str, str]:
    """Build the OAuth-auth header set for an HTTP request.
    a fresh dict so callers can ``.update()`` it with request-specific
    headers (e.g. ``anthropic-beta``, ``x-organization-uuid``) without
    mutating shared state.
    """
    return {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'anthropic-version': ANTHROPIC_VERSION,
    }


__all__ = ['ANTHROPIC_VERSION', 'get_oauth_headers']
