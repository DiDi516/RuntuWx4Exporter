"""微信 4.x WCDB 数据库密钥提取 + SQLCipher4 逐页解密。

密钥在内存中的形态（4.1+）：
    字符串常量 "com.Tencent.WCDB.Config.Cipher"
      └─ 其 std::string 对象 {ptr,size,cap} 被引用处 -0x10 为节点基址
          └─ node + 0x28 = 配置对象指针
              └─ config + 0x88 起是一个 {ptr,len}
                  └─ blob 与固定 32 字节掩码循环异或后 = x'<64hex enc_key><32hex salt>'

拿到 enc_key 后用 SQLCipher4 页格式验证：页 4096，尾部 reserve 80 = IV(16)+HMAC(64)，
页 1 前 16 字节是 salt，解密后前面补 "SQLite format 3\\x00"。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import hashlib
import re
import sqlite3
import struct
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from Crypto.Cipher import AES

NEEDLE = b"com.Tencent.WCDB.Config.Cipher"
CONFIG_XOR_MASK = bytes.fromhex(
    "d2c7442458020000004889442450488b450048844c2448488944254048584c24")

PAGE_SZ, RESERVE_SZ, IV_SZ, HMAC_SZ, SALT_SZ, KEY_SZ = 4096, 80, 16, 64, 16, 32
HEX_RE = re.compile(rb"x'([0-9a-fA-F]{64,192})'")

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = wt.HANDLE
k32.VirtualQueryEx.restype = ctypes.c_size_t


class MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_uint64), ("AllocationBase", ctypes.c_uint64),
                ("AllocationProtect", wt.DWORD), ("_pad", wt.DWORD),
                ("RegionSize", ctypes.c_uint64), ("State", wt.DWORD),
                ("Protect", wt.DWORD), ("Type", wt.DWORD)]


MEM_COMMIT = 0x1000
PROT_GUARD = 0x100
READABLE = {0x02, 0x04, 0x20, 0x40, 0x80, 0x08}


# ------------------------------------------------------------------ 进程
def find_weixin_pids() -> list[tuple[int, int]]:
    """返回 [(pid, 内存占用)]，按占用降序；优先主进程。"""
    import subprocess
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Weixin.exe", "/FO", "CSV"],
                         capture_output=True, text=True, encoding="gbk", errors="ignore").stdout
    pids = []
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) >= 5 and parts[0].lower() == "weixin.exe":
            try:
                mem = int(re.sub(r"[^\d]", "", parts[4]) or 0)
                pids.append((int(parts[1]), mem))
            except ValueError:
                continue
    return sorted(pids, key=lambda x: -x[1])


def _read(h, addr: int, size: int) -> bytes:
    if not addr or size <= 0 or size > 64 * 1024 * 1024:
        return b""
    buf = ctypes.create_string_buffer(size)
    n = ctypes.c_size_t(0)
    if not k32.ReadProcessMemory(h, ctypes.c_uint64(addr), buf, size, ctypes.byref(n)):
        return b""
    return buf.raw[:n.value]


def _regions(h) -> Iterator[tuple[int, int]]:
    addr, mbi = 0, MBI()
    while addr < 0x7FFFFFFFFFFF:
        if not k32.VirtualQueryEx(h, ctypes.c_uint64(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            return
        base, size, prot = mbi.BaseAddress, mbi.RegionSize, mbi.Protect
        if (mbi.State == MEM_COMMIT and size <= 256 * 1024 * 1024
                and not prot & PROT_GUARD and (prot & 0xFF) in READABLE):
            yield base, size
        addr = base + size


def _scan_bytes(h, needle: bytes, overlap: int | None = None) -> Iterator[int]:
    """在可读内存中搜索字节串，返回绝对地址。

    注意：必须按「实际读取长度」推进偏移，ReadProcessMemory 可能短读，
    否则后续地址会整体错位（这是最容易踩的坑）。
    """
    if overlap is None:
        overlap = len(needle) - 1
    for base, size in _regions(h):
        off, tail = 0, b""
        while off < size:
            data = _read(h, base + off, min(4 * 1024 * 1024, size - off))
            if not data:
                off += 0x1000
                continue
            buf = tail + data
            buf_base = base + off - len(tail)
            i = buf.find(needle)
            while i >= 0:
                yield buf_base + i
                i = buf.find(needle, i + 1)
            tail = buf[-max(overlap, 1):]
            off += len(data)


# ------------------------------------------------------------------ 提取
@dataclass
class KeyCandidate:
    enc_key: bytes
    salt: bytes | None

    @property
    def hex(self) -> str:
        return self.enc_key.hex()


def _decode_blob(blob: bytes) -> bytes:
    mask = CONFIG_XOR_MASK
    return bytes(b ^ mask[i % len(mask)] for i, b in enumerate(blob))


def _probable_key(k: bytes) -> bool:
    return len(k) == 32 and len(set(k)) >= 15 and any(k)


def extract_candidates(pid: int, progress=None) -> list[KeyCandidate]:
    """主路径：Cipher 字符串 -> std::string 节点 -> 配置对象 -> 掩码 blob。"""
    h = k32.OpenProcess(0x0010 | 0x0400, False, pid)
    if not h:
        return []
    try:
        needle_addrs = set(_scan_bytes(h, NEEDLE))
        if progress:
            progress(f"发现 Cipher 字符串 {len(needle_addrs)} 处")
        if not needle_addrs:
            return []
        out: dict[bytes, KeyCandidate] = {}
        for a in needle_addrs:
            pat = struct.pack("<Q", a) + struct.pack("<Q", len(NEEDLE))
            for hit in _scan_bytes(h, pat):
                node = _read(h, hit - 0x10, 0x50)
                if len(node) < 0x38:
                    continue
                if struct.unpack("<Q", node[0x18:0x20])[0] != len(NEEDLE):
                    continue
                cfg = struct.unpack("<Q", node[0x28:0x30])[0]
                if not (0x10000 <= cfg < 0x7FFFFFFFFFFF):
                    continue
                obj = _read(h, cfg + 0x88, 0x28)
                if len(obj) < 0x18:
                    continue
                dptr = struct.unpack("<Q", obj[0x8:0x10])[0]
                dlen = struct.unpack("<Q", obj[0x10:0x18])[0]
                if not (0 < dlen <= 4096) or not (0x10000 <= dptr < 0x7FFFFFFFFFFF):
                    continue
                blob = _read(h, dptr, int(dlen))
                if not blob:
                    continue
                for m in HEX_RE.finditer(_decode_blob(blob)):
                    hx = m.group(1).decode()
                    enc = bytes.fromhex(hx[:64])
                    if not _probable_key(enc) or enc in out:
                        continue
                    salt = bytes.fromhex(hx[64:96]) if len(hx) >= 96 else None
                    out[enc] = KeyCandidate(enc, salt)
        if progress:
            progress(f"配置对象解出候选密钥 {len(out)} 个")
        return list(out.values())
    finally:
        k32.CloseHandle(h)


# ------------------------------------------------------------------ 解密/校验
def page1_plaintext(db_bytes: bytes, enc_key: bytes) -> bytes | None:
    if len(db_bytes) < PAGE_SZ:
        return None
    page = db_bytes[:PAGE_SZ]
    iv = page[PAGE_SZ - RESERVE_SZ:PAGE_SZ - RESERVE_SZ + IV_SZ]
    ct = page[SALT_SZ:PAGE_SZ - RESERVE_SZ]
    if len(ct) % 16:
        return None
    try:
        body = AES.new(enc_key, AES.MODE_CBC, iv).decrypt(ct)
    except ValueError:
        return None
    return b"SQLite format 3\x00" + body


def mac_key_for(enc_key: bytes, salt: bytes) -> bytes:
    """SQLCipher4 的 HMAC 子密钥：PBKDF2-HMAC-SHA512(enc_key, salt^0x3a, 2 轮)。"""
    mac_salt = bytes(b ^ 0x3A for b in salt)
    return hashlib.pbkdf2_hmac("sha512", enc_key, mac_salt, 2, dklen=32)


def verify_key(db_path: Path, enc_key: bytes, head: bytes | None = None) -> bool:
    """用页 1 解密后的 SQLite 页头判定密钥是否正确（WCDB 的 HMAC 参数与
    标准 SQLCipher 略有差异，解密结果最可靠）。"""
    if head is None:
        try:
            with open(db_path, "rb") as f:
                head = f.read(PAGE_SZ)
        except OSError:
            return False
    if len(head) < PAGE_SZ:
        return False
    for reserve in (RESERVE_SZ, 48):
        iv = head[PAGE_SZ - reserve:PAGE_SZ - reserve + IV_SZ]
        ct = head[SALT_SZ:PAGE_SZ - reserve + IV_SZ]
        if len(ct) % 16:
            continue
        try:
            body = AES.new(enc_key, AES.MODE_CBC, iv).decrypt(ct)
        except ValueError:
            continue
        # 页头：page_size(2) + write_ver + read_ver
        if body[:2] == b"\x10\x00" and body[2] in (1, 2) and body[3] in (1, 2):
            return True
    return False


def decrypt_database(db_path: str | Path, enc_key: bytes, out_path: str | Path) -> bool:
    """逐页解密为明文 sqlite。

    每页 4096 = 明文内容(4016) + reserve(80)，页 1 的明文内容是
    header(16) + 解密得到的 4000 字节；输出时必须把 80 字节 reserve 补回，
    否则 SQLite 会认为页大小不符（database disk image is malformed）。
    """
    src, dst = Path(db_path), Path(out_path)
    data = src.read_bytes()
    if len(data) < PAGE_SZ or len(data) % PAGE_SZ:
        return False
    out = bytearray()
    for i in range(len(data) // PAGE_SZ):
        page = data[i * PAGE_SZ:(i + 1) * PAGE_SZ]
        iv = page[PAGE_SZ - RESERVE_SZ:PAGE_SZ - RESERVE_SZ + IV_SZ]
        ct = page[SALT_SZ:PAGE_SZ - RESERVE_SZ] if i == 0 else page[:PAGE_SZ - RESERVE_SZ]
        try:
            body = AES.new(enc_key, AES.MODE_CBC, iv).decrypt(ct)
        except ValueError:
            return False
        out += (b"SQLite format 3\x00" + body if i == 0 else body) + b"\x00" * RESERVE_SZ
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(bytes(out))
    return True


def extract_candidates_by_mask(pid: int, progress=None) -> list[KeyCandidate]:
    """不解析指针，直接在内存里搜「掩码编码后的 x' 前缀」，再整段解码取密钥。

    blob = XOR(明文, 32 字节掩码循环)。明文以 ``x'`` 开头，因此密文前缀只有
    32 种可能（取决于起始相位）。逐个相位搜索，命中后按相位解码并正则提取。
    """
    mask = CONFIG_XOR_MASK
    pat_map: dict[bytes, int] = {}
    for i in range(len(mask)):
        cipher = bytes([ord("x") ^ mask[i], ord("'") ^ mask[(i + 1) % len(mask)]])
        pat_map.setdefault(cipher, i)

    h = k32.OpenProcess(0x0010 | 0x0400, False, pid)
    if not h:
        return []
    found: dict[bytes, KeyCandidate] = {}
    scanned = 0
    try:
        for base, size in _regions(h):
            off, carry = 0, b""
            while off < size:
                data = _read(h, base + off, min(4 * 1024 * 1024, size - off))
                off += 4 * 1024 * 1024
                if not data:
                    break
                scanned += len(data)
                blob = carry + data
                for cipher, phase in pat_map.items():
                    s = 0
                    while True:
                        i = blob.find(cipher, s)
                        if i < 0:
                            break
                        s = i + 1
                        # 按相位解码 400 字节
                        seg = blob[i:i + 400]
                        plain = bytes(b ^ mask[(phase + j) % len(mask)] for j, b in enumerate(seg))
                        if not plain.startswith(b"x'"):
                            continue
                        for m in HEX_RE.finditer(plain):
                            hx = m.group(1).decode()
                            enc = bytes.fromhex(hx[:64])
                            if not _probable_key(enc) or enc in found:
                                continue
                            salt = bytes.fromhex(hx[64:96]) if len(hx) >= 96 else None
                            found[enc] = KeyCandidate(enc, salt)
                carry = blob[-512:]
    finally:
        k32.CloseHandle(h)
    if progress:
        progress(f"扫描 {scanned/1024/1024:.0f} MB，候选密钥 {len(found)} 个")
    return list(found.values())


def extract_all_candidates(progress=None) -> list[KeyCandidate]:
    """遍历所有 Weixin.exe 进程提取候选密钥（只扫一遍，供多账号匹配）。"""
    merged: dict[bytes, KeyCandidate] = {}
    for pid, mem in find_weixin_pids():
        if progress:
            progress(f"扫描进程 PID={pid}（{mem/1024:.0f} MB）")
        for c in extract_candidates(pid, progress):
            merged.setdefault(c.enc_key, c)
    return list(merged.values())


def match_keys(account_dir: str | Path, candidates: list[KeyCandidate],
               progress=None) -> dict[str, bytes]:
    """用候选密钥逐个尝试该账号下的库，返回 {相对路径(posix): enc_key}。"""
    db_storage = Path(account_dir) / "db_storage"
    result: dict[str, bytes] = {}
    for db in sorted(db_storage.rglob("*.db")):
        rel = db.relative_to(db_storage).as_posix()
        try:
            with open(db, "rb") as f:
                head = f.read(PAGE_SZ)
        except OSError:
            continue
        if len(head) < PAGE_SZ:
            continue
        salt = head[:SALT_SZ]
        ordered = sorted(candidates, key=lambda c: 0 if c.salt == salt else 1)
        for c in ordered:
            if c.salt and c.salt != salt:
                continue
            if verify_key(db, c.enc_key, head):
                result[rel] = c.enc_key
                if progress:
                    progress(f"  ✓ {rel}")
                break
    return result


def find_keys_for_account(account_dir: str | Path, progress=None) -> dict[str, bytes]:
    """扫描内存并把密钥匹配到该账号下的每个 db，返回 {相对路径: enc_key}。"""
    account = Path(account_dir)
    db_storage = account / "db_storage"
    dbs = sorted(db_storage.rglob("*.db"))
    if not dbs:
        raise SystemExit(f"未找到数据库: {db_storage}")
    result: dict[str, bytes] = {}
    for pid, mem in find_weixin_pids():
        if progress:
            progress(f"扫描进程 PID={pid}（{mem/1024/1024:.0f} MB）")
        cands = extract_candidates(pid, progress)
        if not cands:
            continue
        for db in dbs:
            rel = str(db.relative_to(db_storage))
            if rel in result:
                continue
            # 同 salt 候选优先，减少尝试次数
            head = db.read_bytes()[:SALT_SZ]
            ordered = sorted(cands, key=lambda c: 0 if c.salt == head else 1)
            for c in ordered:
                if c.salt and c.salt != head:
                    continue
                if verify_key(db, c.enc_key):
                    result[rel] = c.enc_key
                    if progress:
                        progress(f"  ✓ {rel}")
                    break
        if result:
            break
    return result


def open_plain(db_path: str | Path) -> sqlite3.Connection:
    p = Path(db_path).resolve().as_posix()
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn
