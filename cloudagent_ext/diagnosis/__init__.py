#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""CloudAgent 研发问题诊断域（data model layer）。

本包承载「企业研发问题诊断工作台」的领域数据模型（诊断请求 / 调查任务 /
证据 / 候选根因 / 统一诊断结果），供主 Agent（CloudAgent）与四个专业
子 Agent（sql-diagnosis / code-analysis / log-analysis / sync-diagnosis）
共用。

边界说明：``cloudagent_ext.diagnostics``（复数）是运行时自检模块
（freeze 配置与恢复），与本包的诊断业务域无关，两者不要混用。

设计依据：``docs/cloudagent-development-guide.md`` §5.2–§5.5；
变更记录：``openspec/changes/add-diagnosis-data-model``。
"""

from cloudagent_ext.diagnosis.models import (
    EVIDENCE_SOURCE_AGENT,
    EVIDENCE_SOURCE_DATABASE,
    EVIDENCE_SOURCE_GIT,
    EVIDENCE_SOURCE_KAFKA,
    EVIDENCE_SOURCE_LOG,
    EVIDENCE_SOURCE_OTHER,
    EVIDENCE_SOURCE_SYNC_JOB,
    EVIDENCE_SOURCE_TOOL,
    EVIDENCE_SOURCE_USER,
    STATUS_FAILED,
    STATUS_PARTIAL,
    STATUS_SUCCESS,
    VALID_STATUSES,
    DiagnosisRequest,
    DiagnosisResult,
    Evidence,
    InvestigationTask,
    RootCause,
    new_evidence_id,
    new_id,
    new_request_id,
    new_task_id,
)

__all__ = [
    # 状态常量
    "STATUS_SUCCESS",
    "STATUS_PARTIAL",
    "STATUS_FAILED",
    "VALID_STATUSES",
    # 证据来源词表
    "EVIDENCE_SOURCE_DATABASE",
    "EVIDENCE_SOURCE_GIT",
    "EVIDENCE_SOURCE_LOG",
    "EVIDENCE_SOURCE_KAFKA",
    "EVIDENCE_SOURCE_SYNC_JOB",
    "EVIDENCE_SOURCE_TOOL",
    "EVIDENCE_SOURCE_AGENT",
    "EVIDENCE_SOURCE_USER",
    "EVIDENCE_SOURCE_OTHER",
    # 数据模型
    "DiagnosisRequest",
    "InvestigationTask",
    "Evidence",
    "RootCause",
    "DiagnosisResult",
    # 关联标识辅助
    "new_id",
    "new_request_id",
    "new_task_id",
    "new_evidence_id",
]
