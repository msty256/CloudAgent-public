#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""主 Agent → Agent tool → sql-diagnosis 子会话 → 工具 → 结果校验 全链路离线验证（P2.8）。

复用设施：P2.4 的脚本化 provider（``_ScriptedProvider``）、真实 ToolRegistry、
``make_agent_tool`` 工厂（注入 fake provider 与真实工具池）。

覆盖：
1. 成功链（模拟工具结果 → 合法协议 → 结构化校验块 passed）；
2. 协议无效 → 校验块 FAILED（安全降级，不吞错）；
3. 工具失败（无 DSN）→ 子会话部分降级 → 协议仍合法；
4. 白名单外工具（Write）在执行边界被拒（副作用断言：文件未产生）；
5. 权限语义（resolve_permission_mode：agent 声明 dontAsk 覆盖 default 父模式）；
6. 不误派静态面（可见性 + 描述质量）+ 子会话模型故障安全处理。

全程离线：无模型 API Key、无真实数据库（工具结果以 monkeypatch 模拟，
测试 docstring 与断言中明确区分"模拟结果"与"真实执行证据"）。
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import pytest

pytest.importorskip("psycopg")
pytest.importorskip("sqlglot")

from cloudagent_ext.agent._bundled_agents import sql_diagnosis
from cloudagent_ext.agent.load_agents_dir import get_agent_definitions_with_overrides
from cloudagent_ext.agent.run_agent import resolve_permission_mode
from cloudagent_ext.permissions.types import ToolPermissionContext
from cloudagent_ext.providers.base import ChatResponse
from cloudagent_ext.tool_system.context import ToolContext
from cloudagent_ext.tool_system.defaults import build_default_registry
from cloudagent_ext.tool_system.tools.agent import make_agent_tool

from tests.diagnosis.test_sql_agent_delegation import _ScriptedProvider

_MODEL = "fake-main-agent-integration"

_VALID_RESULT = {
    "request_id": "itg-1",
    "task_id": "itg-task",
    "agent_name": "sql-diagnosis",
    "skill_name": "sql-optimization",
    "status": "success",
    "summary": "orders.tenant_id 缺索引，查询退化为全表扫描",
    "findings": ["Seq Scan on orders"],
    "evidence": [
        {
            "evidence_id": "E1",
            "source_type": "get_schema",
            "source_ref": "public.orders",
            "observation": "orders 含 tenant_id 列",
        }
    ],
    "root_causes": [
        {
            "description": "tenant_id 无索引导致全表扫描",
            "confidence": 0.8,
            "supporting_evidence_ids": ["E1"],
            "counter_evidence": [],
        }
    ],
    "recommendations": ["为 orders(tenant_id) 建索引"],
    "validation_plan": [],
    "limitations": [],
    "next_steps": [],
}


def _final_text(payload: dict) -> str:
    return "分析如下：\n\n```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"


def _tool_use(name: str, tool_input: dict, tool_use_id: str) -> ChatResponse:
    return ChatResponse(
        content="",
        model=_MODEL,
        usage={"input_tokens": 1, "output_tokens": 1},
        finish_reason="tool_calls",
        tool_uses=[{"id": tool_use_id, "name": name, "input": tool_input}],
    )


def _final_response(payload: dict) -> ChatResponse:
    return ChatResponse(
        content=_final_text(payload),
        model=_MODEL,
        usage={"input_tokens": 1, "output_tokens": 1},
        finish_reason="stop",
        tool_uses=None,
    )


def _make_context(workspace_root: Path) -> ToolContext:
    # 父会话 = default 模式；sql-diagnosis 定义声明的 dontAsk 覆盖之（P2.8）
    return ToolContext(
        workspace_root=workspace_root,
        permission_context=ToolPermissionContext(mode="default"),
    )


