#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""``CaseRun → RunRecord`` 映射测试（EVAL-P1a）——全部用 fake 数据，零模型成本。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from cloudagent_ext.diagnosis.eval_support.execute import (
    _CALL_TEXT_LIMIT,
    case_run_to_record,
    execute_case,
)
from cloudagent_ext.diagnosis.eval_support.record import (
    RunRequest,
    record_from_json,
    record_to_json,
)


def _request(**options: Any) -> RunRequest:
    return request_of(
        dispatch_mode=options.get("dispatch_mode", "main"),
        grade_source=options.get("grade_source", "auto"),
    )


def request_of(dispatch_mode: str = "main", grade_source: str = "auto") -> RunRequest:
    return RunRequest(
        request_id="req-0001",
        case_id="sql-001",
        domain="sql",
        question="订单列表页变慢，请诊断",
        options={"dispatch_mode": dispatch_mode, "grade_source": grade_source},
    )


#: P7c.1：能通过协议解析的最小合法 payload（FakeCaseRun 默认 raw_output 用它——
#: 状态诚实化后，非空且解析失败会记 invalid_output，测试替身必须与现实一致）
_VALID_PROTOCOL_PAYLOAD = {
    "request_id": "req-0001",
    "agent_name": "sql-diagnosis",
    "status": "success",
    "summary": "诊断结论摘要",
    "findings": [],
    "evidence": [],
    "root_causes": [],
    "recommendations": [],
    "validation_plan": [],
    "limitations": [],
    "next_steps": [],
}


@dataclass
class FakeCaseRun:
    """只带映射表用到的字段（CaseRun 的测试替身）。"""

    case_id: str = "sql-001"
    source: str = "live"
    raw_output: str = json.dumps(_VALID_PROTOCOL_PAYLOAD, ensure_ascii=False)
    events: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    error: str | None = None
    calls: list = field(default_factory=list)
    main_answer: str = ""


class FakeExecutor:
    """返回固定 CaseRun 的桩（任务卡 4.4：不调模型）。"""

    def __init__(self, case_run: FakeCaseRun) -> None:
        self._case_run = case_run
        self.model_label = "fake-model"

    def run_case(self, case: dict) -> FakeCaseRun:
        assert case["case_id"] == "sql-001"
        assert case["input"]["question"]
        return self._case_run


_SUBJECT = {"product": "cloudagent", "version": "test", "git_sha": "unknown",
            "model": "fake-model", "provider": "deepseek", "dispatch_mode": "main",
            "grade_source": "auto", "permission_mode": "dontAsk", "arm_env": {}}


def _to_record(case_run: FakeCaseRun, request: RunRequest | None = None, **kw: Any):
    return case_run_to_record(
        case_run,
        request or _request(),
        record_id="rec-sql-001-x",
        started_at="2026-11-07T11:28:00+08:00",
        finished_at="2026-11-07T11:30:03+08:00",
        subject=dict(_SUBJECT),
        **kw,
    )


_META = {
    "model": "fake-model",
    "elapsed_sec": 12.5,
    "model_calls": 3,
    "tool_calls": 5,
    "main_tool_calls": 2,
    "sub_tool_calls": 3,
    "delegations": 2,
    "agents_dispatched": ["sql-diagnosis"],
    "gaps_total": 5,
    "gaps_resolved": 1,
    "injected_dispatches": 0,
    "decision_counts": {"gap_resolved": 1},
    "decision_log": [{"reason": "x"}],
    "gap_events": [{"gap_id": "g1"}],
    "compaction": {"sr_applied": 1},
    "recall_count": 0,
    "recall_miss": 0,
    "state_revision": 0,
    "stale_discarded": 0,
    "assessments": {"ok": 1},
    # 不在白名单里的字段（将来 meta 可能新增的调试字段）——必须被排除
    "tools_resolved": ["Read", "Grep"],
    "terminal": "completed",
    "dispatch_incomplete": False,
    "grade_source": "subagent",
    "usage": {
        "input_tokens": 1000,
        "output_tokens": 200,
        "cached_input_tokens": 50,
        "calls_with_usage": 3,
        "calls_without_usage": 0,
        "available": True,
    },
}


