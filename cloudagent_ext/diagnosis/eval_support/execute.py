#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""跑一个 case → RunRecord（EVAL-P1a）。

**只做执行与序列化**：任何评分、GT 比对、markdown 都不在这里——
看到 ``match_terms`` / ``top1`` / ``score`` 出现在本文件即为越界（任务卡红线 1）。

# KNOWN-ISSUE(eval-bash-empty)
``dontAsk`` 权限模式下，子代理调 ``Bash`` 返回空字符串（``is_error=None``），
模型于是自己总结成 "Bash is unavailable" 改用 Read/Grep/Glob——评测环境里任何
需要跑命令的代码诊断都做不到，且症状表现为"模型答不好"而不是"链路坏了"。
**本卡不修**（属执行层改动，会与 P2 迁移纠缠）；建议在 EVAL-P3（修评分口径）一起修。
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from cloudagent_ext.diagnosis.assessor import summarize_assessments
from cloudagent_ext.diagnosis.eval_support.record import (
    RunRecord,
    RunRequest,
    record_to_json,
)
from cloudagent_ext.utils.redaction import redact_sensitive

__all__ = ["execute_case", "case_run_to_record", "build_subject"]

#: trace.calls 的 content 截断长度（与 evaluation.executors._EVENT_TEXT_LIMIT 一致）
_CALL_TEXT_LIMIT = 20000
_EVENT_TEXT_LIMIT = 20000

