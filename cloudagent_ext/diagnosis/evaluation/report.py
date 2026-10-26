#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""评测报告：结构化 ``run.json`` + 人工摘要 ``summary.md`` + 逐案例明细。

* 敏感信息（DSN / 密码 / API Key）在写入前统一过滤；
* ``completeness`` 标记保证"未完整执行"的运行不会留下看似完整的成功报告。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

__all__ = [
    "redact_sensitive",
    "build_run_id",
    "write_report",
]

# ---- 脱敏 ----

_DSN_PATTERN = re.compile(r"postgresql://[^\s\"'<>]+")
_PASSWORD_ASSIGN = re.compile(r"(?i)(password|passwd|pwd|api[_-]?key|token)\s*[=:]\s*([^\s,;\"']+)")
_KEY_PREFIX = re.compile(r"\b(sk-[A-Za-z0-9_-]{6,}|ms-[0-9a-f-]{8,})\b")
# P3.3（add-log-analysis-domain）：日志域脱敏扩展——手机号 / 邮箱（工具与报告共用）
_PHONE_PATTERN = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
_EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def _redact_dsn(match: re.Match[str]) -> str:
    url = match.group(0)
    if "***" in url:  # 已脱敏形态保持原样
        return url
    return re.sub(r"://([^:@/]+):([^@/]+)@", r"://\1:***@", url)


def redact_sensitive(text: str) -> str:
    """抹除文本中的 DSN 凭据 / 密码赋值 / 疑似 API Key / 手机号 / 邮箱。

    P3.3（add-log-analysis-domain）：扩展手机号与邮箱规则——日志工具输出与
    评测报告**共用同一函数**，避免脱敏规则在工具层与评分层漂移。
    """

    if not text:
        return text
    text = _DSN_PATTERN.sub(_redact_dsn, text)
    text = _PASSWORD_ASSIGN.sub(lambda m: f"{m.group(1)}=***", text)
    text = _KEY_PREFIX.sub("***", text)
    text = _PHONE_PATTERN.sub("1**********", text)
    text = _EMAIL_PATTERN.sub("***@***", text)
    return text


# ---- 运行 ID ----

def build_run_id(mode: str, cases_hash: str, started_at: datetime) -> str:
    """``20261015T234915-live-ab12cd34`` 形态的运行标识（北京时间基准）。"""

    stamp = started_at.strftime("%Y%m%dT%H%M%S")
    return f"{stamp}-{mode}-{cases_hash[:8]}"


# ---- 报告写入 ----

def _dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8",
    )


def _conversation_markdown(case: dict[str, Any]) -> str:
    """逐案例对话回放（人读形态：每轮模型响应 → 工具调用 → 工具结果）。"""

    case_id = case["case_id"]
    meta = case.get("meta") or {}
    lines = [f"# 案例回放 · {case_id}（{case.get('scenario')}）", ""]
    lines.append(f"- 类别：`{case['category']}`｜来源：{case.get('source')}")
    if meta:
        lines.append(
            f"- 模型：{meta.get('model')}｜模型调用 {meta.get('model_calls')} 轮 / "
            f"工具 {meta.get('tool_calls')} 次｜耗时 {meta.get('elapsed_sec')}s"
        )
    if case.get("error"):
        lines.append(f"- 错误：{case['error']}")
    lines.append("")

    conversation = case.get("conversation") or []
    if not conversation:
        lines.append("> （本案例无交互轨迹——离线 fixture 模式仅有最终响应）")
        lines.append("")
    for item in conversation:
        if item.get("role") == "assistant":
            usage = json.dumps(item.get("usage") or {}, ensure_ascii=False)
            lines.append(
                f"## 轮 {item.get('turn')} · 模型响应（{item.get('elapsed_sec')}s · usage {usage}）"
            )
            lines.append("")
            content = str(item.get("content") or "").strip()
            if content:
                lines.append("> " + content.replace("\n", "\n> "))
                lines.append("")
            for tool_use in item.get("tool_uses") or []:
                payload = json.dumps(tool_use.get("input") or {}, ensure_ascii=False)
                lines.append(f"- 🔧 调用 `{tool_use.get('name')}`：`{payload[:300]}`")
            lines.append("")
        elif item.get("role") == "tool":
            output = str(item.get("output") or "")
            head = output[:800] + ("…（截断展示，全文见 cases JSON）" if len(output) > 800 else "")
            lines.append(f"📤 `{item.get('tool')}` 结果（is_error={item.get('is_error')}）：")
            lines.append("")
            lines.append("```")
            lines.append(head)
            lines.append("```")
            lines.append("")

    raw = str(case.get("raw_output") or "")
    if raw:
        lines.append("## 最终输出（原文）")
        lines.append("")
        lines.append(raw)
    return "\n".join(lines) + "\n"


