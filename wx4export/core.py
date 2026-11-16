"""wx4export 核心逻辑：定位账号 → 取密钥 → 解密库 → 按名字找会话 → 导出。"""
from __future__ import annotations

import hashlib
import html as html_mod
import json
import os
import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import zstandard as zstd

from wxmanager.wx4 import image_kind, pil_verify, sniff_xor, v2_decrypt, wxgf_to_jpeg
from wxmanager.wx4keys import (
    decrypt_database,
    extract_all_candidates,
    match_keys,
    open_plain,
    verify_key,
)

CACHE_ROOT = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "wx4export"
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
XOR_KEY = 0x35

TYPE_NAME = {
    1: "文本", 3: "图片", 34: "语音", 42: "名片", 43: "视频", 47: "表情",
    48: "位置", 49: "链接/文件", 50: "通话", 10000: "系统消息", 10002: "撤回",
}

# ------------------------------------------------------------------ 账号/密钥
def find_account_dir(explicit: str | None = None, progress=None) -> Path:
    """定位 xwechat_files 下的账号目录。"""
    if explicit:
        p = Path(explicit)
        if not (p / "db_storage").exists():
            raise SystemExit(f"不是有效的微信 4.x 账号目录（缺 db_storage）: {p}")
        return p
    roots = []
    home = Path(os.environ.get("USERPROFILE", Path.home()))
    roots.append(home / "Documents" / "xwechat_files")
    for drive in ("C:", "D:", "E:", "F:"):
        for user_dir in Path(drive + "/Users").glob("*") if Path(drive + "/Users").exists() else []:
            roots.append(user_dir / "Documents" / "xwechat_files")
    for root in roots:
        if not root.exists():
            continue
        cands = [p for p in root.iterdir() if p.is_dir() and (p / "db_storage").exists()]
        if len(cands) == 1:
            return cands[0]
        if cands:
            if progress:
                progress("检测到多个微信账号目录：")
                for i, c in enumerate(cands):
                    progress(f"  [{i}] {c}")
            return max(cands, key=lambda p: (p / "db_storage").stat().st_mtime)
    raise SystemExit("未找到微信 4.x 账号目录，请用 --account 指定（形如 ...\\xwechat_files\\wxid_xxx_d04f）")


def discover_account_dirs() -> list[Path]:
    """列出本机所有微信 4.x 账号目录。"""
    roots: list[Path] = []
    home = Path(os.environ.get("USERPROFILE", Path.home()))
    roots.append(home / "Documents" / "xwechat_files")
    for drive in ("C:", "D:", "E:", "F:"):
        users = Path(drive + "/Users")
        if users.exists():
            for user_dir in users.glob("*"):
                roots.append(user_dir / "Documents" / "xwechat_files")
    found: dict[str, Path] = {}
    for root in roots:
        if not root.exists():
            continue
        for p in root.iterdir():
            if p.is_dir() and (p / "db_storage").exists():
                found[str(p.resolve())] = p
    return list(found.values())


