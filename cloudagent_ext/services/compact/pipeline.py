#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""
Compression pipeline — orchestrates the 5 compression layers in order.

Runs cheap → expensive.  If earlier layers free enough tokens, later
layers are no-ops.

Layers:
  1. apply_tool_result_budget  — Persist large results to disk
  2. snip_compact              — Trim old tool results
  3. microcompact              — Compress intermediate tool calls
  4. context_collapse          — Read-time projection
  5. autocompact               — Full LLM summarization (last resort)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cloudagent_ext.context_system.microcompact import (  # pylint: disable=no-name-in-module
    TimeBasedMCConfig,
    microcompact_typed_messages,
)
from cloudagent_ext.diagnosis.switches import context_reduce_enabled  # 阶段 5 分臂开关
from cloudagent_ext.providers.base import BaseProvider  # pylint: disable=no-name-in-module
from cloudagent_ext.types.messages import Message  # pylint: disable=no-name-in-module

from .autocompact import (
    AutoCompactTracking,
    auto_compact_if_needed,
)
from .context_collapse import ContextCollapseStore, get_context_collapse_state
from .gating import (
    resolve_skip_ratio_from_env,
    should_run_compression_pipeline,
)
from .snip_compact import snip_compact
from .tool_result_budget import apply_tool_result_budget

logger = logging.getLogger(__name__)


@dataclass
class CompressionResult:
    """Result of running the compression pipeline."""

    messages: list[Message]
    tokens_saved: int = 0
    layers_applied: list[str] = field(default_factory=list)
    autocompact_result: Any | None = None  # CompactionResult if layer 5 ran
    #: 阶段 3（Layer 2.5）的结构归约统计：折了几条、产生哪些句柄、失败几条
    reduce_stats: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineConfig:
    """Configuration for the compression pipeline."""

    # Layer 1: tool result budget
    budget_dir: Path | str | None = None
    max_result_tokens: int = 8_000

    # Layer 2: snip compact
    snip_keep_recent: int = 10

    # Layer 2.5: structural reduce（阶段 3）——把取证大结果"折"成摘要 + 句柄。
    # 与 Layer 3 的 microcompact 正交：那边是**清空**可重新获得的中间产物，
    # 这边是**折叠**一次性取到的证据。两张名单不重叠，互不替代。
    sr_enabled: bool = True
    #: 低于这个字符数不值得归档（摘要未必比原文短）
    sr_min_chars: int = 4_000
    #: 一轮最多折几条——改历史消息会让 prompt cache 失效，一次改太多等于全废
    sr_max_items: int = 8
    #: 最新 N 条取证结果**不折**。压缩发生在"每轮请求前"，连当轮刚查到的也折掉
    #: 会让模型看不到明细——省 token 变成拿诊断质量换。
    sr_keep_recent: int = 2
    #: 归档用的会话标识；为空则**只渲染摘要、不写句柄**（避免留下取不回的句柄）
    sr_session_id: str = ""
    #: 归档根目录；None = 走 get_user_config_dir()/evidence
    sr_evidence_root: Path | str | None = None
    #: 运行期统计出口（通常是 ``ToolContext``）。管线把 Layer 2.5 的统计写回
    #: ``stats_sink.compaction_stats``，评测层再从那里读。
    #: 用"传引用"而不是"加返回值"，是因为 ``run()`` 的返回契约被多处依赖，
    #: 改签名会牵动整条 query 链路。
    stats_sink: Any | None = None

    # Layer 3: microcompact
    # TS time-based MC is disabled by default (GrowthBook enabled: false),
    # cached MC uses API cache_edits (no local mutation), and legacy MC was
    # removed.  So microcompact is effectively a no-op on the main thread.
    mc_enabled: bool = False
    mc_keep_recent: int = 5
    mc_time_config: TimeBasedMCConfig | None = None

    # Layer 4: context collapse
    collapse_store: ContextCollapseStore | None = None

    # Layer 5: autocompact
    context_window: int = 200_000
    max_output_tokens: int | None = None
    autocompact_threshold: float = 0.80
    autocompact_tracking: AutoCompactTracking | None = None

    # lazy compression gate. When ``est_input_tokens`` is below
    # ``context_window * gate_skip_ratio``, the pipeline short-circuits
    # and returns an empty result instead of running all 5 layers. Set
    # to 0 to disable the gate (always run). Overridable at runtime via
    # the ``CLOUDAGENT_COMPRESSION_GATE_SKIP_RATIO`` env var.
    gate_skip_ratio: float = 0.6
    # Force-run overrides for the gate. Forwarded by the caller when
    # the current turn is a compact/session_memory flow, a recovery
    # retry, or follows a pipeline error. The defaults are permissive
    # — they must be set explicitly for the gate to actually skip.
    gate_query_source: str = ""
    gate_transition_reason: str | None = None
    gate_previous_pipeline_errored: bool = False

    # Layer 5: post-compact attachment context
    # Forwarded into auto_compact_if_needed → CompactContext so post-compact
    # file/plan restoration fires on auto-compact, not just /compact.
    read_file_state: dict[str, Any] | None = None
    plan_file_path: str | None = None
    memory_paths: set[str] | None = None

    # Global
    provider: BaseProvider | None = None
    model: str = ""
    custom_instructions: str | None = None

    # Token budget: if pipeline frees this many tokens, skip remaining layers
    early_exit_tokens: int = 20_000

    # Goal-aware compression.
    # When ``goal_active`` is True, the autocompact threshold is raised
    # (compact less aggressively) and messages containing
    # ``<goal-steering`` are preserved from compaction so the model
    # never loses sight of the current objective.
    goal_active: bool = False


