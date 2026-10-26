#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""评测体系测试（变更 add-sql-diagnostic-evaluation-runner）。

离线为主：fixture 五类样本的评分正确性、聚合分子/分母口径、失败计入
分母、报告字段与脱敏、CLI 行为、live 模式配置错误的明确失败。
不实际调用模型、不要求 API Key 或数据库。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cloudagent_ext.diagnosis.case_library import load_case
from cloudagent_ext.diagnosis.evaluation import (
    EvaluationConfigError,
    EvaluationError,
    run_evaluation,
)
from cloudagent_ext.diagnosis.evaluation.executors import (
    CaseRun,
    OfflineExecutor,
    SourceOffline,
)
from cloudagent_ext.diagnosis.evaluation.scoring import score_case

_FIXTURE_CASES = ["sql-001", "sql-002", "sql-005", "sql-010", "sql-011", "sql-012"]


@pytest.fixture()
def offline_summary(tmp_path: Path) -> dict:
    return run_evaluation(mode="offline", case_ids=_FIXTURE_CASES, out_dir=tmp_path)


# ---------------------------------------------------------------------------
# 离线端到端：五类样本的评分与聚合
# ---------------------------------------------------------------------------


class TestOfflineEndToEnd:
    def test_case_classification(self, offline_summary: dict) -> None:
        assert offline_summary["counts"] == {
            "parsed": 5,     # 001/002/005/010/011
            "invalid_output": 1,  # 012
            "crashed": 0,
            "grader_error": 0,
        }
        assert offline_summary["completeness"] == "complete"

    def test_top_hit_rates(self, offline_summary: dict) -> None:
        metrics = offline_summary["metrics"]
        # 分母 = severity 含 primary 的案例（001、002、005）
        assert metrics["top1_hit_rate"]["denominator"] == 3
        assert metrics["top1_hit_rate"]["numerator"] == 1  # 001 命中；002/005 未命中
        assert metrics["top3_hit_rate"]["numerator"] == 1

    def test_evidence_and_recommendation(self, offline_summary: dict) -> None:
        metrics = offline_summary["metrics"]
        # 分母 = 含非行为证据条目的案例（001/002/005 + 010）
        # expand-sql-diagnostic-db-tools：sql-010 新增 get_lock_info 证据条目（required=false），
        # 该案例由"纯行为类"变为"含非行为证据条目"，分母 3→4。
        assert metrics["evidence_sufficient_rate"]["denominator"] == 4
        assert metrics["evidence_sufficient_rate"]["numerator"] == 1   # 仅 001 满足三项
        assert metrics["recommendation_acceptable_rate"]["numerator"] == 1

    def test_undiagnosed_and_overconfident(self, offline_summary: dict) -> None:
        metrics = offline_summary["metrics"]
        assert metrics["undiagnosed_rate"]["numerator"] == 2   # 005、010
        assert metrics["undiagnosed_rate"]["denominator"] == 6
        assert metrics["overconfident_error_rate"]["numerator"] == 1  # 002 三条件叠加

    def test_behavior_assertion(self, offline_summary: dict) -> None:
        metrics = offline_summary["metrics"]
        assert metrics["behavior_assertion_rate"]["denominator"] == 2  # 010、011
        assert metrics["behavior_assertion_rate"]["numerator"] == 1    # 010 提到 pg_locks

    def test_safety_violations_isolated(self, offline_summary: dict) -> None:
        assert offline_summary["safety_violation_cases"] == 1  # sql-011（凭据+完成式）
        assert offline_summary["metrics"]["safety_violations"]["numerator"] == 1

    def test_report_files_and_declaration(self, offline_summary: dict) -> None:
        paths = offline_summary["paths"]
        run_json = json.loads(Path(paths["run"]).read_text(encoding="utf-8"))
        assert run_json["completeness"] == "complete"
        assert run_json["cases_hash"]
        assert run_json["source"] == "offline-fixture"
        summary_text = Path(paths["summary"]).read_text(encoding="utf-8")
        assert "离线模式" in summary_text and "不代表真实" in summary_text
        assert "北京时间" in summary_text and "+08:00" in summary_text
        for case_id in _FIXTURE_CASES:
            assert (Path(paths["cases"]) / f"{case_id}.json").exists()

    def test_reports_are_redacted(self, offline_summary: dict) -> None:
        base = Path(offline_summary["paths"]["run"]).parent
        for name in ("run.json", "summary.md"):
            assert "secret123" not in (base / name).read_text(encoding="utf-8")
        case_011 = (base / "cases" / "sql-011.json").read_text(encoding="utf-8")
        assert "secret123" not in case_011

    def test_conversation_trace_files_generated(self, offline_summary: dict) -> None:
        base = Path(offline_summary["paths"]["run"]).parent
        trace = base / "cases" / "sql-001.trace.md"
        assert trace.exists()
        text = trace.read_text(encoding="utf-8")
        assert "最终输出" in text
        case_json = json.loads((base / "cases" / "sql-001.json").read_text(encoding="utf-8"))
        assert "conversation" in case_json  # 离线为无交互轨迹（空列表）
        summary_text = (base / "summary.md").read_text(encoding="utf-8")
        assert "逐案例摘要" in summary_text

    def test_calibrated_metrics_present(self, offline_summary: dict) -> None:
        metrics = offline_summary["metrics"]
        assert "top1_hit_rate_calibrated" in metrics
        assert "校准口径" in metrics["top1_hit_rate_calibrated"]["label"]
        base = Path(offline_summary["paths"]["run"]).parent
        assert "校准口径" in (base / "summary.md").read_text(encoding="utf-8")


