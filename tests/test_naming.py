"""纯函数测试：命名/大小/文件名归一化（不依赖微信数据库与 Qt）。"""
from __future__ import annotations

import pytest

from wx4view.naming import human_size, normalize_filename, safe_dirname


class TestSafeDirname:
    def test_replaces_windows_illegal_chars(self):
        assert safe_dirname('a/b\\c:d*e?f"g<h>i|j') == "a_b_c_d_e_f_g_h_i_j"

    def test_collapses_spaces(self):
        assert safe_dirname("  产品需求   讨论  ") == "产品需求_讨论"

    def test_keeps_chinese_and_apostrophe(self):
        assert safe_dirname("It's said that…Alice") == "It's_said_that…Alice"

    def test_strips_trailing_dots(self):
        assert safe_dirname("群聊...") == "群聊"

    @pytest.mark.parametrize("raw", ["", "   ", "...", None])
    def test_empty_falls_back(self, raw):
        assert safe_dirname(raw) == "unnamed"

    def test_limit(self):
        assert len(safe_dirname("群" * 100, limit=10)) == 10


class TestHumanSize:
    @pytest.mark.parametrize(
        ("size", "expected"),
        [
            (0, ""),
            (None, ""),
            (500, "1 KB"),
            (2048, "2 KB"),
            (271492, "265 KB"),
            (5 * 1024 * 1024, "5.0 MB"),
            (3 * 1024**3, "3.00 GB"),
        ],
    )
    def test_format(self, size, expected):
        assert human_size(size) == expected

    def test_invalid_input_is_tolerated(self):
        assert human_size("abc") == ""


class TestNormalizeFilename:
    def test_strips_copy_suffix(self):
        assert normalize_filename("20250614_1737(1).txt") == "20250614_1737.txt"
        assert normalize_filename("报告 (2).pdf") == "报告.pdf"

    def test_keeps_digits_inside_name(self):
        assert normalize_filename("v1.2(3).zip") == "v1.2.zip"
        assert normalize_filename("2024(1).xlsx") == "2024.xlsx"

    def test_collapses_spaces_and_lowercases(self):
        assert normalize_filename("  Hello   World.PDF ") == "hello world.pdf"

    def test_idempotent(self):
        once = normalize_filename("A (1).Docx")
        assert normalize_filename(once) == once
