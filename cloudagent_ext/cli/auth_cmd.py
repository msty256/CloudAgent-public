#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Auth CLI subcommand — login/logout/status."""

from __future__ import annotations

import sys

from cloudagent_ext.auth.codex_store import (
    AUTH_FILE,
    logout as _logout,
    zeroize_auth,
)
from cloudagent_ext.cli.subcommand_registry import register


@register("auth")
def run_auth_command(args: list[str]) -> int:
    """Handle ``cloudagent auth <subcommand>``.

    Subcommands:
        logout    — delete encrypted auth file + zeroize in-memory secrets
        status    — show whether auth file exists
        zeroize   — scrub in-memory credential cache only (keep file)
    """
    if not args:
        print("Usage: cloudagent auth [logout|status|zeroize]", file=sys.stderr)
        return 1

    cmd = args[0]
    if cmd == "logout":
        if not AUTH_FILE.exists():
            print("Already logged out — no auth file found.")
        else:
            _logout()
            print(f"Logged out. Auth file deleted and memory scrubbed: {AUTH_FILE}")
        return 0

    if cmd == "status":
        if AUTH_FILE.exists():
            size = AUTH_FILE.stat().st_size
            print(f"Auth file exists: {AUTH_FILE} ({size} bytes, encrypted)")
            return 0
        print("No auth file found — not logged in.")
        return 1

    if cmd == "zeroize":
        zeroize_auth()
        print("In-memory credential cache zeroized.")
        return 0

    print(f"Unknown auth subcommand: {cmd}", file=sys.stderr)
    print("Usage: cloudagent auth [logout|status|zeroize]", file=sys.stderr)
    return 1
