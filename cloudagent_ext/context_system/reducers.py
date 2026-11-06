#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""结构归约器（阶段 3 · T3.1）：把取证大结果"折"成摘要，而不是"丢"。

**与 `microcompact` 的区别是本质的**：

=============  ==============================  ============================
               清空（`microcompact`）           折叠（本模块）
结果            ``[Old tool result content
                cleared]``                      结构化摘要 + 句柄
证据            消失                            保留要点，细节可回取
适用            可重新获得的中间产物            一次性取到的证据
=============  ==============================  ============================

**为什么不用 LLM 摘要**：论文 §2.2 的顺序是"先确定性归约，归约不动了再用模型"。
确定性归约可复现、零成本、不会编造；LLM 摘要留作可选档位（决策点 2，默认关闭）。

**收益的量级要说清**：单次 `query_table_rows` 的硬上限是 ``MAX_RESULT_ROWS = 200`` 行
（`diagnosis/db/tools.py:59`），所以**不存在"一条 5000 行结果"**。
归约的收益来自"多轮累计的取证结果"，不是单条超大——这一点决定了 T3.3 的阈值该按
会话累计量来定，而不是按单条长度。

**两个函数都不抛异常**：拿不准就返回 ``None``，由调用方保留原文。
"折不好"永远好过"折丢了"。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from cloudagent_ext.diagnosis.text_match import extract_keywords

__all__ = [
    "Reduced",
    "reduce_sql_rows",
    "reduce_log_block",
    "render_summary",
]

#: 数值列判定的覆盖比例：一列里 80% 以上是数字才当数值列处理
_NUMERIC_COVERAGE = 0.8
#: 低基数列（适合做分布摘要）的最大去重值个数
_MAX_CATEGORICAL_CARDINALITY = 8
#: 一行里最多取多少个字符放进 sample
_SAMPLE_CHARS = 160

_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d{3})?")
_LEVEL_RE = re.compile(r"\b(ERROR|WARN|WARNING|FATAL|CRITICAL)\b")
_EXC_RE = re.compile(
    r"\b((?:[a-zA-Z_$][\w$]*\.)+[A-Z][A-Za-z0-9_$]*(?:Exception|Error|Throwable))\b"
)


@dataclass(frozen=True)
class Reduced:
    """一次归约的产物。

    ``payload`` 是结构化的（便于断言与二次处理），``render_summary`` 负责变成
    给模型看的文本——两者分开，是因为"能测的东西"和"好看的东西"不是一回事。
    """

    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    original_chars: int = 0
    reduced_chars: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "original_chars": self.original_chars,
            "reduced_chars": self.reduced_chars,
            "payload": self.payload,
        }


def _is_number(value: Any) -> bool:
    # bool 是 int 的子类，单独排除（否则 True/False 会被当成 1/0 参与统计）
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _short(value: Any) -> str:
    text = str(value)
    return text if len(text) <= _SAMPLE_CHARS else text[:_SAMPLE_CHARS] + "…"


# ---------------------------------------------------------------------------
# SQL 行集
# ---------------------------------------------------------------------------


