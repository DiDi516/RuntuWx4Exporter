"""纯函数工具：安全目录名、可读大小、文件名归一化。

这个模块刻意不依赖任何第三方库或项目内其它模块，
方便单元测试，也可以被 CLI / 桌面端 / 服务端复用。
"""
from __future__ import annotations

import re

__all__ = ["safe_dirname", "human_size", "normalize_filename"]

_INVALID_CHARS = re.compile(r'[\\/:*?"<>|\s]+')
_MULTI_SPACE = re.compile(r"\s+")
_COPY_SUFFIX = re.compile(r"\s*\(\d+\)(?=\.[^.]+$|$)")


def safe_dirname(name: str, limit: int = 60) -> str:
    """把会话名转成安全的目录名（Windows 非法字符替换为下划线）。"""
    cleaned = _INVALID_CHARS.sub("_", (name or "").strip()).strip(" .")
    return (cleaned or "unnamed")[:limit]


def human_size(size: int | float) -> str:
    """人类可读的文件大小，例如 12 KB / 3.4 MB。"""
    try:
        size = int(size or 0)
    except (TypeError, ValueError):
        return ""
    if size <= 0:
        return ""
    if size >= 1024 * 1024 * 1024:
        return f"{size / 1024 / 1024 / 1024:.2f} GB"
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} MB"
    return f"{max(1, round(size / 1024))} KB"


def normalize_filename(name: str) -> str:
    """归一化文件名后用于匹配：去掉微信重名追加的 (1)/(2)，压缩空格并转小写。"""
    n = _COPY_SUFFIX.sub("", (name or "").strip())
    return _MULTI_SPACE.sub(" ", n).strip().lower()
