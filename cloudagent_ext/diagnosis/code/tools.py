#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""只读代码工具（``find_symbol`` / ``find_references``）——变更 add-code-analysis-domain。

* **find_symbol**：在 ``repo_root`` 内按名称查找 Python 符号
  （function / method / class / constant），返回 ``path:line`` + 签名摘要；
* **find_references**：查找符号的字面引用（``ast.Name`` / ``ast.Attribute``），
  排除定义点本身；**能力边界**（P3.2 审查 P1-2）：
  - 同名不区分作用域（``note=same_name_no_scope``，引用集可能高估）；
  - ``getattr(obj, "name")`` 字符串引用与装饰器别名**不覆盖**；
  - 空结果区分 ``no_match`` 与 ``scan_truncated``；
* **安全**（P3.2 D2/D3/D4，不照搬 SQL 三重防线）：
  - 路径白名单：``repo_root``（默认 cwd，``CLOUDAGENT_CODE_ROOT`` 可覆盖），
    ``resolve()`` 后必须 ``is_relative_to(root)``，拒绝逃逸；
  - **不执行代码**：仅 ``ast.parse`` + 只读 ``open``；
  - 限额：单文件 512KB / 单次扫描 5000 文件 / 输出 200 行、256KB；
    ``find_references`` 单符号命中 500 处。