#: mechanism 的搬运白名单（schema §4.2）——白名单而非黑名单：
#: meta 里将来新增的调试字段不进契约，否则"契约稳定"变成空话
_MECHANISM_KEYS = (
    "delegations",
    "agents_dispatched",
    "gaps_total",
    "gaps_resolved",
    "injected_dispatches",
    "decision_counts",
    "decision_log",
    "gap_events",
    "compaction",
    "recall_count",
    "recall_miss",
    "state_revision",
    "stale_discarded",
    "assessments",
    # P3-T3.3（schema §8.2）：P3 区分"没派发子代理"与"派发了但不合协议"、
    # 判"撞轮次上限"与统计工具调用都需要这三/五个键
    "dispatch_incomplete",
    "terminal",
    "tool_calls",
    "main_tool_calls",
    "sub_tool_calls",
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _product_version() -> str:
    try:
        from cloudagent_ext._version import __version__

        return str(__version__) or "unknown"
    except Exception:  # noqa: BLE001 — 取不到就写 unknown，不许编
        return "unknown"


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        sha = out.stdout.strip()
        return sha or "unknown"
    except Exception:  # noqa: BLE001 — 非 git 环境 / 无 git 命令 → unknown
        return "unknown"


def _provider_name() -> str:
    """配置面 provider 名（与 evaluation.executors._default_provider_factory 的取值顺序一致）。

    只读配置，不构造 provider——构造失败会在执行阶段以 EvaluationExecutorError 暴露。
    """

    name = str(os.environ.get("CLOUDAGENT_PROVIDER", "") or "").strip()
    if name:
        return name
    try:
        from cloudagent_ext.config import get_default_provider

        return str(get_default_provider() or "").strip() or "unknown"
    except Exception:  # noqa: BLE001 — 读配置失败就写 unknown
        return "unknown"


def build_subject(request: RunRequest, model_label: str = "") -> dict[str, Any]:
    """被测系统身份（schema §3.2，R7 全链路版本化）。取不到的写 ``"unknown"``，不许猜。"""

    from cloudagent_ext.diagnosis.switches import SWITCHES

    # arm_env 只记机制开关的原始环境值（不 dump 整个 os.environ——那会把凭据写进记录）
    arm_env = {
        spec.env: os.environ[spec.env]
        for spec in SWITCHES.values()
        if spec.env in os.environ
    }
    return {
        "product": "cloudagent",
        "version": _product_version(),
        "git_sha": _git_sha(),
        "model": str(model_label or "").strip() or "unknown",
        "provider": _provider_name(),
        "dispatch_mode": request.options.get("dispatch_mode", "main"),
        "grade_source": request.options.get("grade_source", "auto"),
        "permission_mode": request.options.get("permission_mode", "dontAsk"),
        "arm_env": arm_env,
    }


def _wants_subagent_grade(dispatch_mode: str, grade_source: str) -> bool:
    """与 ``evaluation.executors._wants_subagent_grade`` 同语义（照抄不另立）。

    P2 搬迁该函数后，这里改为从唯一实现导入。
    """

    if grade_source == "subagent":
        return True
    if grade_source == "main":
        return False
    return dispatch_mode == "main"


def _truncate_calls(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """``content`` 可能很大：截断到 20000 字符并打 ``truncated`` 标记。"""

    trimmed: list[dict[str, Any]] = []
    for call in calls:
        item = dict(call)
        content = item.get("content")
        if isinstance(content, str) and len(content) > _CALL_TEXT_LIMIT:
            item["content"] = content[:_CALL_TEXT_LIMIT]
            item["truncated"] = True
        trimmed.append(item)
    return trimmed


def _determine_status(case_run: Any) -> tuple[str, bool]:
    """status 判定（审查 eval-p1a-round1 §2 疑问 2 裁决后的五档口径）。

    * 空输出 → ``unfinished``（与 ``scoring.categorize()`` 一致：空输出=
      没拿到作答机会=链路问题，不是独立的 "empty" 档）；
    * "撞轮次上限 / 明显截断" 与 "输出不合协议" 的细分是评分层的事（P3）：
      本卡对"非空、无错"的输出记 ``ok`` 并打 ``status_provisional``，
      让 P3 知道这条还没细分过。
    """

    error = case_run.error
    if error and "timeout" in str(error).lower():
        return "timeout", False
    if error:
        return "crashed", False
    if not str(case_run.raw_output or "").strip():
        return "unfinished", False
    return "ok", True


def case_run_to_record(
    case_run: Any,
    request: RunRequest,
    *,
    record_id: str,
    started_at: str,
    finished_at: str,
    subject: dict[str, Any],
    elapsed_sec: float | None = None,
) -> RunRecord:
    """``CaseRun → RunRecord`` 的字段映射（实现时唯一要对照的是 schema §4 的表）。"""

    meta: dict[str, Any] = dict(getattr(case_run, "meta", None) or {})
    status, provisional = _determine_status(case_run)

    # ---- graded_text（schema §5）：选谁评分只有这一处实现 ----
    raw_output = str(case_run.raw_output or "")
    main_answer = str(case_run.main_answer or "")
    dispatch_mode = request.options.get("dispatch_mode", "main")
    grade_source = request.options.get("grade_source", "auto")
    if _wants_subagent_grade(dispatch_mode, grade_source):
        # LiveExecutor 在拿到子代理结果时会把 meta.grade_source 记为 "subagent"；
        # 请求要子代理结果但没拿到（如 main 模式没派发）→ graded_text 留空、
        # status 记 unfinished（空输出=没拿到作答机会，与 categorize 口径一致）
        if str(meta.get("grade_source") or "") == "subagent":
            graded_text = raw_output
        else:
            graded_text = ""
            if status == "ok":
                status, provisional = "unfinished", False
    else:
        graded_text = main_answer

    # P7c.1（状态诚实化）：产品自报 ok 之前，对评分对象（raw_output）做一次协议解析
    # 验证——解析失败记 invalid_output 并带原因，不再冒充 ok。
    # 依据（breadth 2026-11-08 实测）：43 例里 9 例（21%）是"完整诊断 + task_id 空串"，
    # 评测仓判 invalid_output 而产品记 ok——跨仓状态语义不一致会让"产品自报状态"
    # 失去可信度，污染后续所有 unfinished/invalid 分类。
    # 契约不变：invalid_output 本就在五档 status 里；raw_output 原样保留（内容不丢）。
    parse_error: str | None = None
    if status == "ok":
        from cloudagent_ext.diagnosis.protocol import (
            DiagnosisParseError,
            parse_diagnosis_result,
        )

        try:
            parse_diagnosis_result(raw_output)
        except DiagnosisParseError as exc:
            status, provisional = "invalid_output", False
            parse_error = f"payload 协议解析失败：{exc}"

    outcome: dict[str, Any] = {
        "status": status,
        "error": (
            None
            if case_run.error is None and parse_error is None
            else redact_sensitive(str(case_run.error or parse_error))
        ),
        "raw_output": raw_output,
        "main_answer": main_answer,
        "graded_text": graded_text,
    }
    if provisional:
        outcome["status_provisional"] = True

    mechanism = {key: meta[key] for key in _MECHANISM_KEYS if key in meta}

    usage_meta = meta.get("usage") or {}
    available = bool(usage_meta.get("available"))
    usage: dict[str, Any] = {
        "input_tokens": usage_meta.get("input_tokens") if available else None,
        "output_tokens": usage_meta.get("output_tokens") if available else None,
        "cached_input_tokens": usage_meta.get("cached_input_tokens") if available else None,
        "model_calls": int(meta.get("model_calls", 0) or 0),
        "calls_without_usage": int(usage_meta.get("calls_without_usage", 0) or 0),
        "available": available,
    }

    events = list(getattr(case_run, "events", None) or [])
    trace = {"events": events, "calls": _truncate_calls(list(getattr(case_run, "calls", None) or []))}

    if elapsed_sec is None:
        elapsed_sec = float(meta.get("elapsed_sec", 0.0) or 0.0)

    return RunRecord(
        schema_version=1,
        record_id=record_id,
        request_id=request.request_id,
        case_id=request.case_id,
        domain=request.domain,
        started_at=started_at,
        finished_at=finished_at,
        elapsed_sec=float(elapsed_sec),
        subject=dict(subject),
        outcome=outcome,
        trace=trace,
        mechanism=mechanism,
        usage=usage,
    )


def execute_case(
    request: RunRequest,
    *,
    executor: Any = None,
) -> RunRecord:
    """跑一个 case，产出 :class:`RunRecord`。

    P2（T2.4）已偿还技术债：装配与采集逻辑全部迁入本模块
    （:class:`LiveCaseRunner` + 顶部那批函数），``evaluation/`` 随本卡删除。
    ``executor`` 参数用于测试注入（fake executor，零模型成本）。
    """

    if executor is None:
        executor = LiveCaseRunner(
            timeout_per_case=float(request.options.get("timeout_sec", 300)),
            dispatch_mode=request.options.get("dispatch_mode", "main"),
            grade_source=request.options.get("grade_source", "auto"),
        )

    case = {
        "case_id": request.case_id,
        "domain": request.domain,
        "input": {
            "question": request.question,
            "context": dict(request.context),
        },
    }

    started = time.time()
    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        case_run = executor.run_case(case)
    except Exception as exc:  # noqa: BLE001 — 执行层异常也要落记录（脱敏）
        # 契约要求"执行失败仍写出 RunRecord"：构造最小 crashed CaseRun，
        # 让失败样本与成功样本走同一条序列化路径
        case_run = CaseRun(
            case_id=request.case_id,
            source="live",
            raw_output="",
            meta={
                "model": getattr(executor, "model_label", "") or "",
                "elapsed_sec": round(time.time() - started, 2),
            },
            error=f"{type(exc).__name__}: {redact_sensitive(str(exc))}",
        )
    finished_at = datetime.now().astimezone().isoformat(timespec="seconds")

    meta: dict[str, Any] = dict(getattr(case_run, "meta", None) or {})
    model_label = str(meta.get("model", "") or getattr(executor, "model_label", "") or "")
    record_id = "rec-{}-{}".format(
        request.case_id, datetime.now().strftime("%Y%m%dT%H%M%S")
    )
    elapsed = float(meta.get("elapsed_sec", 0.0) or 0.0) or round(time.time() - started, 2)
    return case_run_to_record(
        case_run,
        request,
        record_id=record_id,
        started_at=started_at,
        finished_at=finished_at,
        subject=build_subject(request, model_label),
        elapsed_sec=elapsed,
    )


def write_record(record: RunRecord, out_path: str | Path) -> None:
    """把 RunRecord 写成 JSON（字段顺序稳定，便于 diff）。"""

    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json_dumps(record)
    path.write_text(payload, encoding="utf-8")


def json_dumps(record: RunRecord) -> str:
    import json

    return json.dumps(record_to_json(record), ensure_ascii=False, indent=2) + "\n"


# ---------------------------------------------------------------------------
# P2（T2.0）：从 evaluation.executors 迁入的装配/采集逻辑
# （T2.4 删除 evaluation/ 后这里是唯一实现；evaluation.executors 过渡期 re-export）
# ---------------------------------------------------------------------------

class EvaluationExecutorError(Exception):
    """执行链路装配失败（配置错误、agent 未注册等），fail fast 且不泄露凭据。"""


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


_RESTRICTED_PERMISSION_MODE = "dontAsk"


def build_diagnosis_tool_context(workspace_root: Path | None = None):
    """诊断执行链路的**受限**工具上下文（变更 harden-sql-diagnostic-safety）。

    * 权限模式固定为 ``dontAsk``（need-ask 即拒）：写 / 破坏性 / 凭据访问类
      命令在无交互环境下**执行前确定性拒绝**；可证明只读且限域的命令放行；
    * P2.8 统一会话接入时 MUST 复用本构造（含 agent 独立调用链路）。
    """

    from cloudagent_ext.permissions.types import ToolPermissionContext
    from cloudagent_ext.tool_system.context import ToolContext

    return ToolContext(
        workspace_root=workspace_root or Path.cwd(),
        permission_context=ToolPermissionContext(mode=_RESTRICTED_PERMISSION_MODE),
    )


def build_restricted_registry(full_registry: Any, allowed_names: list[str]) -> Any:
    """执行层白名单强制（P2.7 R1-②）：loop 的执行 registry 仅含白名单工具。

    修复前：loop 持有**全量** registry，"工具白名单"仅约束模型可见列表——实测
    白名单外工具（如 ``DashboardList``）在 default/bypass 会话中可被 dispatch 并
    返回真实结果。修复后：不在白名单内的工具在 dispatch 层解析为 unknown tool。
    """

    from cloudagent_ext.tool_system.registry import ToolRegistry

    allowed = {name.casefold() for name in allowed_names}
    tools = [tool for tool in full_registry.all_tools() if tool.name.casefold() in allowed]
    return ToolRegistry(tools)


#: 旧名别名——既有测试（security/test_prompt_injection 等）经此名字引用
_build_restricted_registry = build_restricted_registry

_DOMAIN_TO_AGENT: dict[str, str] = {
    "code": "code-diagnosis",
    "log": "log-diagnosis",
    "sql": "sql-diagnosis",
    # cross / sync 没有专属子代理（跨域、同步面），暂用 sql 承担数据侧取证
    "cross": "sql-diagnosis",
    "sync": "sql-diagnosis",
}


def agent_for_domain(domain: str) -> str:
    return _DOMAIN_TO_AGENT.get(str(domain or "").strip().lower(), "sql-diagnosis")


#: 旧名别名
_agent_for_domain = agent_for_domain


class RecordingProvider:
    """包装真实 provider，记录每次调用的完整响应（评测取证）。

    P2（T2.0）自 evaluation.executors 迁入：OfflineExecutor（录制回放）与
    LiveExecutor（真跑采集）共用；T2.4 删除 evaluation/ 后这里是唯一实现。
    """

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


#: 旧名别名
_RecordingProvider = RecordingProvider


def last_subagent_payload(runtime: Any, domain: str = "") -> str:
    """取**期望域 agent** 的最新协议 JSON（评分对象）。

    为什么从会话账本取而不是从主 Agent 的回复里抠：子代理结果在
    ``finish_delegation`` 时已被解析并存在 ``entry.result``，是结构化且未经主 Agent
    转述的原始结论。从散文里再抠 JSON 等于把"主 Agent 复述得准不准"混进评分。

    **P2-T2.0 修正（schema §9 第 2 条的真跑实测）**：旧实现取"最后一个有结果的
    子代理"，main 模式派发多域子代理时会取错域（实测 sql-002 的评分文本来自
    ``code-diagnosis``——拿它评分等于给 code agent 打 SQL 分，分数低是测量伪影）。
    现按 ``domain`` 选期望 agent（:func:`agent_for_domain`），取"最后一个**匹配域**"
    而不是"第一个"：多轮诊断里最后一批证据代表最终状态。
    期望 agent 无结果时返回空串，由调用方回退主回答——**不许退回别的域**。
    ``domain`` 为空时保持旧行为（不过滤）。
    """

    entries = getattr(getattr(runtime, "session", None), "entries", None) or ()
    expected_agent = agent_for_domain(domain) if str(domain or "").strip() else ""
    for entry in reversed(list(entries)):
        if expected_agent and str(
            getattr(getattr(entry, "task", None), "agent_type", "")
        ) != expected_agent:
            continue  # 其它域的子代理结果不归本题——宁可空着也不张冠李戴
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


#: 旧名别名（tests/diagnosis/test_grade_source.py 引用）
_last_subagent_payload = last_subagent_payload


def ensure_ready_for_domain(executor: Any, domain: str = "") -> None:
    """:class:`LiveExecutor` 的装配逻辑（P2 从 evaluation.executors 迁入）。

    ``executor`` 需要提供 ``_provider_factory`` / ``_dispatch_mode`` 属性，并接受
    ``_provider`` / ``_registry`` / ``_agent_name`` / ``_model_label`` /
    ``_tool_names`` 的写入（与原 ``LiveExecutor._ensure_ready`` 的隐式契约一致）。
    """

    wanted_agent = agent_for_domain(domain)
    if executor._registry is not None and getattr(executor, "_agent_name", "") == wanted_agent:
        return
    try:
        provider = executor._provider_factory()
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
    executor._agent_name = wanted_agent

    executor._provider = RecordingProvider(provider)
    # P8-B4（2026-11-08）：装配必须走 knowledge-aware 路径。
    # 原先直接调 register_sql_diagnosis_tools —— 那只装域工具，不装 search_knowledge，
    # 导致 KB=on/off 两臂真跑时两臂的 search_knowledge 调用数都是 0（3.46M input 作废）。
    # 生产路径（agent/_bundled_agents/*.py 的 provision_tools）走的正是
    # provision_with_knowledge，eval-run 必须与之一致，否则开关是死的。
    from cloudagent_ext.diagnosis.knowledge.provision import provision_with_knowledge

    registry = build_default_registry(
        provider=executor._provider,
        load_agent_tools=(executor._dispatch_mode == "main"),
    )
    if not provision_with_knowledge(sql_diagnosis.register_sql_diagnosis_tools, registry):
        raise EvaluationExecutorError("诊断工具装配失败（域工具或知识库装配失败）")


    if executor._dispatch_mode == "main":
        # 主 Agent 模式：只保留"派发 + 只读检索"，禁止它自己干活或写文件
        allowed = {"Agent", "Read", "Grep", "Glob", "Skill", "TodoWrite"}
        subset = [tool for tool in registry.list_tools() if tool.name in allowed]
        if not any(tool.name == "Agent" for tool in subset):  # pragma: no cover
            raise EvaluationExecutorError("主 Agent 模式缺少 Agent 工具")
        executor._tool_names = [tool.name for tool in subset]
        executor._registry = build_restricted_registry(registry, executor._tool_names)
        executor._system_prompt = build_main_dispatch_prompt(
            cwd=str(Path.cwd()),
            tools=subset,
            agents=AgentRegistry.all(),
        )
    else:
        resolved = resolve_agent_tools(agent_def, registry.list_tools(), is_async=False)
        executor._tool_names = [tool.name for tool in resolved.resolved_tools]
        # P2.7：执行层白名单强制（模型可见列表之外，dispatch 边界同样受限）
        executor._registry = build_restricted_registry(registry, executor._tool_names)
        executor._system_prompt = agent_def.get_system_prompt()

    executor._model_label = str(getattr(executor._provider, "model", "") or "unknown")


# ---------------------------------------------------------------------------
# P2（T2.4）：真跑引擎（LiveExecutor）/ CaseRun / 事件摘要 / 召回统计 / usage 归一
# ——自 evaluation.executors & evaluation.cost 迁入；evaluation/ 随本卡删除
# ---------------------------------------------------------------------------

SourceOffline = "offline-fixture"
SourceLive = "live-model"

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


#: 输入 token 的候选键（按优先级）
INPUT_KEYS: tuple[str, ...] = ("input_tokens", "prompt_tokens")
#: 输出 token 的候选键
OUTPUT_KEYS: tuple[str, ...] = ("output_tokens", "completion_tokens")
#: 缓存命中 token 的候选键（含嵌套路径，用 ``.`` 分隔）
CACHE_KEYS: tuple[str, ...] = (
    "cache_read_input_tokens",
    "prompt_cache_hit_tokens",
    "cached_tokens",
    "prompt_tokens_details.cached_tokens",
)


def _as_mapping(usage: Any) -> dict[str, Any]:
    """把 usage 统一成 dict（可能是 pydantic 模型 / SimpleNamespace / None）。"""

    if usage is None:
        return {}
    if isinstance(usage, dict):
        return usage
    dump = getattr(usage, "model_dump", None)
    if callable(dump):
        try:
            data = dump()
            return data if isinstance(data, dict) else {}
        except Exception:  # noqa: BLE001 — 归一失败按"没有 usage"处理
            return {}
    if hasattr(usage, "__dict__"):
        return {k: v for k, v in vars(usage).items() if not k.startswith("_")}
    return {}


def _lookup(usage: dict[str, Any], path: str) -> int | None:
    """按 ``a.b.c`` 路径取一个非负整数；取不到或不是数字返回 ``None``。"""

    node: Any = usage
    for part in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    if isinstance(node, bool):  # bool 是 int 的子类，单独排除
        return None
    if isinstance(node, int):
        return node if node >= 0 else None
    if isinstance(node, float) and node >= 0:
        return int(node)
    return None


def _first(usage: dict[str, Any], keys: Iterable[str]) -> tuple[int | None, str]:
    for key in keys:
        value = _lookup(usage, key)
        if value is not None:
            return value, key
    return None, ""


def summarize_usage(calls: Iterable[Any]) -> dict[str, Any]:
    """聚合一组 ``_RecordingProvider.calls`` 的 token 用量。

    ``calls`` 里每项是 ``{"usage": <原始 usage>}`` 形状；缺失或为 None 都算"没采到"。
    """

    input_tokens = 0
    output_tokens = 0
    cached_tokens = 0
    with_usage = 0
    without_usage = 0
    cache_field = ""

    for call in calls or []:
        usage = _as_mapping(call.get("usage") if isinstance(call, dict) else None)
        if not usage:
            without_usage += 1
            continue
        with_usage += 1

        value, _ = _first(usage, INPUT_KEYS)
        if value is not None:
            input_tokens += value
        value, _ = _first(usage, OUTPUT_KEYS)
        if value is not None:
            output_tokens += value
        value, key = _first(usage, CACHE_KEYS)
        if value is not None:
            cached_tokens += value
            cache_field = key

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        # 缓存命中已计入输入侧，不再重复加到 total
        "cached_input_tokens": cached_tokens,
        "total_tokens": input_tokens + output_tokens,
        "calls_with_usage": with_usage,
        "calls_without_usage": without_usage,
        # "" 表示本批次没有任何一次调用返回缓存字段 → 报告里应写"不可得"而不是 0
        "cache_field": cache_field,
        "available": with_usage > 0,
    }


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


class LiveCaseRunner:
    """真跑引擎（P2 自 evaluation.executors.LiveExecutor 迁入，行为不变）。"""

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
        """装配（P2-T2.0 迁入 eval_support.execute，本方法仅委托保持调用点不变）。"""

        ensure_ready_for_domain(self, domain)

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
            # P7c.2（方案 B，降发生率）：breadth 实测 21% 例把 task_id 写成空串
            # （协议要求"未提供时省略"）。提示词不保证模型照做（所以方案 A 才是
            # 主修），但明确一句话成本为零。
            task_text += (
                "\n若本轮没有「任务标识」（task_id），省略该字段；不要写成空字符串。"
            )

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
            # P2-T2.0：按 domain 选期望 agent，不跨域取评分对象
            sub_text = _last_subagent_payload(runtime, domain=str(case.get("domain") or ""))
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
            # P3-T3.3（P2 一审 R1）：与评分对象同一套期望 agent 选择，
            # 否则"不完整"标记与 graded_text 出处可能各说各话
            "dispatch_incomplete": bool(
                delegations > 0
                and not _last_subagent_payload(runtime, domain=str(case.get("domain") or ""))
            ),
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
