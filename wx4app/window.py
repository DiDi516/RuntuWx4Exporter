"""wx4app 主窗口（PySide6 · Element 风格）。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from wx4view.live import LiveSource

from . import config
from .assets import APP_NAME, APP_VERSION, logo_icon, logo_pixmap
from .dialogs import notify
from .export_dialog import ExportDialog
from .frameless import RoundedMainWindow, TitleBar
from .logging_setup import get_logger, setup_logging
from .settings_dialog import SettingsDialog
from .setup import SetupDialog
from .theme import QSS, add_shadow
from .widgets import ChatView, ConvDelegate, ImagesView, Lightbox

log = get_logger("window")

TYPES = [("all", "全部类型"), ("text", "文本"), ("image", "图片"), ("file", "文件"),
         ("link", "链接"), ("voice", "语音"), ("sticker", "表情"), ("video", "视频"),
         ("system", "系统消息")]


# ---------------------------------------------------------------- 线程
class WorkerSignals(QObject):
    """普通线程 -> 主线程的信号桥（避免 QThread 里跑 sqlite 的稳定性问题）。"""

    ready = Signal(object)
    done = Signal(object)
    failed = Signal(object)
    progress = Signal(int, int)
    progress_text = Signal(int, int, str)
    finished = Signal()


class InitWorker(threading.Thread):
    def __init__(self, account: str | None):
        super().__init__(daemon=True)
        self.account = account
        self.signals = WorkerSignals()

    def run(self):
        try:
            self.signals.ready.emit(LiveSource(self.account))
        except Exception as exc:  # noqa: BLE001
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}")


class MessagesWorker(threading.Thread):
    def __init__(self, source, cid: str, limit: int = 150, before=None):
        super().__init__(daemon=True)
        self.source = source
        self.cid = cid
        self.limit = limit
        self.before = before
        self.signals = WorkerSignals()

    def run(self):
        try:
            data = self.source.messages(self.cid, limit=self.limit, before=self.before)
            self.signals.done.emit({"cid": self.cid, "data": data})
        except Exception as exc:  # noqa: BLE001
            self.signals.failed.emit(
                {"cid": self.cid, "error": f"{type(exc).__name__}: {exc}"})
        finally:
            self.signals.finished.emit()


class ExportJob(QObject):
    """独立进程导出：子进程干活，父进程轮询进度文件，UI 永不卡死、也不会被拖崩。"""

    done = Signal(object)
    failed = Signal(str)
    progress_text = Signal(int, int, str)

    def __init__(self, spec: dict):
        super().__init__()
        self.spec = spec
        self.proc: subprocess.Popen | None = None
        self._spec_path: str | None = None
        self._prog_path: str | None = None
        self._pos = 0
        self._buf = ""
        self._cancelled = False
        self._result: dict | None = None
        self._error: str | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._poll)

    def start(self):
        fd, spec_path = tempfile.mkstemp(prefix="wx4job_", suffix=".json")
        os.close(fd)
        fd, prog_path = tempfile.mkstemp(prefix="wx4job_", suffix=".log")
        os.close(fd)
        self._spec_path, self._prog_path = spec_path, prog_path
        payload = dict(self.spec, progress_path=prog_path)
        Path(spec_path).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--export-job", spec_path]
        else:
            cmd = [sys.executable, "-m", "wx4app.job_runner", spec_path]
        flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, creationflags=flags)
        self._timer.start()

    def _drain(self):
        if not self._prog_path:
            return
        try:
            with open(self._prog_path, encoding="utf-8") as fh:
                fh.seek(self._pos)
                chunk = fh.read()
                self._pos = fh.tell()
        except OSError:
            return
        if not chunk:
            return
        self._buf += chunk
        *lines, self._buf = self._buf.split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if "p" in msg:
                self.progress_text.emit(int(msg.get("p") or 0),
                                        int(msg.get("t") or 0),
                                        str(msg.get("label") or ""))
            elif msg.get("ok") is True:
                self._result = msg.get("result") or {}
            elif msg.get("ok") is False:
                self._error = str(msg.get("error") or "导出失败")

    def _poll(self):
        self._drain()
        if self.proc is None or self.proc.poll() is None:
            return
        self._drain()
        self._timer.stop()
        code = self.proc.returncode
        if self._cancelled:
            self.done.emit({"cancelled": True})
        elif self._error:
            self.failed.emit(self._error)
        elif self._result is None:
            self.failed.emit(f"导出进程异常退出（退出码 {code}）")
        else:
            self.done.emit(self._result)
        self._cleanup()

    def _cleanup(self):
        for path in (self._spec_path, self._prog_path):
            if path:
                try:
                    os.remove(path)
                except OSError:
                    pass
        self._spec_path = self._prog_path = None

    def stop(self):
        self._cancelled = True
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except OSError:
                pass


# ---------------------------------------------------------------- 兜底数据源
class FilesSource:
    mode = "files"

    def __init__(self, root: Path):
        self.root = Path(root)
        self.account = None
        self.sessions: list[dict] = []
        for d in sorted(self.root.iterdir() if self.root.exists() else []):
            f = d / "messages.json"
            if not f.is_file():
                continue
            try:
                meta = json.loads(f.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            msgs = meta.get("messages", [])
            last = msgs[-1] if msgs else {}
            self.sessions.append({
                "id": d.name, "name": meta.get("name") or d.name,
                "is_group": bool(meta.get("is_group")),
                "count": meta.get("count", len(msgs)),
                "images": sum(1 for m in msgs if m.get("img") or m.get("src")),
                "last_ts": meta.get("last_ts", 0),
                "preview": (last.get("text") or "")[:40],
            })
        self.sessions.sort(key=lambda s: -(s["last_ts"] or 0))

    def messages(self, username: str, limit: int = 300, before: int | None = None) -> dict:
        meta = json.loads((self.root / username / "messages.json").read_text(encoding="utf-8"))
        msgs = meta.get("messages", [])
        end = len(msgs)
        if before:
            while end > 0 and msgs[end - 1].get("ts", 0) > before:
                end -= 1
        start = max(0, end - limit)
        return {**meta, "messages": msgs[start:end], "has_more": start > 0,
                "next_before": msgs[start]["ts"] if start < len(msgs) else 0,
                "images": sum(1 for m in msgs if m.get("img") or m.get("src"))}

    def images(self, username: str) -> list[dict]:
        meta = json.loads((self.root / username / "messages.json").read_text(encoding="utf-8"))
        return [m for m in meta.get("messages", []) if m.get("img") or m.get("src")]

    def image_path(self, username: str, key: str) -> Path | None:
        p = self.root / username / key
        return p if p.exists() else None

    def avatar_path(self, username: str):
        return None

    def export_images(self, username, out_root):
        raise RuntimeError("当前是「已导出目录」模式，请用 wx4export 批量导出")

    def export_chat(self, username, out_root):
        raise RuntimeError("当前是「已导出目录」模式，请用 wx4export 批量导出")

    def export_all(self, out_root, include_images=True, progress=None, should_stop=None):
        raise RuntimeError("当前是「已导出目录」模式，请用 wx4export 批量导出")


def image_path_of(source, username: str, msg: dict) -> Path | None:
    src = msg.get("src") or ""
    if isinstance(source, LiveSource):
        return source.image_path(username, src.rsplit("/", 1)[-1]) if src else None
    return source.image_path(username, msg.get("img") or "")


# ---------------------------------------------------------------- 会话条目
# ---------------------------------------------------------------- 主窗口
class MainWindow(RoundedMainWindow):
    def __init__(self, account: str | None = None, files_only: bool = False,
                 export_root: str | None = None):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1280, 840)
        self.setMinimumSize(1000, 660)
        self.setStyleSheet(QSS)

        cfg = config.load()
        self.export_root = Path(export_root or cfg.get("export_dir")
                                or config.default_export_dir())
        self.export_root.mkdir(parents=True, exist_ok=True)
        config.save(export_dir=str(self.export_root))

        self.source = None
        self.sessions: list[dict] = []
        self.current: dict | None = None
        self.msgs: list[dict] = []
        self.has_more = False
        self.next_before = 0
        self.filter_kind = "all"
        self.type_filter = "all"
        self.tab = "chat"
        self.is_group = False
        self._avatar_cache: dict[str, Path | None] = {}
        self._conv_index: dict[str, dict] = {}

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(180)
        self._search_timer.timeout.connect(self.refresh_list)

        self._msg_timer = QTimer(self)
        self._msg_timer.setSingleShot(True)
        self._msg_timer.setInterval(260)
        self._msg_timer.timeout.connect(self._apply_msg_filter)
        self._cancel_fn = None
        self._msg_workers: list[threading.Thread] = []
        self._load_gen = 0
        self.setWindowIcon(logo_icon())

        self._build_ui()
        QApplication.instance().aboutToQuit.connect(self._shutdown)
        QTimer.singleShot(0, lambda: self._startup(account, files_only))

    def _shutdown(self):
        """退出前收尾：停掉图片解码计时器，等待后台线程结束，避免 Qt 崩溃。"""
        try:
            self.chat._img_timer.stop()
        except (AttributeError, RuntimeError):
            pass
        for attr in ("_export_job", "_export_all_job"):
            job = getattr(self, attr, None)
            if job is not None:
                job.stop()
        workers = list(getattr(self, "_msg_workers", []))
        for attr in ("_init_worker",):
            w = getattr(self, attr, None)
            if w is not None:
                workers.append(w)
        for w in workers:
            if w.is_alive():
                w.join(5.0)

    # ---------------- UI ----------------
    def _build_ui(self):
        outer = self.card_layout

        # 顶栏（作为可拖动标题栏的标题区）
        bar = QFrame()
        bar.setObjectName("AppBar")
        bar.setMinimumHeight(54)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 0, 16, 0)
        bl.setSpacing(10)
        logo = QLabel()
        logo.setObjectName("AppLogo")
        logo.setFixedSize(32, 32)
        logo.setAlignment(Qt.AlignCenter)
        pix = logo_pixmap(30)
        if not pix.isNull():
            logo.setPixmap(pix)
        else:
            logo.setText("微")
        bl.addWidget(logo)
        tb = QVBoxLayout()
        tb.setSpacing(0)
        t1 = QLabel(APP_NAME)
        t1.setObjectName("AppTitle")
        ver = QLabel(f"v{APP_VERSION}")
        ver.setObjectName("AppVersion")
        ver.setAlignment(Qt.AlignCenter)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        title_row.addWidget(t1)
        title_row.addWidget(ver)
        title_row.addStretch(1)
        self.sub_label = QLabel("正在初始化…")
        self.sub_label.setObjectName("AppSub")
        tb.addLayout(title_row)
        tb.addWidget(self.sub_label)
        bl.addLayout(tb)
        bl.addStretch(1)

        self.btn_dir = QPushButton("连接微信数据")
        self.btn_dir.setObjectName("Plain")
        self.btn_dir.setCursor(Qt.PointingHandCursor)
        self.btn_dir.setMinimumHeight(32)
        self.btn_dir.clicked.connect(lambda: self._ask_setup(first=False))
        bl.addWidget(self.btn_dir)

        self.btn_settings = QPushButton("设置")
        self.btn_settings.setObjectName("Plain")
        self.btn_settings.setCursor(Qt.PointingHandCursor)
        self.btn_settings.setMinimumHeight(32)
        self.btn_settings.clicked.connect(self._open_settings)
        bl.addWidget(self.btn_settings)

        self.btn_all = QPushButton("一键导出全部")
        self.btn_all.setObjectName("Primary")
        self.btn_all.setCursor(Qt.PointingHandCursor)
        self.btn_all.setMinimumHeight(32)
        self.btn_all.setEnabled(False)
        self.btn_all.clicked.connect(self._export_all)
        bl.addWidget(self.btn_all)

        self.titlebar = TitleBar(self, bar, show_max=True)
        outer.addWidget(self.titlebar)
        self.attach_size_grip()

        # 内容区
        content = QWidget()
        cl = QHBoxLayout(content)
        cl.setContentsMargins(12, 12, 12, 12)
        cl.setSpacing(12)
        outer.addWidget(content, 1)

        # 左卡片
        left = QFrame()
        left.setObjectName("Card")
        left.setFixedWidth(304)
        add_shadow(left)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(10, 12, 10, 10)
        ll.setSpacing(8)

        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索会话")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumHeight(32)
        self.search.textChanged.connect(lambda: self._search_timer.start())
        ll.addWidget(self.search)

        chips = QHBoxLayout()
        chips.setSpacing(6)
        chips.addWidget(self._chip("全部", "all", True))
        chips.addWidget(self._chip("群聊", "group"))
        chips.addWidget(self._chip("单聊", "single"))
        chips.addStretch(1)
        ll.addLayout(chips)

        self.conv_list = QListWidget()
        self.conv_list.setObjectName("ConvList")
        self.conv_list.setFrameShape(QFrame.NoFrame)
        self.conv_list.setSpacing(0)
        self.conv_list.setMouseTracking(True)
        self.conv_list.setUniformItemSizes(True)
        self.conv_list.setItemDelegate(ConvDelegate(self.conv_list))
        self.conv_list.currentRowChanged.connect(self._safe_conv_changed)
        ll.addWidget(self.conv_list, 1)

        self.list_foot = QLabel("连接中…")
        self.list_foot.setObjectName("CardFoot")
        self.list_foot.setFixedHeight(24)
        self.list_foot.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        ll.addWidget(self.list_foot)
        cl.addWidget(left)

        # 右卡片
        right = QFrame()
        right.setObjectName("Card")
        add_shadow(right)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)

        head = QWidget()
        head.setObjectName("CardHead")
        hl = QVBoxLayout(head)
        hl.setContentsMargins(16, 12, 16, 10)
        hl.setSpacing(8)
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        self.title = QLabel("请选择左侧会话")
        self.title.setObjectName("ConvTitle")
        self.tag = QLabel("")
        self.tag.setStyleSheet(
            "background:#ECF5FF;color:#409EFF;border:1px solid #B3D8FF;"
            "border-radius:9px;padding:2px 9px;font-size:11px;")
        self.tag.hide()
        self.meta = QLabel("")
        self.meta.setObjectName("ConvMeta")
        row1.addWidget(self.title)
        row1.addWidget(self.tag)
        row1.addSpacing(4)
        row1.addWidget(self.meta)
        row1.addStretch(1)
        hl.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self.type_combo = QComboBox()
        for key, label in TYPES:
            self.type_combo.addItem(label, key)
        self.type_combo.setMinimumHeight(30)
        self.type_combo.setEnabled(False)
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        row2.addWidget(self.type_combo)

        self.msg_filter = QLineEdit()
        self.msg_filter.setPlaceholderText("在会话内搜索")
        self.msg_filter.setFixedWidth(160)
        self.msg_filter.setMinimumHeight(30)
        self.msg_filter.setEnabled(False)
        self.msg_filter.textChanged.connect(lambda: self._msg_timer.start())
        row2.addWidget(self.msg_filter)
        row2.addStretch(1)

        self.btn_export_img = QPushButton("导出图片")
        self.btn_export_chat = QPushButton("导出记录")
        for b in (self.btn_export_img, self.btn_export_chat):
            b.setObjectName("Plain")
            b.setCursor(Qt.PointingHandCursor)
            b.setEnabled(False)
            b.setMinimumHeight(30)
        self.btn_export_img.clicked.connect(lambda: self._export("images"))
        self.btn_export_chat.clicked.connect(lambda: self._export("chat"))
        row2.addWidget(self.btn_export_img)
        row2.addWidget(self.btn_export_chat)

        self.tab_chat = self._chip("聊天", "chat", True)
        self.tab_images = self._chip("图片", "images")
        self.tab_chat.clicked.connect(lambda: self._set_tab("chat"))
        self.tab_images.clicked.connect(lambda: self._set_tab("images"))
        row2.addWidget(self.tab_chat)
        row2.addWidget(self.tab_images)
        hl.addLayout(row2)
        rl.addWidget(head)

        self.chat = ChatView()
        self.images = ImagesView()
        self.images.open_image.connect(self._open_lightbox)
        self.chat.load_more.connect(self._load_more)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.chat)
        self.stack.addWidget(self.images)
        rl.addWidget(self.stack, 1)

        self.overlay = QLabel("正在加载会话…", self.stack)
        self.overlay.setAlignment(Qt.AlignCenter)
        self.overlay.setStyleSheet(
            "background:rgba(250,251,252,0.82);color:#606266;font-size:13px;")
        self.overlay.hide()

        # 导出进度条（默认隐藏，导出时显示）
        self.prog_area = QWidget()
        self.prog_area.setObjectName("ProgArea")
        pl = QHBoxLayout(self.prog_area)
        pl.setContentsMargins(16, 8, 16, 10)
        pl.setSpacing(10)
        self.prog_label = QLabel("准备导出…")
        self.prog_label.setObjectName("ConvMeta")
        self.prog_bar = QProgressBar()
        self.prog_bar.setMinimumWidth(280)
        self.prog_bar.setMinimumHeight(14)
        self.prog_bar.setTextVisible(True)
        self.prog_bar.setFormat("%v / %m")
        self.prog_cancel = QPushButton("取消")
        self.prog_cancel.setObjectName("Plain")
        self.prog_cancel.setCursor(Qt.PointingHandCursor)
        self.prog_cancel.setMinimumHeight(26)
        self.prog_cancel.clicked.connect(self._cancel_export)
        pl.addWidget(self.prog_label)
        pl.addWidget(self.prog_bar, 1)
        pl.addWidget(self.prog_cancel)
        self.prog_area.hide()
        rl.addWidget(self.prog_area)
        cl.addWidget(right, 1)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if hasattr(self, "overlay") and self.overlay.isVisible():
            self.overlay.setGeometry(0, 0, self.stack.width(), self.stack.height())

    def _chip(self, text: str, key: str, checked: bool = False) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("Chip")
        b.setCheckable(True)
        b.setChecked(checked)
        b.setCursor(Qt.PointingHandCursor)
        b.setMinimumHeight(28)
        if key in ("all", "group", "single"):
            b.clicked.connect(lambda _=False, k=key: self._set_filter(k))
        return b

    # ---------------- 设置 ----------------
    def _open_settings(self):
        dlg = SettingsDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        cfg = config.load()
        setup_logging(cfg)
        self.export_root = Path(cfg["export_dir"])
        self.export_root.mkdir(parents=True, exist_ok=True)
        self.list_foot.setText(
            f"共 {len(self.sessions)} 个会话 · 工作空间 {self.export_root}")
        notify(self, "设置已保存",
               f"配置文件：{config.config_file()}\n工作空间：{cfg['workspace']}\n"
               f"日志目录：{cfg['log_dir']}（保留 {cfg['log_retention']} 天）",
               str(config.config_file().parent), "⚙️")

    # ---------------- 启动 / 数据源 ----------------
    def _startup(self, account: str | None, files_only: bool):
        if files_only:
            self._apply_source(FilesSource(self.export_root))
            return
        cfg = config.load()
        acc = account or cfg.get("account_dir")
        if acc and config.normalize_account(acc):
            self._load_live(acc)
        else:
            self._ask_setup(first=True)

    def _ask_setup(self, first: bool = False):
        cfg = config.load()
        dlg = SetupDialog(self, initial=cfg.get("account_dir", ""), allow_cancel=not first)
        if dlg.exec() != QDialog.Accepted:
            if first:
                if any(self.export_root.glob("*/messages.json")):
                    self._apply_source(FilesSource(self.export_root))
                else:
                    self.close()
            return
        if dlg.mode == "files":
            self._apply_source(FilesSource(self.export_root))
            return
        if dlg.remember and dlg.account_dir:
            config.save(account_dir=dlg.account_dir)
            log.info("切换微信目录：%s", dlg.account_dir)
        self._load_live(dlg.account_dir)

    def _load_live(self, account: str | None, allow_auto_retry: bool = True):
        dlg = QProgressDialog("正在连接微信数据库…\n首次需要从内存取密钥，约 10~40 秒",
                              None, 0, 0, self)
        dlg.setWindowTitle("请稍候")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setCancelButton(None)
        dlg.setMinimumWidth(380)
        dlg.show()

        self._init_worker = InitWorker(account)

        def ok(src):
            dlg.close()
            config.save(account_dir=str(src.account))
            self._apply_source(src)

        def bad(msg):
            dlg.close()
            # 指定账号打不开时，自动改为“按密钥匹配度选账号”再试一次
            if allow_auto_retry and account:
                self._load_live(None, allow_auto_retry=False)
                return
            if any(self.export_root.glob("*/messages.json")):
                QMessageBox.warning(self, "实时模式不可用",
                                    f"{msg}\n\n将改为浏览已导出的目录。")
                self._apply_source(FilesSource(self.export_root))
            else:
                QMessageBox.critical(self, "无法读取微信数据", msg)

        self._init_worker.signals.ready.connect(ok, Qt.QueuedConnection)
        self._init_worker.signals.failed.connect(bad, Qt.QueuedConnection)
        self._init_worker.start()

    def _apply_source(self, source):
        self.source = source
        self.sessions = source.sessions
        live = isinstance(source, LiveSource)
        mode = "实时微信库" if live else "已导出目录"
        account = getattr(source, "account", None)
        name = account.name if account else self.export_root.name
        self.sub_label.setText(f"{mode} · {name}")
        log.info("连接数据源：模式=%s 账号=%s 会话=%d", mode, name, len(self.sessions))
        self.setWindowTitle(f"{APP_NAME} — {mode}（{len(self.sessions)} 个会话）")
        self.list_foot.setText(
            f"共 {len(self.sessions)} 个会话 · 头像 {len(getattr(source, '_avatars', {}))} 个")
        self.btn_all.setEnabled(live)
        self._conv_index = {c["id"]: c for c in self.sessions}
        self._populate_items()
        self.refresh_list()
        if self.sessions:
            self.conv_list.setCurrentRow(0)

    # ---------------- 列表 ----------------
    def _populate_items(self):
        """列表只建一次（277 条），之后筛选只切可见性，避免反复创建控件。"""
        self.conv_list.blockSignals(True)
        self.conv_list.setUpdatesEnabled(False)
        self.conv_list.clear()
        for conv in self.sessions:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, conv["id"])
            item.setData(ConvDelegate.NAME, conv["name"])
            item.setData(ConvDelegate.PREVIEW, conv.get("preview") or "")
            item.setData(ConvDelegate.TIME, conv.get("last_ts") or 0)
            item.setData(ConvDelegate.GROUP, bool(conv["is_group"]))
            item.setData(ConvDelegate.AVA, self._avatar(conv["id"]))
            self.conv_list.addItem(item)
        self.conv_list.setUpdatesEnabled(True)
        self.conv_list.update()
        self.conv_list.blockSignals(False)

    def refresh_list(self):
        kw = self.search.text().strip().lower()
        self.conv_list.blockSignals(True)
        first_visible = -1
        for i in range(self.conv_list.count()):
            item = self.conv_list.item(i)
            conv = self._conv_index.get(item.data(Qt.UserRole)) or {}
            visible = True
            if self.filter_kind == "group" and not conv.get("is_group"):
                visible = False
            elif self.filter_kind == "single" and conv.get("is_group"):
                visible = False
            elif kw:
                name = (conv.get("name") or "").lower()
                preview = (conv.get("preview") or "").lower()
                visible = kw in name or kw in preview
            item.setHidden(not visible)
            if visible and first_visible < 0:
                first_visible = i
        # 恢复当前选中；若当前被过滤掉，则选第一个可见项
        target_row = -1
        if self.current:
            for i in range(self.conv_list.count()):
                item = self.conv_list.item(i)
                if item.data(Qt.UserRole) == self.current["id"] and not item.isHidden():
                    target_row = i
                    break
        if target_row < 0:
            target_row = first_visible
        self.conv_list.blockSignals(False)
        if target_row >= 0:
            self.conv_list.setCurrentRow(target_row)

    def _avatar(self, username: str):
        if not self.source or not hasattr(self.source, "avatar_path"):
            return None
        if username not in self._avatar_cache:
            try:
                self._avatar_cache[username] = self.source.avatar_path(username)
            except Exception:  # noqa: BLE001
                self._avatar_cache[username] = None
        return self._avatar_cache[username]

    def _set_filter(self, kind: str):
        self.filter_kind = kind
        for b in self.findChildren(QPushButton):
            if b.objectName() == "Chip" and b.text() in ("全部", "群聊", "单聊"):
                b.setChecked({"全部": "all", "群聊": "group", "单聊": "single"}[b.text()] == kind)
        self.refresh_list()

    def _on_type_changed(self, _idx: int):
        self.type_filter = self.type_combo.currentData() or "all"
        if self.current:
            self._render_chat(keep_bottom=False)

    def _set_tab(self, key: str):
        self.tab = key
        self.tab_chat.setChecked(key == "chat")
        self.tab_images.setChecked(key == "images")
        self.stack.setCurrentIndex(0 if key == "chat" else 1)
        if key == "images":
            self.chat.pause_images()      # 让出解码资源给图片墙
            if self.current:
                self._reset_images()
        else:
            self.chat.resume_images()

    # ---------------- 会话 ----------------
    def _safe_conv_changed(self, row: int):
        """Qt 槽里抛异常在部分版本会导致进程直接退出，这里兜住并记录。"""
        try:
            self._on_conv_changed(row)
        except Exception:  # noqa: BLE001
            import traceback
            traceback.print_exc()

    def _on_conv_changed(self, row: int):
        if row < 0 or not self.source:
            return
        item = self.conv_list.item(row)
        if item is None or item.isHidden():
            return
        if item.data(Qt.UserRole) is None:
            return
        cid = item.data(Qt.UserRole)
        conv = self._conv_index.get(cid)
        if not conv:
            return
        self.current = conv
        self._load_gen += 1
        gen = self._load_gen
        if cid in getattr(self.source, "_msg_cache", {}):
            try:
                self._apply_messages(conv, self.source.messages(cid, limit=150))
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "读取失败", str(exc))
            return
        # 快速切换时限制并发线程数量，避免线程/连接堆积
        self._msg_workers = [w for w in self._msg_workers if w.is_alive()]
        running_same = any(getattr(w, "cid", None) == cid for w in self._msg_workers)
        if running_same or len(self._msg_workers) >= 3:
            try:
                self._apply_messages(conv, self.source.messages(cid, limit=150))
            except Exception as exc:  # noqa: BLE001
                self._hide_loading()
                QMessageBox.critical(self, "读取失败", str(exc))
            return

        # 首次打开：后台解析，避免几万条消息把界面卡住
        self._show_loading(f"正在加载「{conv['name']}」…")
        w = MessagesWorker(self.source, cid, limit=150)
        # 用列表持有线程：如果直接覆盖引用，上一个还在跑的 QThread 会被销毁导致崩溃
        self._msg_workers.append(w)
        w.signals.done.connect(
            lambda payload, g=gen: self._on_messages_ready(
                payload.get("cid", ""), payload.get("data") or {}, g),
            Qt.QueuedConnection)
        w.signals.failed.connect(
            lambda payload, g=gen: self._on_messages_failed(
                payload.get("cid", ""), payload.get("error", ""), g),
            Qt.QueuedConnection)
        w.signals.finished.connect(
            lambda: self._msg_workers.remove(w) if w in self._msg_workers else None,
            Qt.QueuedConnection)
        w.start()

    def _show_loading(self, text: str):
        self.overlay.setText(text)
        self.overlay.setGeometry(0, 0, self.stack.width(), self.stack.height())
        self.overlay.raise_()
        self.overlay.show()

    def _hide_loading(self):
        self.overlay.hide()

    def _on_messages_ready(self, cid: str, data: dict, gen: int = -1):
        if gen != self._load_gen or not self.current or self.current["id"] != cid:
            return
        self._hide_loading()
        self._apply_messages(self.current, data)

    def _on_messages_failed(self, cid: str, msg: str, gen: int = -1):
        if gen != self._load_gen or not self.current or self.current["id"] != cid:
            return
        self._hide_loading()
        QMessageBox.critical(self, "读取失败", msg)

    def _apply_messages(self, conv: dict, data: dict):
        self.msgs = data.get("messages", [])
        log.debug("打开会话：%s（%d 条）", data.get("name") or conv.get("name"), len(self.msgs))
        self.has_more = bool(data.get("has_more"))
        self.next_before = data.get("next_before") or 0
        self.is_group = bool(data.get("is_group"))
        self.title.setText(data.get("name") or conv["name"])
        self.tag.setText("群聊" if self.is_group else "单聊")
        self.tag.show()
        rng = ""
        if data.get("first_ts") and data.get("last_ts"):
            start_s = datetime.fromtimestamp(data["first_ts"]).strftime("%Y-%m-%d")
            end_s = datetime.fromtimestamp(data["last_ts"]).strftime("%Y-%m-%d")
            rng = f"{start_s} 至 {end_s} · "
        self.meta.setText(f"{rng}{data.get('count', 0)} 条消息 · "
                          f"{data.get('images', 0)} 张图片 · {data.get('files', 0)} 个文件")
        self.msg_filter.setEnabled(True)
        self.type_combo.setEnabled(True)
        self.btn_export_chat.setEnabled(True)
        self.btn_export_img.setEnabled(bool(data.get("images")))
        self.msg_filter.clear()
        self.type_combo.blockSignals(True)
        self.type_combo.setCurrentIndex(0)
        self.type_combo.blockSignals(False)
        self.type_filter = "all"
        self._render_chat(keep_bottom=True)
        if self.tab == "images":
            self._reset_images()

    def _render_chat(self, keep_bottom=True):
        if not self.current:      # 快速切换时可能已被清空
            return
        kw = self.msg_filter.text().strip().lower()
        msgs = self.msgs
        if self.type_filter != "all":
            msgs = [m for m in msgs if m.get("type") == self.type_filter]
        if kw:
            msgs = [m for m in msgs
                    if kw in (m.get("text") or "").lower() or kw in (m.get("who") or "").lower()]
        self.chat.set_has_more(self.has_more and not kw and self.type_filter == "all")
        self.chat.render(msgs, self.is_group,
                         lambda m: image_path_of(self.source, self.current["id"], m),
                         self._open_lightbox_for_msg,
                         avatar_for=self._avatar, keep_bottom=keep_bottom)

    def _apply_msg_filter(self):
        if self.current:
            self._render_chat(keep_bottom=False)

    def _load_more(self):
        if not self.has_more or not self.current:
            return
        from PySide6.QtWidgets import QApplication
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            data = self.source.messages(self.current["id"], limit=300, before=self.next_before)
        finally:
            QApplication.restoreOverrideCursor()
        older = data.get("messages", [])
        if not older:
            self.has_more = False
            self.chat.set_has_more(False)
            return
        self.msgs = older + self.msgs
        self.has_more = bool(data.get("has_more"))
        self.next_before = data.get("next_before") or 0
        self._render_chat(keep_bottom=False)

    # ---------------- 图片 ----------------
    def _reset_images(self):
        if not self.current:
            return
        cid = self.current["id"]
        self.images.reset(
            lambda before=None: self.source.images_page(cid, before),
            lambda m: image_path_of(self.source, cid, m))

    def _open_lightbox_for_msg(self, msg: dict):
        imgs = self.images.items or [msg]
        idx = next((i for i, m in enumerate(imgs) if m.get("src") == msg.get("src")), 0)
        Lightbox(imgs, idx,
                 lambda m: image_path_of(self.source, self.current["id"], m), self).exec()

    def _open_lightbox(self, index: int):
        if not self.current:
            return
        imgs = self.images.items
        if not imgs:
            return
        Lightbox(imgs, index,
                 lambda m: image_path_of(self.source, self.current["id"], m), self).exec()

    # ---------------- 导出 ----------------
    def _choose_dir(self) -> bool:
        d = QFileDialog.getExistingDirectory(self, "选择导出目录", str(self.export_root))
        if not d:
            return False
        self.export_root = Path(d)
        config.save(export_dir=str(self.export_root))
        log.info("导出目录设为：%s", self.export_root)
        return True

    def _show_progress(self, text: str):
        self.prog_label.setText(text)
        self.prog_bar.setRange(0, 0)
        self.prog_bar.setFormat("准备中…")
        self.prog_cancel.setEnabled(True)
        self.prog_area.show()

    def _update_progress(self, done: int, total: int, text: str = ""):
        if total <= 0:
            return
        self.prog_bar.setRange(0, total)
        self.prog_bar.setValue(min(done, total))
        self.prog_bar.setFormat("%v / %m")
        if text:
            self.prog_label.setText(text)

    def _hide_progress(self):
        self.prog_area.hide()
        self._cancel_fn = None

    def _cancel_export(self):
        self._stop_flag = True
        if self._cancel_fn:
            try:
                self._cancel_fn()
            except Exception:  # noqa: BLE001
                pass
        self.prog_label.setText("正在取消…")
        self.prog_cancel.setEnabled(False)

    def _notify_done(self, text: str, folder: str):
        """导出完成提示（圆角风格，与应用一致），可直接打开目录。"""
        notify(self, "导出完成", text, folder, "✅")

    def _export(self, what: str):
        if not self.current:
            return
        cfg = config.load()
        dlg = ExportDialog(
            title=f"导出「{self.current['name']}」",
            subtitle="可指定时间范围、导出内容（记录 / 图片 / 文件），以及目录结构",
            allow_content=True,
            preselect_images=(what == "images"),
            preselect_chat=(what == "chat"),
            default_layout=cfg.get("export_layout", "date"))
        if dlg.exec() != QDialog.Accepted:
            return
        opt = dlg.options()
        config.save(export_layout=opt["layout"])
        if not self._choose_dir():
            return

        cid = self.current["id"]
        name = self.current["name"]
        btn = self.btn_export_img if what == "images" else self.btn_export_chat
        btn_text = btn.text()
        btn.setEnabled(False)
        btn.setText("导出中…")
        self._stop_flag = False
        self._cancel_fn = None
        self._show_progress(f"正在导出「{name}」…")

        do_img, do_chat, do_file = opt["do_images"], opt["do_chat"], opt["do_files"]
        log.info("开始导出：会话=%s 记录=%s 图片=%s 文件=%s 目录=%s 拆分HTML=%s",
                 name, do_chat, do_img, do_file, self.export_root,
                 opt.get("html_split", True))
        st, et, layout = opt["start_ts"], opt["end_ts"], opt["layout"]

        spec = {
            "kind": "chat",
            "account": str(self.source.account),
            "cid": cid,
            "out_root": str(self.export_root),
            "start_ts": st, "end_ts": et, "layout": layout,
            "do_images": do_img, "do_files": do_file, "do_chat": do_chat,
            "html_split": opt.get("html_split", True),
        }
        w = ExportJob(spec)
        self._export_job = w
        self._cancel_fn = w.stop
        if do_img or do_file:
            w.progress_text.connect(
                lambda i, t, label: self._update_progress(
                    i, t, f"正在导出{label or '内容'}：{i}/{t}"),
                Qt.QueuedConnection)

        def done(res: dict):
            self._hide_progress()
            btn.setEnabled(True)
            btn.setText(btn_text)
            if res.get("cancelled"):
                notify(self, "已取消", f"已导出 {res.get('images', 0)} 张图片",
                       res.get("dir", ""), "⏹️")
                return
            parts = []
            if do_chat:
                parts.append(f"{res.get('count', 0)} 条消息")
            if do_img:
                parts.append(f"{res.get('images', 0)} 张图片"
                             + (f"（{res.get('missing', 0)} 张缺失）" if res.get("missing") else ""))
            if do_file:
                parts.append(f"{res.get('files', 0)} 个文件"
                             + (f"（{res.get('missing_files', 0)} 个本地缺失）"
                                if res.get("missing_files") else ""))
            rng = ""
            if st and et:
                rng = f"\n时间范围：{datetime.fromtimestamp(st):%Y-%m-%d} ~ {datetime.fromtimestamp(et):%Y-%m-%d}"
            log.info("导出完成：会话=%s 结果=%s 目录=%s", name, res, res.get("dir", ""))
            self._notify_done("、".join(parts) + rng + f"\n{res.get('dir', '')}",
                              res.get("dir", str(self.export_root)))

        def failed(msg: str):
            log.error("导出失败：会话=%s 错误=%s", name, msg)
            self._hide_progress()
            btn.setEnabled(True)
            btn.setText(btn_text)
            notify(self, "导出失败", msg, "", "⚠️")

        w.done.connect(done, Qt.QueuedConnection)
        w.failed.connect(failed, Qt.QueuedConnection)
        w.start()

    def _export_all(self):
        if not isinstance(self.source, LiveSource):
            QMessageBox.information(self, "提示", "「一键导出全部」仅支持实时微信库模式。")
            return
        cfg = config.load()
        dlg = ExportDialog(
            title="导出全部会话",
            subtitle=f"共 {len(self.sessions)} 个会话；可按时间范围筛选，并选择是否包含图片",
            allow_content=False,
            preselect_images=True,
            default_layout=cfg.get("export_layout", "date"))
        if dlg.exec() != QDialog.Accepted:
            return
        opt = dlg.options()
        config.save(export_layout=opt["layout"])
        if not self._choose_dir():
            return

        self._stop_flag = False
        log.info("开始导出全部：会话数=%d 含图片=%s 含文件=%s 目录=%s",
                 len(self.sessions), opt["do_images"], opt["do_files"], self.export_root)
        self._show_progress("正在导出全部会话…")
        spec = {
            "kind": "all",
            "account": str(self.source.account),
            "out_root": str(self.export_root),
            "start_ts": opt["start_ts"], "end_ts": opt["end_ts"],
            "layout": opt["layout"],
            "do_images": opt["do_images"], "do_files": opt["do_files"],
            "html_split": opt.get("html_split", True),
        }
        worker = ExportJob(spec)
        self._export_all_job = worker
        self._cancel_fn = worker.stop
        worker.progress_text.connect(
            lambda i, t, n: self._update_progress(i, t, f"正在导出（{i}/{t}）：{n}"),
            Qt.QueuedConnection)

        def on_done(res: dict):
            self._hide_progress()
            if res.get("cancelled"):
                notify(self, "已取消", f"已导出部分会话：{res.get('sessions', 0)} 个",
                       res.get("dir", ""), "⏹️")
                return
            log.info("导出全部完成：%s", res)
            size_mb = res.get("size", 0) / 1024 / 1024
            self._notify_done(
                f"会话：{res.get('sessions', 0)} 个\n图片：{res.get('images', 0)} 张\n"
                f"文件：{res.get('files', 0)} 个\n"
                f"打包文件：{res.get('zip', '')}\n大小：{size_mb:.1f} MB",
                res.get("dir") or str(self.export_root))

        def on_failed(msg: str):
            log.error("导出全部失败：%s", msg)
            self._hide_progress()
            notify(self, "导出失败", msg, "", "⚠️")

        worker.done.connect(on_done, Qt.QueuedConnection)
        worker.failed.connect(on_failed, Qt.QueuedConnection)
        worker.start()
