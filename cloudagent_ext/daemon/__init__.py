#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Daemon downstream extension hooks.

This package is the *Layer-1* counterpart to ``extensions.daemon/``.
It owns the wiring that:

* Registers the ``DAEMON`` + ``BRIDGE_MODE`` feature flags with
  the runtime registry (only when called from :func:`install_daemon_gate`).
* Connects the ``extensions.daemon.cli`` verb to the downstream CLI
  subcommand registry, gated behind the feature flags so disabled
  daemons don't pollute ``cloudagent --help``.

Decoupling note
---------------
We intentionally do NOT modify ``src/entrypoints/daemon.py``. The
``src.cli.dispatch`` sieve matches ``token == 'daemon'`` against the
subcommand registry *before* importing ``src.entrypoints.daemon``
when ``get_subcommand('daemon')`` returns a handler. That's our
extension point: registering here lets the new verbs win without
patching upstream.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def install_daemon_gate() -> None:
    """Idempotently register the daemon CLI behind a double feature gate.

    Called from :func:`cloudagent_ext.ensure_eager_extensions_installed`
    so the registration happens once per process. We don't fail if
    the feature registry isn't available yet (e.g. minimal CLI) — we
    just log and move on.
    """
    try:
        from cloudagent_ext.cli.subcommand_registry import register
    except ImportError:  # pragma: no cover — minimal CLI bootstrap
        logger.debug("install_daemon_gate: subcommand_registry unavailable")
        return

    try:
        from cloudagent_ext.feature_gate import get_registry
    except ImportError:  # pragma: no cover
        logger.debug("install_daemon_gate: feature_gate unavailable")
        return

    reg = get_registry()
    if not reg.is_enabled("DAEMON"):
        logger.debug(
            "install_daemon_gate: skipping (DAEMON=%s)",
            reg.is_enabled("DAEMON"),
        )
        return

    # Heavy imports are deferred to handler-invocation time so the
    # ``cloudagent --help`` path stays light.
    @register("daemon")
    def _daemon_handler(args: list[str]) -> int:
        from extensions.daemon.cli import run_daemon

        return run_daemon(args)

    logger.info("install_daemon_gate: registered 'daemon' subcommand (DAEMON enabled)")


__all__ = ["install_daemon_gate"]