def prepare(account_arg: str | None, progress=None) -> tuple[Path, dict[str, bytes]]:
    """确定账号目录并拿到密钥：优先缓存，否则扫一遍内存后按「能解开的库最多」选账号。"""
    cache_file = CACHE_ROOT / "keys.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache: dict = {}
    if cache_file.exists():
        try:
            cache = json.loads(cache_file.read_text(encoding="utf-8"))
        except ValueError:
            cache = {}

    def cached_keys(acc: Path) -> dict[str, bytes] | None:
        entry = cache.get(str(acc))
        if not entry:
            return None
        keys = {k: bytes.fromhex(v) for k, v in entry.items()}
        sample = list(keys.items())[:2]
        if sample and all(verify_key(acc / "db_storage" / k, v) for k, v in sample):
            return keys
        return None

    if account_arg:
        acc = find_account_dir(account_arg, progress)
        keys = cached_keys(acc)
        if keys:
            if progress:
                progress(f"使用缓存密钥（{len(keys)} 个库）")
            return acc, keys
        if progress:
            progress("正在从微信进程内存提取密钥（需微信已登录）…")
        cands = extract_all_candidates(progress)
        keys = match_keys(acc, cands, progress)
        if not keys:
            raise SystemExit("未能解开该账号的数据库：确认微信已登录，或以管理员身份运行。")
        cache[str(acc)] = {k: v.hex() for k, v in keys.items()}
        cache_file.write_text(json.dumps(cache, indent=1), encoding="utf-8")
        return acc, keys

    accounts = discover_account_dirs()
    if not accounts:
        raise SystemExit("未找到微信 4.x 账号目录，请用 --account 指定")
    # 先看缓存
    for acc in sorted(accounts, key=lambda p: -(p / "db_storage").stat().st_mtime):
        keys = cached_keys(acc)
        if keys:
            if progress:
                progress(f"账号: {acc}")
            return acc, keys
    if progress:
        progress(f"发现 {len(accounts)} 个账号目录，开始提取密钥…")
    cands = extract_all_candidates(progress)
    best: tuple[int, Path, dict[str, bytes]] | None = None
    for acc in accounts:
        keys = match_keys(acc, cands)
        if progress:
            progress(f"  {acc.name}: 解开 {len(keys)} 个库")
        if best is None or len(keys) > best[0]:
            best = (len(keys), acc, keys)
    if not best or not best[2]:
        raise SystemExit("未能获取数据库密钥：请确认微信 4.x 已登录运行，或用管理员身份重试。")
    _, acc, keys = best
    cache[str(acc)] = {k: v.hex() for k, v in keys.items()}
    cache_file.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    if progress:
        progress(f"选定账号: {acc}")
    return acc, keys


def get_keys(account: Path, progress=None) -> dict[str, bytes]:
    """兼容入口：只取指定账号的密钥。"""
    return prepare(str(account), progress)[1]


def ensure_decrypted(account: Path, keys: dict[str, bytes],
                     needed: Iterable[str], progress=None) -> dict[str, Path]:
    """把需要的库解密到缓存目录（按大小+mtime 判断是否复用）。"""
    out_root = CACHE_ROOT / ("db_" + hashlib.md5(str(account).encode()).hexdigest()[:10])
    result: dict[str, Path] = {}
    for rel in needed:
        src = account / "db_storage" / rel
        if not src.exists() or rel not in keys:
            continue
        dst = out_root / rel
        if dst.exists() and dst.stat().st_size >= src.stat().st_size - 8192:
            result[rel] = dst
            continue
        if progress:
            progress(f"  解密 {rel} ({src.stat().st_size/1024/1024:.0f} MB)")
        if decrypt_database(src, keys[rel], dst):
            result[rel] = dst
    return result


# ------------------------------------------------------------------ 会话解析
@dataclass
class Target:
    username: str
    display: str
    is_group: bool
    msg_count: int = 0
    last_ts: int = 0
    db: str = ""
    table: str = ""
    db_list: list[str] = field(default_factory=list)


def _contact_names(contact_db: Path) -> dict[str, str]:
    names: dict[str, str] = {}
    conn = open_plain(contact_db)
    try:
        for r in conn.execute("SELECT username, remark, nick_name, alias FROM contact"):
            names[r["username"]] = (r["remark"] or r["nick_name"] or r["alias"] or r["username"])
    except sqlite3.DatabaseError:
        pass
    conn.close()
    return names


