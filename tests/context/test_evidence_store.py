#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""证据句柄存储测试（阶段 3 · T3.2）。

两类断言，分量不同：

1. **功能**：存进去能取回来、序号递增、跨 session 隔离；
2. **安全**：句柄会被写进提示、也可能被模型原样回传——所以
   ``load()`` 面对任何奇怪输入都只能返回 ``None``，绝不能真的去开文件。
   这一半用例比功能那半更重要：一个能穿越目录的句柄读取，等于给模型一个
   "读本机任意文件"的入口。

还有一条"不传播"原则的用例：归档失败时必须返回 ``None``，
让调用方知道**不该在摘要里写这个句柄**——取不回来的句柄比没有句柄更糟。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cloudagent_ext.services.compact.evidence_store import (
    EVIDENCE_HANDLE_PATTERN,
    EvidenceStore,
    build_handle,
    parse_handle,
)


@pytest.fixture()
def store(tmp_path: Path) -> EvidenceStore:
    return EvidenceStore(root=tmp_path / "evidence")


class TestHandleFormat:
    def test_build_and_parse(self) -> None:
        handle = build_handle("code", 3)
        assert handle == "evh:code:3"
        assert parse_handle(handle) == ("code", 3)

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "ev:code:1",            # 少了 h，是另一套命名（Gap.evidence_refs）
            "evh:code",             # 缺序号
            "evh:code:",            # 空序号
            "evh:code:abc",         # 序号非数字
            "evh:CODE:1",           # 大写域
            "evh:../../x:1",        # 域里塞路径
            "evh:" + "a" * 40 + ":1",  # 域过长
            "evh:code:1234567890",  # 序号过 9 位
            "evh:code:1x",
        ],
    )
    def test_rejects_bad_handles(self, bad: str) -> None:
        assert parse_handle(bad) is None
        assert EVIDENCE_HANDLE_PATTERN.match(bad) is None

    def test_tolerates_surrounding_whitespace(self) -> None:
        """模型回传时常带空格——strip 后仍要能解析，且**只能**是 strip。"""

        assert parse_handle("  evh:code:1 \n") == ("code", 1)
        # 但中间夹空白就不行了（那说明不是同一个句柄）
        assert parse_handle("evh: code:1") is None


class TestRoundTrip:
    def test_string_payload(self, store: EvidenceStore) -> None:
        text = "x" * 5000
        handle = store.save(session_id="req-1", domain="code", tool="query_table_rows", payload=text)
        assert handle is not None
        assert store.load("req-1", handle) == text

    def test_dict_payload_is_serialised(self, store: EvidenceStore) -> None:
        payload = {"mode": "rows", "rows": [{"id": 1}]}
        handle = store.save(session_id="req-1", domain="code", tool="query_table_rows", payload=payload)
        assert handle is not None
        loaded = store.load("req-1", handle)
        assert loaded is not None
        assert json.loads(loaded) == payload

    def test_sequence_increments(self, store: EvidenceStore) -> None:
        first = store.save(session_id="req-1", domain="code", tool="t", payload="a")
        second = store.save(session_id="req-1", domain="code", tool="t", payload="b")
        assert (first, second) == ("evh:code:1", "evh:code:2")

    def test_sequence_is_per_domain(self, store: EvidenceStore) -> None:
        store.save(session_id="req-1", domain="code", tool="t", payload="a")
        other = store.save(session_id="req-1", domain="sql", tool="t", payload="b")
        assert other == "evh:sql:1"

    def test_domain_is_lowercased(self, store: EvidenceStore) -> None:
        handle = store.save(session_id="req-1", domain="CODE", tool="t", payload="a")
        assert handle == "evh:code:1"

    def test_file_name_is_windows_safe(self, store: EvidenceStore, tmp_path: Path) -> None:
        """句柄里有 ``:``，Windows 文件名不允许——文件名必须换一种写法。"""

        handle = store.save(session_id="req-1", domain="code", tool="t", payload="a")
        assert handle is not None
        files = list((tmp_path / "evidence" / "req-1").iterdir())
        assert [f.name for f in files] == ["evh_code_1.json"]
        assert ":" not in files[0].name

    def test_exists(self, store: EvidenceStore) -> None:
        handle = store.save(session_id="req-1", domain="code", tool="t", payload="a")
        assert store.exists("req-1", handle) is True
        assert store.exists("req-1", "evh:code:99") is False