def build_production_pipeline_config(
    provider: Any,
    tool_context: Any,
    autocompact_tracking: AutoCompactTracking | None,
) -> PipelineConfig:
    """The minimal correct PipelineConfig for the live surfaces.

    ch05 round-4 GAP A — mirrors the test-only ``QueryEngine``'s
    construction (``query/engine.py:233-250``) exactly: provider + model +
    the read-file fingerprints (so post-compact file restoration fires) +
    the SESSION-scoped ``autocompact_tracking``. The tracking instance MUST
    outlive single turns — the 3-consecutive-failures circuit breaker
    counts across prompts; a per-turn instance would reset it every turn
    (the exact reason the engine holds one at ``engine.py:74-79``).
    """
    fingerprints = getattr(tool_context, "read_file_fingerprints", None) or {}
    read_file_state = {
        str(path): {"timestamp": fp[0]} for path, fp in fingerprints.items() if isinstance(fp, (tuple, list)) and fp
    }
    model = getattr(provider, "model", "") or ""
    context_window = 200_000
    max_output_tokens = None
    if model:
        try:
            from cloudagent_ext.models.context import (
                get_context_window_for_model,
                get_model_max_output_tokens,
            )

            context_window = get_context_window_for_model(model, base_url=getattr(provider, "base_url", None))
            max_output_tokens = get_model_max_output_tokens(model, base_url=getattr(provider, "base_url", None))
        except Exception:
            logger.debug("model context-window resolution failed", exc_info=True)
    return PipelineConfig(
        provider=provider,
        model=model,
        context_window=context_window,
        max_output_tokens=max_output_tokens,
        read_file_state=read_file_state or None,
        autocompact_tracking=autocompact_tracking,
        # 阶段 3：结构归约需要一个稳定的归档目录名。优先诊断域的真实 request_id
        # （这样一次诊断的证据都落在同一个目录下），否则用 ToolContext.session_id。
        # 两者都没有 → 空串 → 归约只出摘要、不写句柄（不传播原则）。
        # 阶段 5：对照实验需要一个独立开关。默认值与改造前一致（开启），
        # 环境变量只用于分臂，不改变生产默认行为。
        sr_enabled=context_reduce_enabled(),
        sr_session_id=_resolve_evidence_session_id(tool_context),
        # 统计出口：管线把 Layer 2.5 的结果写回 tool_context.compaction_stats，
        # 评测层从 meta 里读。不新开参数通道，避免动整条 query 调用链。
        stats_sink=tool_context,
    )


