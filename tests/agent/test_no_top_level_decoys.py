#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Regression guard: shadowed-dead decoy modules must not return.

Phase 2 of the ch01 architecture refactor deleted top-level modules that
were shadowed by same-named packages or had zero consumers (``query.py``,
``Tool.py``, ``models.py``; later ``repl.py``). Round-2 P3 relocated all
audit-only scaffolding to ``scripts/audit/``, emptying the
``KNOWN_SHADOWS_PENDING_P3`` allowlist.

The upstream ``src/`` tree has since been merged into ``cloudagent_ext/``,
so the guard now scans the single-layer package root. Re-introducing any
decoy — or adding a *new* same-name-as-package module — would re-create
the same unreachable-module trap (see
``my-docs/ch01-architecture-gap-analysis.md`` §1 TL;DR item 1).
"""

from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2] / "cloudagent_ext"


SHADOWED_DEAD_FORBIDDEN = (
    "query.py",
    "Tool.py",
    "models.py",
)


PACKAGE_NAMES = (
    "query",
    "tool_system",
    "tasks",
    "permissions",
    "providers",
    "memdir",
    "hooks",
    "state",
    "bootstrap",
    "services",
    "context_system",
    "command_system",
    "tui",
    "entrypoints",
    "transports",
    "remote",
    "server",
    "bridge",
    "models",
    "coordinator",
    "assistant",
    "buddy",
    "plugins",
    "skills",
    "schemas",
    "screens",
    "constants",
    "keybindings",
    "migrations",
    "components",
    "auth",
    "moreright",
    "compact_service",
    "voice",
    "repl",
)


KNOWN_SHADOWS_PENDING_P3: dict[str, str] = {}


@pytest.mark.parametrize("filename", SHADOWED_DEAD_FORBIDDEN)
def test_no_shadowed_dead_decoy(filename: str) -> None:
    """A previously-deleted top-level decoy module must not reappear."""
    path = PKG_ROOT / filename
    assert not path.exists(), (
        f"Top-level decoy {path} was re-introduced after Phase 2 of the "
        f"ch01 architecture refactor. See my-docs/ch01-architecture-"
        f"refactoring-plan.md §P2."
    )


@pytest.mark.parametrize("pkg", PACKAGE_NAMES)
def test_no_module_shadows_package(pkg: str) -> None:
    """Same-named .py + package/ creates a silent shadow trap (the .py
    becomes unreachable via ``import cloudagent_ext.<pkg>``). Allowlist entries
    in ``KNOWN_SHADOWS_PENDING_P3`` exempt their package; everything
    else must not shadow.
    """
    if pkg in KNOWN_SHADOWS_PENDING_P3:
        pytest.skip(f"{pkg}: allowed pending P3 — {KNOWN_SHADOWS_PENDING_P3[pkg]}")
    package_init = PKG_ROOT / pkg / "__init__.py"
    same_name_module = PKG_ROOT / f"{pkg}.py"
    if package_init.exists() and same_name_module.exists():
        pytest.fail(
            f"cloudagent_ext/{pkg}.py shadows cloudagent_ext/{pkg}/__init__.py — "
            f"Python's import resolution prefers the package, leaving "
            f"{pkg}.py unreachable. "
            f"See my-docs/ch01-architecture-gap-analysis.md §1 TL;DR item 1."
        )


def test_known_shadow_allowlist_is_tight() -> None:
    """Every entry in ``KNOWN_SHADOWS_PENDING_P3`` must correspond to a
    real shadow on disk. Round-2 P3 landed: the dict is now empty and
    must stay empty unless a future plan introduces a transitional
    shadow.
    """
    for pkg in KNOWN_SHADOWS_PENDING_P3:
        package_init = PKG_ROOT / pkg / "__init__.py"
        same_name_module = PKG_ROOT / f"{pkg}.py"
        assert package_init.exists() and same_name_module.exists(), (
            f"KNOWN_SHADOWS_PENDING_P3 lists '{pkg}' but no shadow exists on disk. Remove the allowlist entry."
        )
