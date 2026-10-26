#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Failure recovery helpers for LLM-driven ultraplan generation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlannerRecoveryHint:
    message: str
    can_retry: bool = True
    manual_mode_suggested: bool = True


def recovery_hint(error: Exception) -> PlannerRecoveryHint:
    return PlannerRecoveryHint(
        message=(f"LLM planning failed. Try simplifying the goal or provide a manual plan JSON. Last error: {error}")
    )