def _resolve_evidence_session_id(tool_context: Any) -> str:
    """证据归档的目录名——**直接复用存储层的解析**，保证读写同一个目录。"""

    from cloudagent_ext.services.compact.evidence_store import resolve_session_id

    return resolve_session_id(tool_context)


class CompressionPipeline:
    """
    Orchestrates the 5-layer compression pipeline.

    Usage::

        pipeline = CompressionPipeline(config)
        result = await pipeline.run(messages, input_token_count)
    """

    def __init__(self, config: PipelineConfig | None = None) -> None:
        self._config = config or PipelineConfig()

    async def run(
        self,
        messages: list[Message],
        input_token_count: int = 0,
    ) -> CompressionResult:
        """跑完整管线，并把 Layer 2.5 的统计写回 ``config.stats_sink``。

        包一层的原因：``_run_layers`` 里有 5 处 early-exit 直接 return，
        逐个加"写回"既啰嗦又容易漏。统一在外层收口，一处就够。
        """

        result = await self._run_layers(messages, input_token_count)
        self._publish_stats(result.reduce_stats)
        return result

    def _publish_stats(self, stats: dict[str, Any] | None) -> None:
        """把结构归约统计写到 sink 上（失败不影响管线）。

        顺带把**归档根目录**也写过去：召回工具必须用同一个目录去找，
        否则句柄永远取不回来（不报错，只是取不到）。
        """

        sink = getattr(self._config, "stats_sink", None)
        if sink is None:
            return
        root = getattr(self._config, "sr_evidence_root", None)
        if root is not None:
            try:
                setattr(sink, "evidence_root", str(root))
            except Exception:  # noqa: BLE001
                logger.debug("evidence root publish failed", exc_info=True)
        if not stats:
            return
        try:
            setattr(sink, "compaction_stats", dict(stats))
        except Exception:  # noqa: BLE001 — sink 可能是 slots 类或只读对象
            logger.debug("compaction stats publish failed", exc_info=True)

    async def _run_layers(
        self,
        messages: list[Message],
        input_token_count: int = 0,
    ) -> CompressionResult:
        """
        Run all compression layers in order, short-circuiting if enough
        tokens are freed by early layers.

        Args:
            messages: Current conversation messages.
            input_token_count: Estimated input token count (for autocompact decision).

        Returns:
            ``CompressionResult`` with the (potentially modified) messages,
            total tokens saved, and which layers were applied.
        """
        cfg = self._config
        total_saved = 0
        layers_applied: list[str] = []
        # 阶段 3：结构归约的统计（各 early-exit 都要带回去，否则中途返回就丢了）
        reduce_stats: dict[str, Any] = {}
        current_messages = messages

        # lazy compression gate. When est_input_tokens is well
        # below context_window * skip_ratio, all five layers would be
        # no-ops; short-circuit before doing any work.  A zero (or
        # negative) input_token_count means "not measured" — skip the
        # gate so the pipeline runs normally for backward compat.
        if input_token_count > 0:
            effective_ratio = resolve_skip_ratio_from_env(cfg.gate_skip_ratio)
            gate_should_run, gate_reason = should_run_compression_pipeline(
                est_input_tokens=input_token_count,
                context_window=cfg.context_window,
                skip_ratio=effective_ratio,
                query_source=cfg.gate_query_source,
                transition_reason=cfg.gate_transition_reason,
                previous_pipeline_errored=cfg.gate_previous_pipeline_errored,
            )
            if not gate_should_run:
                logger.debug(
                    "compression pipeline skipped reason=%s est=%d threshold=%d",
                    gate_reason,
                    input_token_count,
                    int(cfg.context_window * effective_ratio),
                )
                return CompressionResult(
                    messages=messages,
                    tokens_saved=0,
                    layers_applied=[f"skipped:{gate_reason}"],
                )

        # --- Layer 1: Tool Result Budget ---
        try:
            current_messages, saved = apply_tool_result_budget(
                current_messages,
                budget_dir=cfg.budget_dir,
                max_result_tokens=cfg.max_result_tokens,
            )
            if saved > 0:
                total_saved += saved
                layers_applied.append("tool_result_budget")
                logger.debug("Layer 1 (tool_result_budget): saved %d tokens", saved)
                if total_saved >= cfg.early_exit_tokens:
                    return CompressionResult(
                        messages=current_messages,
                        tokens_saved=total_saved,
                        layers_applied=layers_applied,
                        reduce_stats=reduce_stats,
                    )
        except Exception:
            logger.warning("Layer 1 (tool_result_budget) failed", exc_info=True)

        # --- Layer 2: Snip Compact ---
        try:
            current_messages, saved = snip_compact(
                current_messages,
                keep_recent=cfg.snip_keep_recent,
            )
            if saved > 0:
                total_saved += saved
                layers_applied.append("snip_compact")
                logger.debug("Layer 2 (snip_compact): saved %d tokens", saved)
                if total_saved >= cfg.early_exit_tokens:
                    return CompressionResult(
                        messages=current_messages,
                        tokens_saved=total_saved,
                        layers_applied=layers_applied,
                        reduce_stats=reduce_stats,
                    )
        except Exception:
            logger.warning("Layer 2 (snip_compact) failed", exc_info=True)

        # --- Layer 2.5: Structural Reduce（阶段 3）---
        # 放在 Layer 3 之前：先把取证结果折成摘要 + 句柄，之后 microcompact
        # 只处理它自己那份白名单（Read/Grep/Bash 等），两者不会打架。
        # 归约失败**不退回清空**——清空等于丢证据（见下面 Layer 3 的注释）。
        if cfg.sr_enabled:
            try:
                from cloudagent_ext.services.compact.evidence_store import EvidenceStore
                from cloudagent_ext.services.compact.structural_reduce import (
                    reduce_forensic_messages,
                )

                store = EvidenceStore(root=Path(cfg.sr_evidence_root) if cfg.sr_evidence_root else None)
                outcome = reduce_forensic_messages(
                    current_messages,
                    store=store,
                    session_id=cfg.sr_session_id,
                    min_chars=cfg.sr_min_chars,
                    max_items=cfg.sr_max_items,
                    keep_recent=cfg.sr_keep_recent,
                )
                reduce_stats = outcome.as_dict()
                if outcome.reduced_count > 0:
                    current_messages = outcome.messages
                    layers_applied.append("structural_reduce")
                    logger.debug(
                        "Layer 2.5 (structural_reduce): %d 条，省 %d 字符，句柄 %d 个",
                        outcome.reduced_count,
                        outcome.saved_chars,
                        len(outcome.handles),
                    )
            except Exception:
                logger.warning("Layer 2.5 (structural_reduce) failed", exc_info=True)

        # --- Layer 3: Microcompact ---
        # Gated by mc_enabled (default False) to match TS where microcompact
        # is a no-op on the main thread (time-based disabled, cached MC uses
        # API cache_edits, legacy removed).  Clearing tool results locally
        # breaks file_unchanged (model told to "refer to earlier content"
        # that microcompact already erased → falls back to Bash cat).
        if cfg.mc_enabled:
            try:
                current_messages, saved = microcompact_typed_messages(
                    current_messages,
                    keep_recent=cfg.mc_keep_recent,
                    time_config=cfg.mc_time_config,
                    force=True,
                )
                if saved > 0:
                    total_saved += saved
                    layers_applied.append("microcompact")
                    logger.debug("Layer 3 (microcompact): saved %d tokens", saved)
                    if total_saved >= cfg.early_exit_tokens:
                        return CompressionResult(
                            messages=current_messages,
                            tokens_saved=total_saved,
                            layers_applied=layers_applied,
                            reduce_stats=reduce_stats,
                        )
            except Exception:
                logger.warning("Layer 3 (microcompact) failed", exc_info=True)

        # --- Layer 4: Context Collapse ---
        try:
            store = cfg.collapse_store or get_context_collapse_state()
            if store is not None and store.enabled and store.commits:
                current_messages = store.project_view(current_messages)
                layers_applied.append("context_collapse")
                logger.debug("Layer 4 (context_collapse): projected %d commits", len(store.commits))
        except Exception:
            logger.warning("Layer 4 (context_collapse) failed", exc_info=True)

        # --- Layer 5: Autocompact ---
        autocompact_result = None
        if cfg.provider is not None and cfg.model:
            # when a goal is active, raise the autocompact threshold
            # (compact less aggressively) and pre-filter goal-steering
            # messages so they survive compaction.
            effective_threshold = cfg.autocompact_threshold
            filtered_messages = current_messages
            if cfg.goal_active:
                effective_threshold = min(effective_threshold + 0.10, 0.95)
                # Remove goal-steering messages before the autocompact
                # check so the token estimate doesn't count them, but
                # keep them in the final message stream.
                filtered_messages = [m for m in current_messages if not _is_goal_steering_message(m)]
            try:
                result = await auto_compact_if_needed(
                    filtered_messages if cfg.goal_active else current_messages,
                    input_token_count - total_saved,
                    cfg.context_window,
                    cfg.provider,
                    cfg.model,
                    max_output_tokens=cfg.max_output_tokens,
                    threshold_fraction=cfg.autocompact_threshold,
                    tracking=cfg.autocompact_tracking,
                    custom_instructions=cfg.custom_instructions,
                    read_file_state=cfg.read_file_state,
                    plan_file_path=cfg.plan_file_path,
                    memory_paths=cfg.memory_paths,
                )
                if result is not None:
                    total_saved += result.tokens_saved
                    layers_applied.append("autocompact")
                    autocompact_result = result
                    # R6 — APPLY the compaction to the working messages. This
                    # was the bug: the pipeline computed the summary (an LLM
                    # call, cost incurred) but returned the UNCOMPACTED
                    # current_messages, so query() kept the full conversation
                    # and auto-compact re-fired every turn without ever
                    # shrinking the context — the exact opposite of what a
                    # long task needs. Assemble the compacted conversation the
                    # way the manual /compact path does (compact_service/
                    # service.py:101-104): the summary (a USER message — safe
                    # as the first message) + kept recent messages + the
                    # post-compact attachments (file-state a coding agent needs
                    # after compaction). The system boundary_marker is
                    # bookkeeping for the persisted conversation and is omitted
                    # from the working set (as the reactive path does), so the
                    # working messages stay API-clean.
                    n_before = len(current_messages)
                    current_messages = (
                        list(result.summary_messages) + list(result.messages_to_keep) + list(result.attachments)
                    )
                    logger.debug(
                        "Layer 5 (autocompact): saved %d tokens, %d -> %d msgs",
                        result.tokens_saved,
                        n_before,
                        len(current_messages),
                    )
            except Exception:
                logger.warning("Layer 5 (autocompact) failed", exc_info=True)

        return CompressionResult(
            messages=current_messages,
            tokens_saved=total_saved,
            layers_applied=layers_applied,
            autocompact_result=autocompact_result,
            reduce_stats=reduce_stats,
        )


def _is_goal_steering_message(message: Message) -> bool:
    """Check if a message is a goal-steering injection.

    Goal-steering prompts are wrapped in ``<goal-steering type=...>``
    XML tags. These must survive autocompact so the model never loses
    sight of the active objective.
    """
    if not hasattr(message, "content"):
        return False
    content = message.content
    if isinstance(content, str):
        return "<goal-steering" in content
    if isinstance(content, list):
        for block in content:
            text = getattr(block, "text", None) or getattr(block, "content", None)
            if isinstance(text, str) and "<goal-steering" in text:
                return True
    return False


async def run_compression_pipeline(
    messages: list[Message],
    input_token_count: int = 0,
    config: PipelineConfig | None = None,
) -> CompressionResult:
    """
    Convenience function: run the full compression pipeline.

    Args:
        messages: Current conversation messages.
        input_token_count: Estimated input token count.
        config: Pipeline configuration.

    Returns:
        ``CompressionResult``
    """
    pipeline = CompressionPipeline(config)
    return await pipeline.run(messages, input_token_count)