def resolve_targets(contact_db: Path, session_db: Path | None, message_dbs: dict[str, Path],
                    keyword: str, progress=None) -> list[Target]:
    """按群名/昵称/备注/微信号模糊匹配会话，并统计消息数。"""
    names = _contact_names(contact_db)
    kw = keyword.strip().lower()
    hits: list[Target] = []
    seen = set()

    def add(username: str, display: str, is_group: bool):
        if not username or username in seen:
            return
        seen.add(username)
        hits.append(Target(username=username, display=display,
                           is_group=username.endswith("@chatroom")))

    conn = open_plain(contact_db)
    try:
        for r in conn.execute("SELECT username, remark, nick_name, alias FROM contact"):
            u, remark, nick, alias = r["username"], r["remark"] or "", r["nick_name"] or "", r["alias"] or ""
            blob = f"{u}\n{remark}\n{nick}\n{alias}".lower()
            if kw and kw in blob:
                # 完全相等优先
                hits_priority = 0 if kw in (remark.lower(), nick.lower(), alias.lower(), u.lower()) else 1
                add(u, remark or nick or alias or u, u.endswith("@chatroom"))
                if hits_priority:
                    hits[-1].display = f"{remark or nick or alias or u}"
    finally:
        conn.close()

    # 会话表补漏（公众号/未加好友的群等）
    if session_db and session_db.exists():
        try:
            sconn = open_plain(session_db)
            for r in sconn.execute("SELECT username, summary, last_timestamp FROM SessionTable"):
                u = r["username"] or ""
                if u in seen or not u:
                    continue
                disp = names.get(u, u)
                if kw and kw not in f"{u}\n{disp}".lower():
                    continue
                hits.append(Target(u, disp, u.endswith("@chatroom")))
                seen.add(u)
            sconn.close()
        except sqlite3.DatabaseError:
            pass

    # 预统计各消息表规模（同一会话的消息会分片在多个 message_*.db 中）
    table_stats: dict[str, dict] = {}
    for rel, path in message_dbs.items():
        try:
            conn = open_plain(path)
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'")]
            for tbl in tables:
                try:
                    n, last = conn.execute(
                        f"SELECT count(*), max(create_time) FROM {tbl}").fetchone()
                except sqlite3.DatabaseError:
                    continue
                entry = table_stats.setdefault(tbl, {"dbs": [], "count": 0, "last": 0})
                if n:
                    entry["dbs"].append(rel)
                    entry["count"] += n
                    entry["last"] = max(entry["last"], last or 0)
            conn.close()
        except sqlite3.DatabaseError:
            continue

    for t in hits:
        tbl = "Msg_" + hashlib.md5(t.username.encode()).hexdigest()
        entry = table_stats.get(tbl)
        if entry and entry["count"]:
            t.table = tbl
            t.db_list = entry["dbs"]
            t.db = entry["dbs"][0] if entry["dbs"] else ""
            t.msg_count = entry["count"]
            t.last_ts = entry["last"]
    hits = [t for t in hits if t.msg_count]
    hits.sort(key=lambda t: (-t.msg_count, -t.last_ts))
    return hits


# ------------------------------------------------------------------ 消息解析
def _decode_content(local_type: int, data, decompressor) -> tuple[str, str]:
    """返回 (展示文本, 原始 XML/文本)。

    4.x 的 local_type 是复合值：(子类型 << 32) | 主类型，
    例如 244813135921 = (57 << 32) | 49（引用消息）。
    """
    base = local_type & 0xFFFFFFFF
    sub = local_type >> 32
    if data is None:
        return "", ""
    if isinstance(data, bytes):
        if data[:4] == ZSTD_MAGIC:
            try:
                data = decompressor.decompress(data, max_output_size=4 << 20)
            except Exception:
                return "[压缩内容解压失败]", ""
        text = data.decode("utf-8", "ignore")
    else:
        text = str(data)

    if base == 3:
        return "[图片]", text
    if base == 34:
        return "[语音]", text
    if base == 43:
        return "[视频]", text
    if base == 47:
        return "[表情]", text
    if base == 48:
        return "[位置]", text
    if base in (10000, 10002):
        # 撤回/系统提示优先取 CDATA 里的纯文本，避免 XML 属性里的数字残留
        m = (re.search(r"<replacemsg><!\[CDATA\[(.*?)\]\]></replacemsg>", text, re.S)
             or re.search(r"<content><!\[CDATA\[(.*?)\]\]></content>", text, re.S))
        plain = re.sub(r"<[^>]+>", "", m.group(1) if m else text)
        plain = re.sub(r"[\s\u200b]+", " ", plain).strip()
        plain = re.sub(r'^"([^"]+)"', r"\1", plain)      # 去掉人名两侧的引号
        plain = re.sub(r"(消息)\d+$", r"\1", plain)       # 去掉尾部残留序号
        return f"[系统] {plain[:80]}" if plain else "[系统消息]", text
    if base == 49:
        title = re.search(r"<title>(.*?)</title>", text, re.S)
        label = {6: "文件", 5: "链接", 57: "引用", 33: "小程序", 36: "小程序",
                 19: "聊天记录", 51: "视频号", 2000: "转账", 2001: "红包",
                 63: "视频号", 87: "群公告"}.get(sub, "消息")
        name = html_mod.unescape(title.group(1).strip()) if title else ""
        return f"[{label}] {name}".strip(), text
    if base == 42:
        return "[名片]", text
    return text.strip(), text