def reduce_sql_rows(
    payload: Any,
    *,
    max_rows: int = 5,
    min_rows: int = 20,
) -> Reduced | None:
    """把 ``query_table_rows`` 的 rows 结果折成摘要。

    保留的四类东西（缺一不可）：

    1. **头尾各 N 行**——纯聚合会把"唯一的异常行"吃掉，而异常行常常就是线索；
    2. **数值列统计**（min/max/mean）——回答"量级对不对"；
    3. **低基数列分布**（如 status 的取值计数）——回答"数据长什么样"；
    4. **极值行**——把 min/max 落在哪一行单独拎出来。

    ``min_rows`` 以下不折：行数太少时摘要比原文还长，折了纯亏。
    """

    if not isinstance(payload, dict):
        return None
    if str(payload.get("mode") or "") != "rows":
        # aggregate 模式（只有一个 count）本身已经很小，没有折的必要
        return None
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        return None
    if len(rows) < max(min_rows, max_rows * 2):
        return None
    first = rows[0]
    if not isinstance(first, dict):
        return None

    columns = list(first.keys())
    head = [row for row in rows[:max_rows]]
    tail = [row for row in rows[-max_rows:]]

    numeric: dict[str, dict[str, float]] = {}
    categorical: dict[str, dict[str, int]] = {}
    nulls: dict[str, int] = {}

    for column in columns:
        values = [row.get(column) if isinstance(row, dict) else None for row in rows]
        null_count = sum(1 for value in values if value is None)
        if null_count:
            nulls[column] = null_count

        numbers = [value for value in values if _is_number(value)]
        if numbers and len(numbers) >= len(values) * _NUMERIC_COVERAGE:
            numeric[column] = {
                "min": min(numbers),
                "max": max(numbers),
                "mean": round(sum(numbers) / len(numbers), 4),
            }
            continue

        # 低基数列：给出取值分布（状态、分类这类最有信息量的列）
        distribution: dict[str, int] = {}
        too_many = False
        for value in values:
            if value is None:
                continue
            key = _short(value)
            if key not in distribution and len(distribution) >= _MAX_CATEGORICAL_CARDINALITY:
                too_many = True
                break
            distribution[key] = distribution.get(key, 0) + 1
        if not too_many and distribution:
            categorical[column] = distribution

    # 极值行：每列 min/max 落在哪一行（去重，避免同一行重复出现）
    extremes: list[dict[str, Any]] = []
    seen_indexes: set[int] = set()
    for column, stats in numeric.items():
        for target in (stats["min"], stats["max"]):
            for index, row in enumerate(rows):
                if index in seen_indexes or not isinstance(row, dict):
                    continue
                if row.get(column) == target:
                    seen_indexes.add(index)
                    extremes.append({"row_index": index, "column": column, "value": target, "row": row})
                    break

    summary_payload: dict[str, Any] = {
        "table": payload.get("table"),
        "target": payload.get("target"),
        "row_count": len(rows),
        "truncated": bool(payload.get("truncated")),
        "columns": columns,
        "head": head,
        "tail": tail,
        "numeric": numeric,
        "categorical": categorical,
        "nulls": nulls,
        "extremes": extremes[:4],
    }
    if payload.get("redacted_columns"):
        summary_payload["redacted_columns"] = list(payload["redacted_columns"])

    reduced = Reduced(kind="sql_rows", payload=summary_payload)
    rendered = render_summary(reduced)
    return Reduced(
        kind=reduced.kind,
        payload=reduced.payload,
        original_chars=len(str(rows)),
        reduced_chars=len(rendered),
    )


# ---------------------------------------------------------------------------
# 日志块
# ---------------------------------------------------------------------------


def reduce_log_block(
    text: Any,
    *,
    max_fingerprints: int = 5,
    min_lines: int = 20,
) -> Reduced | None:
    """把日志文本折成"时间范围 + 错误指纹聚类"。

    只在**确实是日志**时归约：认不出时间戳或没有 ERROR/WARN 行就返回 ``None``，
    让调用方保留原文。强行归约一段散文会把信息折没。

    指纹 = 异常类名（有的话）否则关键词集合。**不做中文分词**（复用
    `extract_keywords` 的口径），所以中文日志容易抽不出指纹——那种情况直接放弃归约。
    """

    if not isinstance(text, str) or not text.strip():
        return None
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < min_lines:
        return None

    timestamps = _TS_RE.findall(text)
    if not timestamps:
        # 没有时间戳 → 大概率不是日志，不折
        return None

    severity = {"ERROR": 0, "WARN": 0}
    fingerprints: dict[str, dict[str, Any]] = {}

    for line in lines:
        level_match = _LEVEL_RE.search(line)
        if level_match:
            level = level_match.group(1).upper()
            key = "WARN" if level.startswith("WARN") else level
            severity[key] = severity.get(key, 0) + 1
        if not level_match:
            continue

        exception = _EXC_RE.search(line)
        if exception:
            fingerprint = exception.group(1)
        else:
            keywords = extract_keywords(line)
            if not keywords:
                # 抽不出结构化特征 → 不聚类（宁可不折，也不要伪造归类）
                continue
            fingerprint = "|".join(sorted({keyword.casefold() for keyword in keywords})[:4])

        entry = fingerprints.setdefault(
            fingerprint,
            {"fingerprint": fingerprint, "count": 0, "first_ts": "", "last_ts": "", "sample": ""},
        )
        entry["count"] += 1
        line_ts = _TS_RE.search(line)
        if line_ts:
            stamp = line_ts.group(0)
            if not entry["first_ts"] or stamp < entry["first_ts"]:
                entry["first_ts"] = stamp
            if not entry["last_ts"] or stamp > entry["last_ts"]:
                entry["last_ts"] = stamp
        if not entry["sample"]:
            entry["sample"] = _short(line)

    if not fingerprints:
        return None

    ranked = sorted(fingerprints.values(), key=lambda item: (-item["count"], item["fingerprint"]))
    summary_payload = {
        "line_count": len(lines),
        "time_range": {"first": timestamps[0], "last": timestamps[-1]},
        "severity": severity,
        "fingerprints": ranked[:max_fingerprints],
        "fingerprint_total": len(ranked),
    }
    reduced = Reduced(kind="log_block", payload=summary_payload)
    rendered = render_summary(reduced)
    return Reduced(
        kind=reduced.kind,
        payload=reduced.payload,
        original_chars=len(text),
        reduced_chars=len(rendered),
    )


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------


