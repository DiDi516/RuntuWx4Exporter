"""config.ini 读写、默认路径与容错测试。"""
from __future__ import annotations

from pathlib import Path

import pytest

from wx4app import config


@pytest.fixture()
def ini(tmp_path, monkeypatch):
    target = tmp_path / "config.ini"
    monkeypatch.setattr(config, "config_file", lambda: target)
    # 避免读到本机旧版 config.json 的迁移数据
    monkeypatch.setattr(config, "_legacy_json", lambda: {})
    return target


def test_save_creates_ini_with_sections(ini, tmp_path):
    ws = tmp_path / "workspace"
    logs = tmp_path / "logs"
    config.save(account_dir=r"E:\wx\wxid_test", workspace=str(ws), export_dir=str(ws),
                log_enabled=True, log_dir=str(logs), log_retention=7, log_level="DEBUG")
    assert ini.exists()
    text = ini.read_text(encoding="utf-8")
    assert "[general]" in text and "[logging]" in text
    assert "retention_days = 7" in text
    assert "level = DEBUG" in text


def test_roundtrip(ini, tmp_path):
    ws = str(tmp_path / "ws")
    config.save(workspace=ws, export_dir=ws, log_enabled=False,
                log_dir=str(tmp_path / "lg"), log_retention=14, log_level="WARNING")
    cfg = config.load()
    assert cfg["workspace"] == ws
    assert cfg["export_dir"] == ws
    assert cfg["log_enabled"] is False
    assert cfg["log_retention"] == 14
    assert cfg["log_level"] == "WARNING"


def test_invalid_values_fall_back(ini, tmp_path):
    ini.write_text(
        "[general]\nworkspace = " + str(tmp_path / "ws") + "\n\n"
        "[logging]\nretention_days = abc\nlevel = NOISY\n",
        encoding="utf-8",
    )
    (tmp_path / "ws").mkdir()
    cfg = config.load()
    assert cfg["log_retention"] == 30
    assert cfg["log_level"] == "INFO"


def test_defaults_fill_when_missing(ini):
    cfg = config.load()
    assert cfg["workspace"]
    assert cfg["export_dir"] == cfg["workspace"]
    assert cfg["log_retention"] == 30
    assert Path(cfg["log_dir"]).name == "logs"


def test_default_dirs_under_app_dir():
    assert config.default_logs_dir().endswith("logs")
    assert config.default_workspace_dir().endswith("workspace")
    assert Path(config.default_logs_dir()).exists()