def _kind_of(base: int, sub: int) -> str:
    """把 4.x 的 (sub<<32|base) 归成前端好用的类型名。"""
    if base == 49:
        return "file" if sub == 6 else ("chatrecord" if sub == 19 else "link")
    return {3: "image", 34: "voice", 43: "video", 47: "sticker", 48: "location",
            42: "card", 10000: "system", 10002: "system"}.get(base, "text")


def _strip_group_prefix(text: str) -> str:
    """群消息正文常带 "wxid_xxx:\\n" 前缀，展示时去掉。"""
    return re.sub(r"^[A-Za-z0-9_\-@.]{4,}:\n", "", text, count=1)


def _sender_name(real_sender_id: int, n2id: dict[int, str], names: dict[str, str],
                 self_wxid: str) -> str:
    u = n2id.get(real_sender_id, "")
    if not u:
        return "未知"
    if u == self_wxid:
        return "我"
    return names.get(u, u)


def _name2id(conn: sqlite3.Connection) -> dict[int, str]:
    out: dict[int, str] = {}
    try:
        for r in conn.execute("SELECT rowid, user_name FROM Name2Id"):
            out[r[0]] = r[1]
    except sqlite3.DatabaseError:
        pass
    return out


# ------------------------------------------------------------------ 图片
class MediaStore:
    """attach 目录索引：md5 -> 最大体积的 dat 文件。"""

    def __init__(self, account: Path, username: str):
        self.base = account / "msg" / "attach" / hashlib.md5(username.encode()).hexdigest()
        self.index: dict[str, Path] = {}
        if self.base.exists():
            for f in self.base.rglob("*.dat"):
                m = re.match(r"^([0-9a-f]{32})", f.stem)
                if not m:
                    continue
                key = m.group(1)
                cur = self.index.get(key)
                try:
                    if cur is None or f.stat().st_size > cur.stat().st_size:
                        self.index[key] = f
                except OSError:
                    continue

    def load(self, md5: str) -> bytes | None:
        f = self.index.get(md5)
        if not f:
            return None
        try:
            data = f.read_bytes()
        except OSError:
            return None
        if data[:6] == b"\x07\x08V2\x08\x07":
            img = v2_decrypt(data, _aes_key(), XOR_KEY)
        else:
            k = sniff_xor(data)
            img = bytes(b ^ k for b in data) if k is not None else None
        if not img:
            return None
        kind = image_kind(img)
        if kind == "wxgf":
            jpg = wxgf_to_jpeg(img)
            return jpg
        if not kind or not pil_verify(img):
            return None
        return img


_AES_KEY: list[bytes] = []


def _aes_key() -> bytes:
    """图片 AES 密钥（与数据库密钥不同，仍由 UIN+wxid 派生）。"""
    return _AES_KEY[0]


def init_image_key(account: Path) -> bytes:
    from wxmanager.wx4 import aes_key_for, discover_uins, wxid_from_account_dir
    from wxmanager.wx4 import v2_decrypt as vd
    wxid = wxid_from_account_dir(account)
    for uin in discover_uins():
        key = aes_key_for(uin, wxid)
        for f in (account / "msg" / "attach").rglob("*.dat"):
            d = f.read_bytes()
            if d[:6] == b"\x07\x08V2\x08\x07":
                p = vd(d, key, XOR_KEY)
                if p and image_kind(p):
                    _AES_KEY[:] = [key]
                    return key
            break
    raise SystemExit("无法推导图片密钥（V2 图片将无法解密）")


