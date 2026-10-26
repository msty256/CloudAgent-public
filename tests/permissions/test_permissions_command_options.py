#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""The ``/permissions`` picker must mirror ``cycle.CYCLE_ORDER``.

Change ``expand-permission-mode-cycle``: the picker, the Shift+Tab cycle and
``--permission-mode`` used to carry three different mode sets. The picker now
generates its options from ``CYCLE_ORDER`` so they cannot drift again.
"""

from __future__ import annotations

import unittest

from cloudagent_ext.command_system.permissions_command import _PERMISSION_MODE_OPTIONS
from cloudagent_ext.permissions.cycle import CYCLE_ORDER


class TestPickerOptions(unittest.TestCase):
    def test_options_match_cycle_order(self) -> None:
        self.assertEqual(
            [option.value for option in _PERMISSION_MODE_OPTIONS],
            list(CYCLE_ORDER),
        )

    def test_dont_ask_is_selectable(self) -> None:
        # Previously excluded as an "internal mode — not user-addressable",
        # which contradicted `--permission-mode dontAsk` accepting the value.
        self.assertIn("dontAsk", [option.value for option in _PERMISSION_MODE_OPTIONS])

    def test_bubble_stays_internal(self) -> None:
        self.assertNotIn("bubble", [option.value for option in _PERMISSION_MODE_OPTIONS])

    def test_every_option_has_a_description(self) -> None:
        for option in _PERMISSION_MODE_OPTIONS:
            self.assertTrue(option.description.strip(), msg=option.value)


if __name__ == "__main__":
    unittest.main()
