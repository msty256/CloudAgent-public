#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""逐例比对「诊断结论」与「GT match_terms」，用来估词表假阴性率。

不是评测器的一部分——这是**人工抽查的辅助工具**：把每例的
GT 要求词、诊断实际写的词、以及"哪个词没出现"摆在一起，
再由人判断是「真没答对」还是「答对了但说法不同」。

用法：
    python eval/audit_terms.py <run_dir>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_gt(case_id: str, domain: str) -> dict:
    path = ROOT / "cloudagent_ext" / "diagnosis" / "cases" / domain / f"{case_id}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _cause_text(cause: dict) -> str:
    parts = [str(cause.get("description") or "")]
    for key in ("supporting_evidence_ids", "counter_evidence"):
        value = cause.get(key)
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
    return " ".join(parts)


def audit(run_dir: Path) -> None:
    cases_dir = run_dir / "cases"
    for case_file in sorted(cases_dir.glob("*.json")):
        data = json.loads(case_file.read_text(encoding="utf-8"))
        case_id = data.get("case_id") or case_file.stem
        domain = case_id.split("-")[0]
        gt = _load_gt(case_id, domain)
        gt_causes = (gt.get("ground_truth") or {}).get("root_causes") or []

        print("=" * 78)
        print(f"{case_id}  类别={data.get('category')}  模型={data.get('meta', {}).get('model') or '?'}")
        raw = data.get("raw_output") or ""
        try:
            parsed = json.loads(raw)
        except Exception:
            print("  ⚠ 输出不是纯 JSON，跳过词表比对")
            continue

        outs = parsed.get("root_causes") or []
        outs_text = [_cause_text(c) for c in outs]
        outs_all = " ".join(outs_text)

        print(f"  诊断 status={parsed.get('status')}  根因数={len(outs)}  证据数={len(parsed.get('evidence') or [])}")
        print("  --- GT 要求 ---")
        for idx, gc in enumerate(gt_causes, 1):
            terms = gc.get("match_terms") or []
            print(f"   GT{idx} severity={gc.get('severity')} terms={terms}")
            print(f"        描述：{str(gc.get('description'))[:110]}")
            for term in terms:
                hit_out = term in outs_all
                where = ""
                if hit_out:
                    for oi, text in enumerate(outs_text, 1):
                        if term in text:
                            where = f"（在诊断 RC{oi}）"
                            break
                mark = "✓" if hit_out else "✗"
                print(f"        {mark} {term!r} {where}")
        print("  --- 诊断给的根因 ---")
        for idx, (cause, text) in enumerate(zip(outs, outs_text), 1):
            conf = cause.get("confidence")
            print(f"   D{idx} conf={conf}  {text[:150]}")
        print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        runs = sorted((ROOT / "eval" / "runs").glob("*"), key=lambda p: p.stat().st_mtime)
        if not runs:
            raise SystemExit("没有可审计的 run")
        target = runs[-1]
    else:
        target = Path(sys.argv[1])
    audit(target)
