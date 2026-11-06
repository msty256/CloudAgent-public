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
from dataclasses import asdict, dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Any, Callable

from cloudagent_ext.diagnosis.assessor import summarize_assessments
from cloudagent_ext.diagnosis.evaluation.cost import summarize_usage
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

#: main 派发模式的编排约束（**评测装置的一部分，不属于产品提示词**）。
#:
#: 为什么需要它：`main` 模式的 system prompt 用的是通用 CloudAgent 那套
#: （`build_full_system_prompt`），它教的是"怎么用 Read/Grep 干活"，从没说过要委派；
#: 而工具集里既有 `Agent` 也有 `Read/Grep/Glob`。实测（2026-11-01，`code-001`）：
#: 主 Agent 打了 40 次自己的工具调用、只派 1 次子代理，30 轮打满还没收敛——
#: 于是缺口机制（注入 / decide / 域闸都在 `_agent_call` 里）**一次都没被触发**，
#: `main` 模式退化成"更贵的 direct"。
#:
#: 只加约束、不删工具（方案 a）：`Read` 用于理解任务是必要的，靠提示词把"取证"这件事
#: 显式划归子代理。软约束，但保留了主 Agent 的理解能力。
_MAIN_DISPATCH_CONSTRAINT = """# 诊断编排约束

你在这个会话里的角色是**诊断编排者**，不是执行者。以下四条必须遵守：

1. **取证必须委派**：任何用于支撑结论的证据，都必须来自 `Agent` 工具返回的诊断子代理结果
   （`code-diagnosis` / `sql-diagnosis` / `log-diagnosis`）。只有子代理给出的 evidence 才算证据。
2. **Read / Grep / Glob 只用于理解任务**：定位文件、确认代码结构、读懂问题属于理解；
   一旦开始"自己查证并据此下结论"，就越界了。
3. **不要用阅读印象代替取证**：还没有子代理证据时，继续委派，不要自己下结论。
4. **作答要指出依据**：最终回复说明结论来自哪个子代理的哪条证据。
5. **必须同步等待结果**：委派时**不要**设 `run_in_background: true`。
   子代理返回结果之前不要给结论——"已经启动取证、等子代理返回"不是答案，
   这一轮会被判为无效输出。

子代理会按协议返回结构化结果（含 `evidence` / `root_causes`）。如果一个子代理报告了
"还没查清"的缺口，把那条缺口作为下一次委派的目标，而不是自己去查。"""


def build_main_dispatch_prompt(*, cwd: str, tools: list[Any], agents: list[Any]) -> str:
    """构造 main 派发模式的系统提示（通用提示 + 编排约束）。

    抽成函数而不是内联，是为了能单独断言"约束确实进了提示词"。
    """

    from cloudagent_ext.context_system.prompt_assembly import build_full_system_prompt

    return build_full_system_prompt(
        cwd=cwd,
        tools=tools,
        agents=agents,
        non_interactive=True,
        append_system_prompt=_MAIN_DISPATCH_CONSTRAINT,
    )


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
    #: 主 Agent 的原始最终回答（``main`` 派发时才与 ``raw_output`` 不同）。
    #: 评分用 ``raw_output``，人读/回放用这个——替换掉会丢信息。
    main_answer: str = ""

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
            # T0.2–T0.4：采集键在两种模式下形状一致，报告侧不必按 mode 分支。
            # 离线回放不跑模型、也不走会话账本，所以这里给中性值（不是"测出来是 0"）。
            meta={
                "fixture": _FIXTURE_FILE,
                "decision_counts": {},
                "decision_log": [],
                "gap_events": [],
                "usage": summarize_usage([]),
                # 阶段 2：离线不核查、无版本推进——给中性值，形状与 live 一致
                "state_revision": 0,
                "stale_discarded": 0,
                "assessments": summarize_assessments([]),
                # 阶段 3：离线不跑压缩管线（上下文太小），形状同样对齐
                "compaction": {},
                "recall_count": 0,
                "recall_miss": 0,
            },
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
    """按配置构造 provider（**不再硬编 deepseek**）。

    这里原来写死 ``build_provider_from_config("deepseek")``，后果是：
    改了 ``config.json`` 的 ``default_provider`` 或换端点，评测器**完全不理会**——
    而且不报错，只表现为 ``model_calls=0 / empty output``，非常难查。

    取值顺序：``CLOUDAGENT_PROVIDER`` 环境变量 → 配置里的 ``default_provider``
    → ``deepseek``（保持旧默认，避免无配置环境下直接崩）。
    """

    import os

    from cloudagent_ext.providers.runtime import build_provider_from_config

    name = str(os.environ.get("CLOUDAGENT_PROVIDER", "") or "").strip()
    if not name:
        try:
            from cloudagent_ext.config import get_default_provider

            name = str(get_default_provider() or "").strip()
        except Exception:  # noqa: BLE001 — 读配置失败就退回旧默认
            name = ""
    return build_provider_from_config(name or "deepseek")