class TestIsolation:
    def test_session_isolation(self, store: EvidenceStore) -> None:
        handle = store.save(session_id="req-1", domain="code", tool="t", payload="secret")
        assert handle is not None
        assert store.load("req-2", handle) is None

    @pytest.mark.parametrize("bad_session", ["", "../etc", "req/1", "a" * 80, "req 1"])
    def test_bad_session_rejected(self, store: EvidenceStore, bad_session: str) -> None:
        assert store.save(session_id=bad_session, domain="code", tool="t", payload="a") is None


class TestSecurity:
    """句柄来自模型输出 → 必须当敌意输入处理。"""

    @pytest.mark.parametrize(
        "hostile",
        [
            "../../../etc/passwd",
            "..\\..\\windows\\system32\\config",
            "C:/Windows/win.ini",
            "/etc/passwd",
            "evh:code:1/../../x",
            "evh:..:1",
            "evh:code:1\x00",
            "'; DROP TABLE x; --",
        ],
    )
    def test_hostile_handle_returns_none(self, store: EvidenceStore, hostile: str) -> None:
        assert store.load("req-1", hostile) is None

    def test_path_stays_under_root(self, store: EvidenceStore, tmp_path: Path) -> None:
        handle = store.save(session_id="req-1", domain="code", tool="t", payload="a")
        path = store.path_for("req-1", handle)
        assert path is not None
        assert (tmp_path / "evidence").resolve() in path.resolve().parents

    def test_symlink_escape_refused(self, store: EvidenceStore, tmp_path: Path) -> None:
        """就算有人在归档目录里塞了符号链接，载入路径也必须落在根内。"""

        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "evh_code_1.json").write_text(
            json.dumps({"handle": "evh:code:1", "payload": "LEAK"}), encoding="utf-8"
        )
        session_dir = tmp_path / "evidence" / "req-1"
        session_dir.mkdir(parents=True)
        link = session_dir / "evh_code_1.json"
        try:
            link.symlink_to(outside / "evh_code_1.json")
        except (OSError, NotImplementedError):
            pytest.skip("当前平台/权限不允许创建符号链接")
        # 解析后的路径落在根外 → 拒绝
        assert store.load("req-1", "evh:code:1") is None


