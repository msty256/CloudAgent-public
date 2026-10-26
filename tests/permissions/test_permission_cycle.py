#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Tests for src/permissions/cycle.py.

The cycle is a ring over ``CYCLE_ORDER`` that *skips* unavailable modes instead
of wrapping straight to ``default``. These tests pin the skipped position
(``auto`` → skip ``bypassPermissions`` → ``default``) separately from the
direct successors, because getting that wrong is the easiest way to reintroduce
the old "only three modes" behaviour.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from cloudagent_ext.permissions.types import ToolPermissionContext
from cloudagent_ext.permissions.cycle import (
    CYCLE_ORDER,
    _CYCLE_OVERRIDES,
    cycle_permission_mode,
    get_next_permission_mode,
    register_cycle_step,
)


class TestGetNextPermissionMode(unittest.TestCase):
    def test_default_to_acceptEdits(self) -> None:
        ctx = ToolPermissionContext(mode="default")
        self.assertEqual(get_next_permission_mode(ctx), "acceptEdits")

    def test_acceptEdits_to_plan(self) -> None:
        ctx = ToolPermissionContext(mode="acceptEdits")
        self.assertEqual(get_next_permission_mode(ctx), "plan")

    def test_plan_with_bypass_to_dontAsk(self) -> None:
        # `bypassPermissions` sits at the END of the ring, so plan's direct
        # successor is dontAsk regardless of bypass availability.
        ctx = ToolPermissionContext(
            mode="plan",
            is_bypass_permissions_mode_available=True,
        )
        self.assertEqual(get_next_permission_mode(ctx), "dontAsk")

    def test_plan_without_bypass_to_dontAsk(self) -> None:
        ctx = ToolPermissionContext(
            mode="plan",
            is_bypass_permissions_mode_available=False,
        )
        self.assertEqual(get_next_permission_mode(ctx), "dontAsk")

    def test_bypassPermissions_wraps_to_default(self) -> None:
        ctx = ToolPermissionContext(mode="bypassPermissions")
        self.assertEqual(get_next_permission_mode(ctx), "default")

    def test_dontAsk_to_auto(self) -> None:
        ctx = ToolPermissionContext(mode="dontAsk")
        self.assertEqual(get_next_permission_mode(ctx), "auto")

    def test_auto_to_default_when_bypass_unavailable(self) -> None:
        # The skip happens HERE (auto → bypass is the blocked edge), not
        # between plan and dontAsk.
        ctx = ToolPermissionContext(mode="auto", is_bypass_permissions_mode_available=False)
        self.assertEqual(get_next_permission_mode(ctx), "default")

    def test_auto_to_bypassPermissions_when_available(self) -> None:
        ctx = ToolPermissionContext(mode="auto", is_bypass_permissions_mode_available=True)
        self.assertEqual(get_next_permission_mode(ctx), "bypassPermissions")

    def test_bubble_to_default(self) -> None:
        ctx = ToolPermissionContext(mode="bubble")
        self.assertEqual(get_next_permission_mode(ctx), "default")

    def test_unknown_mode_to_default(self) -> None:
        ctx = ToolPermissionContext(mode="not-a-mode")
        self.assertEqual(get_next_permission_mode(ctx), "default")

    def test_auto_not_blocked_by_danger_history(self) -> None:
        # Shift+Tab is an explicit user action, so the process-global denial
        # history must not silently remove `auto` from the cycle.
        ctx = ToolPermissionContext(mode="dontAsk")
        with patch(
            "cloudagent_ext.permissions.cycle._has_recent_dangerous_operations",
            return_value=True,
        ):
            self.assertEqual(get_next_permission_mode(ctx), "auto")


class TestCyclePermissionMode(unittest.TestCase):
    def test_returns_next_mode_and_updated_context(self) -> None:
        ctx = ToolPermissionContext(mode="default")
        next_mode, next_ctx = cycle_permission_mode(ctx)
        self.assertEqual(next_mode, "acceptEdits")
        self.assertEqual(next_ctx.mode, "acceptEdits")

    def test_full_cycle_no_bypass(self) -> None:
        ctx = ToolPermissionContext(
            mode="default",
            is_bypass_permissions_mode_available=False,
        )
        modes: list[str] = []
        for _ in range(5):
            mode, ctx = cycle_permission_mode(ctx)
            modes.append(mode)
        # acceptEdits → plan → dontAsk → auto → (skip bypass) → default
        self.assertEqual(modes, ["acceptEdits", "plan", "dontAsk", "auto", "default"])

    def test_full_cycle_with_bypass(self) -> None:
        ctx = ToolPermissionContext(
            mode="default",
            is_bypass_permissions_mode_available=True,
        )
        modes: list[str] = []
        for _ in range(6):
            mode, ctx = cycle_permission_mode(ctx)
            modes.append(mode)
        # acceptEdits → plan → dontAsk → auto → bypassPermissions → default
        self.assertEqual(
            modes,
            [
                "acceptEdits",
                "plan",
                "dontAsk",
                "auto",
                "bypassPermissions",
                "default",
            ],
        )

    def test_cycle_preserves_other_context_fields(self) -> None:
        ctx = ToolPermissionContext(
            mode="default",
            always_allow_rules={"session": ["Read"]},
            is_bypass_permissions_mode_available=True,
        )
        _, next_ctx = cycle_permission_mode(ctx)
        self.assertEqual(next_ctx.always_allow_rules, {"session": ["Read"]})
        self.assertTrue(next_ctx.is_bypass_permissions_mode_available)


class TestCycleRingInvariants(unittest.TestCase):
    def test_cycle_order_covers_every_public_mode(self) -> None:
        self.assertEqual(
            CYCLE_ORDER,
            ("default", "acceptEdits", "plan", "dontAsk", "auto", "bypassPermissions"),
        )
        # `bubble` is internal (sub-agent escalation) and must stay out.
        self.assertNotIn("bubble", CYCLE_ORDER)

    def test_every_mode_returns_to_default(self) -> None:
        # A closed loop would strand the user; walking the ring must always
        # reach `default` within one full lap from any starting mode.
        for mode in CYCLE_ORDER:
            ctx = ToolPermissionContext(mode=mode, is_bypass_permissions_mode_available=False)
            seen: list[str] = []
            for _ in range(len(CYCLE_ORDER)):
                nxt = get_next_permission_mode(ctx)
                seen.append(nxt)
                ctx = ToolPermissionContext(
                    mode=nxt, is_bypass_permissions_mode_available=False
                )
            self.assertIn("default", seen, msg=f"loop detected starting from {mode!r}")

    def test_register_cycle_step_overrides_ring(self) -> None:
        try:
            register_cycle_step("default", "plan")
            ctx = ToolPermissionContext(mode="default")
            self.assertEqual(get_next_permission_mode(ctx), "plan")
        finally:
            _CYCLE_OVERRIDES.pop("default", None)

    def test_install_permission_extensions_registers_no_override(self) -> None:
        # Guards the hard prerequisite of the ring rewrite: re-registering
        # `bypassPermissions → dontAsk` turns into an override and closes the
        # loop bypass → dontAsk → auto → bypass.
        from cloudagent_ext.permissions import install_permission_extensions

        install_permission_extensions()
        self.assertEqual(
            _CYCLE_OVERRIDES,
            {},
            msg="install_permission_extensions() must not register cycle overrides",
        )


if __name__ == "__main__":
    unittest.main()
