#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""仿真日志生成器（P3.3 ``add-log-analysis-domain``，确定性）。

生成一组 logback 风格日志（两服务 + 轮转文件 + 不可解析的 .gz），供：

* 本变更的工具测试（``monkeypatch.setenv("CLOUDAGENT_LOG_ROOT", 生成目录)``）；
* **P3.5 日志案例复用同一生成逻辑**（GT 与实测同源，P2-2 决策）。

覆盖：完整 trace 事件链、**首异常在 svc-b + 级联到 svc-a**、traceId 缺失
（仅在 svc-a 出现）、**跨小时边界（09:59 → 10:00）**、**多行 Java 异常栈
（Caused by）**、**含 PII 的日志行**。
"""

from __future__ import annotations

from pathlib import Path

# 固定 trace 与时间（确定性：测试与案例可依赖）
TRACE_FULL = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
TRACE_PARTIAL = "bbbbbbbbccccccccddddeeeeffff0000"
TRACE_MISSING = "cccccccccccccccccccccccccccccccc"
# P1-1（实现审查）：非纯 hex 的 traceId 形态（真实世界常见），用于回归
TRACE_NONHEX = "trace-abc-123"

_SVC_A = """\
2026-10-18 09:59:58.000 INFO [http-nio-8080-exec-1] com.example.svca.Controller - request received path=/orders query=region=north [%(full)s]
2026-10-18 09:59:58.100 INFO [http-nio-8080-exec-1] com.example.svca.Controller - calling svc-b via Feign [%(full)s]
2026-10-18 10:00:00.200 ERROR [http-nio-8080-exec-1] com.example.svca.Service - request failed: downstream svc-b error [%(full)s]
2026-10-18 10:00:00.201 ERROR [http-nio-8080-exec-1] com.example.svca.Service - feign.RetryableException: 500 from svc-b [%(full)s]
\tat com.example.svca.Service.callSvcB(Service.java:88)
\tat com.example.svca.Controller.query(Controller.java:42)
Caused by: com.example.svca.DownstreamException: downstream returned 500
\tat com.example.svca.client.SvcBClient.get(SvcBClient.java:31)
2026-10-18 10:00:01.000 INFO [task-1] com.example.svca.Audit - audit user phone=13800138000 email=alice@example.com password=secret123 [%(partial)s]
2026-10-18 10:00:02.500 WARN [task-1] com.example.svca.Audit - slow audit write took 1200ms [%(missing)s]
2026-10-18 10:00:03.000 INFO [http-nio-8080-exec-2] com.example.svca.Controller - non-hex trace id accepted (real world form) [%(nonhex)s]
""" % {"full": TRACE_FULL, "partial": TRACE_PARTIAL, "missing": TRACE_MISSING, "nonhex": TRACE_NONHEX}

_SVC_B = """\
2026-10-18 09:59:59.500 INFO [exec-1] com.example.svcb.Client - received order query [%(full)s]
2026-10-18 09:59:59.900 INFO [exec-1] com.example.svcb.Repository - loading order rows [%(full)s]
2026-10-18 10:00:00.100 ERROR [exec-1] com.example.svcb.Repository - java.lang.NullPointerException: tenant config missing [%(full)s]
\tat com.example.svcb.Repository.resolveTenant(Repository.java:120)
\tat com.example.svcb.Repository.query(Repository.java:75)
\tat com.example.svcb.Client.handle(Client.java:55)
Caused by: java.util.NoSuchElementException: no tenant config for region=north
\tat com.example.svcb.config.TenantConfig.load(TenantConfig.java:44)
""" % {"full": TRACE_FULL}

_SVC_A_ROTATED = """\
2026-10-18 09:00:00.000 INFO [main] com.example.svca.Boot - started [%(full)s]
""" % {"full": TRACE_FULL}


def write_sim_logs(target_dir: Path) -> dict[str, object]:
    """生成仿真日志到 *target_dir*，返回元信息（供测试/案例断言）。"""

    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "svc-a.log").write_text(_SVC_A, encoding="utf-8")
    (target_dir / "svc-b.log").write_text(_SVC_B, encoding="utf-8")
    # 轮转日志（*.log* 应匹配；验证 P3-2 的轮转命名）
    (target_dir / "svc-a.log.1").write_text(_SVC_A_ROTATED, encoding="utf-8")
    # 压缩日志（.gz 不解析，列入 skipped_files）
    (target_dir / "svc-c.log.gz").write_bytes(b"\x1f\x8b\x08\x00\x00\x00\x00\x00")
    return {
        "dir": str(target_dir),
        "trace_full": TRACE_FULL,
        "trace_partial": TRACE_PARTIAL,
        "trace_missing": TRACE_MISSING,
    }


__all__ = [
    "TRACE_FULL",
    "TRACE_NONHEX",
    "TRACE_PARTIAL",
    "TRACE_MISSING",
    "write_sim_logs",
]
