#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""NO_PROXY allowlist for the CCR upstream proxy (Phase 5).
exact ordering of the three Anthropic forms matters:
``'anthropic.com'`` (apex/Python urllib suffix), then
``'.anthropic.com'`` (Python urllib also strips leading dot), then
``'*.anthropic.com'`` (Bun, curl, Go glob match).
If any of the three forms is missing, runtimes that parse NO_PROXY
strictly will MITM the model API itself, breaking inference. Hence
the explicit triple form rather than relying on glob matching.
Originally lived at
``src/bridge/no_proxy.py``; moved to ``cloudagent_ext/`` during the single-layering
refactor. The ``src/`` compatibility facade was removed along with it,
so import the ``cloudagent_ext`` path directly.
"""

from __future__ import annotations

# Order matters — see module docstring for the rationale on the three
# Anthropic forms specifically.
NO_PROXY_LIST: tuple[str, ...] = (
    "localhost",
    "127.0.0.1",
    "::1",
    "169.254.0.0/16",  # IMDS
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    # Anthropic API: no upstream route will ever match, and the MITM
    # breaks non-Bun runtimes (Python httpx/certifi doesn't trust the
    # forged CA). Three forms because NO_PROXY parsing differs across
    # runtimes — see module docstring.
    "anthropic.com",
    ".anthropic.com",
    "*.anthropic.com",
    "github.com",
    "api.github.com",
    "*.github.com",
    "*.githubusercontent.com",
    "registry.npmjs.org",
    "pypi.org",
    "files.pythonhosted.org",
    "index.crates.io",
    "proxy.golang.org",
)


def default_no_proxy() -> str:
    """Comma-joined ``NO_PROXY`` string for the upstream proxy env."""
    return ",".join(NO_PROXY_LIST)


__all__ = ["NO_PROXY_LIST", "default_no_proxy"]
