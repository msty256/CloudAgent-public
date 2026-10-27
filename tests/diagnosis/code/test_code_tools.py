#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""只读代码工具（find_symbol / find_references）离线测试（P3.2）。

覆盖：符号查找（函数/类/方法/常量、kind 过滤、同名 note）、引用查找（Name/
Attribute、定义点排除、能力边界 note、getattr 不覆盖）、路径逃逸拒绝、超大
文件跳过、语法错误、空根提示、签名截断、注册。不依赖任何外部服务。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cloudagent_ext.diagnosis.code.tools import (
    MAX_SIGNATURE_CHARS,
    find_references_tool,
    find_symbol_tool,
    register_code_tools,
)
from cloudagent_ext.tool_system.context import ToolContext

# 平台相关的绝对路径：Windows 与 POSIX 对"绝对"的定义不同，
# 用 C:/... 在 POSIX 上只是个相对名字（会被拼到 root 下，报 path not found）。
ABSOLUTE_PATH = "C:/Windows/win.ini" if os.name == "nt" else "/etc/passwd"

_CORE_SOURCE = '''"""Core module."""

import os

def run(x, y=1):
    return x + y

class Service:
    def __init__(self):
        self.value = 0

    def run(self):
        return self.value

CONSTANT = 42

def caller():
    s = Service()
    run(1, 2)
    s.run()
    getattr(s, "run")()
    return os.path.join("a", "b")
'''


def _ctx() -> ToolContext:
    return ToolContext(workspace_root=Path.cwd())


