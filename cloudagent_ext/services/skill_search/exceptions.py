#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Skill search exceptions."""

from __future__ import annotations


class SkillSearchError(Exception):
    """Base exception for skill search module."""


class SkillSourceError(SkillSearchError):
    """Raised when a skill source cannot be parsed or extracted."""


class IndexCorruptError(SkillSearchError):
    """Raised when the persisted index is corrupt and cannot be loaded."""


class SearchDisabledError(SkillSearchError):
    """Raised when search is attempted while the feature flag is off."""


class EmptyQueryError(SkillSearchError):
    """Raised when a search query is empty."""
