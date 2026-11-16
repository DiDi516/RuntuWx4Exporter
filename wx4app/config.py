"""本地配置：记住微信账号目录与导出目录。"""
from __future__ import annotations

import json
import os
from pathlib import Path

CFG_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "wx4app"
CFG_FILE = CFG_DIR / "config.json"

DEFAULTS = {"account_dir": "", "export_dir": ""}


def load() -> dict:
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(CFG_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return cfg


def save(**kw) -> None:
    cfg = load()
    cfg.update({k: v for k, v in kw.items() if v is not None})
    CFG_DIR.mkdir(parents=True, exist_ok=True)
    CFG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")


def default_export_dir() -> str:
    cfg = load()
    if cfg.get("export_dir"):
        return cfg["export_dir"]
    cwd = Path.cwd()
    for cand in (cwd / "微信导出", cwd.parent / "微信导出"):
        if cand.is_dir():
            return str(cand)
    return str(Path.home() / "Documents" / "微信导出")


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
    roots: list[Path] = []
    home = Path(os.environ.get("USERPROFILE", Path.home()))
    roots.append(home / "Documents" / "xwechat_files")
    for drive in ("C:", "D:", "E:", "F:"):
        users = Path(drive + "/Users")
        if users.exists():
            for u in users.glob("*"):
                roots.append(u / "Documents" / "xwechat_files")
    found: list[Path] = []
    for root in roots:
        if root.is_dir():
            found += [c for c in root.iterdir() if (c / "db_storage").is_dir()]
    if not found:
        return None
    return max(found, key=_freshness)
