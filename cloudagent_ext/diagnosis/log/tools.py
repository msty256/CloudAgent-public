#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""只读日志工具（``search_logs`` / ``get_log_context`` / ``parse_stack_trace`` /
``correlate_events``）——变更 add-log-analysis-domain（P3.3）。

**通用设计（不假设任何日志目录结构/服务命名）**：

* 只认一个**日志根目录**（``CLOUDAGENT_LOG_ROOT``，必须显式设置）与其下的**文件**；
* 所有引用都是 ``file:line``（相对日志根）——**不引入"服务"概念**（微服务/Pod/
  多日志文件/多级目录均可，只要在日志根下且文件名含 ``.log``）；
* ``search_logs`` 的过滤维度：``file``（相对路径子串）/ ``keyword`` / ``level`` /
  时间窗；返回 ``available_files`` 让模型知道"可搜范围"；
* **时间窗**：``datetime`` 比较（禁止字符串比较）；naive 本地时间；非法格式 →
  ``invalid_time_format``；
* **续行语义**：无时间戳前缀的行继承上一条记录行的 time/level 并标
  ``continuation=true``；``search_logs`` 计入续行，``get_log_context`` 包含续行；
* **栈解析**：给任意行 → 向上回溯最近的异常行 → 向下收栈，返回
  ``resolved_from_line``；
* **脱敏**：复用 ``evaluation/report.py`` 的 ``redact_sensitive``（手机号/邮箱/
  凭证）；traceId 保留并在 note 声明；
* **限额**：单次搜索 ≤ 200 行、单行 ≤ 500 字符、单文件 ≤ 5MB、≤ 200 文件；
  ``*.log*`` 匹配（轮转），``.gz`` 不解析。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from cloudagent_ext.diagnosis.evaluation.report import redact_sensitive
from cloudagent_ext.tool_system.build_tool import Tool, build_tool
from cloudagent_ext.tool_system.context import ToolContext
from cloudagent_ext.tool_system.protocol import ToolResult

__all__ = [
    "MAX_SCAN_FILES",
    "MAX_RESULT_ROWS",
    "MAX_LINE_CHARS",
    "MAX_FILE_BYTES",
    "search_logs_tool",
    "get_log_context_tool",
    "parse_stack_trace_tool",
    "correlate_events_tool",
    "register_log_tools",
    "resolve_log_root",
]

MAX_SCAN_FILES: int = 200
MAX_RESULT_ROWS: int = 200
MAX_LINE_CHARS: int = 500
MAX_FILE_BYTES: int = 5 * 1024 * 1024

_TIME_FORMAT = "%Y-%m-%d %H:%M:%S.%f"
_LEVELS = ("TRACE", "DEBUG", "INFO", "WARN", "ERROR", "FATAL")

_RECORD_RE = re.compile(
    r"^(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}) "
    r"(?P<level>" + "|".join(_LEVELS) + r") "
    r"\[(?P<thread>[^\]]+)\] (?P<logger>\S+) - (?P<message>.*?)"
    # traceId 形态不限纯 hex（trace-abc-123 / AWS X-Ray / W3C header 均可）
    r"(?: \[(?P<trace>[^\]\s]{8,64})\])?$"
)
_EXCEPTION_RE = re.compile(
    r"(?P<type>(?:[a-zA-Z_][\w$]*\.)+[A-Z]\w*(?:Exception|Error|Throwable))"
    r"(?:: (?P<msg>.*))?$"
)
_CAUSED_RE = re.compile(r"^Caused by: (?P<type>(?:[a-zA-Z_][\w$]*\.)+[A-Z]\w*(?:Exception|Error|Throwable))(?:: (?P<msg>.*))?$")
_FRAME_RE = re.compile(r"^\s*at (?P<frame>[\w$.<>]+)\((?P<loc>[^)]*)\)$")


@dataclass(slots=True)
class _Line:
    file: str
    line: int
    time: datetime | None
    level: str | None
    message: str
    trace_id: str | None
    continuation: bool
    raw: str


