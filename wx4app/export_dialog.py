"""导出选项对话框：时间范围 / 导出内容 / 图片目录结构。"""
from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QWidget,
)

from .frameless import RoundedDialog

PRESETS = [
    ("全部时间", 0),
    ("最近 7 天", 7),
    ("最近 30 天", 30),
    ("最近 3 个月", 90),
    ("最近 1 年", 365),
    ("自定义…", -1),
]


class ExportDialog(RoundedDialog):
    def __init__(self, title: str, subtitle: str = "", allow_content: bool = True,
                 preselect_images: bool = True, preselect_chat: bool = True,
                 allow_chat: bool = True, default_layout: str = "date",
                 total_hint: str = "", parent=None):
        super().__init__(parent, title=title, subtitle=subtitle, min_width=480)
        self.setObjectName("Setup")
        self.setWindowTitle(title)
        root = self.body

        # 时间范围
        root.addWidget(self._section("时间范围"))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.preset = QComboBox()
        for label, days in PRESETS:
            self.preset.addItem(label, days)
        self.preset.setMinimumHeight(32)
        self.preset.currentIndexChanged.connect(self._on_preset)
        row.addWidget(self.preset, 1)

        self.from_date = QDateEdit()
        self.to_date = QDateEdit()
        for d in (self.from_date, self.to_date):
            d.setCalendarPopup(True)
            d.setDisplayFormat("yyyy-MM-dd")
            d.setMinimumHeight(32)
            d.setDate(QDate.currentDate())
            d.hide()
        row.addWidget(self.from_date)
        self.to_label = QLabel("至")
        self.to_label.hide()
        row.addWidget(self.to_label)
        row.addWidget(self.to_date)
        root.addLayout(row)

        self.range_hint = QLabel("")
        self.range_hint.setObjectName("SetupHint")
        root.addWidget(self.range_hint)

        # 导出内容
        if allow_content:
            root.addWidget(self._section("导出内容"))
            crow = QHBoxLayout()
            crow.setSpacing(18)
            self.cb_chat = QCheckBox("聊天记录（txt / html / json）")
            self.cb_chat.setChecked(preselect_chat and allow_chat)
            self.cb_chat.setEnabled(allow_chat)
            self.cb_img = QCheckBox("图片")
            self.cb_img.setChecked(preselect_images)
            self.cb_file = QCheckBox("文件（文档/压缩包等）")
            self.cb_file.setChecked(True)
            self.cb_chat.toggled.connect(self._sync_layout_enabled)
            crow.addWidget(self.cb_chat)
            crow.addWidget(self.cb_img)
            crow.addWidget(self.cb_file)
            crow.addStretch(1)
            root.addLayout(crow)
        else:
            self.cb_chat = QCheckBox()
            self.cb_chat.setChecked(True)
            self.cb_chat.hide()
            self.cb_img = QCheckBox("同时导出图片（体积较大）")
            self.cb_img.setChecked(preselect_images)
            self.cb_file = QCheckBox("同时导出文件（文档 / 压缩包等）")
            self.cb_file.setChecked(True)
            self.cb_img.toggled.connect(self._sync_layout_enabled)
            self.cb_file.toggled.connect(self._sync_layout_enabled)
            root.addWidget(self.cb_img)
            root.addWidget(self.cb_file)

        # 图片目录结构
        root.addWidget(self._section("图片 / 文件 目录结构"))
        self.rb_date = QRadioButton("按日期分层：图片(文件)/2026/11/16/xxx")
        self.rb_flat = QRadioButton("平铺到同一目录：图片(文件)/xxx（图片名带日期时间）")
        (self.rb_date if default_layout != "flat" else self.rb_flat).setChecked(True)
        root.addWidget(self.rb_date)
        root.addWidget(self.rb_flat)

        if total_hint:
            hint = QLabel(total_hint)
            hint.setObjectName("SetupHint")
            root.addWidget(hint)

        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet("background:#EBEEF5;")
        root.addWidget(line)

        foot = QHBoxLayout()
        foot.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("Plain")
        cancel.setMinimumHeight(32)
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        ok = QPushButton("选择目录并导出")
        ok.setObjectName("Primary")
        ok.setMinimumHeight(32)
        ok.setCursor(Qt.PointingHandCursor)
        ok.clicked.connect(self._accept)
        foot.addWidget(cancel)
        foot.addWidget(ok)
        root.addLayout(foot)

        self._on_preset()

    def _section(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color:#909399;font-size:12px;padding-top:2px;")
        return lbl

    def _on_preset(self):
        days = self.preset.currentData()
        custom = days == -1
        self.from_date.setVisible(custom)
        self.to_label.setVisible(custom)
        self.to_date.setVisible(custom)
        if custom:
            today = QDate.currentDate()
            if not self.from_date.date().isValid():
                self.from_date.setDate(today.addDays(-30))
            self.to_date.setDate(today)
            self.range_hint.setText("自定义起止日期（含起止当天）")
        elif days == 0:
            self.range_hint.setText("导出全部历史消息")
        else:
            d = datetime.now() - timedelta(days=int(days))
            self.range_hint.setText(f"从 {d:%Y-%m-%d} 至今")

    def _sync_layout_enabled(self, _=None):
        enabled = self.cb_img.isChecked() or self.cb_file.isChecked()
        self.rb_date.setEnabled(enabled)
        self.rb_flat.setEnabled(enabled)

    def _accept(self):
        if (not self.cb_img.isChecked() and not self.cb_chat.isChecked()
                and not self.cb_file.isChecked()):
            self.range_hint.setText("请至少勾选「聊天记录」「图片」或「文件」")
            return
        self.accept()

    # ---------------- 结果 ----------------
    def options(self) -> dict:
        days = self.preset.currentData()
        start_ts = end_ts = 0
        if days == -1:
            start_dt = datetime.combine(self.from_date.date().toPython(),
                                        datetime.min.time())
            end_dt = datetime.combine(self.to_date.date().toPython(),
                                      datetime.max.time().replace(microsecond=0))
            if start_dt > end_dt:
                start_dt, end_dt = end_dt.replace(hour=0, minute=0), start_dt.replace(
                    hour=23, minute=59, second=59)
            start_ts, end_ts = int(start_dt.timestamp()), int(end_dt.timestamp())
        elif days > 0:
            start_ts = int((datetime.now() - timedelta(days=int(days))).timestamp())
            end_ts = int(datetime.now().timestamp())
        return {
            "start_ts": start_ts,
            "end_ts": end_ts,
            "do_chat": self.cb_chat.isChecked(),
            "do_images": self.cb_img.isChecked(),
            "do_files": self.cb_file.isChecked(),
            "layout": "flat" if self.rb_flat.isChecked() else "date",
            "preset": days,
        }
