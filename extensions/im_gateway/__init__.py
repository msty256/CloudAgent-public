#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""IM Message Gateway daemon process.

Hosts :class:`MessageGateway` as a long-running daemon, listening on a
POSIX UDS socket for REPL/orchestrator opt-in clients. Lifecycle is
managed by ``cloudagent gateway server start|stop|status|restart``
via :mod:`cloudagent_ext.cli.gateway_cmd`.

v1 (P1) ships lifecycle + PID/lock/stale-socket/health. WeChat adapter
hosting lands in P2; the full ``GatewayIpcProtocol`` listener + agent
registry in P2/P3; reliability hardening in P4; default host agent in P5.
"""