def resolve_log_root() -> Path:
    """日志根：**必须**由 ``CLOUDAGENT_LOG_ROOT`` 提供（未设置 → 结构化指引）。"""

    raw = os.environ.get("CLOUDAGENT_LOG_ROOT", "").strip()
    if not raw:
        raise ValueError(
            "CLOUDAGENT_LOG_ROOT is not set (log_root_not_configured). Configure it to "
            "the directory containing application logs, e.g. "
            "set CLOUDAGENT_LOG_ROOT=C:\\logs\\app (or add it to the env block of "
            "~/.cloudagent/config.json) — logs are never scanned from cwd by default. "
            "No real logs at hand? Generate the deterministic simulation logs with "
            "`from cloudagent_ext.diagnosis.log.fixtures.sim_logs import write_sim_logs; "
            "write_sim_logs(Path(r'<target-dir>'))` and point CLOUDAGENT_LOG_ROOT there."
        )
    root = Path(raw).resolve()
    if not root.is_dir():
        raise ValueError(f"CLOUDAGENT_LOG_ROOT is not a directory: {raw!r} (log_root_invalid)")
    return root


def _validate_file(raw: Any, root: Path) -> Path:
    text = str(raw or "").strip()
    if not text:
        raise ValueError("file is required (relative to log_root)")
    if Path(text).is_absolute():
        raise ValueError(f"file must be relative to log_root: {text!r} (path_must_be_relative)")
    path = (root / text).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"file outside log_root: {text!r} (path_outside_root)")
    if not path.is_file():
        raise ValueError(f"file not found: {text!r}")
    if not _is_log_file(path):
        raise ValueError(f"not a supported log file: {text!r} (unsupported_file)")
    return path


def _is_log_file(path: Path) -> bool:
    """``*.log*`` 匹配（轮转命名）；``.gz`` 不解析。"""

    name = path.name.lower()
    if name.endswith(".gz"):
        return False
    return ".log" in name


def _iter_log_files(root: Path) -> tuple[list[Path], list[str], bool]:
    """递归扫描日志根；**不假设目录结构**（多级目录/多日志文件均可）。

    Returns:
        ``(files, skipped, truncated)``——达到 ``MAX_SCAN_FILES`` 时 truncated=True。
    """

    files: list[Path] = []
    skipped: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            if name.lower().endswith(".gz"):
                skipped.append(rel + " (compressed logs are not parsed)")
                continue
            if not _is_log_file(path):
                continue
            try:
                size = path.stat().st_size
            except OSError:
                skipped.append(rel)
                continue
            if size > MAX_FILE_BYTES:
                skipped.append(rel + " (exceeds 5MB)")
                continue
            files.append(path)
            if len(files) >= MAX_SCAN_FILES:
                return files, skipped, True
    return files, skipped, False