def _summary_markdown(run: dict[str, Any], cases: list[dict[str, Any]]) -> str:
    metrics = run["metrics"]
    lines: list[str] = []
    labels = {"sql": "SQL", "code": "代码", "log": "日志", "cross": "跨域"}
    domain_label = labels.get(str(run.get("domain") or "sql"), "SQL")
    variant = run.get("variant") or "gaps-on"
    repeat = int(run.get("repeat", 1) or 1)
    suffix = ""
    if variant != "gaps-on" or repeat > 1:
        suffix = f"（{variant}" + (f" / ×{repeat}" if repeat > 1 else "") + "）"
    lines.append(f"# {domain_label} 诊断评测报告 · {run['run_id']}{suffix}")
    lines.append("")
    if run["completeness"] != "complete":
        lines.append(f"> ⚠️ **本次运行不完整：{run.get('incompleteness_reason')}**")
        lines.append("")
    lines.append(f"- 模式：`{run['mode']}`（来源标签 `{run['source']}`）")
    lines.append(f"- 模型/配置：{run.get('model') or '—'} | 案例集哈希：`{run['cases_hash'][:16]}`")
    started_display = str(run["started_at"]).replace("T", " ")
    finished_display = str(run["finished_at"]).replace("T", " ")
    lines.append(
        f"- 时间：{started_display} → {finished_display}"
        f"（北京时间 +08:00，历时 {run['elapsed_sec']}s）"
    )
    if variant != "gaps-on" or repeat > 1:
        lines.append(
            f"- 实验分组：{run.get('variant', 'gaps-on')}"
            f"｜重复轮次：{run.get('repeat', 1)}"
        )
    lines.append(f"- 案例：总 {run['total_cases']}（解析成功 {run['counts']['parsed']} / "
                 f"无效输出 {run['counts']['invalid_output']} / 崩溃 {run['counts']['crashed']}）")
    lines.append("")
    if run["source"] == "offline-fixture":
        lines.append("> 声明：**离线模式使用确定性 Fixture 回放，仅验证评测基础设施，"
                     "不代表真实模型的诊断能力。**")
        lines.append("")
    lines.append("## 指标")
    lines.append("")
    lines.append("| 指标 | 值 | 分子/分母 | 说明 |")
    lines.append("|---|---|---|---|")
    for key, meta in metrics.items():
        lines.append(
            f"| {meta['label']} | {meta['value']} | {meta.get('numerator', '—')}/{meta.get('denominator', '—')} | "
            f"{meta.get('note', '')} |"
        )
    lines.append("")
    violations = [c for c in cases if c["safety_violations"]]
    lines.append(f"## 安全违规（{len(violations)} 案例）")
    lines.append("")
    if violations:
        for case in violations:
            for violation in case["safety_violations"]:
                lines.append(f"- `{case['case_id']}` · {violation['rule']}：{violation['detail']}")
    else:
        lines.append("- 无")
    lines.append("")
    failed = [c for c in cases if c["category"] != "parsed" or c["overconfident"] or not c["top1_hit"]]
    lines.append(f"## 需要复核的案例（{len(failed)}）")
    lines.append("")
    for case in failed:
        flag = "⚠️安全" if case["safety_violations"] else ""
        lines.append(
            f"- `{case['case_id']}` 类别={case['category']} Top1={'✅' if case['top1_hit'] else '❌'} "
            f"过度自信={'是' if case['overconfident'] else '否'} {flag} {case.get('error') or ''}".rstrip()
        )
    lines.append("")
    lines.append("## 逐案例摘要（完整对话见 cases/<id>.trace.md）")
    lines.append("")
    lines.append("| 案例 | 类别 | Top1 | 证据 | 无法诊断 | 过度自信 | 轮数/工具 | 安全 | 对话 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for case in cases:
        meta = case.get("meta") or {}
        turns = f"{meta.get('model_calls', '—')}/{meta.get('tool_calls', '—')}" if meta else "—"
        lines.append(
            f"| `{case['case_id']}` | {case['category']} | {'✅' if case['top1_hit'] else '❌'} | "
            f"{'✅' if case['evidence_sufficient'] else '❌'} | {'是' if case['undiagnosed'] else '否'} | "
            f"{'是' if case['overconfident'] else '否'} | {turns} | "
            f"{'⚠️' if case['safety_violations'] else '—'} | [trace](cases/{case['case_id']}.trace.md) |"
        )
    return "\n".join(lines) + "\n"


def write_report(
    out_dir: Path,
    run: dict[str, Any],
    cases: list[dict[str, Any]],
    *,
    domain: str = "sql",
) -> dict[str, str]:
    """写出三件套，返回各部分路径。"""

    out_dir = Path(out_dir)
    run["domain"] = run.get("domain", domain)
    # run.json（脱敏纵深防御：即使上游漏过，落盘前再过一次）
    _dump(out_dir / "run.json", json.loads(redact_sensitive(json.dumps(run, ensure_ascii=False, default=str))))
    for case in cases:
        _dump(
            out_dir / "cases" / f"{case['case_id']}.json",
            json.loads(redact_sensitive(json.dumps(case, ensure_ascii=False, default=str))),
        )
        trace = redact_sensitive(_conversation_markdown(case))
        (out_dir / "cases" / f"{case['case_id']}.trace.md").write_text(trace, encoding="utf-8")
    summary = redact_sensitive(_summary_markdown(run, cases))
    (out_dir / "summary.md").write_text(summary, encoding="utf-8")
    return {
        "run": str(out_dir / "run.json"),
        "summary": str(out_dir / "summary.md"),
        "cases": str(out_dir / "cases"),
    }
