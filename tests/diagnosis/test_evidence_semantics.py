#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""证据语义字段测试（变更 extend-evidence-semantics）。

覆盖：可选字段与截断、恒输出、构造期清洗与幂等、可核验性三档、冲突统计。
"""

from __future__ import annotations

import json

from cloudagent_ext.diagnosis.evaluation.scoring import (
    _unaligned_conflicts,
    _verifiability_stats,
)
from cloudagent_ext.diagnosis.models import DiagnosisRequest, DiagnosisResult, Evidence
from cloudagent_ext.diagnosis.session import InvestigationSession


def _evidence(**kwargs) -> Evidence:
    base = dict(
        evidence_id="ev:db:1",
        source_type="db",
        source_ref="public.orders",
        observation="orders 表 order-12345 计数为 0",
    )
    base.update(kwargs)
    return Evidence(**base)


def _result(evidence: list[Evidence]) -> DiagnosisResult:
    return DiagnosisResult(
        request_id="req-1",
        agent_name="sql-diagnosis",
        status="success",
        summary="s",
        evidence=evidence,
    )


class TestOptionalFields:
    def test_legacy_output_still_parses_and_gains_four_keys(self) -> None:
        data = {
            "evidence_id": "ev:db:1",
            "source_type": "db",
            "source_ref": "public.orders",
            "observation": "o",
        }
        parsed = Evidence.from_dict(data)
        assert parsed.proves == "" and parsed.cannot_prove == []
        out = parsed.to_dict()
        assert set(out) == {
            "evidence_id",
            "source_type",
            "source_ref",
            "observation",
            "observed_at",
            "scope",
            "reliability",
            "proves",
            "cannot_prove",
            "applicability",
            "relation",
        }
        # 其余字段与旧输出一致
        for key, value in data.items():
            assert out[key] == value

    def test_roundtrip(self) -> None:
        item = _evidence(
            proves="orders 在 23:45 为空",
            cannot_prove=["未落库原因"],
            applicability={"window": "2026-10-24T23:45"},
            relation=[{"kind": "complementary", "with": "ev:db:1"}],
        )
        parsed = Evidence.from_dict(item.to_dict())
        assert parsed.to_dict() == item.to_dict()

    def test_truncation_not_rejection(self) -> None:
        item = _evidence(
            proves="x" * 200,
            cannot_prove=[f"item-{i}" for i in range(8)],
            applicability={f"k{i}": i for i in range(6)},
            relation=[{"kind": "consistent", "with": "ev:db:1"} for _ in range(5)],
        )
        assert len(item.proves) == 120
        assert len(item.cannot_prove) == 5
        assert len(item.applicability) == 4
        assert len(item.relation) == 3

    def test_empty_proves_is_accepted(self) -> None:
        assert _evidence(proves="").proves == ""

    def test_semantic_looseness(self) -> None:
        item = _evidence(
            proves="数据未落库；且同步任务未触发",
            applicability={"custom_key": "whatever"},
        )
        assert "；" in item.proves
        assert item.applicability == {"custom_key": "whatever"}


class TestRelationCleanup:
    def test_dangling_relation_dropped_at_construction(self) -> None:
        result = _result(
            [
                _evidence(
                    relation=[
                        {"kind": "conflict", "with": "ev:db:1"},
                        {"kind": "conflict", "with": "ev:missing"},
                    ]
                )
            ]
        )
        assert [rel["with"] for rel in result.evidence[0].relation] == ["ev:db:1"]
        assert any("ev:missing" in item for item in result.reference_warnings())
        assert result.validate_references() == []

    def test_warnings_are_pure_and_idempotent(self) -> None:
        result = _result([_evidence(relation=[{"kind": "conflict", "with": "nope"}])])
        first = result.reference_warnings()
        second = result.reference_warnings()
        assert first == second and len(first) == 1

    def test_to_dict_unaffected_by_warnings_call(self) -> None:
        """不调用 reference_warnings() 时，to_dict 也不得含悬空引用。"""

        result = _result([_evidence(relation=[{"kind": "conflict", "with": "nope"}])])
        before = json.dumps(result.to_dict(), ensure_ascii=False)
        assert "nope" not in before
        result.reference_warnings()
        after = json.dumps(result.to_dict(), ensure_ascii=False)
        assert before == after

    def test_unconventional_kind_is_warning_not_error(self) -> None:
        result = _result([_evidence(relation=[{"kind": "maybe", "with": "ev:db:1"}])])
        assert result.evidence[0].relation[0]["kind"] == "maybe"
        assert any("unconventional" in item for item in result.reference_warnings())

    def test_session_still_records_result(self) -> None:
        session = InvestigationSession(DiagnosisRequest(request_id="req-1", question="q"))
        task = session.delegate("sql-diagnosis", "查")
        result = _result([_evidence(relation=[{"kind": "conflict", "with": "nope"}])])
        result.task_id = task.task_id
        session.record_result(result)
        assert session.entries[0].status == "completed"


class TestVerifiability:
    def test_three_buckets(self) -> None:
        result = _result(
            [
                _evidence(evidence_id="ev:db:1", proves="orders 表 order-12345 计数为 0"),
                _evidence(evidence_id="ev:db:2", proves="任务执行完毕"),
                _evidence(evidence_id="ev:db:3"),
            ]
        )
        stats = _verifiability_stats(result)
        assert stats["verifiable"] == 1
        assert stats["no_keywords"] == 1
        assert stats["no_proves"] == 1
        assert stats["total"] == 3

    def test_verified_hit_and_miss(self) -> None:
        hit = _result([_evidence(proves="orders 表 order-12345 为 0")])
        miss = _result(
            [
                _evidence(
                    observation="无关内容",
                    proves="orders 表 order-12345 为 0",
                )
            ]
        )
        assert _verifiability_stats(hit)["verified_hits"] == 1
        assert _verifiability_stats(miss)["verified_hits"] == 0

    def test_chinese_proves_not_counted_as_unverified(self) -> None:
        stats = _verifiability_stats(_result([_evidence(proves="数据未落库")]))
        assert stats["verified_rate"] is None
        assert stats["no_keywords"] == 1
        assert stats["no_keywords_rate"] == 1.0

    def test_small_sample_returns_none_rate(self) -> None:
        stats = _verifiability_stats(_result([_evidence(proves="orders 表 order-12345 为 0")]))
        assert stats["verified_rate"] is None  # 分母 1 < 5


class TestConflictStats:
    def test_counts_unaligned_conflict(self) -> None:
        result = _result(
            [
                _evidence(
                    evidence_id="ev:db:1",
                    applicability={"window": "09:00"},
                    relation=[{"kind": "conflict", "with": "ev:db:2"}],
                ),
                _evidence(evidence_id="ev:db:2", applicability={"window": "10:00"}),
            ]
        )
        assert _unaligned_conflicts(result) == 1

    def test_aligned_conflict_not_counted(self) -> None:
        result = _result(
            [
                _evidence(
                    evidence_id="ev:db:1",
                    applicability={"window": "09:00"},
                    relation=[{"kind": "conflict", "with": "ev:db:2"}],
                ),
                _evidence(evidence_id="ev:db:2", applicability={"window": "09:00"}),
            ]
        )
        assert _unaligned_conflicts(result) == 0


class TestSufficiencyUnchanged:
    def test_new_fields_do_not_change_evidence_check(self) -> None:
        from cloudagent_ext.diagnosis.evaluation.scoring import _evidence_check

        case = {
            "ground_truth": {
                "required_evidence": [{"tool": "query_table_rows", "observation_terms": ["order-12345"]}]
            }
        }
        legacy = _result([_evidence()])
        enriched = _result([_evidence(proves="orders 表 order-12345 为 0")])
        assert _evidence_check(case, legacy)["sufficient"] is True
        assert _evidence_check(case, enriched)["sufficient"] is True


class TestRelationStructureSoftFail:
    """relation 元素结构不完整也必须软失败（实现审查 P1-2）。"""

    def test_missing_with_is_dropped_with_warning(self) -> None:
        result = _result([_evidence(relation=[{"kind": "conflict"}])])
        assert result.evidence[0].relation == []
        assert any("invalid 'with'" in item for item in result.reference_warnings())
        assert result.validate_references() == []

    def test_non_string_with_is_dropped_with_warning(self) -> None:
        result = _result([_evidence(relation=[{"kind": "conflict", "with": 123}])])
        assert result.evidence[0].relation == []
        assert any("invalid 'with'" in item for item in result.reference_warnings())

    def test_parse_still_succeeds(self) -> None:
        from cloudagent_ext.diagnosis.protocol import parse_diagnosis_result

        text = (
            '```json\n{"request_id":"r","agent_name":"a","status":"success","summary":"s",'
            '"evidence":[{"evidence_id":"ev:1","source_type":"db","source_ref":"r",'
            '"observation":"o","relation":[{"kind":"conflict"}]}]}\n```'
        )
        parsed = parse_diagnosis_result(text)
        assert parsed.evidence[0].relation == []
        assert parsed.reference_warnings()


class TestTruncationMarker:
    def test_proves_truncated_with_ellipsis(self) -> None:
        item = _evidence(proves="x" * 200)
        assert len(item.proves) == 120
        assert item.proves.endswith("…")


class TestConflictNoSharedKeys:
    def test_no_shared_keys_counts_as_unaligned(self) -> None:
        result = _result(
            [
                _evidence(
                    evidence_id="ev:db:1",
                    applicability={"window": "09:00"},
                    relation=[{"kind": "conflict", "with": "ev:db:2"}],
                ),
                _evidence(evidence_id="ev:db:2", applicability={"tenant": "t1"}),
            ]
        )
        assert _unaligned_conflicts(result) == 1

    def test_missing_applicability_is_not_counted(self) -> None:
        result = _result(
            [
                _evidence(
                    evidence_id="ev:db:1",
                    relation=[{"kind": "conflict", "with": "ev:db:2"}],
                ),
                _evidence(evidence_id="ev:db:2"),
            ]
        )
        assert _unaligned_conflicts(result) == 0


class TestAggregateMetrics:
    """聚合层指标（实现审查 P1-1：分母曾把 verified_hits 计进总数）。"""

    def _case(self, evidence: list[Evidence]) -> dict:
        return {
            "case_id": "c1",
            "category": "parsed",
            "grader_error": False,
            "top1_applicable": False,
            "top1_hit": False,
            "top3_hit": False,
            "top1_hit_calibrated": False,
            "top3_hit_calibrated": False,
            "evidence_applicable": True,
            "evidence_sufficient": True,
            "recommendation_acceptable": True,
            "undiagnosed": False,
            "overconfident": False,
            "behavior_passed": None,
            "safety_violations": [],
            "evidence_sources": {},
            "verifiability": _verifiability_stats(_result(evidence)),
            "unaligned_conflicts": 0,
            "conflict_declarations": 0,
        }

    def test_denominator_equals_evidence_total(self) -> None:
        from cloudagent_ext.diagnosis.evaluation.scoring import aggregate_metrics

        evidence = [
            _evidence(evidence_id="ev:db:1", proves="orders 表 order-12345 为 0"),
            _evidence(evidence_id="ev:db:2", proves="orders 表 order-12345 为 0"),
            _evidence(evidence_id="ev:db:3", proves="任务执行完毕"),
            _evidence(evidence_id="ev:db:4"),
        ]
        metrics = aggregate_metrics([self._case(evidence)])
        total = metrics["evidence_verifiable_count"]["denominator"]
        assert total == 4
        three = sum(
            metrics[key]["numerator"]
            for key in (
                "evidence_verifiable_count",
                "evidence_no_keywords_count",
                "evidence_no_proves_count",
            )
        )
        assert three == total

    def test_small_sample_shows_na_with_denominator(self) -> None:
        from cloudagent_ext.diagnosis.evaluation.scoring import aggregate_metrics

        metrics = aggregate_metrics([self._case([_evidence(proves="orders 表 order-12345 为 0")])])
        assert "n/a" in metrics["evidence_verified_rate"]["value"]
        assert "分母 1" in metrics["evidence_verified_rate"]["value"]

    def test_language_coverage_flag(self) -> None:
        from cloudagent_ext.diagnosis.evaluation.scoring import aggregate_metrics

        evidence = [_evidence(evidence_id=f"ev:db:{i}", proves="数据未落库") for i in range(3)]
        metrics = aggregate_metrics([self._case(evidence)])
        assert "insufficient_language_coverage" in metrics["evidence_no_keywords_rate"]["note"]


class TestOptionalContainerSoftFail:
    """可选字段容器类型错误 → 降级 + warning（变更 soften-optional-evidence-types）。"""

    def _result_with(self, **kwargs) -> DiagnosisResult:
        return _result([_evidence(**kwargs)])

    def test_cannot_prove_string_degrades(self) -> None:
        result = self._result_with(cannot_prove="未落库的原因")
        assert result.evidence[0].cannot_prove == []
        assert any("cannot_prove" in item for item in result.reference_warnings())

    def test_applicability_string_degrades(self) -> None:
        result = self._result_with(applicability="全部租户")
        assert result.evidence[0].applicability == {}
        assert any("applicability" in item for item in result.reference_warnings())

    def test_relation_string_degrades(self) -> None:
        result = self._result_with(relation="conflict")
        assert result.evidence[0].relation == []
        assert any("relation" in item for item in result.reference_warnings())

    def test_observed_at_and_reliability_degrade(self) -> None:
        result = self._result_with(observed_at=12345, reliability=7)
        assert result.evidence[0].observed_at is None
        assert result.evidence[0].reliability == ""
        assert len(result.reference_warnings()) >= 2

    def test_non_string_items_dropped_individually(self) -> None:
        result = self._result_with(cannot_prove=["保留", 123, "也保留"])
        assert result.evidence[0].cannot_prove == ["保留", "也保留"]
        assert any("non-string" in item for item in result.reference_warnings())

    def test_required_field_still_rejected(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            Evidence(evidence_id="e", source_type="db", source_ref="r", observation="")

    def test_real_parse_path_succeeds(self) -> None:
        from cloudagent_ext.diagnosis.protocol import parse_diagnosis_result

        text = (
            '```json\n{"request_id":"r","agent_name":"a","status":"success","summary":"s",'
            '"evidence":[{"evidence_id":"ev:1","source_type":"db","source_ref":"r",'
            '"observation":"o","cannot_prove":"x","applicability":"y","relation":"z"}]}\n```'
        )
        parsed = parse_diagnosis_result(text)
        assert parsed.evidence[0].cannot_prove == []
        assert parsed.reference_warnings()


class TestSoftWarningMetrics:
    """软告警的可观测性（变更 measure-soft-evidence-degradation）。"""

    def _case(self, parsed: DiagnosisResult, *, evidence_count: int) -> dict:
        from cloudagent_ext.diagnosis.evaluation.scoring import _verifiability_stats

        return {
            "case_id": "c1",
            "category": "parsed",
            "grader_error": False,
            "top1_applicable": False,
            "top1_hit": False,
            "top3_hit": False,
            "top1_hit_calibrated": False,
            "top3_hit_calibrated": False,
            "evidence_applicable": True,
            "evidence_sufficient": True,
            "recommendation_acceptable": True,
            "undiagnosed": False,
            "overconfident": False,
            "behavior_passed": None,
            "safety_violations": [],
            "evidence_sources": {},
            "verifiability": _verifiability_stats(parsed),
            "unaligned_conflicts": 0,
            "conflict_declarations": 0,
            "soft_warning_count": len(parsed.reference_warnings()),
            "soft_warning_kinds": __import__(
                "cloudagent_ext.diagnosis.evaluation.scoring", fromlist=["_soft_warning_kinds"]
            )._soft_warning_kinds(parsed.reference_warnings()),
        }

    def test_rate_visible_when_degraded(self) -> None:
        from cloudagent_ext.diagnosis.evaluation.scoring import aggregate_metrics

        parsed = _result(
            [
                _evidence(evidence_id="ev:db:1", cannot_prove="x", applicability="y"),
                _evidence(evidence_id="ev:db:2", proves="orders 表 order-12345 为 0"),
            ]
        )
        metrics = aggregate_metrics([self._case(parsed, evidence_count=2)])
        row = metrics["soft_warning_degradation_rate"]
        assert row["numerator"] == 2
        assert row["denominator"] == 2
        assert row["value"] == "100%"

    def test_zero_when_no_warnings(self) -> None:
        from cloudagent_ext.diagnosis.evaluation.scoring import aggregate_metrics

        parsed = _result([_evidence(proves="orders 表 order-12345 为 0")])
        metrics = aggregate_metrics([self._case(parsed, evidence_count=1)])
        assert metrics["soft_warning_degradation_rate"]["value"] == "0%"

    def test_kinds_classified(self) -> None:
        from cloudagent_ext.diagnosis.evaluation.scoring import _soft_warning_kinds

        kinds = _soft_warning_kinds(
            [
                "ev1: evidence.scope: non-object value dropped",
                "ev1 relation dropped: missing/invalid 'with'",
                "ev1: evidence.cannot_prove: non-list value dropped",
                "ev1: something else",
            ]
        )
        assert kinds == {
            "evidence.scope": 1,
            "relation": 1,
            "evidence.cannot_prove": 1,
            "other": 1,
        }

