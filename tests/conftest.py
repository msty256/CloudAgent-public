#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Project-wide pytest fixtures.

Provides two cross-test isolation guarantees and one opt-in helper:

1. Package submodule re-binding — ``_ensure_patched_submodules_loaded`` keeps
   ``cloudagent_ext.config`` / ``cloudagent_ext.permissions`` /
   ``cloudagent_ext.permissions.modes`` bound on their parent package objects so
   ``monkeypatch.setattr('cloudagent_ext.config.X', ...)`` and
   ``'cloudagent_ext.permissions.modes.X', ...`` resolve even after a previous
   test pops a parent from ``sys.modules``.

2. In-memory keyring backend — ``_isolate_mcp_keyring`` swaps
   ``keyring.get_keyring()`` and the module-level free functions to a
   per-test fake so MCP token-storage tests cannot leak entries into
   the developer's real OS keychain (macOS Keychain / Linux
   secret-service / Windows DPAPI).

3. ``isolated_tmp_repo`` (opt-in) — initializes a deterministic git repo
   on ``tmp_path`` for orchestrator snapshot tests and stability-gate
   transcript tests.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Platform capability probes
# ---------------------------------------------------------------------------

POSIX = os.name == "posix"


def _console_available() -> bool:
    """Whether prompt_toolkit can build a real terminal output here.

    On Windows without a console (pytest under a non-tty runner, CI, or a
    GUI-less session) ``create_output()`` raises
    ``NoConsoleScreenBufferError``. Probed once at import time.
    """
    try:
        from prompt_toolkit.output.defaults import create_output

        create_output()
        return True
    except Exception:
        return False


HAS_CONSOLE = _console_available()


def pytest_collection_modifyitems(config, items):
    """Honour the capability markers declared in ``pyproject.toml``.

    ``linux_only`` was previously declared but never wired up, so the tests
    carrying it failed instead of skipping on Windows. ``requires_console``
    covers the prompt_toolkit/terminal-bound tests, and ``perf_sensitive``
    covers wall-clock budgets that were calibrated on an idle Linux runner.
    """
    if not POSIX:
        posix_marker = pytest.mark.skip(
            reason="requires a POSIX platform (asyncio UDS / termios / pty / signals)"
        )
        perf_marker = pytest.mark.skip(
            reason="wall-clock budget calibrated for an idle Linux runner; "
            "not meaningful on Windows"
        )
        for item in items:
            if "linux_only" in item.keywords:
                item.add_marker(posix_marker)
            if "perf_sensitive" in item.keywords:
                item.add_marker(perf_marker)
    if not HAS_CONSOLE:
        console_marker = pytest.mark.skip(
            reason="requires a real console (prompt_toolkit Win32 output unavailable)"
        )
        for item in items:
            if "requires_console" in item.keywords:
                item.add_marker(console_marker)


# Submodules that tests reach via ``monkeypatch.setattr('<pkg>.<name>.X', ...)``.
# Extend this tuple when adding new dotted-path patch sites; the autouse
# ``_ensure_patched_submodules_loaded`` fixture will pick them up automatically.
# Order: parents before children (so ``cloudagent_ext.permissions`` binds before
# ``setattr(cloudagent_ext.permissions, 'modes', ...)`` resolves).
_PATCHED_SUBMODULES: tuple[str, ...] = (
    "cloudagent_ext.config",
    "cloudagent_ext.permissions",
    "cloudagent_ext.permissions.modes",
)


