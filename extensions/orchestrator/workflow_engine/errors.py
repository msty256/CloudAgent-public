#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Workflow engine exception type definitions."""

from __future__ import annotations

from typing import Any


class WorkflowEngineError(Exception):
    """Base exception for the workflow engine."""

    def __init__(self, message: str, stage_id: int | None = None, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.stage_id = stage_id
        self.details = details or {}


class StageTimeoutError(WorkflowEngineError):
    """Stage execution timed out."""


class StageFailureError(WorkflowEngineError):
    """Stage execution failed."""


class CostExceededError(WorkflowEngineError):
    """Cost budget exceeded."""


class ValidationError(WorkflowEngineError):
    """Stage output validation failed."""


class GateRejectedError(WorkflowEngineError):
    """GATE approval rejected."""


class DecisionExhaustedError(WorkflowEngineError):
    """DECISION loop retries exhausted."""


class ConvergenceError(WorkflowEngineError):
    """DECISION convergence detected -- degenerate loop."""


class CheckpointError(WorkflowEngineError):
    """Checkpoint read/write failed."""


class WorkflowSchemaError(WorkflowEngineError):
    """Invalid workflow.yaml format."""


class ResumeError(WorkflowEngineError):
    """Failed to resume execution from checkpoint."""


class RollbackError(WorkflowEngineError):
    """Stage rollback failed."""
