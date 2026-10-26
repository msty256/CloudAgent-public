#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""SQL 诊断 Ground Truth 案例库（变更 add-sql-diagnostic-case-library）。

* 案例以 JSON 承载（对齐开发指南 §9.2）：``input``（题面）与
  ``ground_truth``（答案）分离——评测时只把题面交给被评对象；
* 校验器落实「**空 Ground Truth 不作数**」原则，约束必填字段、类型与
  匹配锚点（``match_terms`` / ``observation_terms``）；
* :func:`load_cases` / :func:`load_case` 为下游评测（P2.6）的稳定消费
  契约（本模块**不含评分逻辑**）。
"""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

__all__ = [
    "CaseValidationError",
    "VALID_SEVERITIES",
    "validate_case",
    "load_cases",
    "load_case",
]

_RESOURCE_PACKAGES = {
    "sql": "cloudagent_ext.diagnosis.cases.sql",
    "code": "cloudagent_ext.diagnosis.cases.code",
    "log": "cloudagent_ext.diagnosis.cases.log",
    # P3.6：跨域案例（编排域，对应多个 agent）
    "cross": "cloudagent_ext.diagnosis.cases.cross",
    # P4.3：同步域（无专属 agent，方法由主会话 + 委派完成）
    "sync": "cloudagent_ext.diagnosis.cases.sync",
}
_DOMAINS = tuple(_RESOURCE_PACKAGES)

# P0-1（P3.6）：域 → 必需 agent 的白名单（cross 是编排域，要求两个 agent 都在）
_EXPECTED_AGENTS = {
    "sql": ("sql-diagnosis",),
    "code": ("code-diagnosis",),
    "log": ("log-diagnosis",),
    "cross": ("log-diagnosis", "code-diagnosis"),
    # 取数是所有 sync 案例的共同必需；日志/代码由具体案例自行追加
    "sync": ("sql-diagnosis",),
}
VALID_SEVERITIES = frozenset({"primary", "secondary", "none"})

_REQUIRED_TOP_LEVEL = (
    "schema_version",
    "case_id",
    "domain",
    "scenario",
    "input",
    "ground_truth",
    "expected_agents",
    "safety_expectations",
    "verifiable_on_sim",
    "notes",
)


class CaseValidationError(ValueError):
    """案例校验失败（含"空 Ground Truth"等结构性拒绝）。"""


def _fail(message: str) -> None:
    raise CaseValidationError(message)


def _require(condition: bool, message: str) -> None:
    if not condition:
        _fail(message)


def _require_str(value: Any, what: str) -> None:
    _require(isinstance(value, str) and value.strip() != "", f"{what} must be a non-empty string")


def _require_str_list(value: Any, what: str, *, allow_empty: bool = False) -> None:
    _require(isinstance(value, list), f"{what} must be a list")
    if not allow_empty:
        _require(len(value) > 0, f"{what} must not be empty")
    for index, item in enumerate(value):
        _require_str(item, f"{what}[{index}]")


def _validate_ground_truth(gt: Any) -> None:
    _require(isinstance(gt, dict), "ground_truth must be an object")
    # 「空 Ground Truth 不作数」：三要素各至少一项
    root_causes = gt.get("root_causes")
    _require(isinstance(root_causes, list) and len(root_causes) > 0,
             "ground_truth.root_causes must contain at least one entry (empty ground truth is not a valid case)")
    for index, cause in enumerate(root_causes):
        _require(isinstance(cause, dict), f"root_causes[{index}] must be an object")
        _require_str(cause.get("description"), f"root_causes[{index}].description")
        _require_str_list(cause.get("match_terms"), f"root_causes[{index}].match_terms")
        _require(cause.get("severity") in VALID_SEVERITIES,
                 f"root_causes[{index}].severity must be one of {sorted(VALID_SEVERITIES)}")

    evidence = gt.get("required_evidence")
    _require(isinstance(evidence, list) and len(evidence) > 0,
             "ground_truth.required_evidence must contain at least one entry")
    for index, item in enumerate(evidence):
        _require(isinstance(item, dict), f"required_evidence[{index}] must be an object")
        _require_str(item.get("tool"), f"required_evidence[{index}].tool")
        _require_str_list(item.get("observation_terms"), f"required_evidence[{index}].observation_terms")
        _require(isinstance(item.get("required"), bool), f"required_evidence[{index}].required must be a boolean")
        check = item.get("check")
        if check is not None:
            _require(isinstance(check, dict), f"required_evidence[{index}].check must be an object")
            _require_str(check.get("kind"), f"required_evidence[{index}].check.kind")

    recommendations = gt.get("acceptable_recommendations")
    _require(isinstance(recommendations, list) and len(recommendations) > 0,
             "ground_truth.acceptable_recommendations must contain at least one entry")
    for index, rec in enumerate(recommendations):
        _require(isinstance(rec, dict), f"acceptable_recommendations[{index}] must be an object")
        _require_str(rec.get("description"), f"acceptable_recommendations[{index}].description")
        _require_str_list(rec.get("match_terms"), f"acceptable_recommendations[{index}].match_terms")

    forbidden = gt.get("forbidden_findings", [])
    _require_str_list(forbidden, "forbidden_findings", allow_empty=True)


def validate_case(data: Any) -> None:
    """校验单个案例；失败抛 :class:`CaseValidationError`。"""

    _require(isinstance(data, dict), "case must be a JSON object")
    for key in _REQUIRED_TOP_LEVEL:
        _require(key in data, f"missing required field: {key}")

    _require(isinstance(data["schema_version"], int) and data["schema_version"] == 1,
             "schema_version must be the integer 1")
    _require_str(data["case_id"], "case_id")
    _require_str(data["domain"], "domain")
    # P2-1（P3.5）：domain 取值必须在支持域内
    _require(
        data["domain"] in _DOMAINS,
        f"domain must be one of {sorted(_DOMAINS)}, got {data['domain']!r}",
    )
    _require_str(data["scenario"], "scenario")
    _require_str(data["notes"], "notes (人工确认记录不可为空)")
    _require(isinstance(data["verifiable_on_sim"], bool), "verifiable_on_sim must be a boolean")

    inputs = data["input"]
    _require(isinstance(inputs, dict), "input must be an object")
    _require_str(inputs.get("question"), "input.question")
    context = inputs.get("context", {})
    _require(isinstance(context, dict), "input.context must be an object")

    _validate_ground_truth(data["ground_truth"])

    _require_str_list(data["expected_agents"], "expected_agents")
    # P0-1（P3.5/P3.6）：按域白名单校验——cross 要求 log-diagnosis + code-diagnosis 都在；
    # 不得造不存在的 cross-diagnosis 绕过。
    required_agents = _EXPECTED_AGENTS[data["domain"]]
    missing = [agent for agent in required_agents if agent not in data["expected_agents"]]
    _require(
        not missing,
        f"expected_agents must include {missing!r} for domain {data['domain']!r}",
    )

    safety = data["safety_expectations"]
    _require(isinstance(safety, dict), "safety_expectations must be an object")
    _require(safety.get("must_be_read_only") is True, "safety_expectations.must_be_read_only must be true")
    _require_str_list(safety.get("forbidden_actions", []), "safety_expectations.forbidden_actions",
                      allow_empty=True)


def load_cases(domain: str = "sql") -> list[dict[str, Any]]:
    """加载并校验指定域的案例；返回按 ``case_id`` 排序的案例列表。

    * 默认域 ``sql``（向后兼容）；
    * 域目录不存在时返回空列表（P3.5 之前 code/log 可为空）；
    * ``sql`` 域保留非空要求（既有语义），其余域允许空。
    """

    _require(domain in _DOMAINS, f"unknown domain: {domain!r} (supported: {sorted(_DOMAINS)})")

    try:
        root = files(_RESOURCE_PACKAGES[domain])
    except (ModuleNotFoundError, FileNotFoundError):
        return []

    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in sorted(root.iterdir(), key=lambda item: item.name):
        if not entry.name.endswith(".json"):
            continue
        data = json.loads(entry.read_text(encoding="utf-8"))
        validate_case(data)
        case_id = data["case_id"]
        # P2-1（P3.5）：目录名必须与 domain 字段一致（案例放错目录要能发现）
        _require(
            data["domain"] == domain,
            f"{case_id}: domain field {data['domain']!r} does not match directory {domain!r}",
        )
        _require(case_id not in seen, f"duplicate case_id: {case_id}")
        seen.add(case_id)
        cases.append(data)

    if domain == "sql":
        _require(len(cases) > 0, f"no cases found for domain {domain!r}")
    return sorted(cases, key=lambda case: case["case_id"])


def load_case(case_id: str, domain: str = "sql") -> dict[str, Any]:
    """按 ``case_id`` 加载单个案例；未知 ID 抛 :class:`KeyError`。"""

    for case in load_cases(domain):
        if case["case_id"] == case_id:
            return case
    raise KeyError(f"unknown case_id: {case_id}")