#: 域 → 诊断子代理。原先 direct 模式**硬编 sql-diagnosis**，
#: 于是拿 code 域的题去问 SQL 代理——它会如实回答"数据库不可达、无法诊断"，
#: 看起来像模型能力差，其实是问错了对象。
_DOMAIN_TO_AGENT: dict[str, str] = {
    "code": "code-diagnosis",
    "log": "log-diagnosis",
    "sql": "sql-diagnosis",
    # cross / sync 没有专属子代理（跨域、同步面），暂用 sql 承担数据侧取证
    "cross": "sql-diagnosis",
    "sync": "sql-diagnosis",
}


def _agent_for_domain(domain: str) -> str:
    return _DOMAIN_TO_AGENT.get(str(domain or "").strip().lower(), "sql-diagnosis")


def _wants_subagent_grade(dispatch_mode: str, grade_source: str) -> bool:
    """是否用子代理结果评分（P2）。

    * ``main``       —— 显式要主 Agent 的回答（散文），通常解析不了，主要用于排查；
    * ``subagent``   —— 显式要子代理协议结果；
    * ``auto``（默认）—— ``main`` 派发时取子代理（否则恒 invalid_output），``direct`` 取主输出
      （direct 模式下主输出本来就是子代理输出，两者等价）。
    """

    if grade_source == "subagent":
        return True
    if grade_source == "main":
        return False
    return dispatch_mode == "main"


def _recall_stats(all_tool_uses: list[dict], events: list[Any]) -> tuple[int, int]:
    """数召回：``(调用次数, 取不到次数)``（阶段 3 · T3.5）。

    命中与未命中必须分开数——只有未命中率低，才说明"折掉原文"没有把证据弄丢。
    如果只看"折了多少条"却不看"取回失败几次"，一个 100% 折、100% 取不回的管线
    在报告里会显得很漂亮。
    """

    recall_ids = {
        str(use.get("id") or "")
        for use in all_tool_uses
        if use.get("name") == "recall_evidence"
    }
    miss = sum(
        1
        for event in events
        if getattr(event, "kind", "") == "tool_result"
        and getattr(event, "is_error", False)
        and str(getattr(event, "tool_use_id", "") or "") in recall_ids
    )
    return len(recall_ids), miss


