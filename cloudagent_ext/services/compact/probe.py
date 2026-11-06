#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""压缩管线探针：在 CLI 里直接看"折"的效果（阶段 3 · T3.3 的验收工具）。

**为什么需要它**：压缩的默认门槛是"上下文到窗口 60%"（``gate_skip_ratio=0.6``），
普通会话根本到不了，所以**默认配置下你在 REPL 里永远看不到压缩发生**。
这个探针绕过门槛，构造一段确定的会话直接跑管线，把 before/after 打出来。

用法::

    # 看结构归约（阶段 3）的效果
    python -m cloudagent_ext.services.compact.probe

    # 对比：关掉归约，看改造前的行为（取证结果一字不动）
    python -m cloudagent_ext.services.compact.probe --no-sr

    # 看 microcompact（清空语义）对照
    python -m cloudagent_ext.services.compact.probe --mc

全程离线：压缩本身不调模型（LLM 摘要档位默认关闭）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

from cloudagent_ext.services.compact.evidence_store import EvidenceStore
from cloudagent_ext.services.compact.pipeline import CompressionPipeline, PipelineConfig
from cloudagent_ext.types.messages import create_assistant_message, create_user_message

__all__ = ["build_probe_conversation", "run_probe", "main"]


def _rows(count: int = 200) -> list[dict]:
    return [
        {
            "id": index,
            "order_no": f"order-{index}",
            "tenant_id": f"tenant-{index % 8:03d}",
            "amount": 999_999.0 if index == count // 2 else float(index * 10),
            "status": "paid" if index % 2 else "pending",
        }
        for index in range(1, count + 1)
    ]


def _tool_use(block_id: str, name: str) -> dict:
    return {"type": "tool_use", "id": block_id, "name": name, "input": {}}


def _tool_result(block_id: str, content: str, *, metadata: dict | None = None) -> dict:
    block = {"type": "tool_result", "tool_use_id": block_id, "content": content}
    if metadata is not None:
        block["metadata"] = metadata
    return block


def build_probe_conversation(*, rows: int = 200, history: int = 6, results: int = 2) -> list:
    """构造一段"有 N 条大取证结果 + 若干历史"的会话。

    默认两条：**第一条是"上一轮查的"、第二条是"本轮刚查的"**。
    这样探针能同时演示两件事：

    * 历史那条被折成摘要（省下来）；
    * 本轮那条被 `keep_recent` 保住（模型还能看到明细）。

    取证的 output 里刻意包含一个离群值——归约如果把它吃掉了，输出里立刻能看出来。
    """

    messages: list = [create_user_message("订单列表接口变慢了，帮我查原因")]
    for index in range(results):
        block_id = f"t-db-{index}"
        table = "public.orders" if index == 0 else "public.orders_latest"
        payload = {
            "mode": "rows",
            "table": table,
            "target": "primary",
            "returned": rows,
            "truncated": True,
            "rows": _rows(rows),
        }
        body = json.dumps(payload, ensure_ascii=False)
        messages.append(
            create_assistant_message([_tool_use(block_id, "query_table_rows")])
        )
        messages.append(
            create_user_message([_tool_result(block_id, body, metadata={"output": payload})])
        )
        # 每条结果后面垫几轮普通对话，模拟"隔了一轮"
        for step in range(history // max(results, 1)):
            messages.append(create_assistant_message(f"第 {index}-{step} 轮分析"))
            messages.append(create_user_message(f"继续（{index}-{step}）"))
    return messages


def _total_chars(messages) -> int:
    total = 0
    for message in messages:
        content = getattr(message, "content", None)
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            for block in content:
                value = block.get("content") if isinstance(block, dict) else getattr(block, "content", None)
                if isinstance(value, str):
                    total += len(value)
    return total


def run_probe(
    *,
    sr_enabled: bool = True,
    mc_enabled: bool = False,
    rows: int = 200,
    keep_recent: int = 1,
) -> dict:
    """跑一次探针，返回统计（不打印，便于测试复用）。"""

    messages = build_probe_conversation(rows=rows)
    before = _total_chars(messages)

    with tempfile.TemporaryDirectory(prefix="probe-evidence-") as tmp:
        config = PipelineConfig(
            sr_enabled=sr_enabled,
            sr_session_id="probe-session",
            sr_evidence_root=tmp,
            sr_keep_recent=keep_recent,
            mc_enabled=mc_enabled,
        )
        result = asyncio.run(CompressionPipeline(config).run(messages, input_token_count=0))
        after = _total_chars(result.messages)

        # 句柄能不能取回原文
        store = EvidenceStore(root=Path(tmp))
        handles = list((result.reduce_stats or {}).get("handles") or [])
        reloaded = {}
        for handle in handles:
            payload = store.load("probe-session", handle)
            reloaded[handle] = len(payload) if payload else 0

        first_result = ""
        for message in result.messages:
            content = getattr(message, "content", None)
            if isinstance(content, list):
                for block in content:
                    text = block.get("content") if isinstance(block, dict) else getattr(block, "content", None)
                    if isinstance(text, str) and text.startswith("[已归约]"):
                        first_result = text
                        break
            if first_result:
                break

    return {
        "chars_before": before,
        "chars_after": after,
        "layers_applied": list(result.layers_applied),
        "reduce_stats": dict(result.reduce_stats or {}),
        "handles": handles,
        "reloaded_sizes": reloaded,
        "sample": first_result,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="压缩管线探针（离线）")
    parser.add_argument("--no-sr", action="store_true", help="关闭结构归约（看改造前行为）")
    parser.add_argument("--mc", action="store_true", help="同时开启 microcompact（清空语义对照）")
    parser.add_argument("--rows", type=int, default=200, help="构造多少行结果（默认 200）")
    parser.add_argument(
        "--keep-recent",
        type=int,
        default=1,
        help="最新几条取证结果不折（默认 1：本轮刚查的保留明细）",
    )
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)

    stats = run_probe(
        sr_enabled=not args.no_sr,
        mc_enabled=args.mc,
        rows=args.rows,
        keep_recent=args.keep_recent,
    )
    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0

    before, after = stats["chars_before"], stats["chars_after"]
    ratio = f"{(1 - after / before) * 100:.1f}%" if before else "0%"
    print(f"会话字符数：{before} → {after}（-{ratio}）")
    print(f"生效层：{'、'.join(stats['layers_applied']) or '（无）'}")
    reduce_stats = stats["reduce_stats"] or {}
    if reduce_stats:
        print(
            f"结构归约：{reduce_stats.get('reduced_count', 0)} 条，"
            f"失败 {reduce_stats.get('failures', 0)} 条，"
            f"省 {reduce_stats.get('saved_chars', 0)} 字符"
        )
    if stats["handles"]:
        print(f"句柄：{', '.join(stats['handles'])}")
        for handle, size in stats["reloaded_sizes"].items():
            state = f"{size} 字符" if size else "❌ 取不回"
            print(f"  {handle} → 回取 {state}")
    if stats["sample"]:
        print("\n--- 替换后的结果（前 600 字）---")
        print(stats["sample"][:600])
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
