#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""证据句柄存储（阶段 3 · T3.2）。

压缩把一条取证结果折成摘要后，**原文不能丢**——它是"细节可回取"的那个"可"。
本模块负责把原文落到本地，并返回一个短句柄，供摘要里引用、供后续召回。

**与 ``Gap.evidence_refs`` 的 ``ev:sql:1`` 分属两套，不要混用**：

======================  ==========================================
``ev:<domain>:<n>``     子代理**自报**的证据标识（写在结果 JSON 里）
``evh:<domain>:<n>``    **压缩产生**的物理句柄（指向本地归档文件）
======================  ==========================================

一个是"我说我查到了什么"，一个是"我把原文存在这儿了"。混用会让"证据是否成立"
和"原文是否还在"两件事纠缠在一起。

**与 ``CollapseStateFile`` 并存，不合并**：那套存的是折叠后的会话片段，粒度是消息批次；
句柄是单个工具结果，生命周期与清理策略都不同。硬合并会让两边的清理逻辑互相牵制。

**安全边界（重要）**：句柄会出现在提示里，也可能被模型原样回传。
所以 ``load()`` 必须按白名单校验格式、并把最终路径限制在根目录内——
**绝不能拿模型给的字符串直接拼路径**。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = [
    "EVIDENCE_HANDLE_PATTERN",
    "DEFAULT_MAX_BYTES",
    "MAX_HANDLE_DIGITS",
    "EvidenceStore",
    "build_handle",
    "parse_handle",
    "resolve_session_id",
]

logger = logging.getLogger("cloudagent.compact.evidence")

#: 句柄格式：``evh:<domain>:<n>``。domain 只允许小写标识符，n 是纯数字。
#: 这条正则同时是**安全边界**——不匹配的一律不碰文件系统。
EVIDENCE_HANDLE_PATTERN = re.compile(r"^evh:(?P<domain>[a-z0-9][a-z0-9_-]{0,31}):(?P<seq>\d{1,9})$")

#: session_id 只允许常规标识符字符（它来自 request_id，也会被拼进路径）
_SESSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

#: 单条归档上限（原文超过这个就不归档 → 调用方不得写句柄）
DEFAULT_MAX_BYTES: int = 4 * 1024 * 1024

#: 保留多少个会话的归档。**按会话整体过期**，不逐文件淘汰——
#: 一次诊断的证据本来就是一体的，留半个会话没有意义，只会让句柄变成半死状态。
DEFAULT_MAX_SESSIONS: int = 20

#: 序号最大位数（防止构造超大文件名）
MAX_HANDLE_DIGITS: int = 9

_write_lock = threading.Lock()


def build_handle(domain: str, seq: int) -> str:
    """拼句柄（调用方一般不用，``save`` 会返回）。"""

    return f"evh:{domain}:{int(seq)}"


def parse_handle(handle: str) -> tuple[str, int] | None:
    """解析句柄；格式不对返回 ``None``（**不抛**）。

    这是所有外部输入的入口：模型可能回传任意字符串，这里必须挡住。
    """

    match = EVIDENCE_HANDLE_PATTERN.match(str(handle or "").strip())
    if not match:
        return None
    return match.group("domain"), int(match.group("seq"))


def resolve_session_id(tool_context: Any) -> str:
    """归档目录名。**写入与读取必须走同一个函数**。

    这条规则是硬要求：压缩时用 A 目录存、召回时用 B 目录读，句柄就永远取不回来，
    而且症状很隐蔽——模型只会看到"取不到"，不会报错。

    取值优先级：

    1. 诊断域的 ``session.request_id``（一次诊断的证据都落在一个目录下）；
    2. 否则 ``ToolContext.session_id``（通用会话）；
    3. 都没有 → 空串（此时只出摘要、不写句柄）。
    """

    runtime = getattr(tool_context, "diagnosis_session_runtime", None)
    if runtime is not None:
        request_id = str(getattr(getattr(runtime, "session", None), "request_id", "") or "")
        if request_id:
            return request_id
    return str(getattr(tool_context, "session_id", "") or "")


