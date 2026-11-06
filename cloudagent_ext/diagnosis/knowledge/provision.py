#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""子 Agent 工具装配接缝：领域工具 → 召回工具 → 知识库检索工具。

保留 :func:`provision_with_recall` 的语义（域装配失败不影响后续工具），
再补一个 ``search_knowledge``，让三个诊断子 Agent 都能查历史案例/设计文档。

知识库可以整体关闭（评测两臂对照用）：``CLOUDAGENT_KB_ENABLED=off``。
关闭时**不注册工具**，子 Agent 的工具列表里看不到它——这样对照才干净，
不会出现"工具在但不是不调用"的混淆。
"""

from __future__ import annotations

import os
from typing import Any

KB_ENABLED_ENV = "CLOUDAGENT_KB_ENABLED"
_DISABLED_VALUES = {"0", "off", "false", "no", "none"}


def knowledge_enabled() -> bool:
    """知识库是否启用（默认启用；显式设 off 才关闭）。"""

    return os.environ.get(KB_ENABLED_ENV, "").strip().lower() not in _DISABLED_VALUES


def provision_with_knowledge(provision: Any, registry: Any) -> bool:
    """先跑域装配（含召回工具），再补知识库检索工具。

    Returns:
        各环节都成功（或已装配）返回 ``True``；域装配失败返回 ``False``。
        知识库被显式关闭时，不注册工具，但**不算失败**（返回域装配结果）。
    """

    from cloudagent_ext.services.compact.recall_tool import provision_with_recall

    ok = bool(provision_with_recall(provision, registry))
    if not knowledge_enabled():
        return ok
    try:
        from .tools import register_knowledge_tools

        knowledge_ok = bool(register_knowledge_tools(registry))
    except Exception:  # noqa: BLE001 — 知识库装配失败不应阻塞诊断
        knowledge_ok = False
    return ok and knowledge_ok