class TestStatusDetermination:
    """五档口径（审查裁决：empty 档已删除，空输出归 unfinished）。"""

    def test_ok_is_provisional(self) -> None:
        record = _to_record(FakeCaseRun(meta=dict(_META)))
        assert record.outcome["status"] == "ok"
        assert record.outcome["status_provisional"] is True

    def test_timeout_by_error_text(self) -> None:
        record = _to_record(FakeCaseRun(error="timeout after 300s", meta=dict(_META)))
        assert record.outcome["status"] == "timeout"
        assert "status_provisional" not in record.outcome

    def test_crashed_by_other_error(self) -> None:
        record = _to_record(FakeCaseRun(error="RuntimeError: boom", meta=dict(_META)))
        assert record.outcome["status"] == "crashed"

    def test_empty_output_is_unfinished(self) -> None:
        """空输出 = 没拿到作答机会 → unfinished（不是独立的 empty 档）。"""

        record = _to_record(FakeCaseRun(raw_output="   ", main_answer="", meta=dict(_META)))
        assert record.outcome["status"] == "unfinished"
        assert "status_provisional" not in record.outcome


class TestGradedText:
    """schema §5：选谁评分只有这一处实现。"""

    def test_main_mode_auto_takes_subagent_payload(self) -> None:
        case_run = FakeCaseRun(meta=dict(_META))  # auto + main + effective=subagent
        record = _to_record(case_run)
        assert record.outcome["graded_text"] == case_run.raw_output  # 评分对象=子代理 payload

    def test_main_mode_without_subagent_payload_is_unfinished(self) -> None:
        """main 模式没派发子代理 → graded_text 空串、status 记 unfinished
        （空输出=没拿到作答机会；审查裁决后不再有 empty 档）。"""

        meta = dict(_META, grade_source="main")
        record = _to_record(FakeCaseRun(meta=meta))
        assert record.outcome["graded_text"] == ""
        assert record.outcome["status"] == "unfinished"
        assert "status_provisional" not in record.outcome

    def test_explicit_main_grade_takes_prose(self) -> None:
        record = _to_record(
            FakeCaseRun(meta=dict(_META, grade_source="subagent"),
                        main_answer="主代理散文结论"),
            _request(grade_source="main"),
        )
        assert record.outcome["graded_text"] == "主代理散文结论"
        assert record.outcome["status"] == "ok"

    def test_direct_mode_takes_main_output(self) -> None:
        record = _to_record(
            FakeCaseRun(raw_output="直驱协议输出", main_answer="直驱协议输出",
                        meta=dict(_META, grade_source="main")),
            _request(dispatch_mode="direct"),
        )
        assert record.outcome["graded_text"] == "直驱协议输出"


class TestMechanismWhitelist:
    def test_whitelisted_keys_copied(self) -> None:
        record = _to_record(FakeCaseRun(meta=dict(_META)))
        mechanism = record.mechanism or {}
        assert mechanism["delegations"] == 2
        assert mechanism["agents_dispatched"] == ["sql-diagnosis"]
        assert mechanism["gaps_total"] == 5
        assert mechanism["decision_counts"] == {"gap_resolved": 1}
        assert mechanism["compaction"] == {"sr_applied": 1}
        assert mechanism["state_revision"] == 0

    def test_non_whitelisted_keys_excluded(self) -> None:
        """白名单而非黑名单：meta 新增的调试字段不进契约。

        P3-T3.3（schema §8.2 裁决）把 dispatch_incomplete / terminal /
        tool_calls / main_tool_calls / sub_tool_calls 纳入白名单——它们是
        P3 细分 unfinished/invalid_output 与判"撞顶"的必要观测；
        tools_resolved / grade_source 仍是纯调试字段，不进契约。
        """

        record = _to_record(FakeCaseRun(meta=dict(_META)))
        mechanism = record.mechanism or {}
        assert "tools_resolved" not in mechanism
        assert "grade_source" not in mechanism
        # 新纳入的三/五个键必须在
        assert mechanism["terminal"] == "completed"
        assert mechanism["dispatch_incomplete"] is False
        assert mechanism["tool_calls"] == 5
        assert mechanism["main_tool_calls"] == 2
        assert mechanism["sub_tool_calls"] == 3

    def test_error_is_redacted(self) -> None:
        dsn = "postgresql://user:secret@host:5433/db"
        record = _to_record(FakeCaseRun(error=f"RuntimeError: {dsn}"))
        assert record.outcome["error"] is not None
        assert "secret" not in str(record.outcome["error"])


