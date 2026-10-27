#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# This file is part of CloudAgent.
# Copyright (c) 2026 CloudAgent Authors
# Licensed under the MIT License. See the LICENSE file in the project root.
# ---------------------------------------------------------------------------

"""日志 / 代码工具的路径逃逸对抗测试（P5.3）。

此前安全套件只覆盖 SQL 域（42 例），log / code 两个域的工具**从未做过对抗测试**。
本文件针对"能不能读到根目录之外"这一条最危险的边界：

- 相对路径逃逸（``../../etc/passwd``）
- 绝对路径（绕过相对路径假设）
- 未配置根目录时的行为（不能默默读当前目录）
- 根目录不存在时（不能回退到 cwd）

工具层与参数校验层各测一次：**校验函数是防线，工具返回是读者能看到的结果**。
"""

from __future__ import annotations

import os

import pytest

from cloudagent_ext.diagnosis.code import tools as code_tools
from cloudagent_ext.diagnosis.log import tools as log_tools

# 绝对路径要按平台取：POSIX 上 C:/... 只是相对名字，不会被判成绝对路径。
ABSOLUTE_FILE = "C:/Windows/win.ini" if os.name == "nt" else "/etc/passwd"
ABSOLUTE_DIR = "C:/Windows" if os.name == "nt" else "/etc"


class TestLogRootEscape:
    def test_relative_escape_rejected(self, tmp_path) -> None:
        (tmp_path / "a.log").write_text("x", encoding="utf-8")
        with pytest.raises(ValueError, match="path_outside_root"):
            log_tools._validate_file("../escape.log", tmp_path)

    def test_nested_escape_rejected(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="path_outside_root"):
            log_tools._validate_file("sub/../../escape.log", tmp_path)

    def test_absolute_path_rejected(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="path_must_be_relative"):
            log_tools._validate_file(ABSOLUTE_FILE, tmp_path)

    def test_empty_rejected(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="file is required"):
            log_tools._validate_file("", tmp_path)

    def test_get_log_context_rejects_escape(self, tmp_path, monkeypatch) -> None:
        """``get_log_context`` 接收的是真路径；逃逸必须在工具层可见地失败。"""

        monkeypatch.setenv("CLOUDAGENT_LOG_ROOT", str(tmp_path))
        (tmp_path / "a.log").write_text("2026-10-22 09:00:00 INFO ok", encoding="utf-8")
        result = log_tools._get_log_context_call({"file": "../../escape.log"}, None)
        assert result.is_error is True
        assert "path_outside_root" in str(result.output.get("message", ""))

    def test_search_logs_file_is_filter_not_path(self, tmp_path, monkeypatch) -> None:
        """``search_logs`` 的 ``file`` 是文件名子串过滤器，不用于打开文件。

        记录该语义：传 ``../../x.log`` 不会读到根外文件（因为压根不按路径打开），
        但也**不会报错**——它只是没有匹配项。真正的路径入口是 ``get_log_context``。
        """

        monkeypatch.setenv("CLOUDAGENT_LOG_ROOT", str(tmp_path))
        (tmp_path / "a.log").write_text("2026-10-22 09:00:00 INFO ok", encoding="utf-8")
        result = log_tools._search_logs_call({"file": "../../escape.log"}, None)
        assert result.is_error is False
        assert result.output.get("matches") == []

    def test_missing_root_env_fails_loudly(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("CLOUDAGENT_LOG_ROOT", raising=False)
        with pytest.raises(ValueError, match="log_root_not_configured"):
            log_tools.resolve_log_root()

    def test_invalid_root_fails_loudly(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("CLOUDAGENT_LOG_ROOT", str(tmp_path / "nope"))
        with pytest.raises(ValueError, match="log_root_invalid"):
            log_tools.resolve_log_root()


class TestCodeRootEscape:
    def test_relative_escape_rejected(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="path_outside_root"):
            code_tools._validate_relative_path("../outside", tmp_path)

    def test_absolute_path_rejected(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="path_must_be_relative"):
            code_tools._validate_relative_path(ABSOLUTE_DIR, tmp_path)

    def test_root_env_override(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("CLOUDAGENT_CODE_ROOT", str(tmp_path))
        assert code_tools.resolve_code_root() == tmp_path.resolve()

    def test_find_symbol_outside_root_is_error(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("CLOUDAGENT_CODE_ROOT", str(tmp_path))
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "mod.py").write_text("def target(): pass\n", encoding="utf-8")

        # 正常路径能查到（对照组，避免"永远报错"的假安全）
        ok = code_tools._find_symbol_call({"name": "target", "path": "pkg"}, None)
        assert ok.is_error is False

        escaped = code_tools._find_symbol_call({"name": "target", "path": "../.."}, None)
        assert escaped.is_error is True
        assert "path_outside_root" in str(escaped.output.get("message", ""))
