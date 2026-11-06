#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""缺口账本的**唯一写者**（阶段 4 · T4.1）。

**为什么要这一层**：阶段 4 之前，缺口状态只有一个写者（`harvest_gaps` 就地
`runtime.gaps.append(...)` / 改 `gap.status`）。阶段 4 要加入"回退"（`resolved → open`）
和"解除"（`blocked → open`），等于**第二个写者**。

两个写者直接改同一个 list，最终状态就由**调用顺序**决定——这不会立刻出错，
只会在某次结果迟到时让人查一整天。所以把状态变更收口到这里：
`harvest_gaps` 和 `propagate_invalidation` 都只是本类方法的调用方。

**行为等价**：本类的方法逐条复刻改造前的语义（去重、`restatements` 累加、
域回填、`blocked` 降级、事件结构）。T4.1 是纯重构，指标与用例都不该变。

**事件**：`gap_events` 是阶段 0 的度量采集口。`why` 取值：
``new`` / ``blocked`` / ``resolved`` / ``restated`` / ``invalidated`` / ``released``。
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Iterable

from cloudagent_ext.diagnosis.models import Gap, GAP_STATUS_INCONCLUSIVE, GAP_STATUS_OPEN
from cloudagent_ext.diagnosis.text_match import normalize_statement

__all__ = ["GapStore"]

logger = logging.getLogger("cloudagent.diagnosis.gap_store")

#: 事件列表上限（与改造前的 `_MAX_GAP_EVENTS` 保持一致）
MAX_EVENTS: int = 200

#: 单缺口被回退的次数上限：达到后转 inconclusive，放弃自动收敛。
#: 不加约束会形成 `resolved → 冲突 → open → 再 resolved → 再冲突` 的循环，
#: 每一轮都烧委派预算，而且模型会一直被告知"重查同一件事"。
MAX_REVERTS: int = 2


