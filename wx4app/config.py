"""应用配置：本地 config.ini（应用目录下）。

结构：
    [general]  account_dir / workspace / export_dir / export_layout
    [logging]  enabled / dir / retention_days / level

日志与工作空间默认都放在应用目录下（便携式），目录不可写时回退到
%LOCALAPPDATA%\\wx4app。旧版本的 config.json 会自动迁移一次。
"""
from __future__ import annotations

import configparser
import json
import os
import sys
from pathlib import Path

APP_NAME_DIR = "wx4app"

DEFAULTS: dict = {
    "account_dir": "",
    "workspace": "",
    "export_dir": "",
    "export_layout": "date",
    "log_enabled": True,
    "log_dir": "",
    "log_retention": 30,
    "log_level": "INFO",
}

LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]


# ---------------------------------------------------------------- 路径
def app_dir() -> Path:
    """应用所在目录（打包后是 exe 同级目录，开发时是项目根目录）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _fallback_dir(kind: str) -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_NAME_DIR
    return base / kind if kind else base


def _writable(path: Path, fallback: Path) -> Path:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_test"
        probe.write_text("1", encoding="utf-8")
        probe.unlink()
        return path
    except OSError:
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def default_workspace_dir() -> str:
    return str(_writable(app_dir() / "workspace", _fallback_dir("workspace")))


def default_logs_dir() -> str:
    return str(_writable(app_dir() / "logs", _fallback_dir("logs")))


def config_file() -> Path:
    target = app_dir() / "config.ini"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        return target
    except OSError:
        base = _fallback_dir("")
        base.mkdir(parents=True, exist_ok=True)
        return base / "config.ini"


# ---------------------------------------------------------------- 读写
def _legacy_json() -> dict:
    """旧版配置（%LOCALAPPDATA%\\wx4app\\config.json）迁移用。"""
    path = Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_NAME_DIR / "config.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load() -> dict:
    cfg = dict(DEFAULTS)
    path = config_file()
    if path.exists():
        parser = configparser.ConfigParser()
        try:
            parser.read(path, encoding="utf-8")
        except (OSError, configparser.Error):
            pass
        if parser.has_section("general"):
            g = parser["general"]
            cfg["account_dir"] = g.get("account_dir", "").strip()
            cfg["workspace"] = g.get("workspace", "").strip()
            cfg["export_dir"] = g.get("export_dir", "").strip()
            cfg["export_layout"] = g.get("export_layout", "date").strip() or "date"
        if parser.has_section("logging"):
            lg = parser["logging"]
            cfg["log_enabled"] = lg.getboolean("enabled", True)
            cfg["log_dir"] = lg.get("dir", "").strip()
            try:
                cfg["log_retention"] = max(1, lg.getint("retention_days", 30))
            except ValueError:
                cfg["log_retention"] = 30
            level = lg.get("level", "INFO").strip().upper()
            cfg["log_level"] = level if level in LOG_LEVELS else "INFO"
    else:
        legacy = _legacy_json()
        if legacy:
            # 只迁移账号目录与导出布局；导出目录统一由工作空间决定
            cfg["account_dir"] = legacy.get("account_dir", "") or ""
            cfg["export_layout"] = legacy.get("export_layout", "date") or "date"

    if not cfg["workspace"]:
        cfg["workspace"] = default_workspace_dir()
    if not cfg["export_dir"]:
        cfg["export_dir"] = cfg["workspace"]
    if not cfg["log_dir"]:
        cfg["log_dir"] = default_logs_dir()
    return cfg


def save(**kw) -> None:
    cfg = load()
    cfg.update({k: v for k, v in kw.items() if v is not None})

    parser = configparser.ConfigParser()
    parser["general"] = {
        "account_dir": str(cfg.get("account_dir") or ""),
        "workspace": str(cfg.get("workspace") or ""),
        "export_dir": str(cfg.get("export_dir") or ""),
        "export_layout": str(cfg.get("export_layout") or "date"),
    }
    parser["logging"] = {
        "enabled": "true" if cfg.get("log_enabled", True) else "false",
        "dir": str(cfg.get("log_dir") or ""),
        "retention_days": str(int(cfg.get("log_retention") or 30)),
        "level": str(cfg.get("log_level") or "INFO"),
    }
    with open(config_file(), "w", encoding="utf-8") as fh:
        parser.write(fh)


def default_export_dir() -> str:
    return load()["export_dir"]


# ---------------------------------------------------------------- 账号目录
def _freshness(acc: Path) -> float:
    """用消息库最后写入时间判断账号是否在用（比目录 mtime 可靠）。"""
    msgs = list((acc / "db_storage" / "message").glob("message_*.db"))
    if msgs:
        try:
            return max(m.stat().st_mtime for m in msgs)
        except OSError:
            pass
    try:
        return (acc / "db_storage").stat().st_mtime
    except OSError:
        return 0.0


def normalize_account(path: str) -> Path | None:
    """用户可能选到 xwechat_files 根、账号目录、甚至 db_storage，这里做归一化。"""
    p = Path(path.strip().strip('"'))
    if not p.exists():
        return None
    if p.name == "db_storage" and p.is_dir():   # 用户直接选到 db_storage 目录
        p = p.parent
    if (p / "db_storage").is_dir():
        return p
    if (p / "xwechat_files").is_dir():
        p = p / "xwechat_files"
    if p.name.endswith("xwechat_files") or p.name == "xwechat_files":
        cands = [c for c in p.iterdir() if c.is_dir() and (c / "db_storage").is_dir()]
        if cands:
            return max(cands, key=_freshness)
    if (p / "msg").is_dir() and (p / "db_storage").is_dir():
        return p
    return None


def detect_candidates() -> list[dict]:
    """扫描本机所有微信 4.x 账号目录，按最近活跃排序（首个为“使用中”）。"""
    roots: list[Path] = []
    home = Path(os.environ.get("USERPROFILE", Path.home()))
    roots.append(home / "Documents" / "xwechat_files")
    for drive in ("C:", "D:", "E:", "F:"):
        users = Path(drive + "/Users")
        if users.exists():
            for u in users.glob("*"):
                roots.append(u / "Documents" / "xwechat_files")
    found: dict[str, Path] = {}
    for root in roots:
        if root.is_dir():
            for c in root.iterdir():
                if (c / "db_storage").is_dir():
                    found[str(c)] = c
    out = []
    for path, acc in found.items():
        try:
            dbs = len(list((acc / "db_storage").rglob("*.db")))
        except OSError:
            dbs = 0
        out.append({"path": path, "name": acc.name, "dbs": dbs,
                    "last_ts": _freshness(acc)})
    out.sort(key=lambda c: -(c["last_ts"] or 0))
    for i, c in enumerate(out):
        c["active"] = i == 0
    return out


def detect_account() -> Path | None:
    """自动探测本机微信 4.x 账号目录。"""
    cands = detect_candidates()
    return Path(cands[0]["path"]) if cands else None