class TestUsageMapping:
    def test_available_true_maps_tokens(self) -> None:
        record = _to_record(FakeCaseRun(meta=dict(_META)))
        assert record.usage == {
            "input_tokens": 1000,
            "output_tokens": 200,
            "cached_input_tokens": 50,
            "model_calls": 3,
            "calls_without_usage": 0,
            "available": True,
        }

    def test_available_false_means_null_not_zero(self) -> None:
        meta = dict(
            _META,
            usage={
                "input_tokens": 0,
                "output_tokens": 0,
                "cached_input_tokens": 0,
                "calls_with_usage": 0,
                "calls_without_usage": 3,
                "available": False,
            },
        )
        record = _to_record(FakeCaseRun(meta=meta))
        assert record.usage["input_tokens"] is None
        assert record.usage["output_tokens"] is None
        assert record.usage["cached_input_tokens"] is None
        assert record.usage["calls_without_usage"] == 3
        assert record.usage["available"] is False


class TestTraceTruncation:
    def test_long_call_content_truncated_with_marker(self) -> None:
        long_call = {"n": 1, "content": "x" * (_CALL_TEXT_LIMIT + 100), "usage": None}
        record = _to_record(FakeCaseRun(calls=[long_call]))
        call = (record.trace or {})["calls"][0]
        assert len(call["content"]) == _CALL_TEXT_LIMIT
        assert call["truncated"] is True

    def test_short_call_untouched(self) -> None:
        call = {"n": 1, "content": "short", "usage": None}
        record = _to_record(FakeCaseRun(calls=[call]))
        assert (record.trace or {})["calls"][0] == call


class TestExecuteCaseWithFakeExecutor:
    def test_end_to_end_with_injected_executor(self) -> None:
        """端到端（fake executor）：产出可通过 record_from_json 校验的 RunRecord。"""

        record = execute_case(_request(), executor=FakeExecutor(FakeCaseRun(meta=dict(_META))))
        assert record.case_id == "sql-001"
        assert record.record_id.startswith("rec-sql-001-")
        assert record.subject["model"] == "fake-model"
        # 产物必须过得了契约自己的校验
        parsed = record_from_json(record_to_json(record))
        assert parsed.outcome["status"] == record.outcome["status"]

    def test_elapsed_falls_back_to_measured(self) -> None:
        record = execute_case(
            _request(), executor=FakeExecutor(FakeCaseRun(meta={"model": "m"}))
        )
        assert record.elapsed_sec >= 0.0


class TestSubjectArmEnv:
    def test_arm_env_only_records_set_switches(self, monkeypatch) -> None:
        monkeypatch.setenv("CLOUDAGENT_GAP_INJECTION", "off")
        monkeypatch.delenv("CLOUDAGENT_CONTEXT_REDUCE", raising=False)
        from cloudagent_ext.diagnosis.eval_support.execute import build_subject

        subject = build_subject(_request(), "m")
        assert subject["arm_env"] == {"CLOUDAGENT_GAP_INJECTION": "off"}
        assert subject["dispatch_mode"] == "main"
        assert subject["permission_mode"] == "dontAsk"


# ---------------------------------------------------------------------------
# P2-T2.0：last_subagent_payload 按 domain 选期望 agent（schema §9 第 2 条实测修正）
# ---------------------------------------------------------------------------


def _entry(agent_type: str, summary: str):
    from types import SimpleNamespace

    return SimpleNamespace(
        task=SimpleNamespace(agent_type=agent_type),
        result=SimpleNamespace(to_dict=lambda s=summary: {"summary": s, "agent_name": agent_type}),
    )


def _runtime_with(*entries):
    from types import SimpleNamespace

    return SimpleNamespace(session=SimpleNamespace(entries=list(entries)))


class TestLastSubagentPayloadByDomain:
    def test_expected_domain_agent_is_selected_over_later_foreign_one(self) -> None:
        """多子代理：外域结果在最后也不能取——旧实现取"最后一个"正是这里的 bug
        （实测 sql-002 的评分文本来自 code-diagnosis，schema §9 第 2 条）。"""

        runtime = _runtime_with(
            _entry("sql-diagnosis", "SQL 结论"),
            _entry("code-diagnosis", "code 结论"),
        )
        from cloudagent_ext.diagnosis.eval_support.execute import last_subagent_payload

        payload = last_subagent_payload(runtime, domain="sql")
        assert json.loads(payload)["agent_name"] == "sql-diagnosis"

    def test_expected_agent_absent_returns_empty_not_other_domain(self) -> None:
        """期望 agent 无结果 → 空串（调用方回退主回答），**不许退回别的域**。"""

        runtime = _runtime_with(_entry("code-diagnosis", "code 结论"))
        from cloudagent_ext.diagnosis.eval_support.execute import last_subagent_payload

        assert last_subagent_payload(runtime, domain="sql") == ""

    def test_no_subagent_results_returns_empty(self) -> None:
        from types import SimpleNamespace

        from cloudagent_ext.diagnosis.eval_support.execute import last_subagent_payload

        assert last_subagent_payload(_runtime_with(), domain="sql") == ""
        assert last_subagent_payload(SimpleNamespace(session=SimpleNamespace(entries=[])), domain="sql") == ""
        assert last_subagent_payload(None, domain="sql") == ""

    def test_empty_domain_keeps_legacy_last_any_behavior(self) -> None:
        """domain 为空 → 不过滤（旧行为），test_grade_source.py 的既有语义不破。"""

        runtime = _runtime_with(
            _entry("sql-diagnosis", "先"),
            _entry("code-diagnosis", "后"),
        )
        from cloudagent_ext.diagnosis.eval_support.execute import last_subagent_payload

        assert json.loads(last_subagent_payload(runtime))["summary"] == "后"


