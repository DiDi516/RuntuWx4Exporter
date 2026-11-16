"""微信 4.x（xwechat_files）图片提取。

微信 4.0 起图片缓存改为 ".dat V2 容器"，结构：

    偏移 0   6 字节   签名 07 08 56 32 08 07
    偏移 6   4 字节   aes_size  (u32 LE)  —— AES 段原文长度
    偏移 10  4 字节   xor_size  (u32 LE)  —— 尾部 XOR 段长度
    偏移 14  1 字节   占位
    偏移 15  N 字节   AES-128-ECB 密文，N = (aes_size // 16 + 1) * 16（PKCS#7）
    之后      M 字节   明文段（不加密）
    末尾      xor_size 尾部单字节 XOR 段

密钥：
- AES key = MD5(str(UIN) + wxid)[:16] 的 ASCII 字节（UIN 可从
  %APPDATA%/Tencent/xwechat/*/kvcomm/*.statistic 文件名中拿到）
- XOR key 通常是账号级常量（本例为 0x35），也可用尾段 FF D9 反推

解出的载荷可能是 jpg/png/gif，也可能是 wxgf（微信自有封装，内部为 HEVC），
后者需要 PyAV 解码首帧转成 jpg。更早的文件仍是单字节 XOR 的老格式，一并兼容。
"""
from __future__ import annotations

import hashlib
import io
import os
import re
import struct
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

V2_SIG = b"\x07\x08V2\x08\x07"

