"""应用元信息与图标资源（兼容 PyInstaller 单文件解包路径）。"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap

APP_NAME = "闰土微信记录导出器"
APP_VERSION = "1.1.0"
APP_NAME_EN = "RuntuWeChatExporter"


def resource_path(rel: str) -> Path:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "wx4app" / rel
    return Path(__file__).resolve().parent / rel


def logo_path() -> Path:
    return resource_path("assets/logo.png")


def icns_path() -> Path:
    return resource_path("assets/logo.ico")


def logo_pixmap(size: int = 30) -> QPixmap:
    pix = QPixmap(str(logo_path()))
    if pix.isNull():
        return QPixmap()
    return pix.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def logo_icon() -> QIcon:
    p = logo_path()
    return QIcon(str(p)) if p.exists() else QIcon()
