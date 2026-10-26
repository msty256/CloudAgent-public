#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""只读日志工具离线测试（P3.3）。

覆盖：fixture 生成器自检 / search（file/keyword/level/时间窗/**跨小时**/
**续行**/轮转 `*.log*`/`.gz` 跳过/未命中）/ get_log_context（**含续行**）/
parse_stack_trace（**任意行向上回溯**/Caused by/多行栈）/ correlate_events
（完整 trace / 出现文件列表 / **traceId 缺失**）/ log_root 未配置指引 /
路径逃逸 / PII 打码（复用 redact_sensitive）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cloudagent_ext.diagnosis.evaluation.report import redact_sensitive
from cloudagent_ext.diagnosis.log.fixtures.sim_logs import (
    TRACE_FULL,
    TRACE_MISSING,
    TRACE_NONHEX,
    TRACE_PARTIAL,
    write_sim_logs,
)
from cloudagent_ext.diagnosis.log.tools import (
    correlate_events_tool,
    get_log_context_tool,
    parse_stack_trace_tool,
    register_log_tools,
    search_logs_tool,
)
from cloudagent_ext.tool_system.context import ToolContext


def _ctx() -> ToolContext:
    return ToolContext(workspace_root=Path.cwd())


@pytest.fixture()
def log_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    info = write_sim_logs(tmp_path / "logs")
    monkeypatch.setenv("CLOUDAGENT_LOG_ROOT", info["dir"])
    return tmp_path / "logs"


class TestFixture:
    def test_generated_files(self, log_root: Path) -> None:
        names = {p.name for p in log_root.iterdir()}
        assert {"svc-a.log", "svc-b.log", "svc-a.log.1", "svc-c.log.gz"} <= names


