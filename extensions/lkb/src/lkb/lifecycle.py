#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Public facade for LKB board lifecycle operations."""

from .lifecycle_core import (
    GC_QUARANTINE_AGE_SECONDS,
    GC_SESSION_ORPHAN_AGE_SECONDS,
    GC_TEMP_AGE_SECONDS,
    GC_TOMBSTONE_AGE_SECONDS,
    LifecycleData,
    LifecycleError,
    LifecycleTransitionDenied,
    VALID_STATES,
    archive_board,
    board_lifecycle_state,
    close_board,
    genesis_lifecycle,
    ordinary_write_allowed,
    ordinary_write_denial_reason,
    read_archive,
    reopen_board,
    restore_board,
    transition,
    trash_board,
)
from .lifecycle_gc import GcCandidate, gc_apply, gc_scan
from .lifecycle_purge import purge_board, read_tombstone, tombstone_path

__all__ = [
    "GC_QUARANTINE_AGE_SECONDS",
    "GC_SESSION_ORPHAN_AGE_SECONDS",
    "GC_TEMP_AGE_SECONDS",
    "GC_TOMBSTONE_AGE_SECONDS",
    "GcCandidate",
    "LifecycleData",
    "LifecycleError",
    "LifecycleTransitionDenied",
    "VALID_STATES",
    "archive_board",
    "board_lifecycle_state",
    "close_board",
    "gc_apply",
    "gc_scan",
    "genesis_lifecycle",
    "ordinary_write_allowed",
    "ordinary_write_denial_reason",
    "purge_board",
    "read_archive",
    "read_tombstone",
    "reopen_board",
    "restore_board",
    "tombstone_path",
    "transition",
    "trash_board",
]