class GapStore:
    """缺口清单 + 状态迁移事件。所有状态变更都必须走这里。"""

    def __init__(self) -> None:
        self._gaps: list[Gap] = []
        self._events: list[dict] = []
        self._seq = 0
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # 读
    # ------------------------------------------------------------------

    def gaps(self) -> tuple[Gap, ...]:
        """当前缺口（只读视图）。要改状态请用下面的方法。"""

        with self._lock:
            return tuple(self._gaps)

    def events(self) -> tuple[dict, ...]:
        with self._lock:
            return tuple(self._events)

    @property
    def seq(self) -> int:
        """事件序号（单调递增，截断后不重置——否则先后顺序就丢了）。"""

        with self._lock:
            return self._seq

    def find(self, gap_id: str) -> Gap | None:
        with self._lock:
            for gap in self._gaps:
                if gap.gap_id == gap_id:
                    return gap
        return None

    def resolved_claiming(self, evidence_id: str) -> tuple[Gap, ...]:
        """哪些**已核销**的缺口把这条证据记进了 ``evidence_refs``。

        这是"证据 → 缺口"的反查边：`evidence_refs` 在判 resolved 时就被填上了，
        所以回退不需要建全量依赖图。
        """

        if not evidence_id:
            return ()
        with self._lock:
            return tuple(
                gap
                for gap in self._gaps
                if gap.status == "resolved" and evidence_id in gap.evidence_refs
            )

    # ------------------------------------------------------------------
    # 写：向前（原有语义，行为等价）
    # ------------------------------------------------------------------

    def add(self, statement: str, *, domain: str = "", status: str = GAP_STATUS_OPEN) -> Gap:
        """登记一条缺口：同命题去重 + 累加复述次数；``blocked`` 可降级 ``open``。"""

        text = str(statement or "").strip()
        normalized = normalize_statement(text)
        with self._lock:
            existing = next(
                (gap for gap in self._gaps if normalize_statement(gap.statement) == normalized),
                None,
            )
            if existing is not None:
                existing.restatements += 1
                # 早先收割时还没有域维度 → 这次能归因就补上
                if domain and not getattr(existing, "source_domain", ""):
                    existing.source_domain = str(domain).strip()
                if status == "blocked" and existing.status == GAP_STATUS_OPEN:
                    self._emit(existing, existing.status, "blocked", "blocked")
                    existing.status = "blocked"
                return existing

            gap = Gap(
                gap_id=f"gap-{len(self._gaps) + 1}",
                statement=text,
                status=status,
                source_domain=str(domain or "").strip(),
            )
            self._gaps.append(gap)
            self._emit(gap, "", status, "new")
            return gap

    def add_existing(self, gap: Gap) -> Gap:
        """把一条**已经构造好**的 Gap 放进账本（迁移 / 测试准备数据用）。

        与 ``add()`` 的区别：不做去重、不累加 ``restatements``、不重新编号——
        调用方已经想清楚要放什么。存在这个入口，是为了让"直接 append 到 list"
        这个老习惯有一个明确的替代品，而不是让人去戳私有字段。
        """

        with self._lock:
            self._gaps.append(gap)
            self._emit(gap, "", gap.status, "new")
            return gap

    def mark_blocked(self, gap_id: str, *, why: str = "") -> bool:
        gap = self.find(gap_id)
        if gap is None or gap.status == "blocked":
            return False
        with self._lock:
            self._emit(gap, gap.status, "blocked", "blocked")
            gap.status = "blocked"
            if why:
                gap.note = why
        return True

    def mark_resolved(self, gap_id: str, *, evidence_id: str = "") -> bool:
        gap = self.find(gap_id)
        if gap is None or gap.status == "resolved":
            return False
        with self._lock:
            self._emit(gap, gap.status, "resolved", "resolved", evidence_id)
            gap.status = "resolved"
            if evidence_id and evidence_id not in gap.evidence_refs:
                gap.evidence_refs.append(evidence_id)
        return True

    def mark_inconclusive(self, gap_id: str, *, why: str = "restated") -> bool:
        gap = self.find(gap_id)
        if gap is None or gap.status == "inconclusive":
            return False
        with self._lock:
            self._emit(gap, gap.status, "inconclusive", why)
            gap.status = GAP_STATUS_INCONCLUSIVE
        return True

    # ------------------------------------------------------------------
    # 写：往回走（阶段 4 新增）
    # ------------------------------------------------------------------

    def revert(self, gap_id: str, *, why: str, evidence_id: str = "") -> bool:
        """``resolved → open``（待复核）。

        **不裁决谁对谁错**——只是把"有争议"这件事记录下来，让缺口重新进入取证队列。
        回退次数达到 ``MAX_REVERTS`` 就转 ``inconclusive``：反复冲突说明这对证据
        自动收敛不了，再试下去只是烧预算。
        """

        gap = self.find(gap_id)
        if gap is None or gap.status != "resolved":
            return False
        with self._lock:
            gap.revert_count += 1
            if gap.revert_count >= MAX_REVERTS:
                gap.note = f"{why}（证据反复冲突，已放弃自动收敛）"
                self._emit(gap, gap.status, "inconclusive", "invalidated", evidence_id)
                gap.status = GAP_STATUS_INCONCLUSIVE
                return True
            gap.note = why
            # 回退与"复述"是两件事，各自计数：restatements 记"被再次陈述"，
            # revert_count 记"被推翻"。混在一起会让震荡上限提前触发。
            self._emit(gap, gap.status, "open", "invalidated", evidence_id)
            gap.status = GAP_STATUS_OPEN
        return True

    def release(self, gap_id: str, *, why: str, evidence_id: str = "") -> bool:
        """``blocked → open``。

        覆盖性证据到达时用：它说明"前提可能已满足"，但**"能查了"不等于"已查清"**，
        所以只解除阻塞、不直接判 resolved——让它走正常流程，再次 resolved 还要过核查。
        """

        gap = self.find(gap_id)
        if gap is None or gap.status != "blocked":
            return False
        with self._lock:
            self._emit(gap, gap.status, "open", "released", evidence_id)
            gap.status = GAP_STATUS_OPEN
            gap.note = why
        return True

    # ------------------------------------------------------------------

    def _emit(
        self,
        gap: Any,
        from_status: str,
        to_status: str,
        why: str,
        evidence_id: str = "",
    ) -> None:
        """记一次状态迁移。**绝不抛出**：度量失败不得影响账本。"""

        try:
            self._seq += 1
            self._events.append(
                {
                    "seq": self._seq,
                    "gap_id": str(getattr(gap, "gap_id", "") or ""),
                    "domain": str(getattr(gap, "source_domain", "") or ""),
                    "from": from_status,
                    "to": to_status,
                    "why": why,
                    "evidence_id": evidence_id,
                }
            )
            if len(self._events) > MAX_EVENTS:
                del self._events[: -MAX_EVENTS]
        except Exception:  # noqa: BLE001
            logger.debug("gap event append failed", exc_info=True)
