"""wx4view 实时数据源：直连解密后的微信 4.x 数据库，按需解析会话/消息/图片。

相比「只读导出目录」，这里能列出**全部会话**，点开任意一个即时解析，
图片按需解密并缓存到本地，支持一键导出当前会话的图片与聊天记录。
"""
from __future__ import annotations

import base64
import hashlib
import html as html_mod
import json
import re
import shutil
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

import zstandard as zstd

from wx4export.core import (
    CACHE_ROOT,
    MediaStore,
    _contact_names,
    _decode_content,
    _kind_of,
    _name2id,
    _sender_name,
    _strip_group_prefix,
    ensure_decrypted,
    init_image_key,
    prepare,
)
from wxmanager.wx4 import wxid_from_account_dir
from wxmanager.wx4keys import open_plain

from .naming import human_size, normalize_filename
from .naming import safe_dirname as _safe

IMG_CACHE = CACHE_ROOT / "img"


def _clean_preview(text: str) -> str:
    if not text:
        return ""
    t = re.sub(r"<[^>]+>", "", text)
    t = re.sub(r"[\s\u200b]+", " ", t).strip()
    return t[:44]


class LiveSource:
    """直连微信库的数据源。"""

    def __init__(self, account_arg: str | None = None, progress=None):
        self.progress = progress or (lambda s: None)
        self.account, self.keys = prepare(account_arg, progress)
        needed = ["contact/contact.db", "session/session.db", "head_image/head_image.db"] + [
            f"message/message_{i}.db" for i in range(8)]
        dbs = ensure_decrypted(self.account, self.keys, needed, progress)
        if "contact/contact.db" not in dbs:
            raise RuntimeError("contact.db 解密失败")
        self.contact_db = dbs["contact/contact.db"]
        self.session_db = dbs.get("session/session.db")
        self.msg_dbs = {k: v for k, v in dbs.items() if k.startswith("message/message_")}
        self.names = _contact_names(self.contact_db)
        self.self_wxid = wxid_from_account_dir(self.account)

        self.table_index: dict[str, list[str]] = {}
        self.table_count: dict[str, int] = {}
        self.table_last: dict[str, int] = {}
        self._scan_tables()

        self._avatars: dict[str, bytes] = {}
        self._load_avatars(dbs)
        self.sessions = self._build_sessions()
        self._msg_cache: dict[str, list[dict]] = {}
        self._media: dict[str, MediaStore] = {}
        init_image_key(self.account)
        # 注意：zstandard 的 decompressor 不是线程安全的，多线程解析时会崩溃，
        # 因此每次解析都新建一个；缓存读写用锁保护。
        self._cache_lock = threading.Lock()
        self._msg_cache: dict[str, list[dict]] = {}
        self._count_cache: dict[str, tuple[int, int, int, int]] = {}

    # ---------------- 初始化 ----------------
    def _scan_tables(self) -> None:
        for rel, path in self.msg_dbs.items():
            try:
                conn = open_plain(path)
                for (tbl,) in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"):
                    try:
                        n, last = conn.execute(
                            f"SELECT count(*), max(create_time) FROM {tbl}").fetchone()
                    except sqlite3.DatabaseError:
                        continue
                    if not n:
                        continue
                    self.table_index.setdefault(tbl, []).append(rel)
                    self.table_count[tbl] = self.table_count.get(tbl, 0) + n
                    self.table_last[tbl] = max(self.table_last.get(tbl, 0), last or 0)
                conn.close()
            except sqlite3.DatabaseError:
                continue

    def _build_sessions(self) -> list[dict]:
        out: list[dict] = []
        seen: set[str] = set()
        titles: dict[str, str] = {}
        summaries: dict[str, str] = {}
        last_ts: dict[str, int] = {}
        if self.session_db and self.session_db.exists():
            try:
                conn = open_plain(self.session_db)
                try:
                    for r in conn.execute("SELECT username, summary, last_timestamp FROM SessionTable"):
                        u = r["username"] or ""
                        if not u:
                            continue
                        summaries[u] = r["summary"] or ""
                        last_ts[u] = r["last_timestamp"] or 0
                except sqlite3.DatabaseError:
                    pass
                try:
                    for r in conn.execute("SELECT username, session_title FROM SessionNoContactInfoTable"):
                        titles[r["username"]] = r["session_title"] or ""
                except sqlite3.DatabaseError:
                    pass
                conn.close()
            except sqlite3.DatabaseError:
                pass

        candidates = set(summaries) | set(self.names)
        for u in candidates:
            h = hashlib.md5(u.encode()).hexdigest()
            tbl = "Msg_" + h
            if tbl not in self.table_count:
                continue
            name = self.names.get(u) or titles.get(u) or u
            out.append({
                "id": u,
                "name": name,
                "is_group": u.endswith("@chatroom"),
                "count": self.table_count[tbl],
                "images": 0,
                "last_ts": self.table_last.get(tbl, 0) or last_ts.get(u, 0),
                "preview": _clean_preview(summaries.get(u, "")),
            })
            seen.add(u)
        out.sort(key=lambda s: -(s["last_ts"] or 0))
        return out

    # ---------------- 头像 ----------------
    def _load_avatars(self, dbs: dict[str, Path]) -> None:
        db = dbs.get("head_image/head_image.db")
        if not db:
            return
        try:
            conn = open_plain(db)
            for r in conn.execute("SELECT username, image_buffer FROM head_image"):
                blob = r["image_buffer"]
                if blob:
                    self._avatars[r["username"]] = bytes(blob)
            conn.close()
        except sqlite3.DatabaseError:
            pass

    def avatar_path(self, username: str) -> Path | None:
        """真实好友头像（head_image.db），落盘缓存后返回路径。"""
        data = self._avatars.get(username)
        if not data:
            return None
        folder = IMG_CACHE / "avatars"
        folder.mkdir(parents=True, exist_ok=True)
        p = folder / f"{hashlib.md5(username.encode()).hexdigest()}.img"
        if not p.exists():
            p.write_bytes(data)
        return p

    # ---------------- 查询 ----------------
    def list_sessions(self, q: str = "", kind: str = "all") -> list[dict]:
        res = self.sessions
        if kind == "group":
            res = [s for s in res if s["is_group"]]
        elif kind == "single":
            res = [s for s in res if not s["is_group"]]
        if q:
            k = q.lower()
            res = [s for s in res if k in s["name"].lower() or k in s["id"].lower()]
        return res[:500]

    def _table_for(self, username: str) -> str:
        return "Msg_" + hashlib.md5(username.encode()).hexdigest()

    _SQL_COLS = ("local_id, server_id, local_type, create_time, real_sender_id, "
                 "message_content, packed_info_data")

    def _fetch(self, username: str, limit: int = 0, before: int | None = None,
               only_images: bool = False, start_ts: int = 0,
               end_ts: int = 0, only_files: bool = False) -> list[tuple[sqlite3.Row, dict[int, str]]]:
        """按需从各分库取一页消息（倒序），不再整表解析。"""
        tbl = self._table_for(username)
        rows: list[tuple[sqlite3.Row, dict[int, str]]] = []
        for rel in self.table_index.get(tbl, []):
            conn = open_plain(self.msg_dbs[rel])
            n2id = _name2id(conn)
            sql = f"SELECT {self._SQL_COLS} FROM {tbl}"
            conds, args = [], []
            if before:
                conds.append("create_time < ?")
                args.append(before)
            if only_images:
                conds.append("(local_type & 4294967295) = 3")
            if only_files:
                conds.append("(local_type & 4294967295) = 49 AND (local_type >> 32) = 6")
            if start_ts:
                conds.append("create_time >= ?")
                args.append(int(start_ts))
            if end_ts:
                conds.append("create_time <= ?")
                args.append(int(end_ts))
            if conds:
                sql += " WHERE " + " AND ".join(conds)
            sql += " ORDER BY create_time DESC, local_id DESC"
            if limit:
                sql += " LIMIT ?"
                args.append(limit + 1)
            try:
                for r in conn.execute(sql, args):
                    rows.append((r, n2id))
            except sqlite3.DatabaseError:
                pass
            finally:
                conn.close()
        rows.sort(key=lambda t: ((t[0]["create_time"] or 0), t[0]["local_id"] or 0),
                  reverse=True)
        seen, uniq = set(), []
        for item in rows:
            r = item[0]
            sid = r["server_id"] or 0
            key = sid if sid else (r["create_time"], r["local_id"])
            if key in seen:
                continue
            seen.add(key)
            uniq.append(item)
        return uniq

    def _counts(self, username: str) -> tuple[int, int, int, int]:
        """(消息总数, 图片数, 最早时间, 最晚时间)，结果缓存。"""
        with self._cache_lock:
            hit = self._count_cache.get(username)
        if hit:
            return hit
        tbl = self._table_for(username)
        total = images = 0
        first, last = 0, 0
        for rel in self.table_index.get(tbl, []):
            conn = open_plain(self.msg_dbs[rel])
            try:
                row = conn.execute(
                    f"SELECT count(*) c, min(create_time) a, max(create_time) b, "
                    f"sum(case when (local_type & 4294967295) = 3 then 1 else 0 end) i "
                    f"FROM {tbl}").fetchone()
                total += row["c"] or 0
                images += row["i"] or 0
                a, b = row["a"] or 0, row["b"] or 0
                first = min(first, a) if first else a
                last = max(last, b)
            except sqlite3.DatabaseError:
                pass
            finally:
                conn.close()
        result = (total, images, first, last)
        with self._cache_lock:
            self._count_cache[username] = result
        return result

    def _file_count(self, username: str) -> int:
        key = f"__files__{username}"
        with self._cache_lock:
            hit = self._count_cache.get(key)
        if hit:
            return hit[0]
        tbl = self._table_for(username)
        total = 0
        for rel in self.table_index.get(tbl, []):
            conn = open_plain(self.msg_dbs[rel])
            try:
                row = conn.execute(
                    f"SELECT count(*) c FROM {tbl} WHERE (local_type & 4294967295) = 49 "
                    f"AND (local_type >> 32) = 6").fetchone()
                total += row["c"] or 0
            except sqlite3.DatabaseError:
                pass
            finally:
                conn.close()
        with self._cache_lock:
            self._count_cache[key] = (total, 0, 0, 0)
        return total

    def _parse_rows(self, rows, username: str) -> list[dict]:
        """把 (row, n2id) 转成前端用的消息字典，按时间升序。"""
        zd = zstd.ZstdDecompressor()  # 每线程独立，避免 C 扩展并发崩溃
        out: list[dict] = []
        for r, n2id in reversed(rows):
            ts = r["create_time"] or 0
            dt = datetime.fromtimestamp(ts)
            ltype = r["local_type"] or 0
            base, sub = ltype & 0xFFFFFFFF, ltype >> 32
            text, raw = _decode_content(ltype, r["message_content"], zd)
            if base == 1:
                text = _strip_group_prefix(text)
            who = "系统" if base in (10000, 10002) else _sender_name(
                r["real_sender_id"], n2id, self.names, self.self_wxid)
            kind = _kind_of(base, sub)
            uid = n2id.get(r["real_sender_id"], "") if base not in (10000, 10002) else ""
            fname, fsize = "", 0
            if base == 49 and sub == 6:
                mt = re.search(r"<title>(.*?)</title>", raw or "", re.S)
                if mt:
                    fname = html_mod.unescape(mt.group(1)).strip()
                ms = re.search(r"<totallen>(\d+)</totallen>", raw or "")
                fsize = int(ms.group(1)) if ms else 0
            dur = 0
            if base == 34:
                mv = re.search(r'voicelength="(\d+)"', raw or "")
                if mv:
                    dur = max(1, round(int(mv.group(1)) / 1000))
            md5 = ""
            if base == 3:
                m = re.search(rb"([0-9a-f]{32})", r["packed_info_data"] or b"")
                if m:
                    md5 = m.group(1).decode()
                else:
                    m2 = re.search(r'md5="([0-9a-f]{32})"', raw or "")
                    md5 = m2.group(1) if m2 else ""
            out.append({
                "ts": ts,
                "t": f"{dt:%Y-%m-%d %H:%M:%S}",
                "who": who,
                "me": 1 if who == "我" else 0,
                "type": kind,
                "text": (f"[语音] {dur}″" if base == 34 else
                         (text if base != 3 else ("[图片]" if md5 else "[图片未找到]"))),
                "dur": dur,
                "src": f"/img/{username}/{md5}" if md5 else "",
                "_md5": md5,
                "_uid": uid,
                "_fname": fname,
                "_fsize": fsize,
                "_fkey": f"{fname}|{fsize}" if fname else "",
            })
        return out

    def messages(self, username: str, limit: int = 150, before: int | None = None) -> dict:
        if not username:
            return {"error": "no conv", "messages": []}
        rows = self._fetch(username, limit, before)
        more = len(rows) > limit
        rows = rows[:limit]
        msgs = self._parse_rows(rows, username)
        total, images, first, last = self._counts(username)
        return {
            "name": self.names.get(username, username),
            "is_group": username.endswith("@chatroom"),
            "count": total,
            "images": images,
            "files": self._file_count(username),
            "first_ts": first,
            "last_ts": last,
            "messages": msgs,
            "has_more": more,
            "next_before": msgs[0]["ts"] if msgs else 0,
        }

    def images(self, username: str, limit: int = 2000) -> list[dict]:
        rows = self._fetch(username, limit, only_images=True)
        return [{"t": m["t"], "who": m["who"], "me": m["me"], "src": m["src"], "ts": m["ts"]}
                for m in self._parse_rows(rows, username) if m.get("src")]

    # ---------------- 文件 ----------------
    def _file_index(self):
        """返回 (文件名索引, 大小索引)。只扫一遍 msg/file。"""
        cache = getattr(self, "_fidx", None)
        if cache is not None:
            return cache
        by_name: dict[str, list[Path]] = {}
        by_size: dict[int, list[Path]] = {}
        root = self.account / "msg" / "file"
        if root.is_dir():
            for f in root.rglob("*"):
                if not f.is_file():
                    continue
                by_name.setdefault(f.name.lower(), []).append(f)
                try:
                    by_size.setdefault(f.stat().st_size, []).append(f)
                except OSError:
                    pass
        self._fidx = (by_name, by_size)
        return self._fidx

    @staticmethod
    def _norm_name(name: str) -> str:
        return normalize_filename(name)

    def _find_file(self, fname: str, fsize: int) -> Path | None:
        if not fname:
            return None
        by_name, by_size = self._file_index()
        key = fname.lower()
        cands = list(by_name.get(key, []))
        if not cands:                      # 本地文件名可能带哈希前缀
            cands = [p for n, ps in by_name.items() if n.endswith(key) for p in ps]
        if not cands:                      # 去掉 (1) 后缀再试
            nk = self._norm_name(fname)
            cands = [p for n, ps in by_name.items() if self._norm_name(n) == nk for p in ps]
        if cands and fsize:
            for p in cands:
                try:
                    if p.stat().st_size == fsize:
                        return p
                except OSError:
                    continue
        if cands:
            return cands[0]
        if fsize:                          # 名称对不上时，按大小唯一匹配
            same = by_size.get(fsize, [])
            if len(same) == 1:
                return same[0]
        return None

    def export_files(self, username: str, out_root: Path, progress=None,
                     should_stop=None, start_ts: int = 0, end_ts: int = 0,
                     layout: str = "date") -> dict:
        msgs = self._parse_rows(
            self._fetch(username, 0, only_files=True, start_ts=start_ts, end_ts=end_ts),
            username)
        name = self.names.get(username, username)
        base_dir = Path(out_root) / _safe(name)
        file_root = base_dir / "文件"
        done: set[str] = set()
        mapping: dict[str, str] = {}
        count = 0
        missing = 0
        uniq = [m for m in msgs if m.get("_fkey")]
        total = len({m["_fkey"] for m in uniq})
        for m in uniq:
            if should_stop and should_stop():
                break
            key = m["_fkey"]
            if key in done:
                continue
            done.add(key)
            if progress and len(done) % 5 == 0:
                progress(len(done), max(total, 1))
            src = self._find_file(m.get("_fname") or "", m.get("_fsize") or 0)
            if not src:
                missing += 1
                continue
            dt = datetime.fromtimestamp(m["ts"])
            if layout == "flat":
                dest_dir = file_root
            else:
                dest_dir = file_root / f"{dt:%Y}" / f"{dt:%m}" / f"{dt:%d}"
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / src.name
            n = 1
            while dest.exists():
                dest = dest_dir / f"{src.stem}_{n}{src.suffix}"
                n += 1
            try:
                shutil.copy2(src, dest)
            except OSError:
                missing += 1
                continue
            try:
                mapping[m["_fkey"]] = dest.relative_to(base_dir).as_posix()
            except ValueError:
                mapping[m["_fkey"]] = dest.as_posix()
            count += 1
        return {"count": count, "missing": missing, "dir": str(file_root),
                "layout": layout, "files": mapping,
                "cancelled": bool(should_stop and should_stop())}

    # ---------------- 图片 ----------------
    def _media_of(self, username: str) -> MediaStore:
        if username not in self._media:
            self._media[username] = MediaStore(self.account, username)
        return self._media[username]

    def image(self, username: str, md5: str) -> tuple[bytes, str] | None:
        IMG_CACHE.mkdir(parents=True, exist_ok=True)
        for ext in ("jpg", "png", "gif", "webp", "bmp"):
            p = IMG_CACHE / f"{md5}.{ext}"
            if p.exists():
                return p.read_bytes(), ext
        data = self._media_of(username).load(md5)
        if not data:
            return None
        from wxmanager.wx4 import image_kind
        ext = image_kind(data) or "jpg"
        (IMG_CACHE / f"{md5}.{ext}").write_bytes(data)
        return data, ext

    def image_path(self, username: str, md5: str) -> Path | None:
        """返回解密后图片的本地缓存路径（供桌面端直接加载）。"""
        got = self.image(username, md5)
        if not got:
            return None
        return IMG_CACHE / f"{md5}.{got[1]}"

    # ---------------- 导出 ----------------
    def export_images(self, username: str, out_root: Path, progress=None,
                      should_stop=None, start_ts: int = 0, end_ts: int = 0,
                      layout: str = "date") -> dict:
        msgs = self._parse_rows(
            self._fetch(username, 0, only_images=True, start_ts=start_ts, end_ts=end_ts),
            username)
        name = self.names.get(username, username)
        base_dir = Path(out_root) / _safe(name)
        img_root = base_dir / "图片"
        done: set[str] = set()
        files: dict[str, str] = {}
        count = 0
        missing = 0
        total = len({m.get("_md5") for m in msgs if m.get("_md5")})
        for _idx, m in enumerate(msgs):
            if should_stop and should_stop():
                break
            md5 = m.get("_md5")
            if not md5:
                continue
            if md5 in done:
                continue
            done.add(md5)
            if progress and len(done) % 10 == 0:
                progress(len(done), total)
            got = self.image(username, md5)
            if not got:
                missing += 1
                continue
            data, ext = got
            dt = datetime.fromtimestamp(m["ts"])
            if layout == "flat":
                day = img_root            # 平铺：全部图片放同一目录
                fn = f"{dt:%Y%m%d_%H%M%S}_{md5[:8]}.{ext}"
            else:
                day = img_root / f"{dt:%Y}" / f"{dt:%m}" / f"{dt:%d}"
                fn = f"{dt:%H%M%S}_{md5[:8]}.{ext}"
            day.mkdir(parents=True, exist_ok=True)
            target = day / fn
            if not target.exists():
                target.write_bytes(data)
            try:
                files[md5] = target.relative_to(Path(out_root) / _safe(name)).as_posix()
            except ValueError:
                files[md5] = target.as_posix()
            count += 1
        return {"count": count, "missing": missing, "dir": str(img_root),
                "name": name, "layout": layout, "files": files,
                "cancelled": bool(should_stop and should_stop())}

    def export_all(self, out_root: Path, include_images: bool = True,
                   progress=None, should_stop=None, limit_sessions: int = 0,
                   start_ts: int = 0, end_ts: int = 0, layout: str = "date",
                   include_files: bool = False) -> dict:
        """导出全部会话（记录 + 可选图片），并打包成一个 zip。"""
        import time
        import zipfile

        out_root = Path(out_root)
        out_root.mkdir(parents=True, exist_ok=True)
        stamp0 = time.strftime("%Y%m%d_%H%M")
        work = out_root / f"微信全部导出_{stamp0}"
        work.mkdir(parents=True, exist_ok=True)
        # 只导出时间范围内有消息的会话
        if start_ts or end_ts:
            sessions = [s for s in self.sessions
                        if not end_ts or self._counts(s["id"])[2] <= end_ts]
            sessions = [s for s in sessions
                        if not start_ts or self._counts(s["id"])[3] >= start_ts]
        else:
            sessions = self.sessions
        sessions = sessions[:limit_sessions] if limit_sessions else sessions
        total = len(sessions)
        done = 0
        images = 0
        files = 0
        skipped = 0
        for i, s in enumerate(sessions, 1):
            if should_stop and should_stop():
                break
            try:
                img_map, file_map = {}, {}
                if include_images:
                    r = self.export_images(s["id"], work, start_ts=start_ts,
                                           end_ts=end_ts, layout=layout)
                    images += r.get("count", 0)
                    img_map = r.get("files") or {}
                if include_files:
                    fr = self.export_files(s["id"], work, start_ts=start_ts,
                                           end_ts=end_ts, layout=layout)
                    files += fr.get("count", 0)
                    file_map = fr.get("files") or {}
                self.export_chat(s["id"], work, start_ts=start_ts, end_ts=end_ts,
                                 images_map=img_map, files_map=file_map)
                done += 1
            except Exception:  # noqa: BLE001
                skipped += 1
            if progress:
                progress(i, total, s["name"])

        # 打包（文本压缩、图片只存储，速度快）
        zip_path = out_root / f"{work.name}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
            for f in work.rglob("*"):
                if not f.is_file():
                    continue
                rel = f.relative_to(work)
                ctype = (zipfile.ZIP_STORED
                         if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
                         else zipfile.ZIP_DEFLATED)
                zf.write(f, str(rel), compress_type=ctype)
        size = zip_path.stat().st_size
        return {"sessions": done, "skipped": skipped, "images": images, "files": files,
                "dir": str(work), "zip": str(zip_path), "size": size,
                "cancelled": bool(should_stop and should_stop())}

    def export_chat(self, username: str, out_root: Path, start_ts: int = 0,
                    end_ts: int = 0, images_map: dict | None = None,
                    files_map: dict | None = None) -> dict:
        msgs = self._parse_rows(
            self._fetch(username, 0, start_ts=start_ts, end_ts=end_ts), username)
        name = self.names.get(username, username)
        base_dir = Path(out_root) / _safe(name)
        base_dir.mkdir(parents=True, exist_ok=True)

        lines = [f"与 {name} 的聊天记录",
                 f"导出时间: {datetime.now():%Y-%m-%d %H:%M:%S}",
                 f"共 {len(msgs)} 条消息", "=" * 60]
        last_day = ""
        for m in msgs:
            day = m["t"][:10]
            if day != last_day:
                lines.append(f"\n===== {day} =====")
                last_day = day
            lines.append(f"[{m['t'][11:]}] {m['who']}: {m['text']}")

        (base_dir / "聊天记录.txt").write_text("\n".join(lines), encoding="utf-8")
        (base_dir / "聊天记录.html").write_text(
            self._chat_html(name, msgs, images_map or {}, files_map or {}), encoding="utf-8")

        records = [{k: v for k, v in m.items() if not k.startswith("_")} for m in msgs]
        n_img = sum(1 for m in msgs if m.get("_md5"))
        (base_dir / "messages.json").write_text(json.dumps({
            "name": name, "username": username,
            "is_group": username.endswith("@chatroom"),
            "count": len(records), "images": n_img,
            "first_ts": msgs[0]["ts"] if msgs else 0,
            "last_ts": msgs[-1]["ts"] if msgs else 0,
            "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "messages": records,
        }, ensure_ascii=False), encoding="utf-8")
        return {"dir": str(base_dir), "count": len(records), "images": n_img}

    # ---------------- HTML（带头像 / 图片 / 语音） ----------------
    def _avatar_uri(self, uid: str) -> str:
        """头像转 base64 data URI，内嵌进 HTML，避免外部依赖。"""
        if not uid:
            return ""
        cache = getattr(self, "_avatar_uri_cache", None)
        if cache is None:
            cache = self._avatar_uri_cache = {}
        if uid in cache:
            return cache[uid]
        raw = self._avatars.get(uid)
        if not raw:
            cache[uid] = ""
            return ""
        ext = "png" if raw[:8] == b"\x89PNG\r\n\x1a\n" else "jpg"
        cache[uid] = f"data:image/{ext};base64,{base64.b64encode(raw).decode()}"
        return cache[uid]

    def _chat_html(self, name: str, msgs: list[dict], images_map: dict,
                   files_map: dict | None = None) -> str:
        files_map = files_map or {}
        speakers = {m.get("who") for m in msgs} - {"我", "系统", name, ""}
        is_group = bool(speakers)

        # 头像只内嵌一次：uid -> CSS 类
        ava_css: dict[str, str] = {}
        ava_class: dict[str, str] = {}
        for m in msgs:
            uid = m.get("_uid") or (self.self_wxid if m.get("me") else "")
            if not uid or uid in ava_class:
                continue
            uri = self._avatar_uri(uid)
            if uri:
                cls = f"av{len(ava_class)}"
                ava_css[cls] = f'.{cls}{{background-image:url("{uri}")}}'
                ava_class[uid] = cls

        palette = ["#409EFF", "#67C23A", "#E6A23C", "#F56C6C", "#909399",
                   "#5B8FF9", "#61C0BF", "#7262FD", "#F6903D", "#008685"]

        rows: list[str] = []
        last_day = ""
        for m in msgs:
            day = (m.get("t") or "")[:10]
            if day != last_day:
                rows.append(f'<div class="day">{day}</div>')
                last_day = day
            if m.get("type") == "system":
                rows.append(f'<div class="sys"><span>'
                            f'{html_mod.escape(m.get("text") or "")}</span></div>')
                continue

            me = bool(m.get("me"))
            who = m.get("who") or ""
            uid = m.get("_uid") or (self.self_wxid if me else "")
            cls = ava_class.get(uid)
            if cls:
                avatar = f'<div class="ava {cls}"></div>'
            else:
                h = sum(ord(c) for c in (who or "?")) % len(palette)
                avatar = (f'<div class="ava" style="background:{palette[h]}">'
                          f'{html_mod.escape((who or "?")[:1])}</div>')

            md5 = m.get("_md5") or ""
            if m.get("type") == "image" and md5:
                rel = images_map.get(md5)
                inner = (f'<div class="bubble img"><img src="{html_mod.escape(rel)}" '
                         f'alt="图片" loading="lazy"></div>' if rel
                         else '<div class="bubble">[图片未随记录导出]</div>')
            elif m.get("type") == "file":
                fname = m.get("_fname") or "文件"
                size = m.get("_fsize") or 0
                human = human_size(size)
                rel = files_map.get(m.get("_fkey") or "")
                if rel:
                    inner = (f'<a class="bubble file" href="{html_mod.escape(rel)}" '
                             f'target="_blank"><span class="ico">📄</span><span class="fmeta">'
                             f'<b>{html_mod.escape(fname)}</b><i>{human}</i></span></a>')
                else:
                    inner = ('<div class="bubble file"><span class="ico">📄</span>'
                             f'<span class="fmeta"><b>{html_mod.escape(fname)}</b>'
                             f'<i>{human}（未随记录导出）</i></span></div>')
            elif m.get("type") == "voice":
                dur = m.get("dur") or 0
                inner = ('<div class="bubble voice" '
                         'title="微信电脑端播放过的语音才会缓存到本地">'
                         f'<span>🔊 语音 {dur}″</span></div>')
            else:
                inner = f'<div class="bubble">{html_mod.escape(m.get("text") or "")}</div>'

            sender = (f'<div class="who">{html_mod.escape(who)}</div>'
                      if is_group and not me else "")
            rows.append(f'<div class="row {"me" if me else ""}">{avatar}'
                        f'<div class="col">{sender}{inner}</div></div>')

        classes = "\n".join(ava_css.values())
        return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>与 {html_mod.escape(name)} 的聊天记录</title>
