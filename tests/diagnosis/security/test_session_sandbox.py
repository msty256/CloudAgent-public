#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""诊断会话受限执行边界测试（R1 修复固化）。

修复前（探针实测，见变更 design）：默认 ``bypassPermissions`` 下 Bash 写命令、
删除命令与凭据环境变量读取**全部可执行**（哨兵变量实测泄露、临时文件实测被写/删）。
修复后：``dontAsk`` 模式下写 / 删除 / 凭据访问在**执行前**拒绝；POSIX 只读命令
（如 ``echo`` / ``cat``）放行；数据库只读工具路径不因权限模式变化而拒绝。

注：PowerShell 形态的只读命令（``Get-Content`` 等）在当前权限判定下同样被拒——
保守取舍，POSIX 命令可替代（实测 ``cat`` 放行）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cloudagent_ext.diagnosis.evaluation.executors import build_diagnosis_tool_context
from cloudagent_ext.tool_system.defaults import build_default_registry
from cloudagent_ext.tool_system.protocol import ToolCall


def _dispatch(context, name: str, tool_input: dict):
    registry = build_default_registry(load_agent_tools=False)
    return registry.dispatch(
        ToolCall(name=name, input=tool_input, tool_use_id="security-test"), context
    )


def _restricted_registry(allowed_names: list[str]):
    from cloudagent_ext.diagnosis.evaluation.executors import _build_restricted_registry

    return _build_restricted_registry(
        build_default_registry(load_agent_tools=False), allowed_names
    )


class TestDiagnosisContext:
    def test_context_uses_restricted_mode(self) -> None:
        context = build_diagnosis_tool_context()
        assert context.permission_context.mode == "dontAsk"

    def test_workspace_root_respected(self, tmp_path: Path) -> None:
        context = build_diagnosis_tool_context(workspace_root=tmp_path)
        assert context.workspace_root == tmp_path


class TestBashBoundary:
    @pytest.fixture()
    def context(self):
        return build_diagnosis_tool_context()

    def test_posix_readonly_command_allowed(self, context) -> None:
        result = _dispatch(context, "Bash", {"command": "echo security-probe"})
        assert result.is_error is False
        assert "security-probe" in str(result.output)

    def test_write_command_denied_before_execution(self, context, tmp_path: Path) -> None:
        target = tmp_path / "should_not_exist.txt"
        result = _dispatch(
            context, "Bash", {"command": f'Set-Content -Path "{target}" -Value x'}
        )
        assert result.is_error is True
        assert "denied" in str(result.output).lower()
        assert not target.exists()  # 副作用断言：命令未被执行

    def test_delete_command_denied_before_execution(self, context, tmp_path: Path) -> None:
        victim = tmp_path / "victim.txt"
        victim.write_text("keep", encoding="utf-8")
        result = _dispatch(context, "Bash", {"command": f'Remove-Item "{victim}" -Force'})
        assert result.is_error is True
        assert victim.exists()  # 副作用断言：未被删除

    def test_credential_env_read_denied(self, context, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLOUDAGENT_SECURITY_TEST_VAR", "do-not-leak")
        result = _dispatch(
            context, "Bash", {"command": "echo $env:CLOUDAGENT_SECURITY_TEST_VAR"}
        )
        assert result.is_error is True
        assert "do-not-leak" not in str(result.output)  # 值未泄露进结果


class TestLiveExecutorWiring:
    """LiveExecutor 装配路径的修复点直测（provider 用 Noop 注入，不调真实模型）。"""

    class _NoopProvider:
        model = "noop-security-test"

        def chat(self, messages, tools=None, **kwargs):  # noqa: ANN001
            raise NotImplementedError("live wiring test must not call the model")

        def chat_stream(self, messages, tools=None, **kwargs):  # noqa: ANN001
            return iter(())

        def chat_stream_response(self, *args, **kwargs):  # noqa: ANN001
            raise NotImplementedError

    def test_live_executor_registry_restricted_to_allowlist(self) -> None:
        from cloudagent_ext.diagnosis.evaluation.executors import LiveExecutor

        executor = LiveExecutor(provider_factory=lambda: self._NoopProvider())
        executor.prepare()
        registry = executor._registry
        # 白名单内工具可达
        for name in ("Bash", "Read", "get_schema", "get_indexes", "explain_sql"):
            assert registry.get(name) is not None, name
        # 白名单外工具（存在于默认注册表）被裁掉
        assert registry.get("DashboardList") is None
        assert registry.get("Write") is None


class TestToolAuthorizationBoundary:
    def test_unauthorized_tool_rejected_at_boundary(self) -> None:
        # 执行层白名单强制（R1-②）：裁剪后的 registry 上，白名单外工具在
        # dispatch 边界解析为 unknown tool（修复前全量 registry 上它真实执行）。
        restricted = _restricted_registry(["Bash", "Read"])
        context = build_diagnosis_tool_context()
        result = restricted.dispatch(
            ToolCall(name="DashboardList", input={}, tool_use_id="security-test"), context
        )
        assert result.is_error is True
        assert "unknown tool" in str(result.output)

    def test_dashboard_tool_exists_but_restricted_out(self) -> None:
        # 对照证据：工具本身在默认注册表中存在（修复点是执行出口，而非工具缺失）
        from cloudagent_ext.tool_system.defaults import build_default_registry

        full = build_default_registry(load_agent_tools=False)
        assert full.get("DashboardList") is not None
        restricted = _restricted_registry(["Bash", "Read"])
        assert restricted.get("DashboardList") is None
        assert restricted.get("Bash") is not None

    def test_db_tool_not_blocked_by_permission_mode(self) -> None:
        # fix-sql-diagnosis-tool-provisioning：原断言沿 unknown-tool 路径
        # **假通过**（当时注册表未装配该工具，错误是 unknown tool 而非权限
        # 拒绝）。现在先装配、再经真实权限判定 dispatch：
        # 无 DSN → 结构化连接错误；有 DSN → 正常结果——两者都不得是权限拒绝。
        from cloudagent_ext.diagnosis.db.tools import register_sql_db_tools
        from cloudagent_ext.diagnosis.evaluation.executors import _build_restricted_registry
        from cloudagent_ext.tool_system.defaults import build_default_registry

        full = build_default_registry(load_agent_tools=False)
        register_sql_db_tools(full)
        registry = _build_restricted_registry(full, ["Bash", "Read", "get_schema"])
        context = build_diagnosis_tool_context()
        result = registry.dispatch(
            ToolCall(name="get_schema", input={"table": "orders"}, tool_use_id="sec-test"),
            context,
        )
        text = str(result.output)
        assert "Permission denied" not in text
        assert "unknown tool" not in text