class TestLiveCaseRunnerMetaShape:
    """自 context/test_compaction_observability.py 迁入（T2.4，管线删除后改用假 provider
    直接驱动真引擎）：离线形态的 meta 必须带 compaction/recall 三个键（形状稳定）。"""

    def test_offline_style_meta_has_compaction_fields(self, monkeypatch) -> None:
        from types import SimpleNamespace

        from cloudagent_ext.diagnosis.eval_support.execute import LiveCaseRunner

        protocol_json = json.dumps({
            "request_id": "req-1", "agent_name": "sql-diagnosis", "status": "success",
            "summary": "s", "findings": [], "evidence": [], "root_causes": [],
            "recommendations": [], "validation_plan": [], "limitations": [], "next_steps": [],
        }, ensure_ascii=False)

        class FakeProvider:
            model = "fake"

            def chat(self, messages, tools=None, **kwargs):
                return SimpleNamespace(
                    model="fake", usage=None, finish_reason="stop",
                    tool_uses=[], content=protocol_json,
                )

            def chat_stream(self, messages, tools=None, **kwargs):
                return iter(())

            def chat_stream_response(self, *args, **kwargs):
                raise NotImplementedError

        monkeypatch.setenv("CLOUDAGENT_PROVIDER", "fake")
        runner = LiveCaseRunner(provider_factory=FakeProvider, dispatch_mode="direct")
        case = {
            "case_id": "sync-001", "domain": "sync",
            "input": {"question": "q", "context": {}},
        }
        run = runner.run_case(case)
        for key in ("compaction", "recall_count", "recall_miss"):
            assert key in run.meta, f"meta 缺 {key}"
        assert run.meta["recall_count"] == 0


class TestStatusHonesty:
    """P7c.1：状态诚实化——解析失败记 invalid_output，不再冒充 ok。

    复现口径 = breadth 2026-11-08 实测（43 例 9 例 invalid 而产品记 ok）：
    direct 模式 + 完整诊断 payload，唯一毛病是 task_id 空串。
    """

    def _direct_record(self, raw_output: str):
        return _to_record(
            FakeCaseRun(raw_output=raw_output),
            request_of(dispatch_mode="direct"),
        )

    def test_empty_task_id_marks_invalid_output(self) -> None:
        """卡面单测 1：task_id 空串 → status=invalid_output 且 error 含 task_id。"""

        payload = dict(_VALID_PROTOCOL_PAYLOAD, task_id="")
        record = self._direct_record(json.dumps(payload, ensure_ascii=False))
        assert record.outcome["status"] == "invalid_output"
        assert "task_id" in str(record.outcome["error"])

    def test_omitted_task_id_stays_ok(self) -> None:
        """卡面单测 2（正例防误杀）：省略 task_id（协议允许）→ status=ok。"""

        payload = {k: v for k, v in _VALID_PROTOCOL_PAYLOAD.items() if k != "task_id"}
        record = self._direct_record(json.dumps(payload, ensure_ascii=False))
        assert record.outcome["status"] == "ok"

    def test_filled_task_id_stays_ok(self) -> None:
        """卡面单测 3（原路径不回归）：task_id 正常回填 → status=ok。"""

        payload = dict(_VALID_PROTOCOL_PAYLOAD, task_id="task-123")
        record = self._direct_record(json.dumps(payload, ensure_ascii=False))
        assert record.outcome["status"] == "ok"

    def test_invalid_record_keeps_raw_output(self) -> None:
        """卡面单测 4：invalid 记录必须保留 raw_output（诊断内容别丢）。"""

        payload = dict(_VALID_PROTOCOL_PAYLOAD, task_id="")
        raw = json.dumps(payload, ensure_ascii=False)
        record = self._direct_record(raw)
        assert record.outcome["status"] == "invalid_output"
        assert len(record.outcome["raw_output"]) > 0
        assert record.outcome["raw_output"] == raw

    def test_main_mode_subagent_payload_still_ok(self) -> None:
        """main 模式（fidelity 主路径）不回归：合法子代理 payload 仍 ok。"""

        record = _to_record(
            FakeCaseRun(raw_output=json.dumps(_VALID_PROTOCOL_PAYLOAD, ensure_ascii=False),
                        meta={"grade_source": "subagent"}),
            request_of(dispatch_mode="main"),
        )
        assert record.outcome["status"] == "ok"

    def test_prose_raw_output_now_invalid(self) -> None:
        """反向条件：散文输出（非协议 JSON）也如实记 invalid_output——
        与评测仓对 raw_output 的解析口径一致，不是只针对 task_id。"""

        record = self._direct_record("这是一段散文结论，没有协议 JSON。")
        assert record.outcome["status"] == "invalid_output"
        assert "协议解析失败" in str(record.outcome["error"])


