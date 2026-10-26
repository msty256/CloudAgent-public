#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Downstream CLI entrypoint."""

from __future__ import annotations

import sys


def main():
    """Delegate to the downstream CLI dispatch.

    Triggers the lazy ``ensure_nested_transcript_initialized()`` from
    ``cloudagent_ext.__init__`` so the nested-session transcript path
    resolver is registered before any code that writes transcripts
    runs. See that function's docstring for the circular-import
    reason this lives here, not in the package ``__init__``.
    """
    from cloudagent_ext import ensure_nested_transcript_initialized

    ensure_nested_transcript_initialized()
    from cloudagent_ext.cli.dispatch import run_cli

    return run_cli()


if __name__ == "__main__":
    sys.exit(main())