class TestPrune:
    """按会话整体过期。

    为什么不是逐文件淘汰：一次诊断的证据是一体的，留半个会话只会让句柄
    变成"有时能取到、有时取不到"——比全删更让人困惑。
    """

    def _fill(self, store: EvidenceStore, count: int) -> None:
        import time

        for index in range(count):
            handle = store.save(
                session_id=f"req-{index}",
                domain="db",
                tool="query_table_rows",
                payload=f"payload-{index}",
            )
            assert handle is not None
            time.sleep(0.01)  # 让 mtime 可区分

    def test_keeps_most_recent(self, tmp_path: Path) -> None:
        root = tmp_path / "evidence"
        store = EvidenceStore(root=root, max_sessions=3)
        self._fill(store, 5)

        survivors = sorted(p.name for p in root.iterdir())
        assert survivors == ["req-2", "req-3", "req-4"]
        assert store.load("req-4", "evh:db:1") == "payload-4"
        assert store.load("req-0", "evh:db:1") is None

    def test_no_prune_below_limit(self, tmp_path: Path) -> None:
        root = tmp_path / "evidence"
        store = EvidenceStore(root=root, max_sessions=10)
        self._fill(store, 3)
        assert len(list(root.iterdir())) == 3

    def test_zero_disables_prune(self, tmp_path: Path) -> None:
        root = tmp_path / "evidence"
        store = EvidenceStore(root=root, max_sessions=0)
        self._fill(store, 4)
        assert len(list(root.iterdir())) == 4

    def test_loose_files_not_deleted(self, tmp_path: Path) -> None:
        """根目录下的散文件不归我们管，不能顺手删。"""

        root = tmp_path / "evidence"
        store = EvidenceStore(root=root, max_sessions=1)
        root.mkdir(parents=True)
        keep = root / "notes.txt"
        keep.write_text("don't touch", encoding="utf-8")
        self._fill(store, 3)
        assert keep.exists()

    def test_symlinked_dir_not_followed(self, tmp_path: Path) -> None:
        """符号链接目录必须跳过——否则可能顺着链接删到根外面。"""

        root = tmp_path / "evidence"
        outside = tmp_path / "outside"
        root.mkdir(parents=True)
        outside.mkdir()
        precious = outside / "keep.txt"
        precious.write_text("keep", encoding="utf-8")
        link = root / "req-link"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("当前平台/权限不允许创建符号链接")

        store = EvidenceStore(root=root, max_sessions=1)
        self._fill(store, 3)

        assert precious.exists(), "顺着符号链接把根外的东西删了"
        assert link.is_symlink(), "符号链接本身也不该被删"

    def test_delete_failure_is_swallowed(self, tmp_path: Path, monkeypatch) -> None:
        """删不掉（文件被占用等）不能影响归档本身。"""

        root = tmp_path / "evidence"
        store = EvidenceStore(root=root, max_sessions=1)
        self._fill(store, 2)

        import shutil as shutil_module

        def boom(*args, **kwargs):
            raise OSError("locked")

        monkeypatch.setattr(shutil_module, "rmtree", boom)
        assert store.prune() == 0  # 不抛
        handle = store.save(session_id="req-new", domain="db", tool="t", payload="ok")
        assert handle is not None  # 归档照常成功

    def test_prune_never_raises_on_missing_root(self, tmp_path: Path) -> None:
        store = EvidenceStore(root=tmp_path / "not-there", max_sessions=2)
        assert store.prune() == 0

    def test_archive_failure_returns_none(self, tmp_path: Path) -> None:
        """归档目录不可建（这里用"root 是个文件"来可靠触发 OSError）。"""

        blocker = tmp_path / "blocker"
        blocker.write_text("not a dir", encoding="utf-8")
        store = EvidenceStore(root=blocker)
        assert store.save(session_id="req-1", domain="code", tool="t", payload="a") is None

    def test_oversize_refused(self, tmp_path: Path) -> None:
        store = EvidenceStore(root=tmp_path / "evidence", max_bytes=100)
        assert store.save(session_id="req-1", domain="code", tool="t", payload="x" * 200) is None

    def test_missing_handle(self, store: EvidenceStore) -> None:
        assert store.load("req-1", "evh:code:7") is None

    def test_corrupt_json(self, store: EvidenceStore, tmp_path: Path) -> None:
        handle = store.save(session_id="req-1", domain="code", tool="t", payload="a")
        assert handle is not None
        path = store.path_for("req-1", handle)
        assert path is not None
        path.write_text("{broken", encoding="utf-8")
        assert store.load("req-1", handle) is None

    def test_handle_mismatch_inside_file(self, store: EvidenceStore) -> None:
        """文件里的 handle 与请求的不一致 → 视为损坏（防错位读取）。"""

        handle = store.save(session_id="req-1", domain="code", tool="t", payload="a")
        assert handle is not None
        path = store.path_for("req-1", handle)
        assert path is not None
        record = json.loads(path.read_text(encoding="utf-8"))
        record["handle"] = "evh:code:999"
        path.write_text(json.dumps(record), encoding="utf-8")
        assert store.load("req-1", handle) is None

    def test_payload_not_string(self, store: EvidenceStore) -> None:
        handle = store.save(session_id="req-1", domain="code", tool="t", payload="a")
        assert handle is not None
        path = store.path_for("req-1", handle)
        assert path is not None
        path.write_text(json.dumps({"handle": handle, "payload": 123}), encoding="utf-8")
        assert store.load("req-1", handle) is None
