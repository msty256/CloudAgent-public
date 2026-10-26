#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Computer Use domain exceptions."""


class ComputerUseError(RuntimeError):
    """Base error for Computer Use failures."""


class BinaryNotFoundError(ComputerUseError):
    """Raised when a required system binary (e.g. xdotool, scrot) is missing."""


class SafetyViolationError(ComputerUseError):
    """Raised when an action is blocked by the safety policy / dry-run gate."""


class CoordinatesOutOfBoundsError(ComputerUseError):
    """Raised when a coordinate is outside the validated region."""


class WindowNotFoundError(ComputerUseError):
    """Raised when a window lookup cannot find a matching window."""
