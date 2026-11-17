"""日志系统：按天滚动、保留 N 天，目录/级别可配置。"""
from __future__ import annotations

import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from . import config

LOGGER_NAME = "wx4app"
_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_LOGGER = logging.getLogger(LOGGER_NAME)
_active_file: Path | None = None


def get_logger(name: str | None = None) -> logging.Logger:
    return logging.getLogger(LOGGER_NAME if not name else f"{LOGGER_NAME}.{name}")


def log_file() -> Path | None:
    return _active_file


def setup_logging(cfg: dict | None = None) -> Path | None:
    """初始化日志，返回日志文件路径；关闭日志时返回 None。"""
    global _active_file
    cfg = cfg or config.load()

    for handler in list(_LOGGER.handlers):
        _LOGGER.removeHandler(handler)
        try:
            handler.close()
        except Exception:  # noqa: BLE001
            pass
    _LOGGER.propagate = False
    _active_file = None

    level = getattr(logging, str(cfg.get("log_level", "INFO")).upper(), logging.INFO)
    _LOGGER.setLevel(level)

    if not cfg.get("log_enabled", True):
        _LOGGER.addHandler(logging.NullHandler())
        return None

    log_dir = Path(cfg.get("log_dir") or config.default_logs_dir())
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        target = log_dir / "app.log"
        retention = max(1, int(cfg.get("log_retention") or 30))
        file_handler = TimedRotatingFileHandler(
            target, when="midnight", backupCount=retention, encoding="utf-8")
        file_handler.suffix = "%Y-%m-%d"
        file_handler.setFormatter(logging.Formatter(_FORMAT))
        _LOGGER.addHandler(file_handler)
        _active_file = target
    except OSError:
        _LOGGER.addHandler(logging.NullHandler())

    # 开发模式（有控制台）同时打到终端
    if not getattr(sys, "frozen", False) and sys.stderr is not None:
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(_FORMAT))
        _LOGGER.addHandler(console)

    return _active_file


def shutdown_logging() -> None:
    for handler in list(_LOGGER.handlers):
        _LOGGER.removeHandler(handler)
        try:
            handler.close()
        except Exception:  # noqa: BLE001
            pass