def _last_subagent_payload(runtime: Any) -> str:
    """取**最后一个有结果的诊断子代理**的协议 JSON（P2：评分对象）。

    为什么从会话账本取而不是从主 Agent 的回复里抠：子代理结果在
    ``finish_delegation`` 时已被解析并存在 ``entry.result``，是结构化且未经主 Agent
    转述的原始结论。从散文里再抠 JSON 等于把"主 Agent 复述得准不准"混进评分。

    取"最后一个"而不是"第一个"：多轮诊断里最后一批证据代表最终状态。
    没有可用结果时返回空串，由调用方回退。
    """

    entries = getattr(getattr(runtime, "session", None), "entries", None) or ()
    for entry in reversed(list(entries)):
        result = getattr(entry, "result", None)
        if result is None:
            continue
        to_dict = getattr(result, "to_dict", None)
        if callable(to_dict):
            try:
                return json.dumps(to_dict(), ensure_ascii=False)
            except (TypeError, ValueError):
                pass
        try:
            return json.dumps(asdict(result), ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            continue
    return ""


class LiveExecutor:
    """真实模型执行：复用 P2.4 的 Agent 调用链（装配工具 + sql-diagnosis + 运行时循环）。"""

    def __init__(
        self,
        *,
        provider_factory: Callable[[], Any] | None = None,
        timeout_per_case: float = 180.0,
        dispatch_mode: str = "direct",
        grade_source: str = "auto",
    ) -> None:
        if dispatch_mode not in ("direct", "main"):
            raise ValueError(f"未知 dispatch_mode：{dispatch_mode!r}")
        if grade_source not in ("auto", "main", "subagent"):
            raise ValueError(f"未知 grade_source：{grade_source!r}")
        self._dispatch_mode = dispatch_mode
        self._grade_source = grade_source
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

    def _ensure_ready(self, domain: str = "") -> None:
        wanted_agent = _agent_for_domain(domain)
        if self._registry is not None and getattr(self, "_agent_name", "") == wanted_agent:
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
        agent_def = AgentRegistry.find(wanted_agent)
        if agent_def is None:  # pragma: no cover - 注册缺失属实现缺陷
            raise EvaluationExecutorError(f"{wanted_agent} agent 未注册")
        self._agent_name = wanted_agent

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
            self._system_prompt = build_main_dispatch_prompt(
                cwd=str(Path.cwd()),
                tools=subset,
                agents=AgentRegistry.all(),
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
        self._ensure_ready(str(case.get("domain") or ""))
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
                # 诊断要读多个文件、必要时跑测试：原值 30/14 偏低，
                # 实测 direct 模式在 26 次工具调用处撞顶，输出退化成
                # `[Max tool turns reached]`——看起来像诊断失败，其实是没查完。
                max_turns=48 if self._dispatch_mode == "main" else 36,
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
        main_answer = response_text or (calls[-1]["content"] if calls and not error else "")
        # 主/子代理工具调用拆分：`events` 只记录**主循环**的工具调用，
        # 因此以它为准，避免用工具名白名单（log/code 域会漏计）。
        all_tool_uses = [use for call in calls for use in call["tool_uses"]]
        main_tool_calls = sum(1 for event in events if getattr(event, "kind", None) == "tool_use")
        sub_tool_calls = max(len(all_tool_uses) - main_tool_calls, 0)
        delegations = sum(1 for use in all_tool_uses if use.get("name") == "Agent")
        runtime = getattr(context, "diagnosis_session_runtime", None)

        # 阶段 3（T3.5）：召回统计。命中/未命中要分开数——
        # 只有未命中率低，才说明"折掉原文"没有把证据弄丢。
        recall_count, recall_miss = _recall_stats(all_tool_uses, events)

        # ---- 评分对象（P2）----
        # `main` 模式下 `response_text` 是**主 Agent 的散文**，而评分器要诊断协议 JSON，
        # 于是恒为 invalid_output（实测 code-001 / code-007 两次）。
        # 这里按 grade_source 决定"评谁"：auto 在 main 模式下取子代理的协议结果。
        raw_output = main_answer
        effective_grade_source = "main"
        if _wants_subagent_grade(self._dispatch_mode, self._grade_source):
            sub_text = _last_subagent_payload(runtime)
            if sub_text:
                raw_output = sub_text
                effective_grade_source = "subagent"
            elif self._grade_source == "subagent":
                # 显式要求评子代理但没有子代理结果 → 如实留空并记录原因
                error = error or "grade_source=subagent 但本次没有可用的子代理结果"
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
            # T0.3 / T0.4（度量地基）：终止原因分布与缺口迁移事件。
            # 之前 "为什么停" 只进 debug 日志，"缺口怎么变的"只有两个快照值，
            # 报告侧无法离线重算——这里一并带出（列表按会话上限截断）。
            "decision_counts": dict(getattr(runtime, "decision_counts", {}) or {}),
            "decision_log": list(getattr(runtime, "decision_log", []) or []),
            "gap_events": list(getattr(runtime, "gap_events", []) or []),
            # T0.2：token / cache（认不出的 usage 记 calls_without_usage，不静默当 0）
            "usage": summarize_usage(calls),
            # 阶段 2：状态可信度的三个观测量
            #   state_revision  —— 状态版本被推进过几次（每次应能说出原因，见 bump_log）
            #   stale_discarded —— 因版本变化而丢弃的写入数（正常应恒 0）
            #   assessments     —— 独立核查的分布与分歧率（含 skipped / unavailable）
            "state_revision": int(getattr(runtime, "state_revision", 0) or 0),
            "stale_discarded": int(getattr(runtime, "stale_discarded", 0) or 0),
            "assessments": summarize_assessments(
                getattr(runtime, "assessments", []) or []
            ),
            # 明细：只给汇总没法复盘"为什么这批全被判 overclaimed"。
            # 每条含 status / claimed_gaps / verified_gaps / reason（模型给的一句话）。
            "assessment_log": [
                item.to_dict()
                for item in (getattr(runtime, "assessments", []) or [])
                if hasattr(item, "to_dict")
            ],
            "dispatch_mode": self._dispatch_mode,
            # 阶段 3（T3.5）：压缩观测。
            #   compaction_stats —— 管线写回的结构归约统计（tool_context.compaction_stats）
            #   recall_count     —— 模型调用 recall_evidence 的次数
            #   recall_miss      —— 其中取不到原文的次数（句柄失效/跨会话）
            # 三者一起看才有意义：只有 recall 发生了，才证明"折"是可逆的。
            "compaction": dict(getattr(context, "compaction_stats", None) or {}),
            "recall_count": recall_count,
            "recall_miss": recall_miss,
            # 阶段 5 实测发现：main 派发下主 Agent 会用 run_in_background 派子代理，
            # 然后不等结果就收尾（trace 里原话："等子代理返回…"），
            # 于是评分拿到的是散文、记成 invalid_output——**看起来像诊断失败，其实是没跑完**。
            # 单独立一个标记，让这种"无效跑"能被单独统计，不混进正确率分母。
            "dispatch_incomplete": bool(delegations > 0 and not _last_subagent_payload(runtime)),
            # P2：这次评分实际用的是谁的结果（auto 在 main 模式下会落成 subagent）
            "grade_source": effective_grade_source,
            "main_answer_chars": len(main_answer),
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
            main_answer=main_answer,
        )