@pytest.fixture(autouse=True)
def _ensure_patched_submodules_loaded():
    """Pre-import patched-path submodules and force-bind them on the
    current package object so ``monkeypatch.setattr`` resolves.

    Background: pytest's ``monkeypatch.setattr`` walks a dotted path
    via successive ``getattr`` calls. ``getattr(pkg, 'config')`` only
    succeeds if ``pkg.config`` is bound as an attribute of the package.
    ``cloudagent_ext/__init__.py`` does ``from .config import ...`` which
    normally binds it, but earlier tests in the same pytest session can
    wipe the binding in two distinct ways:

    1. Aggressive ``monkeypatch.setattr`` / ``del sys.modules['cloudagent_ext.X']``
       chains that remove the submodule.
    2. ``sys.modules.pop('<pkg>', None)`` — seen in
       ``tests/test_downstream_cli_dispatch.py::test_run_cli_version_short_circuit``.
       After this, a plain ``import cloudagent_ext.permissions`` does NOT bind
       ``permissions`` onto the freshly-imported package module because
       Python's import machinery sees the submodule already cached in
       ``sys.modules`` and skips the parent-binding step. The attribute
       then does not exist on the new package module, and any subsequent
       ``monkeypatch.setattr('cloudagent_ext.permissions.X', ...)`` fails with
       ``AttributeError: module ... has no attribute 'permissions'``.

    The same applies one level deeper: ``monkeypatch.setattr(
    'cloudagent_ext.permissions.modes.X', ...)`` reaches the parent package via
    the attribute the fixture just re-bound, then triggers
    ``__getattr__('modes')`` on that module — which only succeeds if
    ``cloudagent_ext.permissions.modes`` is already populated in ``sys.modules``.
    Pre-importing the chain is the only robust fix.

    The robust shape is data-driven via ``_PATCHED_SUBMODULES``: import
    each entry, then ``setattr(parent_module, child_name, mod)`` on
    whichever module object is currently in ``sys.modules``. This is
    cheap (one dict lookup + one attribute write per entry per test)
    and is robust against any test-pollution pattern.

    Residual effect (NOT auto-reverted): the bindings persist across the
    session. This is intentional — pytest's module cache means tests
    cannot observe the prior unbound state anyway, and every subsequent
    test that uses ``monkeypatch.setattr`` with these dotted paths
    needs them. If a future test needs to verify the *unbound* state,
    it must explicitly
    ``monkeypatch.delattr(cloudagent_ext, 'config', raising=False)``.
    """
    for dotted in _PATCHED_SUBMODULES:
        mod = importlib.import_module(dotted)
        parent_name, _, child_name = dotted.rpartition(".")
        setattr(sys.modules[parent_name], child_name, mod)
    yield


@pytest.fixture(autouse=True)
def _dummy_prompt_toolkit_terminal(monkeypatch):
    """Bind prompt_toolkit to a headless terminal when there is no console.

    ``CloudagentREPL.__init__`` builds a ``PromptSession``, which resolves its
    default output through ``prompt_toolkit.output.defaults.create_output``.
    On Windows without a console that raises ``NoConsoleScreenBufferError``,
    so every REPL-level test errored during *setup* rather than exercising the
    behaviour under test.  Substituting the library's own ``DummyOutput`` /
    ``DummyInput`` keeps the logic coverage intact on headless runners while
    leaving real terminals (developer machines, CI with a tty) untouched.

    Both the library's factories *and* the ``AppSession`` singleton cached on
    ``prompt_toolkit.application.current`` are patched, because that singleton
    memoises whichever input/output was resolved first.
    """
    if HAS_CONSOLE:
        yield
        return
    try:
        import prompt_toolkit.application.current as _pt_current
        import prompt_toolkit.input.defaults as _pt_input_defaults
        import prompt_toolkit.output.defaults as _pt_output_defaults
        from prompt_toolkit.input import DummyInput
        from prompt_toolkit.output import DummyOutput
    except ImportError:  # pragma: no cover - prompt_toolkit always installed here
        yield
        return

    monkeypatch.setattr(_pt_output_defaults, "create_output", lambda *a, **k: DummyOutput())
    monkeypatch.setattr(_pt_input_defaults, "create_input", lambda *a, **k: DummyInput())

    session = getattr(_pt_current, "_current_app_session", None)
    if session is not None:
        default = getattr(session, "default", None)
        if default is not None:
            default._input = DummyInput()
            default._output = DummyOutput()
    yield