@pytest.fixture()
def code_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "proj"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "core.py").write_text(_CORE_SOURCE, encoding="utf-8")
    (root / "pkg" / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    monkeypatch.setenv("CLOUDAGENT_CODE_ROOT", str(root))
    return root


class TestFindSymbol:
    def test_find_function(self, code_root: Path) -> None:
        result = find_symbol_tool.call({"name": "caller"}, _ctx())
        assert result.is_error is False
        symbols = result.output["symbols"]
        assert any(
            item["path"] == "pkg/core.py" and item["kind"] == "function" and item["line"] > 0
            for item in symbols
        )
        assert "name-only" in result.output["note"]

    def test_find_class(self, code_root: Path) -> None:
        result = find_symbol_tool.call({"name": "Service"}, _ctx())
        assert result.output["count"] >= 1
        assert all(item["kind"] == "class" for item in result.output["symbols"])

    def test_kind_filter_method(self, code_root: Path) -> None:
        result = find_symbol_tool.call({"name": "run", "kind": "method"}, _ctx())
        assert result.output["count"] >= 1
        assert all(item["kind"] == "method" for item in result.output["symbols"])

    def test_same_name_not_scope_disambiguated(self, code_root: Path) -> None:
        result = find_symbol_tool.call({"name": "run"}, _ctx())
        kinds = {item["kind"] for item in result.output["symbols"]}
        # 函数 run 与方法 run 都应返回（同名不做作用域区分）
        assert {"function", "method"} <= kinds
        assert "name-only" in result.output["note"]

    def test_constant(self, code_root: Path) -> None:
        result = find_symbol_tool.call({"name": "CONSTANT", "kind": "constant"}, _ctx())
        assert result.output["count"] >= 1

    def test_no_match(self, code_root: Path) -> None:
        result = find_symbol_tool.call({"name": "does_not_exist_xyz"}, _ctx())
        assert result.output["count"] == 0
        assert "no_match" in result.output["note"]

    def test_parse_error_reported(self, code_root: Path) -> None:
        result = find_symbol_tool.call({"name": "caller"}, _ctx())
        errors = result.output.get("parse_errors", [])
        assert any(item["file"] == "pkg/broken.py" for item in errors)

    def test_signature_truncated(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        root = tmp_path / "sig"
        root.mkdir()
        params = ", ".join(f"arg_{i}=0" for i in range(120))
        (root / "m.py").write_text(f"def huge({params}):\n    pass\n", encoding="utf-8")
        monkeypatch.setenv("CLOUDAGENT_CODE_ROOT", str(root))
        result = find_symbol_tool.call({"name": "huge"}, _ctx())
        signature = result.output["symbols"][0]["signature"]
        assert len(signature) <= MAX_SIGNATURE_CHARS + 1

    def test_path_escape_rejected(self, code_root: Path) -> None:
        result = find_symbol_tool.call({"name": "x", "path": "../../etc"}, _ctx())
        assert result.is_error is True
        assert "path_outside_root" in result.output["message"]

    def test_big_file_skipped(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        root = tmp_path / "big"
        root.mkdir()
        (root / "ok.py").write_text("def fine():\n    pass\n", encoding="utf-8")
        (root / "huge.py").write_text("# " + "x" * (600 * 1024) + "\n", encoding="utf-8")
        monkeypatch.setenv("CLOUDAGENT_CODE_ROOT", str(root))
        result = find_symbol_tool.call({"name": "fine"}, _ctx())
        assert result.output["count"] == 1
        assert "huge.py" in result.output.get("skipped_files", [])

    def test_empty_root_gives_config_hint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "empty"
        root.mkdir()
        monkeypatch.setenv("CLOUDAGENT_CODE_ROOT", str(root))
        result = find_symbol_tool.call({"name": "x"}, _ctx())
        assert "CLOUDAGENT_CODE_ROOT" in result.output["note"]


class TestFindReferences:
    def test_literal_refs_found_and_definition_excluded(self, code_root: Path) -> None:
        result = find_references_tool.call({"name": "run"}, _ctx())
        assert result.is_error is False
        codes = [item["code"] for item in result.output["references"]]
        assert any("run(1, 2)" in code for code in codes)
        assert any("s.run()" in code for code in codes)
        # 定义行不应作为引用出现
        assert all(not code.startswith("def run(") for code in codes)

    def test_boundary_note_present(self, code_root: Path) -> None:
        result = find_references_tool.call({"name": "run"}, _ctx())
        note = result.output["note"]
        assert "same_name_no_scope" in note
        assert "getattr" in note

    def test_getattr_string_ref_not_covered(self, code_root: Path) -> None:
        result = find_references_tool.call({"name": "run"}, _ctx())
        # getattr(s, "run") 是字符串引用；该行不应出现在结果中（能力边界）
        assert all("getattr" not in item["code"] for item in result.output["references"])

    def test_no_match(self, code_root: Path) -> None:
        result = find_references_tool.call({"name": "zzz_missing"}, _ctx())
        assert result.output["count"] == 0
        assert "no_match" in result.output["note"]

    def test_absolute_path_rejected(self, code_root: Path) -> None:
        result = find_references_tool.call({"name": "run", "path": ABSOLUTE_PATH}, _ctx())
        assert result.is_error is True
        # P2-2：绝对路径显式拒绝（即使位于 root 内也拒绝，语义与 schema 一致）
        assert "path_must_be_relative" in result.output["message"]


class TestAdversarial:
    """P1-1：补齐 4.1 声称的对抗覆盖（绝对路径 / 符号链接 / 非 UTF-8）。"""

    def test_absolute_path_rejected(self, code_root: Path) -> None:
        result = find_symbol_tool.call({"name": "x", "path": str(code_root / "pkg")}, _ctx())
        assert result.is_error is True
        assert "path_must_be_relative" in result.output["message"]

    def test_symlink_escape_rejected_or_skipped(
        self, code_root: Path, tmp_path: Path
    ) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.py").write_text("def secret():\n    pass\n", encoding="utf-8")
        link = code_root / "escape-link"
        try:
            os.symlink(outside, link, target_is_directory=True)
        except OSError as exc:  # WinError 1314：无符号链接特权
            pytest.skip(f"Windows symlink privilege unavailable: {exc}")
        try:
            result = find_references_tool.call({"name": "secret", "path": "escape-link"}, _ctx())
            # 链接 resolve 后位于 root 外 → 拒绝（不读取外部文件）
            assert result.is_error is True
            assert "path_outside_root" in result.output["message"]
        finally:
            try:
                os.remove(link)
            except OSError:
                pass

    def test_non_utf8_file_reports_decode_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "bin"
        root.mkdir()
        (root / "good.py").write_text("def fine():\n    pass\n", encoding="utf-8")
        (root / "latin1.py").write_bytes(b"def caf\xe9():\n    pass\n")
        monkeypatch.setenv("CLOUDAGENT_CODE_ROOT", str(root))
        result = find_symbol_tool.call({"name": "fine"}, _ctx())
        errors = result.output.get("parse_errors", [])
        assert any(
            item["file"] == "latin1.py" and item["error"] == "decode_error" for item in errors
        )


class TestRegistration:
    def test_register_code_tools(self) -> None:
        class _Registry:
            def __init__(self) -> None:
                self.tools: dict[str, object] = {}

            def register(self, tool: object) -> None:
                self.tools[getattr(tool, "name")] = tool

            def get(self, name: str) -> object | None:
                return self.tools.get(name)

        registry = _Registry()
        register_code_tools(registry)
        assert registry.get("find_symbol") is not None
        assert registry.get("find_references") is not None


class TestNoCodeExecution:
    """tasks 4.2：断言工具模块自身不执行目标代码（ast 解析模块源码）。"""

    _ALLOWED_MODULES = {
        "__future__",
        "ast",
        "fnmatch",
        "json",
        "os",
        "pathlib",
        "typing",
        "cloudagent_ext",
    }

    @staticmethod
    def _module_tree():
        import ast as _ast
        import inspect

        from cloudagent_ext.diagnosis.code import tools as code_tools

        return _ast.parse(inspect.getsource(code_tools))

    def test_imports_are_allowlisted(self) -> None:
        import ast as _ast

        imports: set[str] = set()
        for node in _ast.walk(self._module_tree()):
            if isinstance(node, _ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, _ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
        assert imports <= self._ALLOWED_MODULES, f"unexpected imports: {imports - self._ALLOWED_MODULES}"

    def test_no_exec_eval_compile(self) -> None:
        import ast as _ast

        for node in _ast.walk(self._module_tree()):
            if isinstance(node, _ast.Call):
                func = node.func
                name = getattr(func, "id", None) or getattr(func, "attr", None)
                assert name not in {"exec", "eval", "compile"}, f"forbidden call: {name}"
