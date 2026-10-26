#!/usr/bin/env python3
# coding=utf-8

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Paths to versioned macro authoring templates."""

from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parent

HANDWRITTEN_MACRO_TEMPLATE = TEMPLATES_DIR / "macro.definition.yaml.template"

__all__ = [
    "TEMPLATES_DIR",
    "HANDWRITTEN_MACRO_TEMPLATE",
]