@pytest.fixture(autouse=True)
def _stub_provider_credentials(monkeypatch):
    """Seed a placeholder credential for the default provider.

    Several tests build a live provider just to exercise wiring —
    ``RuntimeContext.build(...)`` or ``CloudagentREPL(...)``.  Without a
    resolvable credential the former raises "API key for provider 'zai' is not
    configured" and the latter calls ``sys.exit(1)``, so those tests only
    passed on a machine with a populated ``~/.cloudagent`` config — which
    ``_isolate_cloudagent_state_root`` above deliberately hides (and which is
    never present in CI).

    Only the default provider's env vars are set, so tests that assert an
    *unconfigured* provider (e.g. ``openai``) still see one.  The value is a
    placeholder: nothing here performs a network call.
    """
    monkeypatch.setenv("ZAI_API_KEY", "sk-test-placeholder-0000000000")
    monkeypatch.setenv("GLM_API_KEY", "sk-test-placeholder-0000000000")
    yield


class _InMemoryKeyringBackend:
    """Minimal ``keyring.backend.KeyringBackend`` that holds tokens in a
    process-local dict. Used by ``_isolate_mcp_keyring`` to isolate
    token storage from the real macOS Keychain / Linux secret-service
    / Windows DPAPI.

    Implements only ``get_password`` / ``set_password`` / ``delete_password``
    plus ``priority`` — sufficient for ``cloudagent_ext/.../mcp_token_storage`` as of
    2026-07. Extend with ``get_credential`` / ``set_credential`` if the
    storage layer migrates to keyring ≥ 0.16's Credential-based API.
    """

    priority = 1.0  # higher than FailKeyring

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self._store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self._store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        try:
            del self._store[(service, username)]
        except KeyError:
            # Lazy import so the class loads even when keyring is absent.
            from keyring.errors import PasswordDeleteError  # type: ignore

            raise PasswordDeleteError(f"No such entry: {service}/{username}")


def _git(*args: str, cwd: Path) -> None:
    """Run a git subcommand in ``cwd`` and surface stderr on failure.

    Plain ``subprocess.run(..., check=True, capture_output=True)`` swallows
    stderr into ``CalledProcessError.stderr``, which is rarely read by
    callers — making CI failures cryptic. This helper re-raises with the
    captured stderr/stdout inlined so the diagnostic lands in the
    pytest traceback.
    """
    try:
        subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"git {' '.join(args)} failed in {cwd} (rc={e.returncode}):\n"
            f"  stderr: {e.stderr.strip() or '(empty)'}\n"
            f"  stdout: {e.stdout.strip() or '(empty)'}"
        ) from e


