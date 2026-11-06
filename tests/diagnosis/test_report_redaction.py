#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""报告落盘与脱敏的回归测试。

起因：2026-11-01 第一次跑 live 时，报告写入在
``json.loads(redact_sensitive(json.dumps(case)))`` 处崩掉（``Invalid \\escape``），
整轮数据只落下了 ``run.json``。根因是脱敏正则在**转义后的 JSON 文本**上工作，
一旦匹配跨过 ``\\\\`` 边界就会留下 ``\\U`` 这种非法转义。

所以这里的核心用例是：**含 Windows 路径的 payload 必须能落盘**。
"""

from __future__ import annotations

import json

import pytest

from cloudagent_ext.diagnosis.evaluation.report import (
    redact_payload,
    redact_sensitive,
    write_report,
)


class TestRedactPayload:
    def test_windows_paths_survive(self) -> None:
        payload = {
            "output": r"C:\Users\Administrator\.cloudagent\token",
            "nested": {"path": r"D:\work\myAgent\clawcodex-ascend", "n": 1},
            "list": [r"E:\a\b\c", 2],
        }
        result = redact_payload(payload)
        # 关键不变量：脱敏后仍能被 json 正确往返（改造前这里会抛 Invalid \escape）
        assert json.loads(json.dumps(result, ensure_ascii=False)) == payload

    def test_redacts_sensitive_values(self) -> None:
        payload = {
            "dsn": "postgresql://alice:hunter2@localhost:5433/sim",
            "note": "password=abc123",
            "key": "sk-abcdef123456",
            "phone": "13812345678",
            "mail": "someone@example.com",
        }
        result = redact_payload(payload)
        assert "hunter2" not in result["dsn"]
        assert "abc123" not in result["note"]
        assert "abcdef123456" not in result["key"]
        assert result["phone"] == "1**********"
        assert result["mail"] == "***@***"

    def test_non_string_values_untouched(self) -> None:
        payload = {"a": 1, "b": None, "c": True, "d": 1.5}
        assert redact_payload(payload) == payload

    def test_path_plus_secret_together(self) -> None:
        """最容易崩的组合：同一段文本里既有反斜杠又有密码赋值。"""

        payload = {"t": r"读取 C:\Users\x\config 时发现 password: s3cret!"}
        result = redact_payload(payload)
        assert "s3cret" not in result["t"]
        json.dumps(result)  # 不得抛


def _minimal_run(**overrides) -> dict:
    """``write_report`` 要求的最小 run 形状（summary.md 会读这些键）。"""

    run = {
        "run_id": "r1",
        "mode": "live",
        "source": "live-model",
        "domain": "code",
        "model": "test",
        "cases_hash": "0" * 16,
        "started_at": "2026-11-01T19:00:00+08:00",
        "finished_at": "2026-11-01T19:02:00+08:00",
        "elapsed_sec": 120.0,
        "total_cases": 1,
        "counts": {"parsed": 1, "invalid_output": 0, "crashed": 0, "grader_error": 0},
        "metrics": {},
        "completeness": "complete",
        "case_ids": ["c1"],
    }
    run.update(overrides)
    return run


class TestWriteReport:
    def test_normalize_then_redact_dumps_cleanly(self, tmp_path) -> None:
        """直击 2026-11-01 的崩溃点：case 里含 Windows 路径时，落盘流程必须写完。

        不构造完整的 case 形状（那是 runner 集成测试的事），只验证"归一 → 脱敏 → 落盘"
        这条链路本身不会因为反斜杠而炸。
        """

        from cloudagent_ext.diagnosis.evaluation.report import _dump, _normalize

        case = {
            "case_id": "c1",
            "meta": {"raw": r"见 C:\Users\Administrator\AppData\Local\Temp\x"},
            "calls": [{"content": r"路径 D:\a\b 下的文件\n第二行"}],
            "note": "password=hunter2",
        }
        target = tmp_path / "cases" / "c1.json"
        _dump(target, redact_payload(_normalize(case)))
        loaded = json.loads(target.read_text(encoding="utf-8"))
        assert loaded["meta"]["raw"].startswith("见 C:\\Users")
        assert "hunter2" not in loaded["note"]

    def test_run_json_written(self, tmp_path) -> None:
        run = _minimal_run(note=r"E:\tmp")
        write_report(tmp_path / "run", run, [], domain="code")
        loaded = json.loads((tmp_path / "run" / "run.json").read_text(encoding="utf-8"))
        assert loaded["note"] == r"E:\tmp"


class TestRedactSensitiveStillWorks:
    """``redact_sensitive`` 仍用于纯文本（markdown 回放），行为不变。"""

    def test_text(self) -> None:
        assert "hunter2" not in redact_sensitive("postgresql://u:hunter2@h/db")
        assert redact_sensitive("") == ""

    def test_phone(self) -> None:
        assert redact_sensitive("电话 13812345678") == "电话 1**********"