# ------------------------------------------------------------------ 导出
@dataclass
class ExportResult:
    target: Target
    out_dir: Path
    messages: int = 0
    images: int = 0
    images_missing: int = 0
    bytes_out: int = 0
    first_ts: int = 0
    last_ts: int = 0


def export_target(account: Path, target: Target, msg_db: Path, names: dict[str, str],
                  self_wxid: str, out_root: Path, progress=None,
                  limit: int = 0) -> ExportResult:
    out_dir = out_root / re.sub(r'[\\/:*?"<>|\s]+', "_", target.display)[:60]
    img_root = out_dir / "图片"
    out_dir.mkdir(parents=True, exist_ok=True)
    res = ExportResult(target=target, out_dir=out_dir)

    media = MediaStore(account, target.username)
    zd = zstd.ZstdDecompressor()

    # 同一会话的消息分片在多个 message_*.db 中，逐库读取后按时间合并
    # 每个分库的 Name2Id 行号互不相同，必须「行 + 该库映射」成对保存
    rows_all: list[tuple[sqlite3.Row, dict[int, str]]] = []
    dbs = target.db_list or [target.db]
    for rel in dbs:
        path = Path(msg_db) if len(dbs) == 1 else Path(msg_db).parent / Path(rel).name
        if not path.exists():
            continue
        conn = open_plain(path)
        local_n2id = _name2id(conn)
        try:
            for row in conn.execute(
                f"SELECT local_id, server_id, local_type, create_time, real_sender_id, "
                f"message_content, packed_info_data FROM {target.table}"):
                rows_all.append((row, local_n2id))
        except sqlite3.DatabaseError:
            pass
        conn.close()
    rows_all.sort(key=lambda t: ((t[0]["create_time"] or 0), t[0]["local_id"] or 0))
    seen_ids, uniq = set(), []
    for item in rows_all:
        r = item[0]
        sid = r["server_id"] or 0
        key = sid if sid else (r["create_time"], r["local_id"])
        if key in seen_ids:
            continue
        seen_ids.add(key)
        uniq.append(item)
    rows_all = uniq
    if limit:
        rows_all = rows_all[-limit:]
    rows = rows_all

    lines: list[str] = []
    html_rows: list[str] = []
    records: list[dict] = []
    last_day = ""
    for _i, (r, n2id) in enumerate(rows):
        ts = r["create_time"] or 0
        dt = datetime.fromtimestamp(ts)
        base = (r["local_type"] or 0) & 0xFFFFFFFF
        sub = (r["local_type"] or 0) >> 32
        display, raw_text = _decode_content(r["local_type"], r["message_content"], zd)
        if base == 1:
            display = _strip_group_prefix(display)
        if base in (10000, 10002):
            who = "系统"
        else:
            who = _sender_name(r["real_sender_id"], n2id, names, self_wxid)
        res.first_ts = res.first_ts or ts
        res.last_ts = ts
        rec = {"ts": ts, "t": f"{dt:%Y-%m-%d %H:%M:%S}", "who": who,
               "me": 1 if who == "我" else 0, "type": _kind_of(base, sub),
               "text": display, "img": ""}

        if base == 3:
            m = re.search(rb"([0-9a-f]{32})", r["packed_info_data"] or b"")
            if not m:
                m2 = re.search(r'md5="([0-9a-f]{32})"', raw_text or "")
                md5 = m2.group(1) if m2 else ""
            else:
                md5 = m.group(1).decode()
            img = media.load(md5) if md5 else None
            if img:
                ext = image_kind(img) or "jpg"
                day_dir = img_root / f"{dt:%Y}" / f"{dt:%m}" / f"{dt:%d}"
                day_dir.mkdir(parents=True, exist_ok=True)
                fn = f"{dt:%H%M%S}_{md5[:8]}.{ext}"
                (day_dir / fn).write_bytes(img)
                res.images += 1
                res.bytes_out += len(img)
                rel = (day_dir / fn).relative_to(out_dir).as_posix()
                rec["text"] = "[图片]"
                rec["img"] = rel
                records.append(rec)
                lines.append(f"[{dt:%H:%M}] {who}: [图片] {rel}")
                html_rows.append(_html_msg(who, dt, f'<img src="{html_mod.escape(rel)}" alt="图片">', who == "我"))
                continue
            res.images_missing += 1
            display = "[图片未在本地找到]"
            rec["text"] = display

        day = f"{dt:%Y-%m-%d}"
        if day != last_day:
            lines.append(f"\n===== {day} =====")
            html_rows.append(f'<div class="day">{day}</div>')
            last_day = day
        lines.append(f"[{dt:%H:%M:%S}] {who}: {display}")
        html_rows.append(_html_msg(who, dt, html_mod.escape(display), who == "我"))
        records.append(rec)

        if progress and res.images and res.images % 100 == 0:
            progress(f"  已导出 {res.images} 张图片…")
    res.messages = len(rows)

    title = f"与 {target.display} 的聊天记录"
    (out_dir / "聊天记录.txt").write_text(
        f"{title}\n导出时间: {datetime.now():%Y-%m-%d %H:%M:%S}\n共 {res.messages} 条消息\n"
        + "=" * 60 + "\n" + "\n".join(lines), encoding="utf-8")
    (out_dir / "聊天记录.html").write_text(_html_doc(title, "\n".join(html_rows), res), encoding="utf-8")
    (out_dir / "messages.json").write_text(json.dumps({
        "name": target.display,
        "username": target.username,
        "is_group": target.is_group,
        "count": res.messages,
        "images": res.images,
        "missing_images": res.images_missing,
        "first_ts": res.first_ts,
        "last_ts": res.last_ts,
        "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "messages": records,
    }, ensure_ascii=False), encoding="utf-8")
    return res


