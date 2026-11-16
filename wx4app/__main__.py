"""wx4app 入口：微信风格桌面客户端。"""
from __future__ import annotations

import argparse
import sys


def _default_export_dir() -> str:
    from . import config
    return config.default_export_dir()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="wx4app", description="微信聊天记录桌面版（PySide6）")
    ap.add_argument("--account", help="微信账号目录（默认自动探测）")
    ap.add_argument("--files-only", action="store_true", help="只浏览已导出的目录")
    ap.add_argument("--export-dir", default=None, help="导出目录（默认自动选择）")
    a = ap.parse_args(argv)

    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from .assets import APP_NAME, logo_icon
    from .window import MainWindow

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setWindowIcon(logo_icon())
    app.setFont(QFont("Microsoft YaHei", 10))
    from .theme import QSS
    app.setStyleSheet(QSS)
    export_dir = a.export_dir or _default_export_dir()
    win = MainWindow(account=a.account, files_only=a.files_only, export_root=export_dir)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
