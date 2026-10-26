#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Pipe IPC service primitives."""

from __future__ import annotations

from .codec import PipeJsonCodec, decode_message, encode_message
from .models import PipeMessage, PipeMessageType, PipePeer
from .permissions import PipePermissionForwarder
from .registry import PipeRegistry
from .uds import UdsPipeClient, UdsPipeServer

__all__ = [
    "PipeJsonCodec",
    "PipeMessage",
    "PipeMessageType",
    "PipePeer",
    "PipePermissionForwarder",
    "PipeRegistry",
    "UdsPipeClient",
    "UdsPipeServer",
    "decode_message",
    "encode_message",
]
