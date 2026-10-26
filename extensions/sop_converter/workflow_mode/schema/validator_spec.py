#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Validator dict helpers aligned with ContractValidator types."""

from __future__ import annotations

from ..extractors.models import StageContract

VALIDATOR_TYPES = frozenset(
    {
        "file_exists",
        "file_size",
        "regex",
        "line_count",
        "json_schema",
        "custom",
    }
)


def contract_to_validators(contract: StageContract) -> list[dict]:
    """Map StageContract.output_files to file_exists validators."""
    return [{"type": "file_exists", "path": pattern} for pattern in contract.output_files]


def file_exists_validator(path: str) -> dict:
    return {"type": "file_exists", "path": path}