@pytest.fixture
def isolated_tmp_repo(tmp_path):
    """Initialize a minimal git repo on ``tmp_path`` with deterministic identity.

    Sets ``user.email=test@test`` and ``user.name=Test`` (local scope only)
    so commits are reproducible. Runs ``git init`` with ``-b main`` so the
    default branch is named ``main`` (matching GitHub/GitCode convention).
    Returns ``tmp_path`` ready to commit into.

    Requires Git ≥ 2.28 (released 2020-07-27) for ``-b`` initial-branch
    support. Older Git falls back to the build's default branch name
    (``master`` on most builds).

    Project-wide so both ``tests/stability_gate/`` (future transcript
    tests) and ``tests/orchestrator/`` (P0-3 ``_status_snapshot``
    snapshot tests) can reuse the same minimal-repo boilerplate.
    """
    _git("init", "-b", "main", cwd=tmp_path)
    _git("config", "user.email", "test@test", cwd=tmp_path)
    _git("config", "user.name", "Test", cwd=tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def _isolate_cloudagent_state_root(tmp_path, monkeypatch):
    """Point every CloudAgent state-root override at this test's tmp dir.

    ``CLOUDAGENT_CONFIG_DIR`` (explicit config override) and
    ``CLOUDAGENT_HOME`` (shared fallback for isolated runs / tests /
    ``--agent-debug`` — see ``cloudagent_ext/memdir/paths.py``) are both
    routed to ``tmp_path`` itself so in-process tests never read the
    developer's real ``~/.cloudagent`` config (e.g. a real
    ``config.yaml`` ``multimodel.default_group`` must not trip the
    MULTIMODEL feature gate inside ``run_cli``).

    The root IS ``tmp_path`` (not a subdirectory): a subdirectory would
    show up in tests that enumerate the directory's entries and assert
    an exact listing (e.g. ``tests/input/test_at_file_completer.py``
    asserts the completion set of an empty dir).

    NOTE: ``cloudagent_ext/feature_gate/config.py`` hardcodes
    ``Path.home() / ".cloudagent"`` (module-level constant, no env hook),
    so feature-flag state files are NOT covered here — tests that write
    feature state must construct their own ``ConfigStore`` on ``tmp_path``
    (see ``tests/services/feature_gate/test_facade.py``).
    """
    monkeypatch.setenv("CLOUDAGENT_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("CLOUDAGENT_HOME", str(tmp_path))
    yield tmp_path


@pytest.fixture(autouse=True)
def _isolate_mcp_keyring(request, monkeypatch):
    """Swap ``keyring.get_keyring()`` and the module-level free functions
    to a per-test in-memory backend so MCP token-storage tests don't leak
    into the real OS keychain.

    Autouse — applies to every test, not just MCP token-storage. Reasons:

    1. **Defense in depth**: any test that incidentally touches keyring
       (including a misconfigured import chain) cannot leak tokens to
       the developer's real keychain.
    2. **Cheap**: zero I/O, zero external state; ``monkeypatch`` reverts
       the patch at teardown.
    3. **Safe opt-out**: tests that explicitly want the real keyring can
       mark themselves with ``@pytest.mark.real_keyring``. The marker is
       currently unused; kept as a forward-compat escape hatch for
       future integration tests that intentionally exercise real
       keyring backends (e.g., on a CI runner with a configured
       secret-service stub).
    """
    if "real_keyring" in request.keywords:
        yield
        return
    try:
        import keyring
    except ImportError:
        yield
        return
    fake = _InMemoryKeyringBackend()
    monkeypatch.setattr(keyring, "get_keyring", lambda: fake)
    monkeypatch.setattr(keyring, "get_password", fake.get_password)
    monkeypatch.setattr(keyring, "set_password", fake.set_password)
    monkeypatch.setattr(keyring, "delete_password", fake.delete_password)
    yield


@pytest.fixture(autouse=True)
def _isolate_diagnosis_budget_env(monkeypatch):
    """测试不得继承开发者 shell 里的预算配置。

    ``default_budget()`` 读环境变量；若开发者导出了
    ``CLOUDAGENT_DIAGNOSIS_MAX_DELEGATIONS``，多委派用例（如跨域交接的 2 次）
    会被意外拦死——这类失败与被测逻辑无关，纯属环境泄漏。需要配置的用例
    自己用 ``monkeypatch.setenv`` 再设回来。
    """

    monkeypatch.delenv("CLOUDAGENT_DIAGNOSIS_MAX_DELEGATIONS", raising=False)
    monkeypatch.delenv("CLOUDAGENT_DIAGNOSIS_MAX_DELEGATIONS_PER_AGENT", raising=False)
    yield


@pytest.fixture(autouse=True)
def _isolate_delegation_budget():
    """wire-investigation-session：派发记账改为「每 ToolContext 一个会话」。

    会话绑在 ``ToolContext.diagnosis_session_runtime`` 上，天然按上下文隔离；
    每个测试新建的 context 都是干净会话，无需全局重置。此 fixture 保留为
    空操作，仅为兼容既有引用（若将来引入进程级缓存，在这里清理）。
    """

    yield
