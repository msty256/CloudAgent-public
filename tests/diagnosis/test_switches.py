#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""机制开关测试（阶段 5 · 对照实验的底座）。

对照实验的可信度**完全依赖开关是真的**。如果某个开关"声明关了但实际还开着"，
跑出来的两臂差异就是假的——而且从数据上一点看不出来。

所以这里的断言分两层：

1. **语义**：`env_flag` 只认明确的真假写法，认不出就退回默认（不猜）；
2. **生效**：关掉开关以后，机制**确实不再产生作用**（不是只看变量读到了）。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from cloudagent_ext.diagnosis.models import DiagnosisRequest, DiagnosisResult, Evidence, Gap
from cloudagent_ext.diagnosis.runtime_session import (
    DiagnosisSessionRuntime,
    propagate_invalidation,
)
from cloudagent_ext.diagnosis.session import InvestigationSession, SessionBudget
from cloudagent_ext.diagnosis.switches import (
    ENV_CONTEXT_REDUCE,
    ENV_EVIDENCE_INVALIDATION,
    context_reduce_enabled,
    env_flag,
    evidence_invalidation_enabled,
)


class TestEnvFlagSemantics:
    def test_unset_returns_default(self, monkeypatch) -> None:
        monkeypatch.delenv("CLOUDAGENT_TEST_FLAG", raising=False)
        assert env_flag("CLOUDAGENT_TEST_FLAG", True) is True
        assert env_flag("CLOUDAGENT_TEST_FLAG", False) is False

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " y "])
    def test_truthy(self, monkeypatch, value: str) -> None:
        monkeypatch.setenv("CLOUDAGENT_TEST_FLAG", value)
        assert env_flag("CLOUDAGENT_TEST_FLAG", False) is True

    @pytest.mark.parametrize("value", ["0", "false", "No", "off", "n"])
    def test_falsy(self, monkeypatch, value: str) -> None:
        monkeypatch.setenv("CLOUDAGENT_TEST_FLAG", value)
        assert env_flag("CLOUDAGENT_TEST_FLAG", True) is False

    @pytest.mark.parametrize("value", ["maybe", "", "  ", "2"])
    def test_unrecognised_falls_back_to_default(self, monkeypatch, value: str) -> None:
        """认不出就退回默认——**不猜**。

        猜错会让"我以为关了但没关"这种问题永远查不出来。
        """

        monkeypatch.setenv("CLOUDAGENT_TEST_FLAG", value)
        assert env_flag("CLOUDAGENT_TEST_FLAG", True) is True
        assert env_flag("CLOUDAGENT_TEST_FLAG", False) is False


class TestDefaultsMatchProduction:
    """不设环境变量时，行为必须与加开关之前一致。"""

    def test_both_enabled_by_default(self, monkeypatch) -> None:
        monkeypatch.delenv(ENV_CONTEXT_REDUCE, raising=False)
        monkeypatch.delenv(ENV_EVIDENCE_INVALIDATION, raising=False)
        assert context_reduce_enabled() is True
        assert evidence_invalidation_enabled() is True


def _runtime() -> DiagnosisSessionRuntime:
    return DiagnosisSessionRuntime(
        session=InvestigationSession(
            DiagnosisRequest(request_id="req-1", question="q"), budget=SessionBudget(15, 5)
        )
    )


def _conflict_result() -> DiagnosisResult:
    evidence = Evidence(
        evidence_id="ev:sql:7",
        source_type="sql",
        source_ref="orders",
        observation="count 由 0 变为 5",
        relation=[{"kind": "conflict", "with": "ev:sql:1"}],
    )
    return DiagnosisResult(
        request_id="req-1",
        agent_name="sql-diagnosis",
        status="success",
        summary="s",
        evidence=[evidence],
        next_steps=[],
        limitations=[],
    )


def _resolved(runtime: DiagnosisSessionRuntime) -> Gap:
    runtime.gap_store.add_existing(
        Gap(gap_id="gap-1", statement="核对 orders 表 order-1", status="open")
    )
    runtime.gap_store.mark_resolved("gap-1", evidence_id="ev:sql:1")
    return runtime.gap_store.gaps()[0]


class TestInvalidationSwitchActuallyWorks:
    def test_on_reverts(self, monkeypatch) -> None:
        monkeypatch.delenv(ENV_EVIDENCE_INVALIDATION, raising=False)
        runtime = _runtime()
        gap = _resolved(runtime)
        assert propagate_invalidation(runtime, _conflict_result()) == 1
        assert gap.status == "open"

    def test_off_does_not_revert(self, monkeypatch) -> None:
        monkeypatch.setenv(ENV_EVIDENCE_INVALIDATION, "off")
        runtime = _runtime()
        gap = _resolved(runtime)
        assert propagate_invalidation(runtime, _conflict_result()) == 0
        assert gap.status == "resolved", "声明关掉了，就不能再回退"
        assert gap.revert_count == 0


class TestReduceSwitchActuallyWorks:
    def _messages(self) -> list:
        from cloudagent_ext.types.messages import create_assistant_message, create_user_message

        payload = {
            "mode": "rows",
            "table": "public.orders",
            "rows": [{"id": i, "amount": float(i * 10)} for i in range(1, 201)],
        }
        return [
            create_user_message("q"),
            create_assistant_message(
                [{"type": "tool_use", "id": "t1", "name": "query_table_rows", "input": {}}]
            ),
            create_user_message(
                [
                    {
                        "type": "tool_result",
                        "tool_use_id": "t1",
                        "content": json.dumps(payload, ensure_ascii=False),
                        "metadata": {"output": payload},
                    }
                ]
            ),
        ]

    def test_off_disables_reduction(self, monkeypatch, tmp_path: Path) -> None:
        from cloudagent_ext.services.compact.pipeline import CompressionPipeline, PipelineConfig

        monkeypatch.setenv(ENV_CONTEXT_REDUCE, "off")
        config = PipelineConfig(
            sr_enabled=context_reduce_enabled(),
            sr_session_id="req-1",
            sr_evidence_root=tmp_path,
            sr_keep_recent=0,
            sr_min_chars=500,
        )
        result = asyncio.run(
            CompressionPipeline(config).run(self._messages(), input_token_count=0)
        )
        assert "structural_reduce" not in result.layers_applied

    def test_on_reduces(self, monkeypatch, tmp_path: Path) -> None:
        from cloudagent_ext.services.compact.pipeline import CompressionPipeline, PipelineConfig

        monkeypatch.setenv(ENV_CONTEXT_REDUCE, "on")
        config = PipelineConfig(
            sr_enabled=context_reduce_enabled(),
            sr_session_id="req-1",
            sr_evidence_root=tmp_path,
            sr_keep_recent=0,
            sr_min_chars=500,
        )
        result = asyncio.run(
            CompressionPipeline(config).run(self._messages(), input_token_count=0)
        )
        assert "structural_reduce" in result.layers_applied