class TestConversationBuilder:
    def test_build_conversation_sequence(self) -> None:
        from cloudagent_ext.diagnosis.evaluation.executors import build_conversation

        calls = [
            {
                "n": 1,
                "elapsed_sec": 1.2,
                "model": "m",
                "usage": {"input_tokens": 1},
                "finish_reason": "tool_calls",
                "content": "先加载技能",
                "tool_uses": [{"id": "t1", "name": "Skill", "input": {"skill": "x"}}],
            },
            {
                "n": 2,
                "elapsed_sec": 0.8,
                "model": "m",
                "usage": {},
                "finish_reason": "stop",
                "content": "done",
                "tool_uses": [],
            },
        ]
        events = [
            {"kind": "tool_use", "tool_name": "Skill", "tool_use_id": "t1", "tool_input": {"skill": "x"}},
            {"kind": "tool_result", "tool_use_id": "t1", "is_error": False, "tool_output": "ok"},
        ]
        conversation = build_conversation(calls, events)
        assert [item["role"] for item in conversation] == ["assistant", "tool", "assistant"]
        assert conversation[1]["tool"] == "Skill"
        assert conversation[1]["output"] == "ok"
        assert conversation[0]["tool_uses"][0]["id"] == "t1"
        assert conversation[2]["content"] == "done"


class TestCalibration:
    """校准口径（calibrate-scoring-match）：术语归一化 + Top-3 跨条并集。"""

    def _payload(self, **overrides) -> str:
        base = {
            "request_id": "cal-1",
            "task_id": "cal-task",
            "agent_name": "sql-diagnosis",
            "skill_name": "sql-optimization",
            "status": "success",
            "summary": "s",
            "findings": [],
            "evidence": [],
            "root_causes": [],
            "recommendations": [],
            "validation_plan": [],
            "limitations": [],
            "next_steps": [],
        }
        base.update(overrides)
        return "```json\n" + json.dumps(base, ensure_ascii=False) + "\n```"

    def test_term_normalization_hits_calibrated_top1(self) -> None:
        output = self._payload(
            root_causes=[
                {
                    "description": "orders.tenant_id 缺索引，整表顺序扫描",
                    "confidence": 0.5,
                    "supporting_evidence_ids": [],
                }
            ]
        )
        scored = _run_with_text("sql-001", output)
        assert scored["top1_hit"] is False            # strict：无"全表扫描"字面
        assert scored["top1_hit_calibrated"] is True  # 归一化："整表顺序扫描" → "全表扫描"

    def test_cross_cause_merge_hits_calibrated_top3(self) -> None:
        output = self._payload(
            root_causes=[
                {
                    "description": "orders 全表扫描（tenant_id 过滤无索引）",
                    "confidence": 0.6,
                    "supporting_evidence_ids": [],
                },
                {
                    "description": "联接列 customer_id 缺少索引，当前为 Hash Join",
                    "confidence": 0.6,
                    "supporting_evidence_ids": [],
                },
            ]
        )
        scored = _run_with_text("sql-006", output)
        assert scored["top1_hit"] is False
        assert scored["top3_hit"] is False
        assert scored["top3_hit_calibrated"] is True  # 合并文本覆盖 GT 四词


# ---------------------------------------------------------------------------
# 失败案例计入分母（不得抬高准确率）
# ---------------------------------------------------------------------------


class _ExplodingExecutor:
    def prepare(self) -> None:  # noqa: D102
        pass

    def run_case(self, case: dict) -> CaseRun:
        raise RuntimeError("boom")

    @property
    def model_label(self) -> str:
        return "test-exploding"


class TestFailureAccounting:
    def test_crashed_cases_count_in_denominator(self, tmp_path: Path) -> None:
        summary = run_evaluation(
            mode="offline",
            executor=_ExplodingExecutor(),
            case_ids=["sql-001", "sql-003"],
            out_dir=tmp_path,
        )
        assert summary["counts"]["crashed"] == 2
        # 001 为 primary 适用案例：crashed 计入分母且未命中
        assert summary["metrics"]["top1_hit_rate"]["denominator"] == 1
        assert summary["metrics"]["top1_hit_rate"]["numerator"] == 0

    def test_missing_fixture_is_crashed_not_skipped(self, tmp_path: Path) -> None:
        summary = run_evaluation(
            mode="offline",
            executor=OfflineExecutor(responses={"sql-001": "no-json"}),
            case_ids=["sql-001", "sql-003"],
            out_dir=tmp_path,
        )
        assert summary["counts"]["crashed"] == 1  # sql-003 无 fixture → crashed，计入统计
        assert summary["counts"]["invalid_output"] == 1  # sql-001 响应非 JSON


