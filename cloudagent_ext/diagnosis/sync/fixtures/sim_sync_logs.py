#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""同步域仿真日志生成器（变更 add-sync-analysis-skill，design D8）。

与 ``log/fixtures/sim_logs.py`` **刻意分开**：后者写死 ``svc-a.log`` / ``svc-b.log``
且内容为 log-001 的 NPE 场景，共用一个目录会文件名冲突，也会把两个域的 GT
绑在一起。

本模块覆盖三种同步失败形态（确定性时间戳，便于按时间窗与 trace 断言）：

* ``sync-gateway.log``：增量任务超时，未产出下游批次（``sync-002``）
* ``consumer.log``：消息重复消费，同一业务键处理两次（``sync-003``）
* ``bizsvc.log``：业务校验失败，消费成功但数据未落库（``sync-003``）

用法::

    python -m cloudagent_ext.diagnosis.sync.fixtures.sim_sync_logs
    # → 写到仓库根 logs-sim/（与 log 域夹具同目录），并把路径打印出来
    # 然后把 CLOUDAGENT_LOG_ROOT 指向该目录

**约定落点**：``DEFAULT_LOG_DIR = logs-sim``（相对当前工作目录，与 log 域的夹具同目录——
文件名不冲突，且 ``CLOUDAGENT_LOG_ROOT`` 只能指一个根，分目录会让一个域查不到另一个域的日志）。之所以要固定，
是因为真实跑批时主 Agent 会"猜"日志目录——2026-10-22 的实跑就猜到了
``logs-sim/``（log-001 的旧夹具），于是 sync 关键词全部 0 命中、断点无法定位。
"""

from __future__ import annotations

from pathlib import Path

TRACE_SYNC_002 = "d1e2f3a4b5c60718293a4b5c6d7e8f90"
TRACE_SYNC_003 = "e5f6a7b8c9d00112233445566778899a"
TRACE_SYNC_003_DUP = "f9a8b7c6d5e40112233445566778899b"

_GATEWAY = """\
2026-10-22 09:00:00.120 INFO  [sync-scheduler-1] com.example.sync.Gateway - tenant task started tenant=tenant-003 mode=incremental [%(t2)s]
2026-10-22 09:00:02.400 INFO  [sync-scheduler-1] com.example.sync.Gateway - querying upstream orders where created_at >= 2026-10-22T08:00:00 [%(t2)s]
2026-10-22 09:00:41.900 WARN  [sync-scheduler-1] com.example.sync.Gateway - upstream query slow elapsed=39s rows=18234 [%(t2)s]
2026-10-22 09:01:00.000 ERROR [sync-scheduler-1] com.example.sync.Gateway - task aborted: java.util.concurrent.TimeoutException: batch window exceeded 60s [%(t2)s]
\tat com.example.sync.Gateway.awaitBatch(Gateway.java:214)
\tat com.example.sync.Gateway.runTask(Gateway.java:131)
2026-10-22 09:01:00.010 WARN  [sync-scheduler-1] com.example.sync.Gateway - no downstream batch produced; checkpoint NOT advanced [%(t2)s]
""" % {"t2": TRACE_SYNC_002}

_CONSUMER = """\
2026-10-22 09:05:10.000 INFO  [consumer-2] com.example.sync.Consumer - polled offset=8842 partition=3 count=25 [%(t3)s]
2026-10-22 09:05:10.450 INFO  [consumer-2] com.example.sync.Consumer - handled message key=order-12345 attempt=1 [%(t3)s]
2026-10-22 09:05:11.000 INFO  [consumer-2] com.example.sync.Consumer - offset committed 8842 [%(t3)s]
2026-10-22 09:05:11.200 WARN  [consumer-2] com.example.sync.Consumer - rebalance triggered; offset rewind to 8842 [%(t3)s]
2026-10-22 09:05:11.900 INFO  [consumer-2] com.example.sync.Consumer - handled message key=order-12345 attempt=2 (duplicate delivery) [%(dup)s]
2026-10-22 09:05:12.100 INFO  [consumer-2] com.example.sync.Consumer - offset committed 8842 [%(dup)s]
""" % {"t3": TRACE_SYNC_003, "dup": TRACE_SYNC_003_DUP}

_BIZSVC = """\
2026-10-22 09:05:10.600 INFO  [pool-1] com.example.biz.OrderHandler - validating order key=order-12345 tenant=tenant-003 [%(t3)s]
2026-10-22 09:05:10.900 ERROR [pool-1] com.example.biz.OrderHandler - validation failed: java.lang.IllegalStateException: tenant region mismatch expected=north actual=south [%(t3)s]
\tat com.example.biz.OrderValidator.checkRegion(OrderValidator.java:88)
\tat com.example.biz.OrderHandler.apply(OrderHandler.java:53)
2026-10-22 09:05:11.000 WARN  [pool-1] com.example.biz.OrderHandler - order not persisted (idempotency key computed but insert skipped) [%(t3)s]
""" % {"t3": TRACE_SYNC_003}


def write_sim_sync_logs(target_dir: Path) -> dict[str, object]:
    """生成同步域仿真日志到 *target_dir*，返回 trace 元信息。"""

    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "sync-gateway.log").write_text(_GATEWAY, encoding="utf-8")
    (target_dir / "consumer.log").write_text(_CONSUMER, encoding="utf-8")
    (target_dir / "bizsvc.log").write_text(_BIZSVC, encoding="utf-8")
    return {
        "dir": str(target_dir),
        "trace_sync_002": TRACE_SYNC_002,
        "trace_sync_003": TRACE_SYNC_003,
        "trace_sync_003_duplicate": TRACE_SYNC_003_DUP,
    }


DEFAULT_LOG_DIR = "logs-sim"


def write_default_sim_sync_logs(root: str | Path = ".") -> dict[str, object]:
    """写到 ``<root>/logs-sim``（约定落点），返回元信息与绝对路径。"""

    return write_sim_sync_logs(Path(root) / DEFAULT_LOG_DIR)


__all__ = [
    "DEFAULT_LOG_DIR",
    "write_default_sim_sync_logs",
    "TRACE_SYNC_002",
    "TRACE_SYNC_003",
    "TRACE_SYNC_003_DUP",
    "write_sim_sync_logs",
]


if __name__ == "__main__":
    info = write_default_sim_sync_logs(".")
    print("logs written to:", Path(str(info["dir"])).resolve())
    print("export CLOUDAGENT_LOG_ROOT=" + str(Path(str(info["dir"])).resolve()))