class TestKnowledgeProvisioning:
    """P8-B4：eval-run 装配必须走 knowledge-aware 路径（本次 3.46M 无效真跑的防线）。

    事故：2026-11-08 L3 KB=on/off 两臂真跑，两臂 search_knowledge 调用数都是 0——
    execute.py 直接调 register_sql_diagnosis_tools，只装域工具，不装知识库检索。
    生产路径（agent/_bundled_agents/*.py 的 provision_tools）走的是
    provision_with_knowledge，eval-run 必须一致，否则 KB 开关是死的。
    """

    @staticmethod
    def _agent_tool_names(monkeypatch, kb: str) -> list[str]:
        """复用生产装配链（与 execute.py 的 _configure_executor 同一组调用）。"""

        from cloudagent_ext.agent import ensure_bundled_agents_registered
        from cloudagent_ext.agent._bundled_agents import sql_diagnosis
        from cloudagent_ext.agent.agent_tool_utils import resolve_agent_tools
        from cloudagent_ext.agent.registry import AgentRegistry
        from cloudagent_ext.diagnosis.knowledge.provision import provision_with_knowledge
        from cloudagent_ext.tool_system.defaults import build_default_registry

        monkeypatch.setenv("CLOUDAGENT_KB_ENABLED", kb)
        ensure_bundled_agents_registered()
        registry = build_default_registry(provider=None, load_agent_tools=False)
        assert provision_with_knowledge(sql_diagnosis.register_sql_diagnosis_tools, registry)
        agent_def = AgentRegistry.find("sql-diagnosis")
        resolved = resolve_agent_tools(agent_def, registry.list_tools(), is_async=False)
        return [tool.name for tool in resolved.resolved_tools]

    def test_kb_enabled_registers_search_knowledge(self, monkeypatch) -> None:
        """KB=on → 子代理工具集含 search_knowledge（本次事故的直接断言）。"""

        names = self._agent_tool_names(monkeypatch, "on")
        assert "search_knowledge" in names, (
            "KB=on 时子代理没拿到 search_knowledge —— eval-run 装配走了非 knowledge-aware 路径"
        )

    def test_kb_disabled_does_not_register(self, monkeypatch) -> None:
        """反向条件：KB=off → 不含（否则开关是死的，两臂对照无意义）。"""

        names = self._agent_tool_names(monkeypatch, "off")
        assert "search_knowledge" not in names

    def test_main_mode_agent_excludes_search_knowledge(self, monkeypatch) -> None:
        """main 模式主 Agent 只派发，不该拿到 search_knowledge（能力归子代理）。"""

        from cloudagent_ext.agent._bundled_agents import sql_diagnosis
        from cloudagent_ext.diagnosis.knowledge.provision import provision_with_knowledge
        from cloudagent_ext.tool_system.defaults import build_default_registry

        monkeypatch.setenv("CLOUDAGENT_KB_ENABLED", "on")
        registry = build_default_registry(provider=None, load_agent_tools=True)
        assert provision_with_knowledge(sql_diagnosis.register_sql_diagnosis_tools, registry)

        allowed = {"Agent", "Read", "Grep", "Glob", "Skill", "TodoWrite"}
        main_tools = [t.name for t in registry.list_tools() if t.name in allowed]
        assert "search_knowledge" not in main_tools
        # 但 registry 里必须有（子代理用）
        assert registry.get("search_knowledge") is not None
