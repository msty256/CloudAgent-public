#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""评测执行器（offline fixture 回放 / live 真实 Agent 调用链）。

执行器是两种模式的**唯一差异点**：产出统一的 :class:`CaseRun`（原始输出 +
事件摘要 + 元数据 + 执行错误），下游解析/评分/报告完全共用。
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Any, Callable

from cloudagent_ext.diagnosis.evaluation.report import redact_sensitive

__all__ = [
    "CaseRun",
    "OfflineExecutor",
    "LiveExecutor",
    "SourceOffline",
    "SourceLive",
    "build_conversation",
    "build_diagnosis_tool_context",
]

SourceOffline = "offline-fixture"
SourceLive = "live-model"

_FIXTURE_PACKAGE = "cloudagent_ext.diagnosis.evaluation.fixtures"
_FIXTURE_FILE = "offline_responses.json"
_EVENT_TEXT_LIMIT = 20000
_RESTRICTED_PERMISSION_MODE = "dontAsk"


def build_diagnosis_tool_context(workspace_root: Path | None = None):
    """诊断执行链路的**受限**工具上下文（变更 harden-sql-diagnostic-safety）。

    * 权限模式固定为 ``dontAsk``（need-ask 即拒）：写 / 破坏性 / 凭据访问类
      命令在无交互环境下**执行前确定性拒绝**；可证明只读且限域的命令放行；
    * 修复前该链路使用 ``ToolContext`` 默认的 ``bypassPermissions``（Bash
      检查全部短路）；
    * P2.8 统一会话接入时 MUST 复用本构造（含 agent 独立调用链路）。
    """

    from cloudagent_ext.permissions.types import ToolPermissionContext
    from cloudagent_ext.tool_system.context import ToolContext

    return ToolContext(
        workspace_root=workspace_root or Path.cwd(),
        permission_context=ToolPermissionContext(mode=_RESTRICTED_PERMISSION_MODE),
    )


def _build_restricted_registry(full_registry: Any, allowed_names: list[str]) -> Any:
    """执行层白名单强制（P2.7 R1-②）：loop 的执行 registry 仅含白名单工具。

    修复前：loop 持有**全量** registry，"工具白名单"仅约束模型可见列表——实测
    白名单外工具（如 ``DashboardList``）在 default/bypass 会话中可被 dispatch 并
    返回真实结果。修复后：不在白名单内的工具在 dispatch 层解析为 unknown tool。
    """

    from cloudagent_ext.tool_system.registry import ToolRegistry

    allowed = {name.casefold() for name in allowed_names}
    tools = [tool for tool in full_registry.all_tools() if tool.name.casefold() in allowed]
    return ToolRegistry(tools)


@dataclass
class CaseRun:
    """单个案例的一次执行结果（统一结构）。"""

    case_id: str
    source: str
    raw_output: str
    events: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    @property
    def crashed(self) -> bool:
        return self.error is not None