<style>
body{{margin:0;background:#F5F7FA;font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;color:#303133}}
.wrap{{max-width:840px;margin:0 auto;padding:18px 16px 40px}}
h1{{font-size:16px;font-weight:600;text-align:center;margin:8px 0 4px}}
.sub{{text-align:center;color:#909399;font-size:12px;margin-bottom:14px}}
.day{{text-align:center;color:#909399;font-size:12px;margin:18px 0 8px}}
.row{{display:flex;gap:10px;margin:12px 0;align-items:flex-start}}
.row.me{{flex-direction:row-reverse}}
.ava{{width:34px;height:34px;border-radius:9px;flex:none;color:#fff;font-size:14px;
  background-size:cover;background-position:center;display:flex;align-items:center;justify-content:center}}
.col{{max-width:62%;min-width:0}}
.row.me .col{{text-align:right}}
.who{{font-size:11px;color:#909399;margin:0 2px 3px}}
.bubble{{display:inline-block;text-align:left;background:#fff;border:1px solid #EBEEF5;
  padding:9px 12px;border-radius:12px;white-space:pre-wrap;word-break:break-word;font-size:14px}}
.row.me .bubble{{background:#409EFF;border-color:#409EFF;color:#fff}}
.bubble.img{{padding:0;border:none;background:transparent}}
.bubble.img img{{display:block;max-width:240px;max-height:300px;border-radius:10px;cursor:zoom-in;
  background:#fff;border:1px solid #EBEEF5}}
.bubble.file{{display:inline-flex;align-items:center;gap:10px;max-width:320px;text-decoration:none;
  color:#303133}}
.row.me .bubble.file{{color:#fff}}
.bubble.file .ico{{font-size:22px;line-height:1}}
.bubble.file .fmeta{{display:flex;flex-direction:column;gap:2px;min-width:0}}
.bubble.file b{{font-weight:500;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.bubble.file i{{font-style:normal;font-size:11px;color:#909399}}
.row.me .bubble.file i{{color:#E6F2FF}}
.bubble.voice{{min-width:92px;color:#409EFF}}
.row.me .bubble.voice{{color:#fff}}
.sys{{text-align:center;margin:10px 0}}
.sys span{{background:#F4F4F5;color:#909399;font-size:11px;padding:3px 10px;border-radius:10px}}
.stat{{text-align:center;color:#C0C4CC;font-size:12px;margin-top:22px}}
{classes}
</style></head><body><div class="wrap">
<h1>与 {html_mod.escape(name)} 的聊天记录</h1>
<div class="sub">共 {len(msgs)} 条消息 · 导出时间 {datetime.now():%Y-%m-%d %H:%M}</div>
{"".join(rows)}
<div class="stat">由「闰土微信记录导出器」导出 · 仅本地查看</div>
</div></body></html>"""
