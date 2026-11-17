"""wx4app 入口：微信风格桌面客户端。"""
from __future__ import annotations

import argparse
import sys
import traceback
from datetime import datetime
from pathlib import Path

_LOG_HANDLE = None


def _enable_crash_log() -> None:
    """把段错误/未捕获异常写到 %LOCALAPPDATA%\\wx4app\\crash.log，便于定位崩溃。"""
    global _LOG_HANDLE
    try:
        import faulthandler

        from . import config

        base = Path(config.default_logs_dir())
        base.mkdir(parents=True, exist_ok=True)
        _LOG_HANDLE = open(base / "crash.log", "a", encoding="utf-8", buffering=1)
        _LOG_HANDLE.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} 启动 =====\n")
        faulthandler.enable(file=_LOG_HANDLE, all_threads=True)
    except Exception:  # noqa: BLE001
        pass

    def hook(exc_type, exc, tb):
        try:
            if _LOG_HANDLE:
                _LOG_HANDLE.write("".join(traceback.format_exception(exc_type, exc, tb)))
        except Exception:  # noqa: BLE001
            pass
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = hook


def _default_export_dir() -> str:
    from . import config
    return config.default_export_dir()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # 导出子进程模式：不加载 Qt，直接跑导出任务
    if len(argv) >= 2 and argv[0] == "--export-job":
        from .job_runner import main as run_job
        return run_job([argv[1]])

    _enable_crash_log()
    from . import config as _cfg
    from .logging_setup import get_logger, setup_logging

    _log_path = setup_logging(_cfg.load())
    _log = get_logger("app")
    _log.info("应用启动（日志：%s）", _log_path or "已关闭")

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