def build_conversation(
    calls: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """把逐轮模型调用与工具事件重建为完整交互轨迹（回放序列）。

    序列形态：``assistant（content + tool_uses）`` → 每个 ``tool_use`` 后紧跟其
    ``tool`` 结果（按 tool_use_id 匹配）→ 下一轮 assistant → …。
    """

    results_by_id: dict[str, dict[str, Any]] = {
        str(event.get("tool_use_id")): event
        for event in events or []
        if event.get("kind") == "tool_result"
    }
    conversation: list[dict[str, Any]] = []
    for call in calls or []:
        tool_uses = call.get("tool_uses") or []
        conversation.append(
            {
                "role": "assistant",
                "turn": call.get("n"),
                "model": call.get("model"),
                "elapsed_sec": call.get("elapsed_sec"),
                "usage": call.get("usage"),
                "finish_reason": call.get("finish_reason"),
                "content": call.get("content") or "",
                "tool_uses": tool_uses,
            }
        )
        for tool_use in tool_uses:
            result = results_by_id.get(str(tool_use.get("id"))) or {}
            conversation.append(
                {
                    "role": "tool",
                    "tool": tool_use.get("name"),
                    "tool_use_id": tool_use.get("id"),
                    "input": tool_use.get("input"),
                    "output": result.get("tool_output"),
                    "is_error": result.get("is_error"),
                }
            )
    return conversation


class EvaluationExecutorError(Exception):
    """执行器配置/构建错误（如 live 模式 provider 不可用）。"""


def _event_summary(event: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {"kind": getattr(event, "kind", None)}
    for name in ("tool_name", "name", "tool_use_id", "is_error"):
        if hasattr(event, name):
            summary[name] = getattr(event, name)
    for name in ("tool_input", "input", "tool_output", "output"):
        if hasattr(event, name):
            value = getattr(event, name)
            if isinstance(value, str):
                value = value[:_EVENT_TEXT_LIMIT]
            summary[name] = value
    return summary


class OfflineExecutor:
    """确定性 fixture 回放：不调用模型、不需要 API Key 或真实数据库。

    仅用于验证 Runner / 评分器 / 报告的正确性——**不度量真实诊断能力**。
    """

    def __init__(self, responses: dict[str, str] | None = None) -> None:
        if responses is None:
            payload = json.loads(
                (files(_FIXTURE_PACKAGE) / _FIXTURE_FILE).read_text(encoding="utf-8")
            )
            self._responses = {
                case_id: entry["response_text"]
                for case_id, entry in (payload.get("responses") or {}).items()
            }
        else:
            self._responses = dict(responses)

    def prepare(self) -> None:
        """离线模式无需外部依赖（接口对齐）。"""

    @property
    def model_label(self) -> str:
        return "offline-fixture"

    def run_case(self, case: dict[str, Any]) -> CaseRun:
        case_id = case["case_id"]
        if case_id not in self._responses:
            return CaseRun(
                case_id=case_id,
                source=SourceOffline,
                raw_output="",
                error=f"offline fixture missing for case {case_id}",
            )
        return CaseRun(
            case_id=case_id,
            source=SourceOffline,
            raw_output=self._responses[case_id],
            meta={"fixture": _FIXTURE_FILE},
        )


class _RecordingProvider:
    """包装真实 provider，记录每次调用的完整响应（评测取证）。"""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.calls: list[dict[str, Any]] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def chat(self, messages, tools=None, **kwargs):  # noqa: ANN001
        started = time.time()
        response = self._inner.chat(messages, tools=tools, **kwargs)
        self.calls.append(
            {
                "n": len(self.calls) + 1,
                "elapsed_sec": round(time.time() - started, 2),
                "model": getattr(response, "model", None),
                "usage": getattr(response, "usage", None),
                "finish_reason": getattr(response, "finish_reason", None),
                "tool_uses": [
                    {"id": t.get("id"), "name": t.get("name"), "input": t.get("input")}
                    for t in (getattr(response, "tool_uses", None) or [])
                ],
                "content": getattr(response, "content", "") or "",
            }
        )
        return response

    def chat_stream(self, messages, tools=None, **kwargs):  # noqa: ANN001
        return iter(())

    def chat_stream_response(self, messages, tools=None, **kwargs):  # noqa: ANN001
        raise NotImplementedError


def _default_provider_factory() -> Any:
    from cloudagent_ext.providers.runtime import build_provider_from_config

    return build_provider_from_config("deepseek")


class LiveExecutor:
    """真实模型执行：复用 P2.4 的 Agent 调用链（装配工具 + sql-diagnosis + 运行时循环）。"""

    def __init__(
        self,
        *,
        provider_factory: Callable[[], Any] | None = None,
        timeout_per_case: float = 180.0,
        dispatch_mode: str = "direct",
    ) -> None:
        if dispatch_mode not in ("direct", "main"):
            raise ValueError(f"未知 dispatch_mode：{dispatch_mode!r}")
        self._dispatch_mode = dispatch_mode
        self._provider_factory = provider_factory or _default_provider_factory
        self._timeout_per_case = timeout_per_case
        self._provider: _RecordingProvider | None = None
        self._registry: Any = None
        self._system_prompt: str = ""
        self._model_label: str = ""
        self._tool_names: list[str] = []

    # ---- 装配（惰性，失败给出明确指引且不泄露凭据） ----

    def prepare(self) -> None:
        """构建 provider 与工具链（fail fast；配置错误抛 EvaluationExecutorError）。"""

        self._ensure_ready()

    @property
    def model_label(self) -> str:
        return self._model_label or "unknown"

    def _ensure_ready(self) -> None:
        if self._registry is not None:
            return
        try:
            provider = self._provider_factory()
        except EvaluationExecutorError:
            raise
        except Exception as exc:  # noqa: BLE001 - 转为带指引的配置错误
            raise EvaluationExecutorError(
                "无法构建模型 Provider（请检查 CloudAgent 模型配置，如 "
                "`~/.cloudagent/config.json` 的 providers 段）：" + redact_sensitive(str(exc))
            ) from exc

        from cloudagent_ext.agent import ensure_bundled_agents_registered
        from cloudagent_ext.agent._bundled_agents import sql_diagnosis
        from cloudagent_ext.agent.agent_tool_utils import resolve_agent_tools
        from cloudagent_ext.agent.registry import AgentRegistry
        from cloudagent_ext.tool_system.defaults import build_default_registry

        ensure_bundled_agents_registered()
        agent_def = AgentRegistry.find("sql-diagnosis")
        if agent_def is None:  # pragma: no cover - 注册缺失属实现缺陷
            raise EvaluationExecutorError("sql-diagnosis agent 未注册")

        self._provider = _RecordingProvider(provider)
        if not sql_diagnosis.register_sql_diagnosis_tools(registry := build_default_registry(
            provider=self._provider,
            load_agent_tools=(self._dispatch_mode == "main"),
        )):  # pragma: no cover
            raise EvaluationExecutorError("DB 工具装配失败")

        if self._dispatch_mode == "main":
            # 主 Agent 模式：只保留"派发 + 只读检索"，禁止它自己干活或写文件
            allowed = {"Agent", "Read", "Grep", "Glob", "Skill", "TodoWrite"}
            subset = [tool for tool in registry.list_tools() if tool.name in allowed]
            if not any(tool.name == "Agent" for tool in subset):  # pragma: no cover
                raise EvaluationExecutorError("主 Agent 模式缺少 Agent 工具")
            self._tool_names = [tool.name for tool in subset]
            self._registry = _build_restricted_registry(registry, self._tool_names)
            from cloudagent_ext.context_system.prompt_assembly import build_full_system_prompt

            self._system_prompt = build_full_system_prompt(
                cwd=str(Path.cwd()),
                tools=subset,
                agents=AgentRegistry.all(),
                non_interactive=True,
            )
        else:
            resolved = resolve_agent_tools(agent_def, registry.list_tools(), is_async=False)
            self._tool_names = [tool.name for tool in resolved.resolved_tools]
            # P2.7：执行层白名单强制（模型可见列表之外，dispatch 边界同样受限）
            self._registry = _build_restricted_registry(registry, self._tool_names)
            self._system_prompt = agent_def.get_system_prompt()

        self._model_label = str(getattr(self._provider, "model", "") or "unknown")

    # ---- 执行 ----

    def run_case(self, case: dict[str, Any]) -> CaseRun:
        self._ensure_ready()
        assert self._provider is not None

        from cloudagent_ext.query.agent_loop_compat import run_query_as_agent_loop
        from cloudagent_ext.tool_system.context import ToolContext
        from cloudagent_ext.types.messages import UserMessage

        question = case["input"]["question"]
        sql = (case["input"].get("context") or {}).get("sql")
        if self._dispatch_mode == "main":
            # 主 Agent 拿到的是"用户问题"，由它自己决定派谁；不要替它写诊断指令
            task_text = question
        else:
            task_text = "【诊断任务】" + question
            if sql:
                task_text += "\n\n【目标 SQL（只读参考，不要求执行）】" + sql
            task_text += "\n\n请完成诊断并按统一协议给出最终结果。"

        events: list[Any] = []
        context = build_diagnosis_tool_context()
        calls_before = len(self._provider.calls)

        async def _drive():
            return await run_query_as_agent_loop(
                initial_messages=[UserMessage(content=task_text)],
                provider=self._provider,
                tool_registry=self._registry,
                tool_context=context,
                system_prompt=self._system_prompt,
                max_turns=30 if self._dispatch_mode == "main" else 14,
                on_event=events.append,
            )

        error: str | None = None
        terminal_reason: str | None = None
        response_text = ""
        started = time.time()
        try:
            result = asyncio.run(asyncio.wait_for(_drive(), timeout=self._timeout_per_case))
            terminal_reason = getattr(getattr(result, "terminal", None), "reason", None)
            response_text = str(getattr(result, "response_text", "") or "")
        except (asyncio.TimeoutError, TimeoutError):
            error = f"timeout after {self._timeout_per_case:.0f}s"
        except Exception as exc:  # noqa: BLE001 - 执行层错误如实记录（脱敏）
            error = f"{type(exc).__name__}: {redact_sensitive(str(exc))}"
        elapsed = round(time.time() - started, 2)

        calls = self._provider.calls[calls_before:]
        # 最终输出优先取 loop 的正式出口 response_text（含 max_turns/兜底语义），
        # 回退到最后一轮模型响应内容。
        raw_output = response_text or (calls[-1]["content"] if calls and not error else "")
        # 主/子代理工具调用拆分：`events` 只记录**主循环**的工具调用，
        # 因此以它为准，避免用工具名白名单（log/code 域会漏计）。
        all_tool_uses = [use for call in calls for use in call["tool_uses"]]
        main_tool_calls = sum(1 for event in events if getattr(event, "kind", None) == "tool_use")
        sub_tool_calls = max(len(all_tool_uses) - main_tool_calls, 0)
        delegations = sum(1 for use in all_tool_uses if use.get("name") == "Agent")
        runtime = getattr(context, "diagnosis_session_runtime", None)
        gaps = list(getattr(runtime, "gaps", []) or [])
        meta = {
            "model": self._model_label,
            "elapsed_sec": elapsed,
            "model_calls": len(calls),
            "tool_calls": len(all_tool_uses),
            "main_tool_calls": main_tool_calls,
            "sub_tool_calls": sub_tool_calls,
            "delegations": delegations,
            "gaps_total": len(gaps),
            "gaps_resolved": sum(1 for g in gaps if getattr(g, "status", "") == "resolved"),
            "injected_dispatches": int(getattr(runtime, "injected_dispatches", 0) or 0),
            "dispatch_mode": self._dispatch_mode,
            "agents_dispatched": sorted(
                {
                    str(getattr(entry.task, "agent_type", ""))
                    for entry in getattr(getattr(runtime, "session", None), "entries", []) or []
                }
                - {""}
            ),
            "tools_resolved": list(self._tool_names),
            "terminal": terminal_reason,
        }
        return CaseRun(
            case_id=case["case_id"],
            source=SourceLive,
            raw_output=raw_output,
            events=[_event_summary(event) for event in events],
            meta=meta,
            error=error,
            calls=list(calls),
        )