@dataclass(frozen=True)
class EvidenceStore:
    """按 session 分目录的证据归档。

    ``root`` 默认 ``<user config dir>/evidence``——走 ``get_user_config_dir()``，
    因此尊重 ``$CLOUDAGENT_CONFIG_DIR``（与 sessions/reports 等保持一致）。
    """

    root: Path | None = None
    max_bytes: int = DEFAULT_MAX_BYTES
    max_sessions: int = DEFAULT_MAX_SESSIONS

    # ---- 路径 ----

    def _root(self) -> Path:
        if self.root is not None:
            return Path(self.root)
        from cloudagent_ext.utils.cloudagent_dirs import get_user_config_dir

        return get_user_config_dir() / "evidence"

    def _session_dir(self, session_id: str) -> Path | None:
        if not _SESSION_PATTERN.match(str(session_id or "").strip()):
            return None
        return self._root() / str(session_id).strip()

    def path_for(self, session_id: str, handle: str) -> Path | None:
        """句柄 → 归档文件路径；任何不合规都返回 ``None``。

        两层防护：先验格式，再验"解析后的路径确实在根目录下"——
        后者防的是符号链接与奇怪分隔符。
        """

        parsed = parse_handle(handle)
        session_dir = self._session_dir(session_id)
        if parsed is None or session_dir is None:
            return None
        domain, seq = parsed
        candidate = session_dir / f"evh_{domain}_{seq}.json"
        try:
            resolved = candidate.resolve()
            root_resolved = self._root().resolve()
        except OSError:
            return None
        if root_resolved not in resolved.parents and resolved.parent != root_resolved:
            return None
        return candidate

    # ---- 写 ----

    def save(
        self,
        *,
        session_id: str,
        domain: str,
        tool: str,
        payload: Any,
    ) -> str | None:
        """归档原文并返回句柄；任何失败返回 ``None``。

        **失败必须返回 None 而不是抛**：调用方据此决定"摘要里不写句柄"
        （提案 §2.3 的"不传播"原则）——宁可这一条没折，也不要留一个取不回来的句柄。
        """

        session_dir = self._session_dir(session_id)
        if session_dir is None:
            return None
        domain_text = str(domain or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", domain_text):
            return None

        text = payload if isinstance(payload, str) else json.dumps(
            payload, ensure_ascii=False, default=str
        )
        encoded = text.encode("utf-8")
        if len(encoded) > self.max_bytes:
            logger.info(
                "evidence not archived: %d bytes exceeds limit %d",
                len(encoded),
                self.max_bytes,
            )
            return None

        try:
            session_dir.mkdir(parents=True, exist_ok=True)
            with _write_lock:
                seq = self._next_seq(session_dir, domain_text)
                handle = build_handle(domain_text, seq)
                target = session_dir / f"evh_{domain_text}_{seq}.json"
                record = {
                    "handle": handle,
                    "session_id": str(session_id).strip(),
                    "tool": str(tool or ""),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "original_chars": len(text),
                    "payload": text,
                }
                # 原子写：先写临时文件再 replace，避免留下半截 JSON
                tmp = target.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
                os.replace(tmp, target)
            return handle
        except OSError as exc:  # 只读目录 / 磁盘满 / 权限
            logger.info("evidence archive failed: %s", exc)
            return None
        finally:
            # 清理放在 finally：即使这次归档失败，也不该让旧目录无限堆着。
            # 再包一层 try——finally 里抛异常会盖掉上面的返回值，那才是最坏的结果。
            try:
                self.prune()
            except Exception:  # noqa: BLE001
                logger.debug("evidence prune failed", exc_info=True)

    # ---- 清理 ----

    def prune(self) -> int:
        """按会话整体过期，返回删掉的会话目录数（**永不抛**）。

        策略：只看根目录下的**直接子目录**，按 mtime 从旧到新，
        保留最近 ``max_sessions`` 个，其余整目录删除。

        三条保守约束：

        1. **只碰根目录的直接子目录**——不递归、不跟随符号链接（``is_symlink`` 直接跳过），
           避免把根外的东西删掉；
        2. **失败静默**——Windows 上文件可能被占用，删不掉就下次再删，
           绝不因为清理失败影响归档本身；
        3. **按会话而非按文件**——一次诊断的证据是一体的，留半个会话只会让句柄
           变成"有时能取到、有时取不到"，比全删更让人困惑。
        """

        if self.max_sessions <= 0:
            return 0
        root = self._root()
        try:
            if not root.is_dir():
                return 0
            candidates: list[tuple[float, Path]] = []
            for entry in root.iterdir():
                if entry.is_symlink() or not entry.is_dir():
                    continue
                try:
                    candidates.append((entry.stat().st_mtime, entry))
                except OSError:
                    continue
        except OSError:
            return 0

        if len(candidates) <= self.max_sessions:
            return 0

        candidates.sort(key=lambda item: item[0])
        removed = 0
        for _mtime, directory in candidates[: len(candidates) - self.max_sessions]:
            # 二次确认：解析后仍必须在根之内（防奇怪挂载/符号链接）
            try:
                resolved = directory.resolve()
                root_resolved = root.resolve()
            except OSError:
                continue
            if root_resolved not in resolved.parents:
                continue
            try:
                shutil.rmtree(directory)
                removed += 1
            except OSError as exc:
                logger.debug("evidence prune skipped %s: %s", directory.name, exc)
        if removed:
            logger.info("evidence pruned %d session dirs (kept %d)", removed, self.max_sessions)
        return removed

    def _next_seq(self, session_dir: Path, domain: str) -> int:
        """该域下一个可用序号（同目录内递增；被删过的号不回收）。"""

        highest = 0
        pattern = re.compile(rf"^evh_{re.escape(domain)}_(\d{{1,{MAX_HANDLE_DIGITS}}})\.json$")
        try:
            for entry in session_dir.iterdir():
                match = pattern.match(entry.name)
                if match:
                    highest = max(highest, int(match.group(1)))
        except OSError:
            return 1
        return highest + 1

    # ---- 读 ----

    def load(self, session_id: str, handle: str) -> str | None:
        """按句柄取回原文；取不到返回 ``None``（**不抛**）。

        取不到的原因可能是：句柄非法、session 不匹配、文件被清、内容损坏、超限。
        调用方只关心"有没有拿到"，所以不区分——但要计数（``recall_miss``）。
        """

        path = self.path_for(session_id, handle)
        if path is None:
            return None
        try:
            if not path.is_file():
                return None
            if path.stat().st_size > self.max_bytes * 2:
                # 文件明显过大（上限的 2 倍留出 JSON 包装的余量）→ 拒读，防内存爆
                logger.info("evidence load refused: file too large %s", path.name)
                return None
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.info("evidence load failed: %s", exc)
            return None
        if not isinstance(record, dict):
            return None
        payload = record.get("payload")
        if not isinstance(payload, str):
            return None
        if str(record.get("handle") or "") != str(handle).strip():
            # 文件里的句柄与请求的不一致 → 视为损坏，不返回
            return None
        return payload

    def exists(self, session_id: str, handle: str) -> bool:
        path = self.path_for(session_id, handle)
        return bool(path and path.is_file())