"""

from __future__ import annotations

import ast
import fnmatch
import json
import os
from pathlib import Path
from typing import Any, Iterable

from cloudagent_ext.tool_system.build_tool import Tool, build_tool
from cloudagent_ext.tool_system.context import ToolContext
from cloudagent_ext.tool_system.protocol import ToolResult

__all__ = [
    "MAX_SCAN_FILES",
    "MAX_FILE_BYTES",
    "MAX_RESULT_ROWS",
    "MAX_RESULT_BYTES",
    "MAX_SIGNATURE_CHARS",
    "MAX_REFERENCES_PER_SYMBOL",
    "find_symbol_tool",
    "find_references_tool",
    "register_code_tools",
    "resolve_code_root",
]

# 限额（P3.2 D4：5000 覆盖本仓库实测 2109 个 .py；超出返回 truncated）
MAX_SCAN_FILES: int = 5000
MAX_FILE_BYTES: int = 512 * 1024
MAX_RESULT_ROWS: int = 200
MAX_RESULT_BYTES: int = 256 * 1024
MAX_SIGNATURE_CHARS: int = 200
MAX_REFERENCES_PER_SYMBOL: int = 500

_SKIP_DIRS = frozenset(
    {
        ".git",
        "__pycache__",
        ".venv",
        "node_modules",
        "build",
        "dist",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".import_linter_cache",
    }
)


def resolve_code_root() -> Path:
    """代码根：``CLOUDAGENT_CODE_ROOT`` 优先，否则当前工作目录（P3.2 D2）。"""

    raw = os.environ.get("CLOUDAGENT_CODE_ROOT", "").strip()
    root = Path(raw) if raw else Path.cwd()
    return root.resolve()


def _cap_rows(items: list[Any], limit: int = MAX_RESULT_ROWS) -> tuple[list[Any], bool]:
    if len(items) > limit:
        return items[:limit], True
    return items, False


def _cap_bytes(payload: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    if len(encoded) <= MAX_RESULT_BYTES:
        return payload
    return {
        "truncated": True,
        "note": f"result exceeded {MAX_RESULT_BYTES} bytes and was cut",
        "preview": encoded[:4096].decode("utf-8", errors="ignore"),
    }


def _error_result(name: str, exc: Exception) -> ToolResult:
    return ToolResult(
        name=name,
        output={"error_type": type(exc).__name__, "message": str(exc)},
        is_error=True,
    )


def _readonly_tool_permissions(tool_input: dict[str, Any], _context: Any) -> Any:
    """只读代码工具的权限决策：显式允许（对齐 db/tools.py 的只读语义）。"""

    from cloudagent_ext.permissions.types import (
        OtherDecisionReason,
        PermissionAllowDecision,
    )

    return PermissionAllowDecision(
        behavior="allow",
        updated_input=tool_input,
        decision_reason=OtherDecisionReason(
            reason="read-only code tool (path whitelist / no code execution / limits)"
        ),
    )


def _validate_relative_path(raw: Any, root: Path) -> Path:
    """把 ``path`` 参数解析为 root 内的目录；拒绝逃逸与绝对路径（P2-2）。"""

    text = str(raw or "").strip()
    if text and Path(text).is_absolute():
        raise ValueError(f"path must be relative to repo_root: {text!r} (path_must_be_relative)")
    candidate = (root / text) if text else root
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"path outside repo_root: {text!r} (path_outside_root)")
    if not resolved.exists():
        raise ValueError(f"path not found: {text!r}")
    if not resolved.is_dir():
        raise ValueError(f"path is not a directory: {text!r}")
    return resolved


def _matches_include(rel: str, basename: str, pattern: str) -> bool:
    if pattern in ("**/*.py", "*.py", ""):
        return True
    return fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(basename, pattern)


def _iter_py_files(
    root: Path, base: Path, include: str
) -> tuple[list[Path], list[str], bool]:
    """惰性遍历（``os.walk`` 边遍历边收集，达上限即停）。

    Returns:
        ``(files, skipped, truncated)``——skipped 记录超大/不可读文件（相对路径）。
    """

    files: list[Path] = []
    skipped: list[str] = []
    truncated = False
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for name in sorted(filenames):
            if not name.endswith(".py"):
                continue
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            if not _matches_include(rel, name, include):
                continue
            try:
                size = path.stat().st_size
            except OSError:
                skipped.append(rel)
                continue
            if size > MAX_FILE_BYTES:
                skipped.append(rel)
                continue
            files.append(path)
            if len(files) >= MAX_SCAN_FILES:
                truncated = True
                return files, skipped, truncated
    return files, skipped, truncated


def _read_and_parse(path: Path) -> tuple[str | None, ast.AST | None, str | None]:
    """只读读取 + 解析；返回 ``(source, tree, error_type)``。

    **不执行目标代码**——仅 ``read_text`` 与 ``ast.parse``。
    """

    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None, None, "decode_error"
    except OSError:
        return None, None, "read_error"
    try:
        return source, ast.parse(source, filename=str(path)), None
    except SyntaxError:
        return None, None, "parse_error"


def _signature(node: ast.AST) -> str:
    """签名摘要（超 200 字符截断，P3-1）；不执行代码。"""

    try:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            parts: list[str] = [a.arg for a in args.posonlyargs + args.args]
            if args.vararg:
                parts.append("*" + args.vararg.arg)
            parts.extend(a.arg for a in args.kwonlyargs)
            if args.kwarg:
                parts.append("**" + args.kwarg.arg)
            returns = ast.unparse(node.returns) if node.returns else ""
            sig = f"{node.name}({', '.join(parts)})" + (f" -> {returns}" if returns else "")
        elif isinstance(node, ast.ClassDef):
            sig = f"class {node.name}"
        elif isinstance(node, ast.Assign):
            sig = ast.unparse(node)
        else:  # pragma: no cover - 兜底
            sig = getattr(node, "name", "<unknown>")
    except Exception:  # noqa: BLE001 - 签名拼装失败不影响主结果
        sig = getattr(node, "name", "<unknown>")
    if len(sig) > MAX_SIGNATURE_CHARS:
        sig = sig[:MAX_SIGNATURE_CHARS] + "…"
    return sig


def _collect_symbols(tree: ast.AST) -> Iterable[tuple[str, str, ast.AST]]:
    """收集符号定义：function / method / class / constant。

    同名不做作用域区分（P3.2 D1）——调用方须在 note 中声明该局限。
    """

    symbols: dict[int, tuple[str, str, ast.AST]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.setdefault(id(node), (node.name, "function", node))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    symbols.setdefault(id(target), (target.id, "constant", node))
        elif isinstance(node, ast.ClassDef):
            symbols.setdefault(id(node), (node.name, "class", node))
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols[id(child)] = (child.name, "method", child)
    return symbols.values()


def _find_symbol_call(tool_input: dict[str, Any], _context: ToolContext) -> ToolResult:
    name = "find_symbol"
    try:
        root = resolve_code_root()
        query = str(tool_input.get("name") or "").strip()
        if not query:
            raise ValueError("name is required")
        base = _validate_relative_path(tool_input.get("path"), root)
        include = str(tool_input.get("include") or "**/*.py")
        kind_filter = str(tool_input.get("kind") or "").strip() or None

        files, skipped, scan_truncated = _iter_py_files(root, base, include)
        symbols: list[dict[str, Any]] = []
        parse_errors: list[dict[str, str]] = []
        for path in files:
            _source, tree, error = _read_and_parse(path)
            rel = path.relative_to(root).as_posix()
            if error or tree is None:
                parse_errors.append({"file": rel, "error": error or "parse_error"})
                continue
            for sym_name, kind, node in _collect_symbols(tree):
                if sym_name != query:
                    continue
                if kind_filter and kind != kind_filter:
                    continue
                symbols.append(
                    {
                        "path": rel,
                        "line": getattr(node, "lineno", 0),
                        "kind": kind,
                        "signature": _signature(node),
                    }
                )
        capped, capped_truncated = _cap_rows(symbols)

        notes: list[str] = [
            "name-only matching (no scope disambiguation)",
            "tuple-unpacking assignments (A, B = ...) are not recognized as symbols",
        ]
        if not files:
            notes.append(
                "no Python files found under repo_root "
                "(set CLOUDAGENT_CODE_ROOT if the code root is elsewhere)"
            )
        elif not symbols:
            notes.append("no_match" if not scan_truncated else "scan_truncated")
        payload: dict[str, Any] = {
            "query": query,
            "count": len(symbols),
            "symbols": capped,
            "scanned_files": len(files),
            "note": "; ".join(notes),
        }
        if skipped:
            payload["skipped_files"] = skipped[:50]
        if parse_errors:
            payload["parse_errors"] = parse_errors[:20]
        if scan_truncated or capped_truncated:
            payload["truncated"] = True
            payload["note"] += (
                f"; scan capped at {MAX_SCAN_FILES} files / {MAX_RESULT_ROWS} rows "
                "(use path/include to narrow)"
            )
        return ToolResult(name=name, output=_cap_bytes(payload))
    except Exception as exc:  # noqa: BLE001 - 结构化错误返回
        return _error_result(name, exc)


def _find_references_call(tool_input: dict[str, Any], _context: ToolContext) -> ToolResult:
    name = "find_references"
    try:
        root = resolve_code_root()
        query = str(tool_input.get("name") or "").strip()
        if not query:
            raise ValueError("name is required")
        base = _validate_relative_path(tool_input.get("path"), root)
        include = str(tool_input.get("include") or "**/*.py")

        files, skipped, scan_truncated = _iter_py_files(root, base, include)

        # 第一遍：解析并记录定义点（同文件同行即视为定义，引用扫描时排除）
        parsed: list[tuple[str, str, ast.AST]] = []
        definitions: set[tuple[str, int]] = set()
        parse_errors: list[dict[str, str]] = []
        for path in files:
            source, tree, error = _read_and_parse(path)
            rel = path.relative_to(root).as_posix()
            if error or tree is None or source is None:
                parse_errors.append({"file": rel, "error": error or "parse_error"})
                continue
            parsed.append((rel, source, tree))
            for sym_name, _kind, node in _collect_symbols(tree):
                if sym_name == query:
                    definitions.add((rel, getattr(node, "lineno", 0)))

        # 第二遍：扫描字面引用（Name.id / Attribute.attr），排除定义点
        references: list[dict[str, Any]] = []
        hit_cap = False
        for rel, source, tree in parsed:
            lines = source.splitlines()
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    hit = node.id == query
                elif isinstance(node, ast.Attribute):
                    hit = node.attr == query
                else:
                    continue
                if not hit:
                    continue
                lineno = getattr(node, "lineno", 0)
                if (rel, lineno) in definitions:
                    continue
                code = ""
                if 0 < lineno <= len(lines):
                    code = lines[lineno - 1].strip()[:200]
                references.append({"path": rel, "line": lineno, "code": code})
                if len(references) >= MAX_REFERENCES_PER_SYMBOL:
                    hit_cap = True
                    break
            if hit_cap:
                break

        notes: list[str] = [
            "same_name_no_scope: same-name symbols in different scopes are NOT distinguished",
            "getattr string refs and decorator aliases are NOT covered",
        ]
        if not files:
            notes.append(
                "no Python files found under repo_root "
                "(set CLOUDAGENT_CODE_ROOT if the code root is elsewhere)"
            )
        elif not references:
            notes.append("no_match" if not scan_truncated else "scan_truncated")
        capped, capped_truncated = _cap_rows(references)
        payload: dict[str, Any] = {
            "query": query,
            "count": len(references),
            "references": capped,
            "scanned_files": len(files),
            "note": "; ".join(notes),
        }
        if skipped:
            payload["skipped_files"] = skipped[:50]
        if parse_errors:
            payload["parse_errors"] = parse_errors[:20]
        if scan_truncated or capped_truncated or hit_cap:
            payload["truncated"] = True
            payload["note"] += (
                f"; capped at {MAX_REFERENCES_PER_SYMBOL} references / {MAX_SCAN_FILES} files"
            )
        return ToolResult(name=name, output=_cap_bytes(payload))
    except Exception as exc:  # noqa: BLE001 - 结构化错误返回
        return _error_result(name, exc)


find_symbol_tool: Tool = build_tool(
    name="find_symbol",
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Symbol name to find (exact match)"},
            "path": {
                "type": "string",
                "description": "Relative subdirectory under repo root (default: root)",
            },
            "include": {
                "type": "string",
                "description": (
                    "Glob for file selection (fnmatch semantics; '**' does not recurse; "
                    "default: **/*.py)"
                ),
            },
            "kind": {
                "type": "string",
                "enum": ["function", "method", "class", "constant"],
                "description": "Optional symbol kind filter",
            },
        },
        "required": ["name"],
        "additionalProperties": False,
    },
    call=_find_symbol_call,
    prompt=(
        "Find Python symbol definitions by name under the read-only repo root "
        "(path:line + signature). Name-only matching; target code is never executed."
    ),
    description=(
        "Find Python symbol definitions (function/method/class/constant) by exact name; "
        "returns path:line and a truncated signature."
    ),
    is_read_only=lambda _input: True,
    is_concurrency_safe=lambda _input: True,
    check_permissions=_readonly_tool_permissions,
)

find_references_tool: Tool = build_tool(
    name="find_references",
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Symbol name whose references to find"},
            "path": {
                "type": "string",
                "description": "Relative subdirectory under repo root (default: root)",
            },
            "include": {
                "type": "string",
                "description": (
                    "Glob for file selection (fnmatch semantics; '**' does not recurse; "
                    "default: **/*.py)"
                ),
            },
        },
        "required": ["name"],
        "additionalProperties": False,
    },
    call=_find_references_call,
    prompt=(
        "Find literal references (Name/Attribute) to a symbol under the read-only repo "
        "root. Same-name symbols are not scope-disambiguated; getattr string refs and "
        "decorator aliases are not covered. Target code is never executed."
    ),
    description=(
        "Find literal references to a symbol; excludes the definition site. Boundaries: "
        "name-only (no scope), no getattr-string/decorator coverage."
    ),
    is_read_only=lambda _input: True,
    is_concurrency_safe=lambda _input: True,
    check_permissions=_readonly_tool_permissions,
)


def register_code_tools(registry: Any) -> None:
    """按需装配：把只读代码工具注册进给定注册表（默认注册表不含）。"""

    for tool in (find_symbol_tool, find_references_tool):
        registry.register(tool)
