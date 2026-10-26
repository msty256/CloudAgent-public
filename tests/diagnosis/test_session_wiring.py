#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""会话接线测试（变更 wire-investigation-session）。

覆盖：会话按上下文隔离、委派记账（成功/解析失败/标识归一化）、非诊断委派
只占预算、异步与同步的协议校验块一致、``/tasks`` 轨迹展示。
"""

from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from cloudagent_ext.agent._bundled_agents.sql_diagnosis import (
    _augment_diagnosis_result,
    augment_agent_text,
)
from cloudagent_ext.command_system.tasks_command import TASKS_COMMAND, build_sections
from cloudagent_ext.diagnosis.runtime_session import (
    begin_delegation,
    finish_delegation,
    get_or_create_runtime,
    is_diagnosis_agent,
    reset_session,
)
from cloudagent_ext.diagnosis.session import DiagnosisSessionError, SessionBudget


def _context() -> SimpleNamespace:
    """最小上下文：只需要会话字段（真实 ToolContext 是 slots dataclass）。"""

    return SimpleNamespace(diagnosis_session_runtime=None)


def _result_text(request_id: str = "r", *, with_task_id: bool = False, status: str = "success") -> str:
    payload = {
        "request_id": request_id,
        "agent_name": "code-diagnosis",
        "status": status,
        "summary": "结论",
        "findings": [],
        "evidence": [],
        "root_causes": [],
        "recommendations": [],
        "validation_plan": [],
        "limitations": [],
        "next_steps": [],
    }
    if with_task_id:
        payload["task_id"] = "t-1"
    return "分析如下\n```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"


class TestRuntimeBinding:
    def test_same_context_reuses_runtime(self) -> None:
        ctx = _context()
        assert get_or_create_runtime(ctx) is get_or_create_runtime(ctx)

    def test_different_contexts_are_isolated(self) -> None:
        rt_a, rt_b = get_or_create_runtime(_context()), get_or_create_runtime(_context())
        assert rt_a is not None and rt_b is not None
        assert rt_a.session.request_id != rt_b.session.request_id

    def test_reset_clears_session(self) -> None:
        ctx = _context()
        rt = get_or_create_runtime(ctx)
        begin_delegation(rt, "sql-diagnosis", "查索引")
        reset_session(ctx)
        assert get_or_create_runtime(ctx).session.delegations_used == 0

    def test_concurrent_creation_yields_one_runtime(self) -> None:
        import threading

        ctx = _context()
        seen: list[object] = []

        def worker() -> None:
            seen.append(get_or_create_runtime(ctx))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len({id(item) for item in seen}) == 1

    def test_none_context_is_safe(self) -> None:
        assert get_or_create_runtime(None) is None
        assert begin_delegation(None, "sql-diagnosis", "x") is None
        assert finish_delegation(None, None, "x") == "skipped"


class TestDelegationLedger:
    def test_diagnosis_delegation_is_recorded(self) -> None:
        rt = get_or_create_runtime(_context())
        task = begin_delegation(rt, "code-diagnosis", "查分派")
        assert task is not None
        assert finish_delegation(rt, task, _result_text(rt.session.request_id)) == "completed"
        entries = rt.session.entries
        assert len(entries) == 1
        assert entries[0].status == "completed"

    def test_task_id_is_injected_when_missing(self) -> None:
        rt = get_or_create_runtime(_context())
        task = begin_delegation(rt, "code-diagnosis", "查分派")
        assert finish_delegation(rt, task, _result_text(rt.session.request_id)) == "completed"
        assert rt.session.entries[0].result is not None
        assert rt.session.entries[0].result.task_id == task.task_id

    def test_request_id_is_normalized_not_failed(self) -> None:
        rt = get_or_create_runtime(_context())
        task = begin_delegation(rt, "code-diagnosis", "查分派")
        # 模型回显了错误的 request_id：应纠正后入账，而不是记 failure
        assert finish_delegation(rt, task, _result_text("wrong-id", with_task_id=True)) == "completed"
        assert rt.session.entries[0].status == "completed"

    def test_parse_failure_recorded_as_failed(self) -> None:
        rt = get_or_create_runtime(_context())
        task = begin_delegation(rt, "code-diagnosis", "查分派")
        assert finish_delegation(rt, task, "没有 JSON 的自由文本") == "failed"
        assert rt.session.entries[0].status == "failed"
        assert rt.session.entries[0].failure_reason

    def test_non_diagnosis_counts_but_stays_out_of_trace(self) -> None:
        rt = get_or_create_runtime(_context())
        assert begin_delegation(rt, "Explore", "找文件") is None
        assert rt.session.entries == ()
        assert rt.other_delegations == {"Explore": 1}
        assert rt.total_delegations == 1

    def test_non_diagnosis_shares_budget(self) -> None:
        # 显式预算：本用例测的是"单 Agent 上限生效"，不该被默认值变化牵连
        rt = get_or_create_runtime(_context(), budget=SessionBudget(6, 3))
        for index in range(3):
            begin_delegation(rt, "Explore", f"找文件-{index}")
        with pytest.raises(DiagnosisSessionError, match="budget exhausted for agent"):
            begin_delegation(rt, "Explore", "找文件-又找")

    def test_is_diagnosis_agent(self) -> None:
        assert is_diagnosis_agent("sql-diagnosis")
        assert not is_diagnosis_agent("Explore")
        assert not is_diagnosis_agent(None)


@dataclass
class _Block:
    text: str


class TestAugmentationParity:
    def test_text_level_augment_matches_result_level(self) -> None:
        text = _result_text("r-1")
        # 同步路径：结果级后处理
        sync_result = SimpleNamespace(
            is_error=False,
            output={"content": [{"type": "text", "text": text}]},
        )
        agent_def = SimpleNamespace(agent_type="code-diagnosis")
        _augment_diagnosis_result(sync_result, agent_def, domain_label="code")
        sync_block = sync_result.output["content"][-1]["text"]

        # 异步路径：文本级后处理
        async_text = augment_agent_text(text, "code-diagnosis")
        async_block = async_text[len(text):]

        assert sync_block == async_block
        assert "校验：passed" in async_block

    def test_non_diagnosis_text_untouched(self) -> None:
        assert augment_agent_text("hello", "general-purpose") == "hello"

    def test_failed_block_on_unparsable_text(self) -> None:
        out = augment_agent_text("no json here", "sql-diagnosis")
        assert "校验：FAILED" in out


class _Registry:
    def all(self):
        return []


class TestTasksRendering:
    def _run(self, ctx) -> str:
        command_context = SimpleNamespace(tool_context=ctx)
        outcome = asyncio.run(TASKS_COMMAND.run("", command_context))
        return outcome.message

    def test_shows_session_block(self) -> None:
        rt = get_or_create_runtime(_context())
        task = begin_delegation(rt, "sql-diagnosis", "定位订单表索引缺失")
        finish_delegation(rt, task, _result_text(rt.session.request_id))
        ctx = SimpleNamespace(runtime_tasks=_Registry(), diagnosis_session_runtime=rt)
        message = self._run(ctx)
        assert "诊断会话" in message
        assert "sql-diagnosis" in message
        assert "completed" in message

    def test_no_block_when_no_entries(self) -> None:
        rt = get_or_create_runtime(_context())
        ctx = SimpleNamespace(runtime_tasks=_Registry(), diagnosis_session_runtime=rt)
        assert self._run(ctx) == "No background tasks."

    def test_build_sections_is_shared_with_repl(self) -> None:
        """REPL 的 /tasks 走自己的渲染路径，必须复用 build_sections 才看得到轨迹。"""

        rt = get_or_create_runtime(_context())
        task = begin_delegation(rt, "sql-diagnosis", "定位索引缺失")
        finish_delegation(rt, task, _result_text(rt.session.request_id))
        ctx = SimpleNamespace(runtime_tasks=_Registry(), diagnosis_session_runtime=rt)
        sections = build_sections(ctx)
        assert any("诊断会话" in section for section in sections)

    def test_rendering_is_read_only(self) -> None:
        rt = get_or_create_runtime(_context())
        task = begin_delegation(rt, "sql-diagnosis", "目标")
        finish_delegation(rt, task, _result_text(rt.session.request_id))
        ctx = SimpleNamespace(runtime_tasks=_Registry(), diagnosis_session_runtime=rt)
        before = rt.session.delegations_used
        self._run(ctx)
        self._run(ctx)
        assert rt.session.delegations_used == before


class TestEndToEndWiring:
    """脚本化 provider 跑一次真实派发，确认 Agent 工具确实写进了会话账本。"""

    def test_agent_tool_records_delegation(self, tmp_path) -> None:
        from cloudagent_ext.providers.base import ChatResponse
        from cloudagent_ext.query.agent_loop_compat import run_query_as_agent_loop
        from cloudagent_ext.tool_system.context import ToolContext
        from cloudagent_ext.tool_system.defaults import build_default_registry
        from cloudagent_ext.types.messages import UserMessage

        model = "fake-wiring"
        usage = {"input_tokens": 3, "output_tokens": 3}

        def _text(content: str) -> ChatResponse:
            return ChatResponse(
                content=content,
                model=model,
                usage=dict(usage),
                finish_reason="stop",
                tool_uses=None,
            )

        class _Provider:
            def __init__(self, responses: list[ChatResponse]) -> None:
                self._responses = list(responses)
                self.calls: list[list] = []
                self.model = model

            def chat(self, messages, tools=None, **kwargs):
                self.calls.append(messages)
                index = len(self.calls) - 1
                if index < len(self._responses):
                    return self._responses[index]
                return _text("(unexpected extra call)")

            def chat_stream(self, messages, tools=None, **kwargs):
                return iter(())

        provider = _Provider(
            [
                # 主 Agent：派发一次代码诊断
                ChatResponse(
                    content="",
                    model=model,
                    usage=dict(usage),
                    finish_reason="tool_use",
                    tool_uses=[
                        {
                            "id": "call_1",
                            "name": "Agent",
                            "input": {
                                "description": "code diagnosis",
                                "prompt": "确认 _AUGMENTERS 覆盖哪些域",
                                "subagent_type": "code-diagnosis",
                            },
                        }
                    ],
                ),
                # 子 Agent：给出符合协议的结论（不带 task_id，验证工具补齐）
                _text(_result_text("code-diagnosis-20261020-000000")),
                # 主 Agent：收尾
                _text("结论：三域已覆盖。"),
            ]
        )

        registry = build_default_registry(provider=provider, load_agent_tools=False)
        context = ToolContext(workspace_root=tmp_path)
        context.tool_registry = registry

        result = asyncio.run(
            run_query_as_agent_loop(
                initial_messages=[UserMessage(content="确认 _AUGMENTERS 的覆盖范围")],
                provider=provider,
                tool_registry=registry,
                tool_context=context,
                system_prompt="You are the CloudAgent main agent (deterministic offline test mode).",
                max_turns=6,
                on_event=lambda _event: None,
            )
        )
        assert result.terminal is not None and result.terminal.reason == "completed"

        runtime = context.diagnosis_session_runtime
        assert runtime is not None, "Agent 工具应把会话绑到 ToolContext 上"
        entries = runtime.session.entries
        assert len(entries) == 1, f"expected 1 ledger entry, got {len(entries)}"
        entry = entries[0]
        assert entry.task.agent_type == "code-diagnosis"
        assert entry.status == "completed", entry.failure_reason
        assert entry.result is not None
        # 工具补齐 task_id：入账结果必须能指回本次委派
        assert entry.result.task_id == entry.task.task_id


class TestTotalBudgetAcrossPaths:
    """实现审查 P1-1：总预算 6 必须在「诊断 + 非诊断」混合场景下严格生效。

    旧实现的诊断分支直接调 ``session.delegate()``，而它只数轨迹里的诊断条目，
    看不到 ``other_delegations``，导致 3 非诊断 + 3 诊断之后第 7 次被放行。
    """

    def _runtime(self):
        # 显式 6/3：本类断言的是"总预算语义"，与默认值解耦
        return get_or_create_runtime(_context(), budget=SessionBudget(6, 3))

    def _fill(self, rt) -> None:
        for index in range(3):
            begin_delegation(rt, "general-purpose", f"g-{index}")
        for index in range(3):
            begin_delegation(rt, "code-diagnosis", f"d-{index}")

    def test_mixed_budget_rejects_seventh_diagnosis(self) -> None:
        rt = self._runtime()
        self._fill(rt)
        assert rt.total_delegations == 6
        with pytest.raises(DiagnosisSessionError, match="budget exhausted: 6/6"):
            begin_delegation(rt, "sql-diagnosis", "seventh")

    def test_mixed_budget_rejects_seventh_non_diagnosis(self) -> None:
        rt = self._runtime()
        self._fill(rt)
        with pytest.raises(DiagnosisSessionError, match="budget exhausted: 6/6"):
            begin_delegation(rt, "Explore", "seventh")

    def test_reverse_order_also_capped(self) -> None:
        rt = self._runtime()
        for index in range(3):
            begin_delegation(rt, "log-diagnosis", f"d-{index}")
        for index in range(3):
            begin_delegation(rt, "Plan", f"p-{index}")
        assert rt.total_delegations == 6
        with pytest.raises(DiagnosisSessionError, match="budget exhausted: 6/6"):
            begin_delegation(rt, "code-diagnosis", "seventh")

    def test_failed_reservation_does_not_consume_budget(self) -> None:
        rt = self._runtime()
        self._fill(rt)
        for _ in range(3):
            with pytest.raises(DiagnosisSessionError):
                begin_delegation(rt, "sql-diagnosis", "seventh")
        assert rt.total_delegations == 6


class TestBudgetConfig:
    """变更 make-diagnosis-budget-configurable：默认 15/5，环境变量可覆盖。"""

    def _clear(self, monkeypatch) -> None:
        monkeypatch.delenv("CLOUDAGENT_DIAGNOSIS_MAX_DELEGATIONS", raising=False)
        monkeypatch.delenv("CLOUDAGENT_DIAGNOSIS_MAX_DELEGATIONS_PER_AGENT", raising=False)

    def test_defaults_when_unset(self, monkeypatch) -> None:
        from cloudagent_ext.diagnosis.runtime_session import default_budget

        self._clear(monkeypatch)
        budget = default_budget()
        assert budget.max_delegations == 15
        assert budget.max_delegations_per_agent == 5

    def test_session_uses_defaults(self, monkeypatch) -> None:
        self._clear(monkeypatch)
        rt = get_or_create_runtime(_context())
        assert rt.session.budget.max_delegations == 15
        assert rt.session.budget.max_delegations_per_agent == 5

    def test_env_override(self, monkeypatch) -> None:
        from cloudagent_ext.diagnosis.runtime_session import default_budget

        monkeypatch.setenv("CLOUDAGENT_DIAGNOSIS_MAX_DELEGATIONS", "20")
        monkeypatch.setenv("CLOUDAGENT_DIAGNOSIS_MAX_DELEGATIONS_PER_AGENT", "7")
        budget = default_budget()
        assert (budget.max_delegations, budget.max_delegations_per_agent) == (20, 7)

    @pytest.mark.parametrize("bad", ["abc", "0", "-3", "99999"])
    def test_invalid_values_fall_back_with_warning(self, monkeypatch, caplog, bad: str) -> None:
        import logging

        from cloudagent_ext.diagnosis.runtime_session import default_budget

        self._clear(monkeypatch)
        monkeypatch.setenv("CLOUDAGENT_DIAGNOSIS_MAX_DELEGATIONS", bad)
        with caplog.at_level(logging.WARNING, logger="cloudagent.diagnosis.session"):
            budget = default_budget()
        assert budget.max_delegations == 15
        assert any("CLOUDAGENT_DIAGNOSIS_MAX_DELEGATIONS" in rec.message for rec in caplog.records)

    def test_read_at_session_creation_not_import(self, monkeypatch) -> None:
        """配置在启动阶段注入：读取必须发生在建会话时。"""

        self._clear(monkeypatch)
        first = get_or_create_runtime(_context())
        assert first.session.budget.max_delegations == 15

        monkeypatch.setenv("CLOUDAGENT_DIAGNOSIS_MAX_DELEGATIONS", "20")
        second = get_or_create_runtime(_context())
        assert second.session.budget.max_delegations == 20
        assert first.session.budget.max_delegations == 15  # 已建会话不受影响

    def test_tasks_shows_configured_denominator(self, monkeypatch) -> None:
        self._clear(monkeypatch)
        monkeypatch.setenv("CLOUDAGENT_DIAGNOSIS_MAX_DELEGATIONS", "20")
        rt = get_or_create_runtime(_context())
        begin_delegation(rt, "sql-diagnosis", "查索引")
        ctx = SimpleNamespace(runtime_tasks=_Registry(), diagnosis_session_runtime=rt)
        message = asyncio.run(TASKS_COMMAND.run("", SimpleNamespace(tool_context=ctx))).message
        assert "已用 1/20" in message


class _RoutingProvider:
    """按消息内容路由的脚本化 provider。

    异步派发把子代理放到**另一个线程**里跑，按调用顺序返回响应会与主循环竞态；
    这里改成"看消息里有什么"决定返回哪一档，与调度顺序无关。
    """

    _MODEL = "fake-wiring"
    _USAGE = {"input_tokens": 3, "output_tokens": 3}

    def __init__(self, protocol_text: str) -> None:
        self._protocol_text = protocol_text
        self.model = self._MODEL
        self.calls: list[list] = []
        self._dispatched = False
        self._lock = threading.Lock()

    def _text(self, content: str):
        from cloudagent_ext.providers.base import ChatResponse

        return ChatResponse(
            content=content,
            model=self._MODEL,
            usage=dict(self._USAGE),
            finish_reason="stop",
            tool_uses=None,
        )

    def chat(self, messages, tools=None, **kwargs):
        from cloudagent_ext.providers.base import ChatResponse

        self.calls.append(messages)
        joined = "\n".join(_message_text(m) for m in messages)
        if "调查任务（" in joined:  # 子代理：提示里带调查任务头 → 回协议 JSON
            return self._text(self._protocol_text)
        with self._lock:
            if not self._dispatched:
                self._dispatched = True
                return ChatResponse(
                    content="",
                    model=self._MODEL,
                    usage=dict(self._USAGE),
                    finish_reason="tool_use",
                    tool_uses=[
                        {
                            "id": "call_async_1",
                            "name": "Agent",
                            "input": {
                                "description": "code diagnosis",
                                "prompt": "确认 _AUGMENTERS 覆盖哪些域",
                                "subagent_type": "code-diagnosis",
                                "run_in_background": True,
                            },
                        }
                    ],
                )
        return self._text("结论：三域已覆盖。")

    def chat_stream(self, messages, tools=None, **kwargs):
        return iter(())


def _message_text(message) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        return str(content)


class TestAsyncDelegation:
    """异步完成路径（变更 harden-diagnosis-session-acceptance）。

    ``complete_agent_task`` 是 ``agent.py`` 的**函数内局部 import**，所以 patch 点必须
    是源头模块 ``cloudagent_ext.tasks.local_agent``，不是 ``agent`` 模块。
    """

    def _run(self, tmp_path, monkeypatch):
        from cloudagent_ext.agent._bundled_agents import sql_diagnosis
        from cloudagent_ext.query.agent_loop_compat import run_query_as_agent_loop
        from cloudagent_ext.tasks import local_agent
        from cloudagent_ext.tool_system.context import ToolContext
        from cloudagent_ext.tool_system.defaults import build_default_registry
        from cloudagent_ext.types.messages import UserMessage

        provider = _RoutingProvider(_result_text("code-diagnosis-20261021-000000"))
        registry = build_default_registry(provider=provider, load_agent_tools=False)
        context = ToolContext(workspace_root=tmp_path)
        context.tool_registry = registry

        from cloudagent_ext.tool_system.tools import agent as agent_module

        done = threading.Event()
        captured: dict = {}

        # 负向证据：finish_delegation 拿到的是"后处理之前"的文本（它在 augment 之前被调用），
        # 记录它即可证明校验块是 augment 步骤加的，而不是子代理自己带的。
        # 注意不能 patch sql_diagnosis.augment_agent_text：ensure_bundled_agents_registered()
        # 会 reload 该模块（agent/__init__.py:84），补丁会在运行中被冲掉。
        original_finish = agent_module.finish_delegation

        def finish_wrapper(runtime, task, text):
            captured["pre_augment_text"] = text
            return original_finish(runtime, task, text)

        monkeypatch.setattr(agent_module, "finish_delegation", finish_wrapper)


        original = local_agent.complete_agent_task

        def wrapper(task_id, *, result_text, registry=None):
            runtime = context.diagnosis_session_runtime
            captured["text"] = result_text
            captured["entries"] = tuple(runtime.session.entries) if runtime is not None else ()
            done.set()
            return original(task_id, result_text=result_text, registry=registry)

        monkeypatch.setattr(local_agent, "complete_agent_task", wrapper)
        # P2-1：patch 必须真的装到源头模块上，否则后面的断言全是空跑
        assert local_agent.complete_agent_task is wrapper

        asyncio.run(
            run_query_as_agent_loop(
                initial_messages=[UserMessage(content="确认 _AUGMENTERS 的覆盖范围")],
                provider=provider,
                tool_registry=registry,
                tool_context=context,
                system_prompt="You are the CloudAgent main agent (deterministic offline test mode).",
                max_turns=6,
                on_event=lambda _event: None,
            )
        )
        # 后台子代理跑在独立线程（context.task_manager.start），用 threading.Event 等待
        assert done.wait(15), "后台子代理未在 15s 内完成"
        return context.diagnosis_session_runtime, captured

    def test_result_is_recorded_with_protocol_block(self, tmp_path, monkeypatch) -> None:
        runtime, captured = self._run(tmp_path, monkeypatch)

        assert runtime is not None, "Agent 工具应把会话绑到 ToolContext 上"
        assert "diagnosis-protocol 校验：" in captured["text"]

        entries = runtime.session.entries
        assert len(entries) == 1
        assert entries[0].status == "completed", entries[0].failure_reason
        assert entries[0].result is not None
        assert entries[0].result.task_id == entries[0].task.task_id

    def test_ledger_is_recorded_before_completion_hook(self, tmp_path, monkeypatch) -> None:
        _, captured = self._run(tmp_path, monkeypatch)
        # 顺序断言：钩子被调用时账本必须已经写入（finish_delegation 在 complete 之前）
        at_call = captured["entries"]
        assert len(at_call) == 1
        assert at_call[0].status == "completed"

    def test_block_is_added_after_the_raw_result(self, tmp_path, monkeypatch) -> None:
        """负向证据：子代理原始文本里没有校验块，块是后处理步骤加的。

        `finish_delegation` 在 augment 之前被调用，所以它收到的文本就是"原始结果"；
        与 `complete_agent_task` 收到的文本对比，即可证明块确实由后处理产生。
        """

        _, captured = self._run(tmp_path, monkeypatch)
        assert "diagnosis-protocol 校验：" not in captured["pre_augment_text"]
        assert "diagnosis-protocol 校验：" in captured["text"]


class TestBudgetExhaustion:
    """预算耗尽后：拒绝必须是结构化的，且已有轨迹不被破坏。"""

    def _setup(self):
        rt = get_or_create_runtime(_context(), budget=SessionBudget(2, 2))
        for index, label in enumerate(("第一次", "第二次")):
            task = begin_delegation(rt, "code-diagnosis", f"{label}调查-{index}")
            finish_delegation(rt, task, _result_text(rt.session.request_id))
        return rt

    def test_rejection_is_structured(self) -> None:
        rt = self._setup()
        with pytest.raises(DiagnosisSessionError, match="budget exhausted: 2/2"):
            begin_delegation(rt, "sql-diagnosis", "第三次")

    def test_entries_unchanged_after_rejection(self) -> None:
        rt = self._setup()
        before = [
            (e.task.task_id, e.task.agent_type, e.status, e.failure_reason, id(e.result))
            for e in rt.session.entries
        ]
        with pytest.raises(DiagnosisSessionError):
            begin_delegation(rt, "sql-diagnosis", "第三次")
        after = [
            (e.task.task_id, e.task.agent_type, e.status, e.failure_reason, id(e.result))
            for e in rt.session.entries
        ]
        assert after == before

    def test_tasks_view_still_shows_prior_trace(self) -> None:
        rt = self._setup()
        with pytest.raises(DiagnosisSessionError):
            begin_delegation(rt, "sql-diagnosis", "第三次")
        ctx = SimpleNamespace(runtime_tasks=_Registry(), diagnosis_session_runtime=rt)
        message = asyncio.run(TASKS_COMMAND.run("", SimpleNamespace(tool_context=ctx))).message
        assert "诊断会话" in message
        assert message.count("[completed]") == 2


class TestRecordFailureIsolation:
    """记账异常不得阻断派发（旁路账本定位）。"""

    def test_record_result_failure_does_not_raise(self) -> None:
        rt = get_or_create_runtime(_context())
        task = begin_delegation(rt, "code-diagnosis", "查分派")

        def _boom(_result):
            raise RuntimeError("boom")

        rt.session.record_result = _boom  # type: ignore[method-assign]
        assert finish_delegation(rt, task, _result_text(rt.session.request_id)) == "failed"
        assert rt.session.entries[0].status == "failed"

    def test_double_failure_is_swallowed(self) -> None:
        rt = get_or_create_runtime(_context())
        task = begin_delegation(rt, "code-diagnosis", "查分派")

        def _boom_result(_result):
            raise RuntimeError("record_result boom")

        def _boom_failure(_task_id, *, reason):
            raise RuntimeError("record_failure boom")

        rt.session.record_result = _boom_result  # type: ignore[method-assign]
        rt.session.record_failure = _boom_failure  # type: ignore[method-assign]
        # 不抛，且返回 failed
        assert finish_delegation(rt, task, _result_text(rt.session.request_id)) == "failed"



class TestTruncatedLedgerRecovery:
    """长报告被截断时，入账不得误判为解析失败（实测出现过"块 passed 而账本 failed"）。"""

    def _transcript(self, tmp_path: pathlib.Path, text: str) -> pathlib.Path:
        path = tmp_path / "sub.jsonl"
        payload = {"role": "assistant", "content": [{"type": "text", "text": text}]}
        path.write_text(json.dumps(payload, ensure_ascii=False) + chr(10), encoding="utf-8")
        return path

    def test_recovers_full_text_from_transcript(self, tmp_path) -> None:
        from cloudagent_ext.tool_system.tools.agent import _ledger_text

        full = _result_text("r-full")
        transcript = self._transcript(tmp_path, full)
        truncated = full[:20] + chr(10) + "[truncated: showing first 20 + last 10 chars]"
        result = SimpleNamespace(
            output={
                "content": [{"type": "text", "text": truncated}],
                "transcript_path": str(transcript),
            }
        )
        recovered = _ledger_text(result)
        assert "```json" in recovered
        assert "truncated:" not in recovered

    def test_ledger_records_completed_with_recovered_text(self, tmp_path) -> None:
        from cloudagent_ext.tool_system.tools.agent import _ledger_text

        rt = get_or_create_runtime(_context())
        task = begin_delegation(rt, "code-diagnosis", "定位 _AUGMENTERS")
        full = _result_text(rt.session.request_id)
        transcript = self._transcript(tmp_path, full)
        result = SimpleNamespace(
            output={
                "content": [{"type": "text", "text": full[:15] + "[truncated: x]"}],
                "transcript_path": str(transcript),
            }
        )
        status = finish_delegation(rt, task, _ledger_text(result))
        assert status == "completed", rt.session.entries[0].failure_reason

    def test_falls_back_to_truncated_text_without_transcript(self) -> None:
        from cloudagent_ext.tool_system.tools.agent import _ledger_text

        result = SimpleNamespace(
            output={"content": [{"type": "text", "text": "a [truncated: x]"}]}
        )
        assert _ledger_text(result) == "a [truncated: x]"