class TestSearchLogs:
    def test_search_by_keyword(self, log_root: Path) -> None:
        result = search_logs_tool.call({"keyword": "request received"}, _ctx())
        assert result.is_error is False
        assert result.output["count"] >= 1
        assert any("svc-a.log" in m["file"] for m in result.output["matches"])

    def test_search_by_file(self, log_root: Path) -> None:
        result = search_logs_tool.call({"file": "svc-b"}, _ctx())
        assert result.output["count"] >= 1
        assert all("svc-b" in m["file"] for m in result.output["matches"])

    def test_search_by_level(self, log_root: Path) -> None:
        result = search_logs_tool.call({"level": "ERROR"}, _ctx())
        assert all(m["level"] == "ERROR" for m in result.output["matches"])
        assert result.output["count"] >= 2

    def test_cross_hour_boundary(self, log_root: Path) -> None:
        """P1-1：09:59 不得因字符串比较被误判为晚于 10:00。"""

        result = search_logs_tool.call(
            {"keyword": "request received", "time_from": "2026-10-18 10:00:00.000"},
            _ctx(),
        )
        assert result.output["count"] == 0  # 09:59:58 在窗口外
        result2 = search_logs_tool.call(
            {"keyword": "request received", "time_from": "2026-10-18 09:59:00.000"},
            _ctx(),
        )
        assert result2.output["count"] >= 1

    def test_invalid_time_format(self, log_root: Path) -> None:
        result = search_logs_tool.call({"time_from": "2026/10/18 10:00"}, _ctx())
        assert result.is_error is True
        assert "invalid_time_format" in result.output["message"]

    def test_continuation_lines_included(self, log_root: Path) -> None:
        """P1-2：续行继承记录行字段并可被检索。"""

        result = search_logs_tool.call({"keyword": "NullPointerException"}, _ctx())
        assert result.output["count"] >= 1
        first = result.output["matches"][0]
        assert first["file"] == "svc-b.log"
        assert first["level"] == "ERROR"
        assert first["time"] is not None  # 继承记录行时间

        frames = search_logs_tool.call({"keyword": "Repository.resolveTenant"}, _ctx())
        assert frames.output["count"] >= 1
        assert frames.output["matches"][0]["continuation"] is True
        # 续行也继承时间/服务/级别
        assert frames.output["matches"][0]["time"] is not None
        assert frames.output["matches"][0]["file"] == "svc-b.log"

    def test_no_match(self, log_root: Path) -> None:
        result = search_logs_tool.call({"keyword": "zzz_not_exists"}, _ctx())
        assert result.output["count"] == 0
        assert "no_match_in_scope" in result.output["note"]

    def test_available_scope_visible(self, log_root: Path) -> None:
        """P1-A：可搜范围（日志根/服务/文件）对模型可见。"""

        result = search_logs_tool.call({"keyword": "zzz_none"}, _ctx())
        assert result.output["log_root"]
        assert "svc-a.log" in result.output["available_files"]
        assert "svc-b.log" in result.output["available_files"]

    def test_scope_empty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.setenv("CLOUDAGENT_LOG_ROOT", str(empty))
        result = search_logs_tool.call({"keyword": "x"}, _ctx())
        assert result.output["available_files"] == []
        assert "scope_empty" in result.output["note"]

    def test_files_truncated_flag(
        self, log_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cloudagent_ext.diagnosis.log import tools as log_tools

        monkeypatch.setattr(log_tools, "MAX_SCAN_FILES", 2)
        result = search_logs_tool.call({"keyword": "x"}, _ctx())
        assert result.output["files_truncated"] is True

    def test_rotated_file_matched_and_gz_skipped(self, log_root: Path) -> None:
        result = search_logs_tool.call({"keyword": "started"}, _ctx())
        assert any("svc-a.log.1" in m["file"] for m in result.output["matches"])
        assert any("svc-c.log.gz" in s for s in result.output.get("skipped_files", []))

    def test_pii_redacted(self, log_root: Path) -> None:
        result = search_logs_tool.call({"keyword": "audit"}, _ctx())
        text = str(result.output)
        assert "13800138000" not in text
        assert "alice@example.com" not in text
        assert "secret123" not in text
        assert "1**********" in text

    def test_shared_redaction_function(self) -> None:
        """P2-3：工具与评测报告使用同一脱敏函数。"""

        text = "phone=13800138000 email=a@b.com password=hunter2"
        assert redact_sensitive(text) == "phone=1********** email=***@*** password=***"

    def test_log_root_not_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CLOUDAGENT_LOG_ROOT", raising=False)
        result = search_logs_tool.call({"keyword": "x"}, _ctx())
        assert result.is_error is True
        assert "CLOUDAGENT_LOG_ROOT" in result.output["message"]

    def test_non_hex_trace_id_is_parsed(self, log_root: Path) -> None:
        """P1-1：非纯 hex 的 traceId（trace-abc-123）不得被静默丢弃。"""

        result = search_logs_tool.call({"keyword": "non-hex trace"}, _ctx())
        assert result.output["count"] >= 1
        correlated = correlate_events_tool.call({"trace_id": TRACE_NONHEX}, _ctx())
        assert correlated.output["count"] >= 1

    def test_file_name_with_dots_is_just_a_path(self, log_root: Path) -> None:
        """通用化后：文件名含点（order.service.log）只是路径的一部分，不做服务名截断。"""

        (log_root / "order.service.log").write_text(
            "2026-10-18 10:00:05.000 INFO [m] com.example.X - hello from dotted file [trace-dot-123]\n",
            encoding="utf-8",
        )
        result = search_logs_tool.call({"keyword": "hello from dotted"}, _ctx())
        assert any(m["file"] == "order.service.log" for m in result.output["matches"])


class TestGetLogContext:
    def test_context_includes_continuation(self, log_root: Path) -> None:
        # svc-b 第 3 行是 ERROR 记录行，第 4/5 行是续行
        result = get_log_context_tool.call({"file": "svc-b.log", "line": 3, "context": 2}, _ctx())
        assert result.is_error is False
        continuations = [row for row in result.output["lines"] if row["continuation"]]
        assert continuations, "上下文应包含续行"

    def test_path_escape_rejected(self, log_root: Path) -> None:
        result = get_log_context_tool.call({"file": "../etc/passwd", "line": 1}, _ctx())
        assert result.is_error is True
        assert "path_outside_root" in result.output["message"] or "not found" in result.output["message"]

    def test_absolute_path_rejected(self, log_root: Path) -> None:
        result = get_log_context_tool.call({"file": str(log_root / "svc-a.log"), "line": 1}, _ctx())
        assert result.is_error is True
        assert "path_must_be_relative" in result.output["message"]

    def test_gz_rejected(self, log_root: Path) -> None:
        result = get_log_context_tool.call({"file": "svc-c.log.gz", "line": 1}, _ctx())
        assert result.is_error is True
        assert "unsupported_file" in result.output["message"]


class TestParseStackTrace:
    def test_from_exception_line(self, log_root: Path) -> None:
        result = parse_stack_trace_tool.call({"file": "svc-a.log", "line": 3}, _ctx())
        assert result.is_error is False
        out = result.output
        assert out["exception"]
        assert out["frames"]
        assert out["caused_by"]
        assert out["caused_by"][0]["type"].endswith("DownstreamException")

    def test_resolves_upward_from_frame_line(self, log_root: Path) -> None:
        """P2-1：给栈帧行也能向上回溯到异常行。"""

        # svc-a 第 5/6 行是 \tat 帧
        result = parse_stack_trace_tool.call({"file": "svc-a.log", "line": 6}, _ctx())
        assert result.is_error is False
        out = result.output
        assert out["exception"]
        assert out["resolved_from_line"] <= 6

    def test_no_stack(self, log_root: Path) -> None:
        # 轮转文件只有一行启动日志，与异常无关
        result = parse_stack_trace_tool.call({"file": "svc-a.log.1", "line": 1}, _ctx())
        assert result.is_error is False
        assert "no_stack_found" in result.output["note"]


class TestCorrelateEvents:
    def test_full_trace(self, log_root: Path) -> None:
        result = correlate_events_tool.call({"trace_id": TRACE_FULL}, _ctx())
        out = result.output
        assert out["count"] >= 4
        # TRACE_FULL 也出现在轮转文件 svc-a.log.1（启动日志）——按文件维度如实返回
        assert set(out["files"]) == {"svc-a.log", "svc-a.log.1", "svc-b.log"}
        times = [e["time"] for e in out["events"]]
        assert times == sorted(times)

    def test_partial_trace_reports_files(self, log_root: Path) -> None:
        result = correlate_events_tool.call({"trace_id": TRACE_PARTIAL}, _ctx())
        out = result.output
        assert out["files"] == ["svc-a.log"]

    def test_trace_id_missing(self, log_root: Path) -> None:
        result = correlate_events_tool.call({"trace_id": "0" * 32}, _ctx())
        out = result.output
        assert out["count"] == 0
        assert "cannot_correlate" in out["note"]


class TestRegistration:
    def test_register_log_tools(self) -> None:
        class _Registry:
            def __init__(self) -> None:
                self.tools: dict[str, object] = {}

            def register(self, tool: object) -> None:
                self.tools[getattr(tool, "name")] = tool

            def get(self, name: str) -> object | None:
                return self.tools.get(name)

        registry = _Registry()
        register_log_tools(registry)
        for name in ("search_logs", "get_log_context", "parse_stack_trace", "correlate_events"):
            assert registry.get(name) is not None
