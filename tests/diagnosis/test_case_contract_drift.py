#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""Anti-rot checks: 规范 / 实现 / 案例三处对同一事实的描述必须一致。

变更 ``fix-stale-diagnosis-contracts`` 的由来：P3.6 把协议增强改成三域分派后，
两处规范文本（仍要求 ``source="code"`` / ``source="log"``）与一个案例 GT
（仍称"只覆盖 sql 域"）没有同步，而**离线夹具和 GT 一起陈旧**，导致评测指标
结构上发现不了。这里把三处各自钉成会失败的断言，让下一次漂移在 CI/本地就暴露。
"""

from __future__ import annotations

import ast
import dataclasses
import json
from pathlib import Path

import pytest

from cloudagent_ext.diagnosis.models import Evidence

# 基于测试文件位置定位仓库根，不用 cwd —— pytest 的启动目录可能是任意路径，
# 用 Path("openspec") 会在子目录/部署树里误判成"不存在"而静默整组跳过。
REPO_ROOT = Path(__file__).resolve().parents[2]
SPECS_DIR = REPO_ROOT / "openspec" / "specs"
AGENT_PY = REPO_ROOT / "cloudagent_ext" / "tool_system" / "tools" / "agent.py"
CODE_002_JSON = REPO_ROOT / "cloudagent_ext" / "diagnosis" / "cases" / "code" / "code-002.json"

_EXPECTED_AUGMENTERS = {"sql-diagnosis", "code-diagnosis", "log-diagnosis"}


def _augmenter_keys() -> set[str]:
    """从 ``agent.py`` 的 AST 里取出 ``_AUGMENTERS`` 字典的键集合。"""

    tree = ast.parse(AGENT_PY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "_AUGMENTERS":
                value = node.value
                assert isinstance(value, ast.Dict), "_AUGMENTERS 应为字典字面量"
                keys = {k.value for k in value.keys if isinstance(k, ast.Constant)}
                return {str(k) for k in keys}
    raise AssertionError("agent.py 中找不到 _AUGMENTERS 赋值")


class TestEvidenceModel:
    def test_has_no_source_field(self) -> None:
        # `source` 是已废弃的域标识方式：域由 evidence_id 命名空间前缀承载。
        names = {field.name for field in dataclasses.fields(Evidence)}
        assert "source" not in names
        assert "source_type" in names


@pytest.mark.skipif(not SPECS_DIR.is_dir(), reason="openspec/specs 不在树中（部署树）")
class TestSpecText:
    def test_no_spec_requires_source_field(self) -> None:
        offenders = [
            path.relative_to(REPO_ROOT).as_posix()
            for path in sorted(SPECS_DIR.rglob("*.md"))
            if 'source="' in path.read_text(encoding="utf-8")
        ]
        assert offenders == [], f"这些规范仍在要求 source= 字段：{offenders}"

    @pytest.mark.parametrize("relative", ["code-analysis/spec.md", "log-analysis/spec.md"])
    def test_domain_spec_uses_namespace_contract(self, relative: str) -> None:
        text = (SPECS_DIR / relative).read_text(encoding="utf-8")
        assert "evidence_id" in text
        assert "ev:" in text


class TestCaseGroundTruth:
    def test_code_002_is_a_regression_guard(self) -> None:
        case = json.loads(CODE_002_JSON.read_text(encoding="utf-8"))
        ground_truth = case["ground_truth"]

        # 角色已从"阳性缺陷"转为"阴性回归守卫"。
        assert ground_truth["root_causes"][0]["severity"] == "none"

        # 旧结论必须仍在禁项里，否则旧结论复活的回答不会被判违规。
        forbidden = " ".join(ground_truth["forbidden_findings"])
        assert "sql" in forbidden

        # GT 描述的事实必须与当前实现一致。
        assert _augmenter_keys() == _EXPECTED_AUGMENTERS
        assert "_AUGMENTERS" in ground_truth["root_causes"][0]["description"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
