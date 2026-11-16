"""启动前的「连接微信数据」页面：自动探测候选账号 + 手动选择路径。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import config
from .assets import APP_NAME, logo_icon
from .frameless import RoundedDialog
from .widgets import Avatar


class SetupDialog(RoundedDialog):
    """选择微信账号目录（启动前必须完成；也可改为浏览已导出目录）。"""

    def __init__(self, parent=None, initial: str = "", allow_cancel: bool = True):
        super().__init__(parent, title="连接微信数据",
                         subtitle="选择要读取的微信账号目录，选好后即可进入主界面",
                         min_width=600)
        self.setObjectName("Setup")
        self.setWindowTitle(f"连接微信数据 · {APP_NAME}")
        self.setWindowIcon(logo_icon())
        self.mode = "live"
        self.account_dir: str | None = None
        self.remember = True

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(240)
        self._timer.timeout.connect(self._validate)

        root = self.body

        self.section = QLabel("已自动检测到以下账号")
        self.section.setStyleSheet("color:#909399;font-size:12px;padding-top:4px;")
        root.addWidget(self.section)

        self.list = QListWidget()
        self.list.setObjectName("ConvList")
        self.list.setFixedHeight(96)
        self.list.setStyleSheet(
            "QListWidget{border:1px solid #EBEEF5;border-radius:10px;background:#FFFFFF;}"
            "QListWidget::item{border-radius:8px;margin:3px;}"
            "QListWidget::item:selected{background:#ECF5FF;}")
        self.list.currentRowChanged.connect(self._on_pick)
        root.addWidget(self.list)
        n = self._fill_candidates()
        self.list.setFixedHeight(min(max(n, 1), 3) * 70 + 8)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.path_edit = QLineEdit(initial)
        self.path_edit.setPlaceholderText("或直接粘贴 / 浏览目录…")
        self.path_edit.setMinimumHeight(34)
        self.path_edit.textChanged.connect(lambda: self._timer.start())
        row.addWidget(self.path_edit, 1)
        browse = QPushButton("浏览…")
        browse.setObjectName("Plain")
        browse.setMinimumHeight(34)
        browse.setCursor(Qt.PointingHandCursor)
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        root.addLayout(row)

        self.status = QLabel("")
        self.status.setStyleSheet("color:#909399;font-size:12px;")
        root.addWidget(self.status)

        self.remember_box = QCheckBox("记住此目录，下次直接进入主界面")
        self.remember_box.setChecked(True)
        root.addWidget(self.remember_box)

        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet("background:#EBEEF5;")
        root.addWidget(line)

        foot = QHBoxLayout()
        foot.addStretch(1)
        self.files_btn = QPushButton("改为浏览已导出目录")
        self.files_btn.setObjectName("Text")
        self.files_btn.setCursor(Qt.PointingHandCursor)
        self.files_btn.clicked.connect(self._use_files)
        foot.addWidget(self.files_btn)

        cancel = QPushButton("取消")
        cancel.setObjectName("Plain")
        cancel.setMinimumHeight(32)
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        cancel.setVisible(allow_cancel)
        foot.addWidget(cancel)

        self.ok = QPushButton("连接并进入")
        self.ok.setObjectName("Primary")
        self.ok.setMinimumHeight(32)
        self.ok.setCursor(Qt.PointingHandCursor)
        self.ok.setEnabled(False)
        self.ok.clicked.connect(self._accept)
        foot.addWidget(self.ok)
        root.addLayout(foot)

        if initial:
            self._validate()
        elif self.list.count():
            self.list.setCurrentRow(0)

    # ---------- 候选列表 ----------
    def _fill_candidates(self) -> int:
        cands = config.detect_candidates()
        if not cands:
            self.section.setText(
                r"未自动找到微信目录，请手动选择（形如 …\xwechat_files\wxid_xxx_xxxx）")
            return 0
        for c in cands:
            when = (datetime.fromtimestamp(c["last_ts"]).strftime("%Y-%m-%d %H:%M")
                    if c["last_ts"] else "未知")
            item = QListWidgetItem()
            item.setData(Qt.UserRole, c["path"])
            item.setSizeHint(item.sizeHint().expandedTo(
                self.list.sizeHint().boundedTo(self.list.sizeHint())))
            self.list.addItem(item)
            self.list.setItemWidget(item, self._candidate_widget(c, when, bool(c.get("active"))))
        return len(cands)

    def _candidate_widget(self, c: dict, when: str, active: bool) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(10, 8, 12, 8)
        lay.setSpacing(10)
        lay.addWidget(Avatar(c["name"], None, 34), 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        top = QHBoxLayout()
        name = QLabel(c["name"])
        name.setStyleSheet("font-size:13px;color:#303133;font-weight:500;")
        top.addWidget(name)
        if active:
            tag = QLabel("当前使用中")
            tag.setStyleSheet("background:#ECF5FF;color:#409EFF;border:1px solid #B3D8FF;"
                              "border-radius:8px;padding:0 8px;font-size:11px;")
            top.addWidget(tag)
        top.addStretch(1)
        col.addLayout(top)
        meta = QLabel(f"{c['dbs']} 个数据库 · 最后消息 {when}")
        meta.setStyleSheet("font-size:11px;color:#909399;")
        col.addWidget(meta)
        path = QLabel(c["path"])
        path.setStyleSheet("font-size:11px;color:#C0C4CC;")
        col.addWidget(path)
        lay.addLayout(col, 1)
        return w

    def _on_pick(self, row: int):
        if row < 0:
            return
        item = self.list.item(row)
        if item:
            self.path_edit.setText(item.data(Qt.UserRole))
            self._validate()

    # ---------- 行为 ----------
    def _browse(self):
        start = self.path_edit.text().strip() or str(Path.home())
        d = QFileDialog.getExistingDirectory(self, "选择微信账号目录", start)
        if d:
            self.path_edit.setText(d)
            self._validate()

    def _validate(self) -> bool:
        raw = self.path_edit.text().strip()
        if not raw:
            self.status.setStyleSheet("color:#909399;font-size:12px;")
            self.status.setText("")
            self.ok.setEnabled(False)
            return False
        acc = config.normalize_account(raw)
        if acc:
            self.account_dir = str(acc)
            if str(acc) != raw:
                self.path_edit.blockSignals(True)
                self.path_edit.setText(str(acc))
                self.path_edit.blockSignals(False)
            n = len(list((acc / "db_storage").rglob("*.db")))
            self.status.setStyleSheet("color:#67C23A;font-size:12px;")
            self.status.setText(f"✓ 已识别账号目录（{n} 个数据库），可以进入主界面")
            self.ok.setEnabled(True)
            return True
        self.account_dir = None
        self.status.setStyleSheet("color:#F56C6C;font-size:12px;")
        self.status.setText("✗ 没找到 db_storage，请选到 wxid_xxx_xxxx 目录")
        self.ok.setEnabled(False)
        return False

    def _accept(self):
        if self._validate():
            self.remember = self.remember_box.isChecked()
            self.mode = "live"
            self.accept()

    def _use_files(self):
        self.mode = "files"
        self.accept()
