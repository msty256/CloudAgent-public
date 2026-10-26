#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Compatibility entry point for the CloudAgent REPL PTY controller."""

from cloudagent_ext.debug.repl_pty_session import main


if __name__ == "__main__":
    raise SystemExit(main())
