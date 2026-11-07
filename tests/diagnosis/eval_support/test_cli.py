#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""``eval-run`` CLI 测试（EVAL-P1a）——fake executor，零模型、零数据库成本。"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from cloudagent_ext.diagnosis.eval_support.cli import run_eval_run
from cloudagent_ext.diagnosis.eval_support.record import record_from_json
from tests.diagnosis.eval_support.test_execute import FakeCaseRun, FakeExecutor

_REQUEST_PAYLOAD = {
    "schema_version": 1,
    "request_id": "req-0001",
    "case_id": "sql-001",
    "domain": "sql",
    "question": "订单列表页变慢，请诊断",
}

_OK_META = {
    "model": "fake-model",
    "elapsed_sec": 7.0,
    "model_calls": 2,
    # main 派发 + 拿到子代理结果（auto 口径下的成功形态，见 schema §5）
    "grade_source": "subagent",
    "usage": {
        "input_tokens": 10,
        "output_tokens": 5,
        "cached_input_tokens": 0,
        "calls_with_usage": 2,
        "calls_without_usage": 0,
        "available": True,
    },
}


def _write_request(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "request.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class TestRunEvalRun:
    def test_success_writes_record_and_prints_summary(
        self, tmp_path: Path, capsys
    ) -> None:
        request_path = _write_request(tmp_path, _REQUEST_PAYLOAD)
        out_path = tmp_path / "out" / "rec.json"

        rc = run_eval_run(
            ["--request", str(request_path), "--out", str(out_path)],
            executor=FakeExecutor(FakeCaseRun(meta=dict(_OK_META))),
        )

        assert rc == 0
        assert out_path.exists()
        record = record_from_json(json.loads(out_path.read_text(encoding="utf-8")))
        assert record.case_id == "sql-001"
        assert record.outcome["status"] == "ok"
        # stdout 只打一行摘要（不刷屏）
        lines = capsys.readouterr().out.strip().splitlines()
        assert len(lines) == 1
        assert lines[0].startswith(f"eval-run: {record.record_id} ")
        assert "status=ok" in lines[0]
        assert "elapsed=" in lines[0]

    def test_invalid_request_returns_2_and_writes_nothing(
        self, tmp_path: Path, capsys
    ) -> None:
        payload = dict(_REQUEST_PAYLOAD, ground_truth={"root_causes": []})
        request_path = _write_request(tmp_path, payload)
        out_path = tmp_path / "rec.json"

        rc = run_eval_run(
            ["--request", str(request_path), "--out", str(out_path)],
            executor=FakeExecutor(FakeCaseRun()),
        )

        assert rc == 2
        assert not out_path.exists()
        assert "ground_truth" in capsys.readouterr().err

    def test_malformed_json_returns_2(self, tmp_path: Path) -> None:
        request_path = tmp_path / "request.json"
        request_path.write_text("{not json", encoding="utf-8")
        out_path = tmp_path / "rec.json"

        rc = run_eval_run(
            ["--request", str(request_path), "--out", str(out_path)],
            executor=FakeExecutor(FakeCaseRun()),
        )
        assert rc == 2
        assert not out_path.exists()

    def test_missing_request_file_returns_2(self, tmp_path: Path) -> None:
        rc = run_eval_run(
            ["--request", str(tmp_path / "nope.json"), "--out", str(tmp_path / "r.json")],
            executor=FakeExecutor(FakeCaseRun()),
        )
        assert rc == 2

    def test_missing_args_exit_code_2(self) -> None:
        with pytest.raises(SystemExit) as excinfo:
            run_eval_run(["--request", "x.json"], executor=FakeExecutor(FakeCaseRun()))
        assert excinfo.value.code == 2

    def test_executor_crash_still_writes_record_and_returns_1(
        self, tmp_path: Path
    ) -> None:
        """契约："执行失败仍写出 RunRecord"——硬异常也必须落 crashed 样本。"""

        class ExplodingExecutor:
            model_label = "fake-model"

            def run_case(self, case: dict) -> None:
                raise RuntimeError("provider 不可达")

        request_path = _write_request(tmp_path, _REQUEST_PAYLOAD)
        out_path = tmp_path / "rec.json"

        rc = run_eval_run(
            ["--request", str(request_path), "--out", str(out_path)],
            executor=ExplodingExecutor(),
        )

        assert rc == 1
        assert out_path.exists()
        record = record_from_json(json.loads(out_path.read_text(encoding="utf-8")))
        assert record.outcome["status"] == "crashed"
        assert record.outcome["error"] is not None
        assert "provider" in str(record.outcome["error"])

    def test_timeout_case_writes_record_and_returns_1(self, tmp_path: Path) -> None:
        request_path = _write_request(tmp_path, _REQUEST_PAYLOAD)
        out_path = tmp_path / "rec.json"

        rc = run_eval_run(
            ["--request", str(request_path), "--out", str(out_path)],
            executor=FakeExecutor(FakeCaseRun(error="timeout after 300s", meta=dict(_OK_META))),
        )

        assert rc == 1
        record = record_from_json(json.loads(out_path.read_text(encoding="utf-8")))
        assert record.outcome["status"] == "timeout"


class TestDispatchRegistration:
    def test_run_cli_has_eval_run_fast_path(self) -> None:
        """子命令 sieve 必须注册 eval-run（doctor 同级的 fast-path）。"""

        from cloudagent_ext.cli import dispatch

        source = inspect.getsource(dispatch.run_cli)
        assert '"eval-run"' in source
        assert "run_eval_run" in source
