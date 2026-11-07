#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""``cloudagent eval-run`` 薄入口（EVAL-P1a）。

用法::

    cloudagent eval-run --request req.json --out rec.json

退出码：成功 ``0`` / 请求非法 ``2`` / 执行失败 ``1``（执行失败**仍写出
RunRecord**，``outcome.status`` 标失败——失败样本对评测同样有价值）。
stdout 只打一行摘要，不刷屏。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

__all__ = ["run_eval_run"]


def run_eval_run(argv: list[str] | None = None, *, executor: Any = None) -> int:
    """执行一个 RunRequest 并写出 RunRecord。

    ``executor`` 仅供测试注入（fake executor，零模型成本）；
    生产路径不传，走真实 ``LiveExecutor``。
    """

    from cloudagent_ext.diagnosis.eval_support.execute import execute_case, write_record
    from cloudagent_ext.diagnosis.eval_support.record import (
        RunRequestError,
        request_from_json,
    )
    from cloudagent_ext.utils.redaction import redact_sensitive

    parser = argparse.ArgumentParser(
        prog="eval-run",
        description="执行一个评测请求并写出 RunRecord（只执行，不评分）",
    )
    parser.add_argument("--request", required=True, help="RunRequest JSON 文件路径")
    parser.add_argument("--out", required=True, help="RunRecord JSON 输出路径")
    args = parser.parse_args(argv)

    try:
        payload = json.loads(Path(args.request).read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"eval-run: 读取请求失败：{redact_sensitive(str(exc))}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"eval-run: 请求不是合法 JSON：{exc}", file=sys.stderr)
        return 2

    try:
        request = request_from_json(payload)
    except RunRequestError as exc:
        print(f"eval-run: 非法请求：{exc}", file=sys.stderr)
        return 2

    try:
        record = execute_case(request, executor=executor)
    except Exception as exc:  # noqa: BLE001 — 执行层失败如实记录（脱敏）
        print(f"eval-run: 执行失败：{redact_sensitive(str(exc))}", file=sys.stderr)
        return 1

    write_record(record, args.out)
    elapsed = int(round(record.elapsed_sec))
    print(
        f"eval-run: {record.record_id} "
        f"status={record.outcome['status']} elapsed={elapsed}s"
    )
    # 失败样本也已落盘（对评测有价值），但退出码如实反映执行结果
    return 0 if record.outcome["status"] == "ok" else 1
