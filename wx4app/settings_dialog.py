"""设置页：工作空间（导出默认目录）与日志配置。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
)

from . import config
from .frameless import RoundedDialog
from .logging_setup import get_logger

log = get_logger("settings")


class SettingsDialog(RoundedDialog):
    def __init__(self, parent=None, cfg: dict | None = None):
        super().__init__(parent, title="设置",
                         subtitle="工作空间决定导出默认位置；日志默认保留 30 天", min_width=640)
        self.setWindowTitle("设置")
        self._cfg = cfg or config.load()

        root = self.body

        # ---------- 工作空间 ----------
        root.addWidget(self._section("工作空间"))
        root.addLayout(self._path_row(
            "工作目录", self._cfg.get("workspace") or config.default_workspace_dir(),
            "workspace_edit"))
        hint = QLabel("导出时默认使用该目录（每次导出仍可临时改）")
        hint.setStyleSheet("color:#909399;font-size:11px;")
        root.addWidget(hint)

        # ---------- 日志 ----------
        root.addWidget(self._section("日志"))
        self.cb_log = QCheckBox("启用操作日志")
        self.cb_log.setChecked(bool(self._cfg.get("log_enabled", True)))
        root.addWidget(self.cb_log)

        root.addLayout(self._path_row(
            "日志目录", self._cfg.get("log_dir") or config.default_logs_dir(), "log_edit"))

        opt = QHBoxLayout()
        opt.setSpacing(10)
        lbl = QLabel("保留天数")
        lbl.setStyleSheet("color:#606266;font-size:12px;")
        opt.addWidget(lbl)
        self.spin_days = QSpinBox()
        self.spin_days.setRange(1, 365)
        self.spin_days.setValue(int(self._cfg.get("log_retention") or 30))
        self.spin_days.setSuffix(" 天")
        self.spin_days.setFixedWidth(112)
        self.spin_days.setFixedHeight(32)
        self.spin_days.setAlignment(Qt.AlignCenter)
        opt.addWidget(self.spin_days)

        opt.addSpacing(12)
        lbl2 = QLabel("级别")
        lbl2.setStyleSheet("color:#606266;font-size:12px;")
        opt.addWidget(lbl2)
        self.cb_level = QComboBox()
        self.cb_level.addItems(config.LOG_LEVELS)
        self.cb_level.setCurrentText(str(self._cfg.get("log_level") or "INFO"))
        self.cb_level.setFixedWidth(110)
        opt.addWidget(self.cb_level)
        opt.addStretch(1)

        self.btn_open_log = QPushButton("打开日志目录")
        self.btn_open_log.setObjectName("Text")
        self.btn_open_log.setCursor(Qt.PointingHandCursor)
        self.btn_open_log.clicked.connect(self._open_log_dir)
        opt.addWidget(self.btn_open_log)
        root.addLayout(opt)

        self.tip = QLabel("")
        self.tip.setStyleSheet("color:#909399;font-size:11px;")
        root.addWidget(self.tip)

        cfg_path = QLabel(f"配置文件：{config.config_file()}")
        cfg_path.setWordWrap(True)
        cfg_path.setStyleSheet("color:#C0C4CC;font-size:11px;")
        root.addWidget(cfg_path)

        # ---------- 底部按钮 ----------
        foot = QHBoxLayout()
        foot.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("Plain")
        cancel.setMinimumHeight(32)
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        foot.addWidget(cancel)
        save = QPushButton("保存配置")
        save.setObjectName("Primary")
        save.setMinimumHeight(32)
        save.setCursor(Qt.PointingHandCursor)
        save.clicked.connect(self._save)
        foot.addWidget(save)
        root.addLayout(foot)

        self._sync_enabled()

    # ---------- UI 小工具 ----------
    def _section(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color:#909399;font-size:12px;padding-top:6px;")
        return lbl

    def _path_row(self, label: str, value: str, attr: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        lbl = QLabel(label)
        lbl.setFixedWidth(72)
        lbl.setStyleSheet("color:#606266;font-size:12px;")
        row.addWidget(lbl)
        edit = QLineEdit(value)
        edit.setMinimumHeight(32)
        edit.setCursorPosition(0)      # 长路径时显示开头而不是结尾
        row.addWidget(edit, 1)
        btn = QPushButton("浏览…")
        btn.setObjectName("Plain")
        btn.setMinimumHeight(32)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda: self._browse(edit))
        row.addWidget(btn)
        setattr(self, attr, edit)
        if attr == "log_edit":
            edit.textChanged.connect(self._sync_enabled)
        return row

    def _browse(self, edit: QLineEdit):
        start = edit.text().strip() or str(Path.home())
        d = QFileDialog.getExistingDirectory(self, "选择目录", start)
        if d:
            edit.setText(d)

    def _sync_enabled(self):
        on = self.cb_log.isChecked()
        for w in (self.log_edit, self.spin_days, self.cb_level, self.btn_open_log):
            w.setEnabled(on)

    def _open_log_dir(self):
        path = Path(self.log_edit.text().strip() or config.default_logs_dir())
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    # ---------- 保存 ----------
    def _save(self):
        workspace = self.workspace_edit.text().strip() or config.default_workspace_dir()
        log_dir = self.log_edit.text().strip() or config.default_logs_dir()
        for path in (Path(workspace), Path(log_dir)):
            try:
                path.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                self.tip.setStyleSheet("color:#F56C6C;font-size:11px;")
                self.tip.setText(f"目录不可用：{path}（{exc}）")
                return

        config.save(
            workspace=workspace,
            export_dir=workspace,          # 工作空间即导出默认目录
            log_enabled=self.cb_log.isChecked(),
            log_dir=log_dir,
            log_retention=self.spin_days.value(),
            log_level=self.cb_level.currentText(),
        )
        log.info("设置已保存：workspace=%s logs=%s retention=%d level=%s enabled=%s",
                 workspace, log_dir, self.spin_days.value(),
                 self.cb_level.currentText(), self.cb_log.isChecked())
        self.accept()