def _run_agent_tool(
    context: ToolContext,
    provider,
    prompt: str = "慢查询诊断：SELECT * FROM orders WHERE tenant_id = 7",
):
    # 注意：不手动装配 DB 工具——由 runtime 的 provision_tools 接缝在
    # spawn 前完成（fix-sql-diagnosis-tool-provisioning：测试必须驱动
    # 真实路径，见 test_real_path_provisioning）。
    registry = build_default_registry(load_agent_tools=False)
    tool = make_agent_tool(registry, provider=provider)
    return tool.call(
        {"subagent_type": "sql-diagnosis", "prompt": prompt, "description": "SQL diagnosis"},
        context,
    ), registry


def _result_texts(result) -> list[str]:
    content = (result.output or {}).get("content") or []
    return [str(block.get("text") or "") for block in content if isinstance(block, dict)]


class TestSuccessChain:
    def test_full_chain_with_mocked_tool_and_valid_protocol(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 模拟工具结果（非真实数据库证据——测试事实，docstring 已声明）
        @contextmanager
        def _fake_session(dsn=None):  # noqa: ANN001
            yield object()

        monkeypatch.setattr("cloudagent_ext.diagnosis.db.tools.db_session", _fake_session)
        # 元数据工具现在先 resolve_dsn(target) 再建会话（extend-db-tools-target）；
        # 离线用例没有 DSN，这里一并打桩，避免落到 secondary_dsn_not_configured。
        monkeypatch.setattr(
            "cloudagent_ext.diagnosis.db.tools.resolve_dsn",
            lambda target="primary": f"dsn:{target}",
        )
        monkeypatch.setattr(
            "cloudagent_ext.diagnosis.db.tools.postgres.fetch_schema",
            lambda conn, schema="public", table=None: {
                "schema": schema,
                "table": table,
                "columns": [{"name": "id", "type": "bigint", "nullable": False, "default": None}],
                "primary_key": ["id"],
            },
        )

        provider = _ScriptedProvider(
            [
                _tool_use("Skill", {"skill": "sql-optimization"}, "t1"),
                _tool_use("get_schema", {"table": "orders"}, "t2"),
                _final_response(_VALID_RESULT),
            ]
        )
        result, _registry = _run_agent_tool(_make_context(tmp_path), provider)
        assert result.is_error is False
        assert result.output["agent_type"] == "sql-diagnosis"
        assert result.output["status"] == "completed"

        texts = _result_texts(result)
        assert any("diagnosis-protocol 校验：passed" in t for t in texts), texts
        joined = "\n".join(texts)
        assert "引用校验：通过" in joined
        assert "候选根因" in joined
        assert "不得直接升级为已确认事实" in joined

    def test_invalid_protocol_degrades_safely(self, tmp_path: Path) -> None:
        provider = _ScriptedProvider(
            [
                ChatResponse(
                    content="这是一段没有任何协议 JSON 的最终输出。",
                    model=_MODEL,
                    usage={"input_tokens": 1, "output_tokens": 1},
                    finish_reason="stop",
                    tool_uses=None,
                )
            ]
        )
        result, _registry = _run_agent_tool(_make_context(tmp_path), provider)
        texts = _result_texts(result)
        assert any("diagnosis-protocol 校验：FAILED" in t for t in texts), texts
        assert any("没有任何协议 JSON" in t for t in texts)  # 原文保留（不吞错）

    def test_tool_failure_degrades_to_partial_with_valid_protocol(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 无 DSN：get_schema 走真实错误路径（连接层未配置）
        monkeypatch.delenv("CLOUDAGENT_DB_DSN", raising=False)
        payload = dict(_VALID_RESULT)
        payload.update(
            status="partial",
            evidence=[],
            root_causes=[],
            recommendations=[],
            limitations=["数据库不可用，无法获取执行计划"],
        )
        provider = _ScriptedProvider(
            [
                _tool_use("get_schema", {"table": "orders"}, "t1"),
                _final_response(payload),
            ]
        )
        result, _registry = _run_agent_tool(_make_context(tmp_path), provider)
        assert result.is_error is False
        texts = _result_texts(result)
        joined = "\n".join(texts)
        assert "diagnosis-protocol 校验：passed" in joined
        assert "status：partial" in joined
        assert "数据库不可用" in joined  # 限制如实透传


class TestBoundaryEnforcement:
    def test_allowlist_external_tool_denied_at_execution_boundary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 子模型尝试 Write（存在于 registry、不在 sql-diagnosis 白名单）：
        # capability boundary 应在执行前拒绝——副作用断言：文件未产生。
        target = tmp_path / "should_not_exist.txt"
        payload = dict(_VALID_RESULT)
        provider = _ScriptedProvider(
            [
                _tool_use("Write", {"file_path": str(target), "content": "x"}, "t1"),
                _final_response(payload),
            ]
        )
        result, _registry = _run_agent_tool(_make_context(tmp_path), provider)
        assert result.is_error is False
        assert not target.exists(), "allowlist-external tool must not execute"

    def test_permission_mode_resolution(self) -> None:
        agent_def = next(
            a for a in get_agent_definitions_with_overrides(str(Path.cwd()))
            if a.agent_type == "sql-diagnosis"
        )
        # 定义声明生效（default 父模式被覆盖）
        assert agent_def.permission_mode == "dontAsk"
        default_parent = ToolContext(workspace_root=Path.cwd())
        default_parent.permission_context = ToolPermissionContext(mode="default")
        assert resolve_permission_mode(default_parent, agent_def) == "dontAsk"
        # bypass 父模式优先（尊重用户的显式选择——runtime 既有语义）
        bypass_parent = ToolContext(workspace_root=Path.cwd())
        assert resolve_permission_mode(bypass_parent, agent_def) == "bypassPermissions"


class TestRoutingSurface:
    def test_agent_visible_with_quality_description(self) -> None:
        agents = {a.agent_type: a for a in get_agent_definitions_with_overrides(str(Path.cwd()))}
        assert "sql-diagnosis" in agents
        when_to_use = agents["sql-diagnosis"].when_to_use
        for keyword in ("slow query", "plan", "index", "pagination"):
            assert keyword in when_to_use
        # 反向边界：不宣称通用能力
        assert "any task" not in when_to_use.lower()


class TestProvisioning:
    """fix-sql-diagnosis-tool-provisioning：runtime 接缝装配（不手动预装配）。"""

    def test_real_path_provisioning_registers_db_tools(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 模拟工具结果（同成功链）：装配若未发生，get_schema 会 unavailable。
        @contextmanager
        def _fake_session(dsn=None):  # noqa: ANN001
            yield object()

        monkeypatch.setattr("cloudagent_ext.diagnosis.db.tools.db_session", _fake_session)
        # 元数据工具现在先 resolve_dsn(target) 再建会话（extend-db-tools-target）；
        # 离线用例没有 DSN，这里一并打桩，避免落到 secondary_dsn_not_configured。
        monkeypatch.setattr(
            "cloudagent_ext.diagnosis.db.tools.resolve_dsn",
            lambda target="primary": f"dsn:{target}",
        )
        monkeypatch.setattr(
            "cloudagent_ext.diagnosis.db.tools.postgres.fetch_schema",
            lambda conn, schema="public", table=None: {
                "schema": schema,
                "table": table,
                "columns": [{"name": "id", "type": "bigint", "nullable": False, "default": None}],
                "primary_key": ["id"],
            },
        )
        provider = _ScriptedProvider(
            [
                _tool_use("get_schema", {"table": "orders"}, "t1"),
                _final_response(_VALID_RESULT),
            ]
        )
        result, registry = _run_agent_tool(_make_context(tmp_path), provider)

        # ① 父注册表保持干净：装配 MUST NOT 污染主会话工具面
        # （实测修订 2026-10-17：in-place 装配曾让主 Agent 看到并直连 DB 工具）
        for name in (
            "get_schema",
            "get_indexes",
            "explain_sql",
            "get_table_stats",
            "get_lock_info",
            "query_table_rows",
        ):
            assert registry.get(name) is None, name
        # ② 工具被真实执行（mock 结果进入对话流），而非 unavailable
        joined_calls = "\n".join(str(call) for call in provider.calls)
        assert "primary_key" in joined_calls, "get_schema 应真实执行（mock 结果应出现在对话流）"
        assert "unavailable" not in joined_calls
        # ③ 会话正常完成
        assert result.output["status"] == "completed"

    def test_provision_failure_tolerated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 装配回调抛异常 → spawn 照常（既有 invalid-tools 降级），不阻断链路
        from cloudagent_ext.agent.load_agents_dir import get_agent_definitions_with_overrides

        definition = next(
            a
            for a in get_agent_definitions_with_overrides(str(Path.cwd()))
            if a.agent_type == "sql-diagnosis"
        )

        def _explode(_registry):
            raise RuntimeError("simulated provisioning failure")

        monkeypatch.setattr(definition, "provision_tools", _explode)
        provider = _ScriptedProvider([_final_response(_VALID_RESULT)])
        result, registry = _run_agent_tool(_make_context(tmp_path), provider)
        # 不抛穿、会话照常产出（内容仍为脚本回放）
        assert result.is_error is False
        texts = _result_texts(result)
        assert any("itg-1" in t for t in texts) or any("校验" in t for t in texts)


    def test_provision_return_false_tolerated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 装配回调返回 False（如依赖缺失）→ spawn 照常 + 告警可观测（不静默）
        from cloudagent_ext.agent.load_agents_dir import get_agent_definitions_with_overrides

        definition = next(
            a
            for a in get_agent_definitions_with_overrides(str(Path.cwd()))
            if a.agent_type == "sql-diagnosis"
        )

        monkeypatch.setattr(definition, "provision_tools", lambda _registry: False)
        provider = _ScriptedProvider([_final_response(_VALID_RESULT)])
        result, registry = _run_agent_tool(_make_context(tmp_path), provider)
        assert result.is_error is False  # spawn 未被阻断


class TestSkillVisibility:
    """fix-sql-diagnosis-tool-provisioning：skill 模型可见性按 agent 收窄。"""

    class _Ctx:
        def __init__(self, agent_type):
            self.agent_type = agent_type

    class _Skill:
        def __init__(self, name, mva=None):
            self.name = name
            self.type = "prompt"
            self.disable_model_invocation = False
            self.is_enabled = True
            self.model_visible_agents = mva

    def _skills(self):
        return [
            self._Skill("sql-optimization", ["sql-diagnosis"]),
            self._Skill("verify"),  # 未设置 → 全部可见（回归面）
            self._Skill("scoped-other", ["code-reviewer"]),
        ]

    def test_model_visibility_scoped_by_agent(self) -> None:
        from cloudagent_ext.skills.visibility import filter_model_visible_skills

        main_visible = [s.name for s in filter_model_visible_skills(self._skills(), self._Ctx(None))]
        diag_visible = [
            s.name
            for s in filter_model_visible_skills(self._skills(), self._Ctx("sql-diagnosis"))
        ]
        assert "sql-optimization" not in main_visible  # 主会话不可见
        assert "verify" in main_visible  # 未设置字段的 skill 不变
        assert "sql-optimization" in diag_visible  # 诊断子代理可见
        assert "scoped-other" not in diag_visible  # 其他 agent 的限定同样生效

    def test_bundled_sql_optimization_has_scope_declared(self) -> None:
        # 定义侧已声明（透过 bundled 注册链）
        from cloudagent_ext.skills.bundled import sql_optimization as so

        assert so._MODEL_VISIBLE_AGENTS == ["sql-diagnosis"]


class TestSkillPreauthorization:
    """fix-sql-diagnosis-tool-provisioning：agent 声明的 skills 子会话预授权。"""

    def _sql_definition(self):
        from cloudagent_ext.agent.load_agents_dir import get_agent_definitions_with_overrides

        return next(
            a
            for a in get_agent_definitions_with_overrides(str(Path.cwd()))
            if a.agent_type == "sql-diagnosis"
        )

    def test_declared_skills_injected_as_session_allow_rules(self) -> None:
        from cloudagent_ext.agent.run_agent import _build_permission_context

        parent = _make_context(Path.cwd())
        perm = _build_permission_context(
            parent, "dontAsk", False, agent_definition=self._sql_definition()
        )
        session_rules = (perm.always_allow_rules or {}).get("session", [])
        assert "Skill(sql-optimization)" in session_rules
        # 父上下文原规则不受影响（新 dict）
        assert "session" not in (parent.permission_context.always_allow_rules or {})

    def test_skill_permission_allows_with_preauthorization(self) -> None:
        from cloudagent_ext.agent.run_agent import _build_permission_context
        from cloudagent_ext.permissions.types import PermissionAllowDecision
        from cloudagent_ext.tool_system.tools.skill import _skill_check_permissions

        parent = _make_context(Path.cwd())
        perm = _build_permission_context(
            parent, "dontAsk", False, agent_definition=self._sql_definition()
        )
        child_context = ToolContext(workspace_root=Path.cwd(), permission_context=perm)
        decision = _skill_check_permissions({"skill": "sql-optimization"}, child_context)
        assert isinstance(decision, PermissionAllowDecision)


class TestTranscriptRecovery:
    """fix-diagnosis-result-truncation：注入文本被截断时从会话记录恢复完整文本。"""

    def _agent_def(self):
        from cloudagent_ext.agent.load_agents_dir import get_agent_definitions_with_overrides

        return next(
            a
            for a in get_agent_definitions_with_overrides(str(Path.cwd()))
            if a.agent_type == "sql-diagnosis"
        )

    def _truncated_result(self, transcript_path):
        from cloudagent_ext.tool_system.protocol import ToolResult

        return ToolResult(
            name="Agent",
            output={
                "status": "completed",
                "agent_type": "sql-diagnosis",
                "content": [
                    {
                        "type": "text",
                        "text": "前置分析正文…\n…[omitted 15000 chars]…\n尾部（未含协议 JSON）",
                    }
                ],
                "transcript_path": transcript_path,
            },
        )

    def test_recovery_when_injected_text_lacks_protocol(self, tmp_path: Path) -> None:
        import json as _json

        from cloudagent_ext.agent._bundled_agents.sql_diagnosis import augment_agent_result

        full_text = _final_text(_VALID_RESULT)
        tp = tmp_path / "agent-recover.jsonl"
        tp.write_text(
            _json.dumps(
                {"role": "user", "content": [{"type": "text", "text": "brief"}]},
                ensure_ascii=False,
            )
            + "\n"
            + _json.dumps(
                {"role": "assistant", "content": [{"type": "text", "text": full_text}]},
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

        result = self._truncated_result(str(tp))
        out = augment_agent_result(result, self._agent_def())
        joined = "\n".join(
            b["text"] for b in out.output["content"] if isinstance(b, dict)
        )
        assert "校验：passed" in joined
        assert "经会话记录恢复完整文本" in joined

    def test_recovery_unavailable_keeps_failed(self, tmp_path: Path) -> None:
        from cloudagent_ext.agent._bundled_agents.sql_diagnosis import augment_agent_result

        result = self._truncated_result(str(tmp_path / "missing.jsonl"))
        out = augment_agent_result(result, self._agent_def())
        joined = "\n".join(
            b["text"] for b in out.output["content"] if isinstance(b, dict)
        )
        assert "校验：FAILED" in joined  # 恢复不可用 → 显式失败（不伪造）


class TestAgentFailureHandling:
    def test_subagent_model_failure_is_contained(self, tmp_path: Path) -> None:
        class _Exploding:
            model = _MODEL

            def chat(self, messages, tools=None, **kwargs):  # noqa: ANN001
                raise RuntimeError("simulated model outage")

            def chat_stream(self, messages, tools=None, **kwargs):  # noqa: ANN001
                return iter(())

            def chat_stream_response(self, *args, **kwargs):  # noqa: ANN001
                raise NotImplementedError

        result, _registry = _run_agent_tool(_make_context(tmp_path), _Exploding())
        # 失败被包含在结果中（不向主链路抛穿）；错误消息如实进入内容区
        # （runtime 既有语义：错误文本作为最终输出现身，而非静默成功）。
        texts = _result_texts(result)
        joined = "\n".join(texts)
        assert "simulated model outage" in joined, joined
        # 集成校验后处理把该失败纳入协议降级路径（FAILED 标注，不吞错）
        assert "diagnosis-protocol 校验：FAILED" in joined, joined
