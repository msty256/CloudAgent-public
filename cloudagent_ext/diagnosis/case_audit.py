#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""case 集体检工具（2026-11-01 体检后新增）。

**它回答一个问题：这套题里，有多少条标准答案是我能在这儿核对对错的？**

起因：`code-007` 重跑后 Top-1 = 0%，查下去发现是 `ground_truth` 描述的是**旧行为**。
再一查，38 题里只有 15 题能在仓库内核实——**评测集的正确性无法在 CI 里保证**，
而"正确率"却在照常用这 38 题算。

所以这个模块把 `ground_truth.verification` 的分布显式打出来：

* ``static``   —— 对着仓库内代码/fixture 能核，可复查；
* ``runtime``  —— 要真实数据库或运行期证据；
* ``external`` —— 依赖仓库外的样本项目，本仓无法判定。

**算正确率时只该用前两类。** 把 external 混进去，等于让"判不了的题"稀释成好看的数字。

用法::

    python -m cloudagent_ext.diagnosis.case_audit
    python -m cloudagent_ext.diagnosis.case_audit --domain code
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

__all__ = [
    "VERIFICATION_ORDER",
    "audit_cases",
    "format_audit",
    "main",
]

VERIFICATION_ORDER: tuple[str, ...] = ("static", "runtime", "external")

_CASES_ROOT = Path(__file__).with_name("cases")


def _case_rows(domain: str | None = None) -> list[dict[str, Any]]:
    """读出所有 case 的 id / 域 / verification（不做校验，坏数据也要能报出来）。"""

    rows: list[dict[str, Any]] = []
    for path in sorted(_CASES_ROOT.glob("*/*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        case_id = data.get("case_id")
        if not case_id:  # routing/*.json 是容器文件，不是单题
            continue
        case_domain = data.get("domain") or path.parent.name
        if domain and case_domain != domain:
            continue
        gt = data.get("ground_truth") or {}
        rows.append(
            {
                "case_id": case_id,
                "domain": case_domain,
                "verification": str(gt.get("verification") or ""),
                "verified_against": str(gt.get("verified_against") or ""),
            }
        )
    return rows


def audit_cases(cases: Iterable[dict[str, Any]] | None = None, *, domain: str | None = None) -> dict:
    """汇总 verification 分布。

    **两个口径必须分开报**，因为它们的含义完全不同：

    * ``statically_verifiable`` —— 现在就能对着代码/fixture 复核的题（= static）；
    * ``needs_runtime_env``    —— 语义上可判定，但**要有真实 DB / 现场日志**；
      本仓当前没有 sql seed 也没有 PG，所以这批"理论可核、实际没核过"；
    * ``unverifiable``         —— 依赖仓外项目，本仓永远判不了（= external）。

    正确率的分母**只能是第一个**。把 runtime 混进去，会得到一个
    "看起来能跑、其实一次都没跑过"的数字——这正是本次体检要防的事。
    """

    rows = list(cases) if cases is not None else _case_rows(domain)
    by: dict[str, list[str]] = {key: [] for key in VERIFICATION_ORDER}
    missing: list[str] = []
    for row in rows:
        value = str(row.get("verification") or "")
        if value in by:
            by[value].append(row["case_id"])
        else:
            missing.append(row["case_id"])
    total = len(rows)
    static = len(by["static"])
    runtime = len(by["runtime"])
    external = len(by["external"])
    return {
        "total": total,
        "by_verification": by,
        "missing": missing,
        "statically_verifiable": static,
        "needs_runtime_env": runtime,
        "unverifiable": external,
        # 唯一可以进正确率分母的数字
        "measurable_now": static,
        "measurable_now_ratio": round(static / total, 3) if total else 0.0,
        # 有环境**才**能核的（不是现在能核的）
        "measurable_with_env": static + runtime,
        "cases": rows,
    }


def format_audit(summary: dict[str, Any]) -> str:
    total = summary["total"]
    static = summary["statically_verifiable"]
    runtime = summary["needs_runtime_env"]
    external = summary["unverifiable"]
    ratio = summary["measurable_now_ratio"]
    lines = [
        f"共 {total} 题",
        f"  现在就能复核（static）   {static:>3} 题（{ratio:.0%}）← 正确率只能用这批",
        f"  需运行期环境（runtime）  {runtime:>3} 题 ← 有 DB/seed 才能核，当前跑不了",
        f"  无法复核（external）     {external:>3} 题 ← 依赖仓外项目，永久不可判",
        "",
    ]
    labels = {
        "static": "可静态核实",
        "runtime": "需运行期证据",
        "external": "依赖仓外项目",
    }
    for key in VERIFICATION_ORDER:
        ids = summary["by_verification"][key]
        if not ids:
            continue
        lines.append(f"[{key}] {labels[key]}（{len(ids)}）")
        lines.append("  " + ", ".join(ids))
    if summary["missing"]:
        lines.append("")
        lines.append(f"缺 verification 字段：{len(summary['missing'])} 题")
        lines.append("  " + ", ".join(summary["missing"]))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="case 集体检：标准答案的可核性分布")
    parser.add_argument("--domain", default=None, help="只看某个域（code/sql/log/cross/sync）")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)

    summary = audit_cases(domain=args.domain)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(format_audit(summary))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