_IMG_MAGICS = [
    (b"\xff\xd8\xff", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
]

_THUMB_RE = re.compile(r"_t$|_t_W$|_t_NW$")
_BASE_RE = re.compile(r"^([0-9a-f]{32})(.*)$")
_ACCOUNT_SUFFIX_RE = re.compile(r"^(.*?)_([0-9a-f]{4})$")


# ------------------------------------------------------------------ 密钥
def wxid_from_account_dir(account_dir: str | Path) -> str:
    """从账号目录名还原 wxid，如 wxid_abc123_d04f -> wxid_abc123。"""
    name = Path(account_dir).name
    m = _ACCOUNT_SUFFIX_RE.match(name)
    return m.group(1) if m else name


def aes_key_for(uin: str | int, wxid: str) -> bytes:
    """AES-128 密钥：MD5(十进制 UIN + wxid) 的前 16 位十六进制字符的 ASCII 字节。"""
    return hashlib.md5(f"{uin}{wxid}".encode()).hexdigest()[:16].encode()


def discover_uins() -> list[str]:
    """扫描 kvcomm 统计文件名，收集候选 UIN（10 位数字）。"""
    roots = []
    for env in ("APPDATA", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            roots.append(Path(base) / "Tencent" / "xwechat")
    uins: dict[str, int] = {}
    for root in roots:
        if not root.exists():
            continue
        for f in root.rglob("kvcomm/*.statistic"):
            for m in re.finditer(r"(?<!\d)(\d{8,11})(?!\d)", f.name):
                uins[m.group(1)] = uins.get(m.group(1), 0) + 1
    return [u for u, _ in sorted(uins.items(), key=lambda kv: -kv[1])]


# ------------------------------------------------------------------ 解密
def parse_v2(data: bytes) -> tuple[int, int, int] | None:
    """返回 (aes_size, xor_size, aes_aligned_bytes)。"""
    if not data.startswith(V2_SIG) or len(data) < 15:
        return None
    aes_size, xor_size = struct.unpack("<II", data[6:14])
    if aes_size == 0 or aes_size > 64 * 1024 * 1024:
        return None
    aligned = (aes_size // 16 + 1) * 16
    if 15 + aligned > len(data):
        return None
    return aes_size, xor_size, aligned


def v2_decrypt(data: bytes, aes_key: bytes, xor_key: int) -> bytes | None:
    parsed = parse_v2(data)
    if not parsed:
        return None
    aes_size, xor_size, aligned = parsed
    from Crypto.Cipher import AES  # 延迟导入，未安装时不影响其他功能
    try:
        plain = AES.new(aes_key, AES.MODE_ECB).decrypt(data[15:15 + aligned])
    except ValueError:
        return None
    pad = plain[-1] if plain else 0
    if not 1 <= pad <= 16:
        return None
    plain = plain[:-pad]
    rest = data[15 + aligned:]
    if xor_size > len(rest):
        return None
    raw = rest[:len(rest) - xor_size] if xor_size else rest
    tail = rest[len(rest) - xor_size:] if xor_size else b""
    return plain + raw + bytes(b ^ xor_key for b in tail)


def sniff_xor(data: bytes) -> int | None:
    """老格式 / 未加密文件：用文件头反推单字节 XOR 密钥。"""
    head = data[:16]
    for k in range(256):
        h = bytes(b ^ k for b in head)
        for magic, _ in _IMG_MAGICS:
            if h.startswith(magic):
                return k
        if h.startswith(b"wxgf"):
            return k
    return None


def image_kind(payload: bytes) -> str:
    for magic, ext in _IMG_MAGICS:
        if payload.startswith(magic):
            return ext
    if payload.startswith(b"wxgf"):
        return "wxgf"
    return ""


def tail_ok(payload: bytes, kind: str) -> bool:
    """结构完整性校验，避免『首块对、整图坏』的假成功。"""
    if kind == "jpg":
        return payload.rstrip(b"\x00").endswith(b"\xff\xd9") or payload.endswith(b"\xff\xd9")
    if kind == "png":
        return b"IEND" in payload[-16:]
    if kind == "gif":
        return payload.endswith(b";")
    return True


def pil_verify(payload: bytes) -> bool:
    """用 Pillow 完整解码一次做最终校验。

    微信会在部分大图尾部追加 trace 之类数据，因此不能用「尾部必须 FFD9/IEND」
    这种严格判断；能完整 decode 出合理尺寸才算通过。
    未安装 Pillow 时退化为通过（仅魔数层面）。
    """
    try:
        from PIL import Image
    except ImportError:
        return True
    try:
        Image.MAX_IMAGE_PIXELS = None
        with Image.open(io.BytesIO(payload)) as im:
            im.load()
            w, h = im.size
        return w >= 16 and h >= 16
    except Exception:
        return False


# ------------------------------------------------------------------ wxgf -> 图像
def wxgf_to_jpeg(payload: bytes, quality: int = 92) -> bytes | None:
    """wxgf 内部是 HEVC 码流，取首帧转 JPEG（需 PyAV）。"""
    start = payload.find(b"\x00\x00\x00\x01")
    if start < 0:
        start = payload.find(b"\x00\x00\x01")
    if start < 0:
        return None
    stream = payload[start:]
    try:
        import av
        with av.open(io.BytesIO(stream), format="hevc") as container:
            frame = next(container.decode(video=0))
            img = frame.to_image()
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=quality)
            return buf.getvalue()
    except Exception:
        return None


# ------------------------------------------------------------------ 提取主流程
@dataclass
class ExtractReport:
    scanned: int = 0
    picked: int = 0
    exported: int = 0
    duplicated: int = 0
    wxgf_converted: int = 0
    failed: int = 0
    bytes_out: int = 0
    formats: dict[str, int] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    months: dict[str, int] = field(default_factory=dict)

    def add_format(self, ext: str) -> None:
        self.formats[ext] = self.formats.get(ext, 0) + 1


def _iter_month_dirs(attach_dir: Path) -> Iterable[Path]:
    for session in sorted(attach_dir.iterdir()):
        if not session.is_dir():
            continue
        for month in sorted(session.iterdir()):
            if month.is_dir():
                yield month


def _pick_variants(month_dir: Path, include_thumbs: bool) -> dict[str, Path]:
    """同一张图有 原图/_h/_W/_t 等多个副本，挑体积最大的非缩略图。"""
    best: dict[str, Path] = {}
    best_size: dict[str, int] = {}
    for f in month_dir.rglob("*.dat"):
        m = _BASE_RE.match(f.stem)
        base, suffix = (m.group(1), m.group(2)) if m else (f.stem, "")
        if not include_thumbs and (_THUMB_RE.search(suffix) or "_t" in suffix):
            continue
        try:
            size = f.stat().st_size
        except OSError:
            continue
        if base not in best or size > best_size[base]:
            best[base] = f
            best_size[base] = size
    return best


def extract_images(
    account_dir: str | Path,
    out_dir: str | Path,
    aes_key: bytes | None = None,
    xor_key: int = 0x35,
    include_thumbs: bool = False,
    month_filter: tuple[str, ...] = (),
    limit: int = 0,
    progress: Callable[[str], None] | None = None,
    wxgf_quality: int = 92,
) -> ExtractReport:
    """遍历账号目录下 msg/attach/<会话>/<YYYY-MM>/，导出所有唯一图片。"""
    account = Path(account_dir)
    attach = account / "msg" / "attach"
    if not attach.exists():
        raise SystemExit(f"未找到 {attach}，请确认微信 4.x 账号目录路径")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rep = ExtractReport()
    seen: set[str] = set()
    done_bases: set[str] = set()

    for month_dir in _iter_month_dirs(attach):
        month = month_dir.name
        if month_filter and month not in month_filter:
            continue
        variants = _pick_variants(month_dir, include_thumbs)
        rep.scanned += len(variants)
        out_month = out / month
        for base, path in variants.items():
            if base in done_bases:
                continue
            done_bases.add(base)
            rep.picked += 1
            try:
                data = path.read_bytes()
            except OSError:
                rep.failed += 1
                continue

            payload: bytes | None = None
            if data.startswith(V2_SIG):
                if aes_key is None:
                    rep.failed += 1
                    if len(rep.failures) < 30:
                        rep.failures.append(f"{path.name}: 缺少 AES 密钥")
                    continue
                payload = v2_decrypt(data, aes_key, xor_key)
            else:
                k = sniff_xor(data)
                if k is not None:
                    payload = bytes(b ^ k for b in data)
            if not payload:
                rep.failed += 1
                if len(rep.failures) < 30:
                    rep.failures.append(f"{path.name}: 解密失败/未知格式")
                continue

            kind = image_kind(payload)
            if kind == "wxgf":
                jpg = wxgf_to_jpeg(payload, wxgf_quality)
                if jpg:
                    rep.wxgf_converted += 1
                    payload, kind = jpg, "jpg"
                else:
                    rep.failed += 1
                    if len(rep.failures) < 30:
                        rep.failures.append(f"{path.name}: wxgf/HEVC 解码失败")
                    continue
            elif not kind:
                rep.failed += 1
                if len(rep.failures) < 30:
                    rep.failures.append(f"{path.name}: 载荷不是已知图片格式")
                continue
            elif not pil_verify(payload):
                rep.failed += 1
                if len(rep.failures) < 30:
                    rep.failures.append(f"{path.name}: 图片无法完整解码（可能已损坏）")
                continue

            md5 = hashlib.md5(payload).hexdigest()
            if md5 in seen:
                rep.duplicated += 1
                continue
            seen.add(md5)

            out_month.mkdir(parents=True, exist_ok=True)
            target = out_month / f"{base}.{kind}"
            n = 1
            while target.exists() and hashlib.md5(target.read_bytes()).hexdigest() != md5:
                target = out_month / f"{base}_{n}.{kind}"
                n += 1
            if not target.exists():
                target.write_bytes(payload)
            rep.exported += 1
            rep.bytes_out += len(payload)
            rep.add_format(kind)
            rep.months[month] = rep.months.get(month, 0) + 1

            if progress and rep.exported % 500 == 0:
                progress(f"已导出 {rep.exported:,} 张，当前 {month} …")
            if limit and rep.exported >= limit:
                return rep
    return rep

def autodetect_aes_key(account_dir: str | Path, sample: int = 6) -> tuple[bytes | None, str | None]:
    """从 kvcomm 候选 UIN 中试出可用 AES 密钥，返回 (key, uin)。"""
    wxid = wxid_from_account_dir(account_dir)
    attach = Path(account_dir) / "msg" / "attach"
    samples: list[bytes] = []
    for month_dir in _iter_month_dirs(attach):
        for f in month_dir.rglob("*.dat"):
            try:
                d = f.read_bytes()
            except OSError:
                continue
            if d.startswith(V2_SIG):
                samples.append(d)
            if len(samples) >= sample:
                break
        if len(samples) >= sample:
            break
    if not samples:
        return None, None
    for uin in discover_uins():
        key = aes_key_for(uin, wxid)
        ok = 0
        for d in samples:
            payload = v2_decrypt(d, key, 0x35)
            if payload and image_kind(payload):
                ok += 1
        if ok >= max(1, len(samples) // 2):
            return key, uin
    return None, None