def _parse_time(raw: Any, field: str) -> datetime | None:
    if raw is None or str(raw).strip() == "":
        return None
    text = str(raw).strip()
    for fmt in (_TIME_FORMAT, "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(f"invalid {field}: {text!r} (invalid_time_format; expected YYYY-MM-DD HH:MM:SS.mmm)")


def _parse_lines(text: str, rel: str) -> list[_Line]:
    lines: list[_Line] = []
    last: _Line | None = None
    for idx, raw in enumerate(text.splitlines(), 1):
        match = _RECORD_RE.match(raw)
        if match:
            try:
                ts = datetime.strptime(match.group("time"), _TIME_FORMAT)
            except ValueError:
                ts = None
            item = _Line(
                file=rel,
                line=idx,
                time=ts,
                level=match.group("level"),
                message=match.group("message"),
                trace_id=match.group("trace"),
                continuation=False,
                raw=raw,
            )
            last = item
        else:
            item = _Line(
                file=rel,
                line=idx,
                time=last.time if last else None,
                level=last.level if last else None,
                message=raw,
                trace_id=last.trace_id if last else None,
                continuation=True,
                raw=raw,
            )
        lines.append(item)
    return lines


def _clip(text: str) -> str:
    return redact_sensitive(text)[:MAX_LINE_CHARS]


def _cap(payload: dict[str, Any]) -> dict[str, Any]:
    import json

    encoded = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    if len(encoded) <= 256 * 1024:
        return payload
    return {"truncated": True, "note": "result exceeded 256KB and was cut", "preview": encoded[:4096].decode("utf-8", "ignore")}


def _error(name: str, exc: Exception) -> ToolResult:
    return ToolResult(name=name, output={"error_type": type(exc).__name__, "message": str(exc)}, is_error=True)


def _readonly_permissions(tool_input: dict[str, Any], _context: Any) -> Any:
    from cloudagent_ext.permissions.types import OtherDecisionReason, PermissionAllowDecision

    return PermissionAllowDecision(
        behavior="allow",
        updated_input=tool_input,
        decision_reason=OtherDecisionReason(reason="read-only log tool (log root whitelist / PII redaction / limits)"),
    )


# ---------------------------------------------------------------------------
# search_logs
# ---------------------------------------------------------------------------


def _search_logs_call(tool_input: dict[str, Any], _context: ToolContext) -> ToolResult:
    name = "search_logs"
    try:
        root = resolve_log_root()
        t_from = _parse_time(tool_input.get("time_from"), "time_from")
        t_to = _parse_time(tool_input.get("time_to"), "time_to")
        file_filter = str(tool_input.get("file") or "").strip()
        level_filter = str(tool_input.get("level") or "").strip().upper() or None
        keyword = str(tool_input.get("keyword") or "").strip()
        limit = int(tool_input.get("limit") or MAX_RESULT_ROWS)
        limit = max(1, min(limit, MAX_RESULT_ROWS))

        files, skipped, files_truncated = _iter_log_files(root)
        available_files = [p.relative_to(root).as_posix() for p in files]
        matches: list[dict[str, Any]] = []
        truncated = False
        for path in files:
            rel = path.relative_to(root).as_posix()
            # 文件过滤：相对路径子串匹配（不假设目录结构/服务名）
            if file_filter and file_filter not in rel:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                skipped.append(rel)
                continue
            for item in _parse_lines(text, rel):
                if level_filter and (item.level or "") != level_filter:
                    continue
                if keyword and keyword not in item.message:
                    continue
                if t_from is not None or t_to is not None:
                    if item.time is None:
                        continue
                    if t_from is not None and item.time < t_from:
                        continue
                    if t_to is not None and item.time > t_to:
                        continue
                matches.append(
                    {
                        "file": item.file,
                        "line": item.line,
                        "time": item.time.strftime(_TIME_FORMAT)[:-3] if item.time else None,
                        "level": item.level,
                        "continuation": item.continuation,
                        "message": _clip(item.message),
                    }
                )
                if len(matches) >= limit:
                    truncated = True
                    break
            if truncated:
                break

        notes = [
            "time window uses datetime comparison; naive local time (no clock alignment)",
            "lines without a resolved timestamp (e.g. a file starting with a continuation line) are skipped when a time window is set",
        ]
        if not files:
            notes.append(
                "scope_empty: no log files found under log_root — check CLOUDAGENT_LOG_ROOT; "
                "do not fabricate conclusions"
            )
        elif not matches:
            notes.append("no_match_in_scope: files were scanned but nothing matched the filters")
        payload: dict[str, Any] = {
            "log_root": str(root),
            "available_files": available_files,
            "matches": matches,
            "count": len(matches),
            "scanned_files": len(files),
            "files_truncated": files_truncated,
            "truncated": truncated,
            "note": "; ".join(notes),
        }
        if skipped:
            payload["skipped_files"] = skipped
        return ToolResult(name=name, output=_cap(payload))
    except Exception as exc:  # noqa: BLE001
        return _error(name, exc)


# ---------------------------------------------------------------------------
# get_log_context
# ---------------------------------------------------------------------------


def _get_log_context_call(tool_input: dict[str, Any], _context: ToolContext) -> ToolResult:
    name = "get_log_context"
    try:
        root = resolve_log_root()
        path = _validate_file(tool_input.get("file"), root)
        rel = path.relative_to(root).as_posix()
        line = int(tool_input.get("line") or 0)
        if line <= 0:
            raise ValueError("line must be a positive integer")
        context = int(tool_input.get("context") or 3)
        context = max(0, min(context, 20))
        text = path.read_text(encoding="utf-8", errors="replace")
        all_lines = _parse_lines(text, rel)
        start = max(1, line - context)
        end = min(len(all_lines), line + context)
        rows = [
            {
                "line": item.line,
                "time": item.time.strftime(_TIME_FORMAT)[:-3] if item.time else None,
                "level": item.level,
                "continuation": item.continuation,
                "text": _clip(item.raw),
            }
            for item in all_lines[start - 1 : end]
        ]
        return ToolResult(
            name=name,
            output={"file": rel, "requested_line": line, "lines": rows, "note": "includes continuation lines (stack frames)"},
        )
    except Exception as exc:  # noqa: BLE001
        return _error(name, exc)


# ---------------------------------------------------------------------------
# parse_stack_trace
# ---------------------------------------------------------------------------


def _parse_stack_trace_call(tool_input: dict[str, Any], _context: ToolContext) -> ToolResult:
    name = "parse_stack_trace"
    try:
        root = resolve_log_root()
        path = _validate_file(tool_input.get("file"), root)
        rel = path.relative_to(root).as_posix()
        line = int(tool_input.get("line") or 0)
        if line <= 0:
            raise ValueError("line must be a positive integer")
        raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        idx = min(line, len(raw_lines)) - 1

        # 任意行 → 向上回溯最近的异常行（异常类型行或 Caused by）
        start = None
        for i in range(idx, -1, -1):
            stripped = raw_lines[i].strip()
            if _EXCEPTION_RE.search(stripped) or _CAUSED_RE.match(stripped):
                start = i
                break
        resolved_from_line = (start + 1) if start is not None else line

        exception: str | None = None
        message: str | None = None
        frames: list[dict[str, Any]] = []
        caused_by: list[dict[str, Any]] = []
        begin = start if start is not None else idx
        for i in range(begin, min(len(raw_lines), begin + 80)):
            stripped = raw_lines[i].strip()
            caused = _CAUSED_RE.match(stripped)
            if caused:
                caused_by.append(
                    {
                        "type": caused.group("type"),
                        "message": redact_sensitive(caused.group("msg") or "")[:MAX_LINE_CHARS],
                        "line": i + 1,
                    }
                )
                continue
            frame = _FRAME_RE.match(stripped)
            if frame:
                frames.append({"frame": frame.group("frame"), "location": frame.group("loc"), "line": i + 1})
                continue
            if exception is None:
                matched = _EXCEPTION_RE.search(stripped)
                if matched:
                    exception = matched.group("type")
                    message = redact_sensitive(matched.group("msg") or "")[:MAX_LINE_CHARS]
        notes = ["resolves upward to the nearest exception line; naive local time"]
        if exception is None and not caused_by:
            notes.append("no_stack_found")
        return ToolResult(
            name=name,
            output={
                "file": rel,
                "requested_line": line,
                "resolved_from_line": resolved_from_line,
                "exception": exception,
                "message": message,
                "frames": frames,
                "caused_by": caused_by,
                "note": "; ".join(notes),
            },
        )
    except Exception as exc:  # noqa: BLE001
        return _error(name, exc)


# ---------------------------------------------------------------------------
# correlate_events
# ---------------------------------------------------------------------------


def _correlate_events_call(tool_input: dict[str, Any], _context: ToolContext) -> ToolResult:
    name = "correlate_events"
    try:
        root = resolve_log_root()
        trace_id = str(tool_input.get("trace_id") or "").strip()
        if not trace_id:
            raise ValueError("trace_id is required")
        limit = int(tool_input.get("limit") or MAX_RESULT_ROWS)
        limit = max(1, min(limit, MAX_RESULT_ROWS))

        files, skipped, files_truncated = _iter_log_files(root)
        events: list[dict[str, Any]] = []
        for path in files:
            rel = path.relative_to(root).as_posix()
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                skipped.append(rel)
                continue
            for item in _parse_lines(text, rel):
                # 事件链只取记录行（续行是栈帧细节，不单独作为事件）
                if item.continuation or item.trace_id != trace_id:
                    continue
                events.append(
                    {
                        "time": item.time.strftime(_TIME_FORMAT)[:-3] if item.time else None,
                        "file": item.file,
                        "line": item.line,
                        "level": item.level,
                        "message": _clip(item.message),
                    }
                )
        events.sort(key=lambda e: (e["time"] or "", e["line"]))
        events = events[:limit]
        files_with_events = sorted({e["file"] for e in events})

        notes = ["events sorted by raw timestamps; no clock alignment performed", "trace events exclude continuation lines"]
        if not events:
            notes.append("cannot_correlate: trace_id not found in any scanned file (try keyword/time-window search instead)")
        payload: dict[str, Any] = {
            "trace_id": trace_id,
            "events": events,
            "count": len(events),
            "files": files_with_events,
            "scanned_files": len(files),
            "files_truncated": files_truncated,
            "note": "; ".join(notes),
        }
        if skipped:
            payload["skipped_files"] = skipped
        return ToolResult(name=name, output=_cap(payload))
    except Exception as exc:  # noqa: BLE001
        return _error(name, exc)


# ---------------------------------------------------------------------------
# 工具定义与装配
# ---------------------------------------------------------------------------

search_logs_tool: Tool = build_tool(
    name="search_logs",
    input_schema={
        "type": "object",
        "properties": {
            "file": {"type": "string", "description": "Substring filter on the relative file path (e.g. order-service)"},
            "keyword": {"type": "string", "description": "Substring filter on the message"},
            "level": {"type": "string", "enum": list(_LEVELS)},
            "time_from": {"type": "string", "description": "Inclusive lower bound (YYYY-MM-DD HH:MM:SS.mmm)"},
            "time_to": {"type": "string", "description": "Inclusive upper bound (YYYY-MM-DD HH:MM:SS.mmm)"},
            "limit": {"type": "integer", "minimum": 1, "maximum": MAX_RESULT_ROWS},
        },
        "additionalProperties": False,
    },
    call=_search_logs_call,
    prompt=(
        "Search read-only application logs under the configured log root (any directory "
        "structure). Filters: file path substring / keyword / level / datetime-compared "
        "time window. Continuation lines inherit record fields. PII redacted; traceId kept."
    ),
    description="Search logs by file/keyword/level/time window; returns file:line and the searchable file list.",
    is_read_only=lambda _input: True,
    is_concurrency_safe=lambda _input: True,
    check_permissions=_readonly_permissions,
)

get_log_context_tool: Tool = build_tool(
    name="get_log_context",
    input_schema={
        "type": "object",
        "properties": {
            "file": {"type": "string", "description": "Log file path relative to log_root"},
            "line": {"type": "integer", "minimum": 1},
            "context": {"type": "integer", "minimum": 0, "maximum": 20, "description": "Lines before/after (default 3)"},
        },
        "required": ["file", "line"],
        "additionalProperties": False,
    },
    call=_get_log_context_call,
    prompt="Read N lines around a log line (includes continuation lines / stack frames).",
    description="Get surrounding log lines for a given file:line.",
    is_read_only=lambda _input: True,
    is_concurrency_safe=lambda _input: True,
    check_permissions=_readonly_permissions,
)

parse_stack_trace_tool: Tool = build_tool(
    name="parse_stack_trace",
    input_schema={
        "type": "object",
        "properties": {
            "file": {"type": "string", "description": "Log file path relative to log_root"},
            "line": {"type": "integer", "minimum": 1, "description": "Any line (resolves upward to the nearest exception)"},
        },
        "required": ["file", "line"],
        "additionalProperties": False,
    },
    call=_parse_stack_trace_call,
    prompt=(
        "Parse a Java stack trace from a log file. Give any line: the tool resolves "
        "upward to the nearest exception line, then collects frames and Caused-by chain."
    ),
    description="Parse Java exception + frames + Caused-by chain from any line in a log file.",
    is_read_only=lambda _input: True,
    is_concurrency_safe=lambda _input: True,
    check_permissions=_readonly_permissions,
)

correlate_events_tool: Tool = build_tool(
    name="correlate_events",
    input_schema={
        "type": "object",
        "properties": {
            "trace_id": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": MAX_RESULT_ROWS},
        },
        "required": ["trace_id"],
        "additionalProperties": False,
    },
    call=_correlate_events_call,
    prompt=(
        "Correlate log events by traceId across all scanned files (time ordered). "
        "No service-name assumptions; returns the files that contain events."
    ),
    description="Build an event chain for a traceId across files; returns events and the files involved.",
    is_read_only=lambda _input: True,
    is_concurrency_safe=lambda _input: True,
    check_permissions=_readonly_permissions,
)


def register_log_tools(registry: Any) -> None:
    """按需装配：把只读日志工具注册进给定注册表（默认注册表不含）。"""

    for tool in (search_logs_tool, get_log_context_tool, parse_stack_trace_tool, correlate_events_tool):
        registry.register(tool)
