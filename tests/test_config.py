"""目录归一化测试：用户可能选中不同层级的微信目录。"""
from __future__ import annotations

from pathlib import Path

from wx4app.config import _freshness, normalize_account


def _make_account(root: Path, name: str = "wxid_test_1234") -> Path:
    acc = root / "xwechat_files" / name
    (acc / "db_storage" / "message").mkdir(parents=True)
    (acc / "db_storage" / "message" / "message_0.db").write_bytes(b"x" * 16)
    return acc


def test_normalize_accepts_account_dir(tmp_path):
    acc = _make_account(tmp_path)
    assert normalize_account(str(acc)) == acc


def test_normalize_accepts_db_storage(tmp_path):
    acc = _make_account(tmp_path)
    assert normalize_account(str(acc / "db_storage")) == acc


def test_normalize_accepts_xwechat_root(tmp_path):
    acc = _make_account(tmp_path)
    assert normalize_account(str(tmp_path / "xwechat_files")) == acc


def test_normalize_rejects_unknown_path(tmp_path):
    junk = tmp_path / "not_wechat"
    junk.mkdir()
    assert normalize_account(str(junk)) is None


def test_normalize_handles_quoted_and_missing(tmp_path):
    acc = _make_account(tmp_path)
    assert normalize_account(f'"{acc}"') == acc
    assert normalize_account("") is None
    assert normalize_account(str(tmp_path / "nope")) is None


def test_freshness_prefers_newer_message_db(tmp_path):
    old = _make_account(tmp_path / "a", "wxid_old")
    new = _make_account(tmp_path / "b", "wxid_new")
    (new / "db_storage" / "message" / "message_1.db").write_bytes(b"y" * 32)
    assert _freshness(new) > _freshness(old)
