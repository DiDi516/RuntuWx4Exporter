"""无边框圆角窗口：自绘阴影 + 可拖动标题栏 + 窗口按钮。

Windows 10 不会给无边框窗口自动圆角，这里自己画：
- 外层留 MARGIN 的透明边距用于阴影
- 中间是圆角卡片（QSS: #WindowCard）
- 标题栏可拖动 / 双击最大化
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizeGrip,
    QVBoxLayout,
    QWidget,
)

MARGIN = 10
RADIUS = 14


class WindowButton(QPushButton):
    def __init__(self, text: str, kind: str = "normal", parent=None):
        super().__init__(text, parent)
        self.setObjectName(f"WinBtn{kind.capitalize()}" if kind != "normal" else "WinBtn")
        self.setFixedSize(32, 26)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)


class TitleBar(QWidget):
    """可拖动标题栏（含窗口按钮）。"""

    def __init__(self, window, title_widget: QWidget, show_max: bool = True,
                 show_min: bool = True, parent=None, margins=(14, 8, 10, 8)):
        super().__init__(parent)
        self._win = window
        self._drag = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(*margins)
        lay.setSpacing(8)
        lay.addWidget(title_widget, 1)

        self.btn_min = WindowButton("—")
        self.btn_min.clicked.connect(window.showMinimized)
        self.btn_min.setVisible(show_min)
        lay.addWidget(self.btn_min)
        if show_max:
            self.btn_max = WindowButton("□")
            self.btn_max.clicked.connect(self.toggle_max)
            lay.addWidget(self.btn_max)
        else:
            self.btn_max = None
        self.btn_close = WindowButton("✕", "close")
        self.btn_close.clicked.connect(window.close)
        lay.addWidget(self.btn_close)

    def toggle_max(self):
        if self._win.isMaximized():
            self._win.showNormal()
        else:
            self._win.showMaximized()

    # ---- 拖动 ----
    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._drag = ev.globalPosition().toPoint() - self._win.frameGeometry().topLeft()
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._drag is not None and ev.buttons() & Qt.LeftButton:
            win = self._win
            if win.isMaximized():
                win.showNormal()
                self._drag = QPoint(win.width() // 2, 20)
            win.move(ev.globalPosition().toPoint() - self._drag)
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        self._drag = None
        super().mouseReleaseEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        if self.btn_max is not None:
            self.toggle_max()
        super().mouseDoubleClickEvent(ev)


class _RoundedBase:
    """公共部分：透明背景 + 圆角卡片 + 阴影绘制。"""

    RADIUS = RADIUS
    MARGIN = MARGIN
    _card: QFrame

    def _init_rounded(self):
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        # QMainWindow 不能直接把布局挂在自身上，需要 central widget 承载
        if isinstance(self, QMainWindow):
            host = QWidget(self)
            host.setObjectName("WindowHost")
            host.setStyleSheet("QWidget#WindowHost{background:transparent;}")
            self.setCentralWidget(host)
            outer = QVBoxLayout(host)
        else:
            outer = QVBoxLayout(self)
        outer.setContentsMargins(self.MARGIN, self.MARGIN, self.MARGIN, self.MARGIN)
        self._card = QFrame(outer.parentWidget())
        self._card.setObjectName("WindowCard")
        outer.addWidget(self._card)
        self._outer = outer

    def paintEvent(self, ev):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self.isMaximized():
            painter.fillRect(self.rect(), QColor("#F5F7FA"))
            painter.end()
            return
        m = self.MARGIN
        base = QRectF(self.rect()).adjusted(m, m + 2, -m, -m + 2)
        for i, alpha in ((5, 10), (3, 18), (1, 26)):
            path = QPainterPath()
            path.addRoundedRect(base.adjusted(-i, -i, i, i),
                                self.RADIUS + i, self.RADIUS + i)
            painter.fillPath(path, QColor(0, 0, 0, alpha))
        painter.end()

    def changeEvent(self, ev):
        super().changeEvent(ev)
        if ev.type() == ev.Type.WindowStateChange:
            self._sync_frame()

    def _sync_frame(self):
        if self.isMaximized():
            self._outer.setContentsMargins(0, 0, 0, 0)
            self._card.setProperty("maximized", "true")
        else:
            m = self.MARGIN
            self._outer.setContentsMargins(m, m, m, m)
            self._card.setProperty("maximized", "false")
        self._card.style().unpolish(self._card)
        self._card.style().polish(self._card)
        self.update()


class RoundedMainWindow(QMainWindow, _RoundedBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_rounded()
        self.card_layout = QVBoxLayout(self._card)
        self.card_layout.setContentsMargins(0, 0, 0, 0)
        self.card_layout.setSpacing(0)

    def attach_size_grip(self):
        """右下角拖拽手柄（无边框窗口需要自己提供）。"""
        grip = QSizeGrip(self._card)
        grip.setFixedSize(16, 16)
        grip.setStyleSheet("background:transparent;")
        self._grip = grip
        self._grip.move(self._card.width() - 18, self._card.height() - 18)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if getattr(self, "_grip", None):
            self._grip.move(self._card.width() - 18, self._card.height() - 18)


class RoundedDialog(QDialog, _RoundedBase):
    """圆角弹窗：自带标题栏（标题 + 关闭），内容放在 self.body。"""

    def __init__(self, parent=None, title: str = "", subtitle: str = "",
                 min_width: int = 520):
        super().__init__(parent)
        self._init_rounded()
        self.setModal(True)
        self.setMinimumWidth(min_width + 2 * self.MARGIN)

        lay = QVBoxLayout(self._card)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        head = QWidget()
        title_box = QWidget()
        tb = QVBoxLayout(title_box)
        tb.setContentsMargins(0, 0, 0, 0)
        tb.setSpacing(4)          # 标题与小字之间留呼吸感
        self.title_label = QLabel(title)
        self.title_label.setObjectName("SetupTitle")
        tb.addWidget(self.title_label)
        if subtitle:
            self.sub_label = QLabel(subtitle)
            self.sub_label.setObjectName("SetupSub")
            self.sub_label.setWordWrap(True)
            tb.addWidget(self.sub_label)
        self.titlebar = TitleBar(self, title_box, show_max=False, show_min=False,
                                 margins=(26, 16, 12, 10))
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(self.titlebar)
        lay.addWidget(head)

        self.body = QVBoxLayout()
        self.body.setContentsMargins(26, 8, 26, 18)
        self.body.setSpacing(12)
        lay.addLayout(self.body)