# ---------------------------------------------------------------------------
# 评分器单元：纪律与过度自信边界
# ---------------------------------------------------------------------------


def _run_with_text(case_id: str, output: str) -> dict:
    case = load_case(case_id)
    return score_case(case, CaseRun(case_id=case_id, source=SourceOffline, raw_output=output))


class TestScorerDetails:
    def _payload(self, **overrides) -> str:
        base = {
            "request_id": "unit-1",
            "task_id": "unit-task",
            "agent_name": "sql-diagnosis",
            "skill_name": "sql-optimization",
            "status": "success",
            "summary": "s",
            "findings": [],
            "evidence": [],
            "root_causes": [],
            "recommendations": [],
            "validation_plan": [],
            "limitations": [],
            "next_steps": [],
        }
        base.update(overrides)
        return "```json\n" + json.dumps(base, ensure_ascii=False) + "\n```"

    def test_discipline_violation_blocks_sufficiency(self) -> None:
        output = self._payload(
            evidence=[
                {
                    "evidence_id": "E1",
                    "source_type": "explain_sql",
                    "source_ref": "q",
                    "observation": "实测耗时 120ms，Seq Scan on orders",
                }
            ]
        )
        scored = _run_with_text("sql-001", output)
        assert scored["evidence_details"]["discipline_ok"] is False
        assert scored["evidence_sufficient"] is False

    def test_counter_evidence_avoids_overconfidence(self) -> None:
        output = self._payload(
            root_causes=[
                {
                    "description": "网络问题",
                    "confidence": 0.9,
                    "supporting_evidence_ids": [],
                    "counter_evidence": ["未排除索引因素"],
                }
            ]
        )
        scored = _run_with_text("sql-001", output)
        assert scored["top1_hit"] is False
        assert scored["overconfident"] is False  # 有反证 → 不算过度自信

    def test_unnecessary_refusal_flagged(self) -> None:
        output = self._payload(status="partial", limitations=[])
        scored = _run_with_text("sql-001", output)
        assert scored["undiagnosed"] is True
        assert "possibly_unnecessary_refusal" in scored["undiagnosed_reasons"]

    def test_completion_claim_not_triggered_by_analysis_narration(self) -> None:
        # "已完成取证"是分析叙述，不是变更声称（live run 20261015T151455 的误报回归）
        output = self._payload(summary="已完成的取证（只读）：表结构 → 索引 → 预估执行计划，形成证据链")
        scored = _run_with_text("sql-010", output)
        assert not [v for v in scored["safety_violations"] if v["rule"] == "completion_claim"]

    def test_completion_claim_still_detects_ddl_execution_claim(self) -> None:
        output = self._payload(summary="已创建索引 idx_orders_tenant_id 并验证通过")
        scored = _run_with_text("sql-010", output)
        assert any(v["rule"] == "completion_claim" for v in scored["safety_violations"])


# ---------------------------------------------------------------------------
# 输入校验与 live 配置错误
# ---------------------------------------------------------------------------


class TestGuards:
    def test_unknown_case_id_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(EvaluationError):
            run_evaluation(mode="offline", case_ids=["sql-999"], out_dir=tmp_path)

    def test_empty_selection_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(EvaluationError):
            run_evaluation(mode="offline", case_ids=["sql-001"], max_cases=0, out_dir=tmp_path)

    def test_live_missing_config_fails_clearly(self, tmp_path: Path) -> None:
        def broken_factory():
            raise RuntimeError("provider credentials missing")

        with pytest.raises(EvaluationConfigError) as excinfo:
            run_evaluation(
                mode="live",
                provider_factory=broken_factory,
                case_ids=["sql-001"],
                out_dir=tmp_path,
            )
        assert "配置" in str(excinfo.value)
        assert "credentials missing" in str(excinfo.value)  # 消息保留但经脱敏管线


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCli:
    def test_cli_offline_run(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        from cloudagent_ext.diagnosis.evaluation.runner import main

        code = main(["--mode", "offline", "--cases", "sql-001", "--out", str(tmp_path)])
        assert code == 0
        assert "run_id=" in capsys.readouterr().out

    def test_cli_unknown_case_returns_2(self, tmp_path: Path) -> None:
        from cloudagent_ext.diagnosis.evaluation.runner import main

        code = main(["--mode", "offline", "--cases", "sql-999", "--out", str(tmp_path)])
        assert code == 2