def render_summary(reduced: Reduced) -> str:
    """把归约结果渲染成给模型看的短文本（T3.3 会在这后面追加句柄标记）。"""

    if not isinstance(reduced, Reduced):
        return ""
    data = reduced.payload or {}
    if reduced.kind == "sql_rows":
        return _render_sql(data)
    if reduced.kind == "log_block":
        return _render_log(data)
    return ""


def _render_sql(data: dict[str, Any]) -> str:
    lines = [
        f"[已归约] {data.get('table') or '?'}（target={data.get('target') or '?'}）"
        f" 共 {data.get('row_count')} 行"
        + ("（结果被截断）" if data.get("truncated") else "")
    ]
    if data.get("columns"):
        lines.append("列：" + ", ".join(str(c) for c in data["columns"]))
    if data.get("numeric"):
        parts = [
            f"{column} min={stats['min']} max={stats['max']} mean={stats['mean']}"
            for column, stats in data["numeric"].items()
        ]
        lines.append("数值：" + "；".join(parts))
    if data.get("categorical"):
        parts = []
        for column, dist in data["categorical"].items():
            pairs = sorted(dist.items(), key=lambda item: -item[1])[:6]
            parts.append(f"{column} {{{', '.join(f'{k}={v}' for k, v in pairs)}}}")
        lines.append("分布：" + "；".join(parts))
    if data.get("nulls"):
        lines.append("空值：" + "；".join(f"{k}={v}" for k, v in data["nulls"].items()))
    if data.get("redacted_columns"):
        lines.append("已脱敏列：" + ", ".join(data["redacted_columns"]))
    if data.get("head"):
        lines.append("首若干行：" + " | ".join(_short(row) for row in data["head"]))
    if data.get("tail"):
        lines.append("尾若干行：" + " | ".join(_short(row) for row in data["tail"]))
    if data.get("extremes"):
        parts = [
            f"第 {item['row_index']} 行 {item['column']}={item['value']}"
            for item in data["extremes"]
        ]
        lines.append("极值行：" + "；".join(parts))
    return "\n".join(lines)


def _render_log(data: dict[str, Any]) -> str:
    span = data.get("time_range") or {}
    lines = [
        f"[已归约] 日志 {data.get('line_count')} 行，时间范围 {span.get('first')} ~ {span.get('last')}",
    ]
    severity = data.get("severity") or {}
    shown = [f"{k} {v}" for k, v in severity.items() if v]
    if shown:
        lines.append("级别：" + "、".join(shown))
    for item in data.get("fingerprints") or []:
        lines.append(
            f"- {item['fingerprint']} ×{item['count']}"
            f"（{item.get('first_ts') or '?'} ~ {item.get('last_ts') or '?'}）"
            f" 例：{item.get('sample', '')}"
        )
    total = data.get("fingerprint_total") or 0
    shown_count = len(data.get("fingerprints") or [])
    if total > shown_count:
        lines.append(f"（共 {total} 种指纹，已列前 {shown_count} 种）")
    return "\n".join(lines)
