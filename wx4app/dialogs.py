"""与应用风格一致的结果提示框（圆角、无边框、Element 按钮）。"""
from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .frameless import RoundedDialog


class ResultDialog(RoundedDialog):
    """导出成功/失败/取消的提示框，风格与主窗口一致。"""

    def __init__(self, parent=None, title: str = "导出完成", text: str = "",
                 folder: str = "", icon: str = "✅", min_width: int = 460):
        super().__init__(parent, title=title, subtitle="", min_width=min_width)
        self.setWindowTitle(title)
        self.open_clicked = False
        self._folder = folder

        row = QHBoxLayout()
        row.setSpacing(12)
        ic = QLabel(icon)
        ic.setFixedWidth(34)
        ic.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        ic.setStyleSheet("font-size:24px;background:transparent;")
        row.addWidget(ic)

        col = QVBoxLayout()
        col.setSpacing(6)
        msg = QLabel(text)
        msg.setWordWrap(True)
        msg.setTextInteractionFlags(Qt.TextSelectableByMouse)
        msg.setStyleSheet("color:#303133;font-size:13px;background:transparent;")
        col.addWidget(msg)
        if folder:
            path = QLabel(folder)
            path.setWordWrap(True)
            path.setStyleSheet("color:#909399;font-size:11px;background:transparent;")
            col.addWidget(path)
        row.addLayout(col, 1)
        self.body.addLayout(row)

        spacer = QWidget()
        spacer.setFixedHeight(4)
        self.body.addWidget(spacer)

        foot = QHBoxLayout()
        foot.setSpacing(8)
        foot.addStretch(1)
        close = QPushButton("关闭")
        close.setObjectName("Plain")
        close.setMinimumHeight(32)
        close.setMinimumWidth(76)
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.reject)
        foot.addWidget(close)
        if folder:
            open_btn = QPushButton("打开目录")
            open_btn.setObjectName("Primary")
            open_btn.setMinimumHeight(32)
            open_btn.setMinimumWidth(96)
            open_btn.setCursor(Qt.PointingHandCursor)
            open_btn.clicked.connect(self._open)
            foot.addWidget(open_btn)
        self.body.addLayout(foot)

    def _open(self):
        self.open_clicked = True
        if self._folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._folder))
        self.accept()


def notify(parent, title: str, text: str, folder: str = "", icon: str = "✅") -> bool:
    """弹出结果提示，返回用户是否点了「打开目录」。"""
    dlg = ResultDialog(parent, title, text, folder, icon)
    dlg.exec()
    return dlg.open_clicked