def _html_msg(who: str, dt: datetime, body: str, me: bool) -> str:
    cls = "me" if me else ""
    return (f'<div class="row {cls}"><div class="avatar">{html_mod.escape(who[:1])}</div>'
            f'<div class="col"><div class="name">{html_mod.escape(who)}</div>'
            f'<div class="bubble">{body}</div><div class="time">{dt:%H:%M}</div></div></div>')


_HTML = """<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>
body{{margin:0;background:#f5f5f5;color:#111;font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}}
.wrap{{max-width:760px;margin:0 auto;padding:16px}}
h1{{font-size:16px;text-align:center;color:#666;font-weight:400;margin:8px 0 16px}}
.row{{display:flex;margin:10px 0;align-items:flex-start}}
.row.me{{flex-direction:row-reverse}}
.avatar{{width:36px;height:36px;border-radius:6px;background:#d8d8d8;color:#555;flex:none;
display:flex;align-items:center;justify-content:center;margin:0 8px}}
.me .avatar{{background:#4f7cff;color:#fff}}
.col{{max-width:70%;min-width:0}}
.me .col{{text-align:right}}
.name{{font-size:11px;color:#999;margin-bottom:2px}}
.bubble{{display:inline-block;text-align:left;padding:8px 12px;border-radius:8px;background:#fff;
box-shadow:0 1px 1px rgba(0,0,0,.06);white-space:pre-wrap;word-break:break-word}}
.me .bubble{{background:#95ec69}}
.bubble img{{max-width:100%;border-radius:6px;display:block;cursor:zoom-in}}
.time{{font-size:10px;color:#bbb;margin-top:2px}}
.day{{text-align:center;margin:18px 0 6px}}
.day span,.day{{color:#999;font-size:12px}}
.stats{{text-align:center;color:#999;font-size:12px;padding:24px 0}}
</style></head><body><div class="wrap">
<h1>{title}</h1>
{body}
<div class="stats">消息 {messages} 条 · 图片 {images} 张 · 导出时间 {now}</div>
</div></body></html>"""


def _html_doc(title: str, body: str, res: ExportResult) -> str:
    return _HTML.format(title=html_mod.escape(title), body=body, messages=res.messages,
                        images=res.images, now=f"{datetime.now():%Y-%m-%d %H:%M}")
