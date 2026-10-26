#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""The ``cloudagent viz`` CLI subcommand.

Usage::

    cloudagent viz                       # Start visualizer server (port 8765)
    cloudagent viz --port 9000           # Custom port
    cloudagent viz --allow-import        # Enable session import endpoint
    cloudagent viz --sessions-dir /path  # Custom sessions directory
    cloudagent viz --transcripts-dir /path  # Custom sub-agent transcripts dir
    cloudagent viz --no-open             # Don't open browser

Layout in the new CloudAgent format:

- ``~/.cloudagent/sessions/<sid>/transcript.jsonl`` — main session transcript
- ``~/.cloudagent/transcripts/<agent_id>.jsonl`` — sub-agent transcript
  (flat fallback, used when the nested resolver is not registered)
- ``~/.cloudagent/sessions/<sid>/subagents/agent-<agent_id>.jsonl`` —
  sub-agent transcript nested under the parent session
- ``~/.cloudagent/tool-events/<run_id>/events.ndjson`` — tool-event audit log
- ``~/.cloudagent/reports/run_*/state_journal.ndjson`` — orchestrator
  state journals
"""

from __future__ import annotations

import argparse
import logging
import sys
import webbrowser
from pathlib import Path

logger = logging.getLogger(__name__)


def register_viz_subcommand() -> None:
    """Register the ``viz`` subcommand with the CLI registry.

    This helper is self-contained. It tries to import the
    CLI subcommand registry lazily and silently no-ops if the registry
    is unavailable (e.g. a minimal environment where
    ``cloudagent_ext.cli.subcommand_registry`` has not been installed,
    or tests that mock the CLI surface). The visualizer package no
    longer has a hard import-time dependency on
    ``cloudagent_ext.cli.subcommand_registry`` — the dependency is
    optional and explicit, suitable for an entry-points style plugin
    loader.
    """
    try:
        from cloudagent_ext.cli.subcommand_registry import register  # pylint: disable=no-name-in-module
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug(
            "Could not register viz subcommand (registry unavailable): %s",
            exc,
        )
        return

    @register("viz")
    def _viz_handler(args: list[str]) -> int:
        return run_viz(args)


def run_viz(args: list[str] | None = None) -> int:
    """Entry point for the ``cloudagent viz`` subcommand."""
    parser = argparse.ArgumentParser(
        prog="cloudagent viz",
        description="Start the local Session Visualizer web server",
    )
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=8765,
        help="Port to listen on (default: 8765)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1; use 0.0.0.0 explicitly for LAN access)",
    )
    parser.add_argument(
        "--sessions-dir",
        type=Path,
        default=None,
        help="Main sessions directory (default: ~/.cloudagent/sessions)",
    )
    parser.add_argument(
        "--transcripts-dir",
        type=Path,
        default=None,
        help="Sub-agent transcripts directory (default: ~/.cloudagent/transcripts)",
    )
    parser.add_argument(
        "--workspaces-file",
        type=Path,
        default=None,
        help="Path to workspaces.json (default: ~/.cloudagent/workspaces.json)",
    )
    parser.add_argument(
        "--allow-import",
        action="store_true",
        default=False,
        help="Enable the session import endpoint (SSRF-protected)",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        default=False,
        help="Don't open the browser automatically",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        default=False,
        help="Enable uvicorn auto-reload (dev mode)",
    )
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["debug", "info", "warning", "error"],
        help="Logging level",
    )

    parsed = parser.parse_args(args)

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, parsed.log_level.upper()),
        format="%(asctime)s %(name)s [%(levelname)s] %(message)s",
    )

    # Lazy import to avoid pulling in FastAPI on every CLI invocation
    try:
        import uvicorn
    except ImportError:
        print(
            "Error: uvicorn is required for the visualizer. "
            "Ensure the runtime provides uvicorn[standard].",
            file=sys.stderr,
        )
        return 1

    try:
        from .server import create_app
    except ImportError as exc:
        missing = exc.name or "visualizer web dependency"
        print(
            f"Error: Visualizer web dependency is unavailable: {missing}",
            file=sys.stderr,
        )
        return 1

    app = create_app(
        sessions_dir=parsed.sessions_dir,
        transcripts_dir=parsed.transcripts_dir,
        workspaces_file=parsed.workspaces_file,
        allow_import=parsed.allow_import,
        host=parsed.host,
        port=parsed.port,
    )

    url = f"http://localhost:{parsed.port}"

    if not parsed.no_open:
        # Open browser after a short delay
        import threading

        def _open_browser() -> None:
            import time

            time.sleep(1.5)
            webbrowser.open(url)

        threading.Thread(target=_open_browser, daemon=True).start()

    print(f"CloudAgent Visualizer starting at {url}")
    print(f"   Sessions dir: {parsed.sessions_dir or '~/.cloudagent/sessions'}")
    print(f"   Transcripts dir: {parsed.transcripts_dir or '~/.cloudagent/transcripts'}")
    print(f"   Import: {'enabled' if parsed.allow_import else 'disabled'}")
    print("   Press Ctrl+C to stop\n")

    try:
        uvicorn.run(
            app,
            host=parsed.host,
            port=parsed.port,
            log_level=parsed.log_level,
            reload=parsed.reload,
        )
    except KeyboardInterrupt:
        print("\nVisualizer stopped.")
    except Exception as e:
        print(f"Error starting visualizer: {e}", file=sys.stderr)
        return 1

    return 0
