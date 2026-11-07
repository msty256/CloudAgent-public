#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""RunRecord 契约的执行与序列化支撑（EVAL-P1a）。

* ``record`` —— 纯 schema（零内部依赖），评测仓与产品仓的共同语言；
* ``execute`` —— 跑一个 case → RunRecord（临时复用 evaluation.executors，P2 还债）；
* ``cli`` —— ``cloudagent eval-run`` 薄入口。

本包**不做**任何评分、聚合与报告——那是评测仓（cloudagent-eval）的职责。
"""
