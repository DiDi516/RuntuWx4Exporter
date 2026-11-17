"""Element 风格界面组件：头像、气泡、聊天区、图片墙、灯箱。"""
from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImageReader, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from .theme import TEXT_SECONDARY

PALETTE = ["#409EFF", "#67C23A", "#E6A23C", "#F56C6C", "#909399",
           "#5B8FF9", "#61C0BF", "#7262FD", "#F6903D", "#008685"]

# 头像/图片解码有个明显开销，缓存起来避免每次重绘都读盘解码
_PIX_CACHE: dict[tuple[str, int], QPixmap] = {}


def _decode(path: str | Path, target: QSize | None) -> QPixmap | None:
    """用 QImageReader 直接按目标尺寸解码（JPEG 可硬件级缩放，比先全解码再缩放快很多）。"""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    if target is not None:
        reader.setScaledSize(target)
    img = reader.read()
    if img.isNull():
        return None
    return QPixmap.fromImage(img)


def fit_pixmap(path: str | Path | None, max_w: int, max_h: int) -> QPixmap | None:
    """等比缩放到不超过 (max_w, max_h)，结果按 (path, 尺寸) 缓存。"""
    if not path:
        return None
    key = (str(path), -max_w, -max_h)
    if key in _PIX_CACHE:
        p = _PIX_CACHE[key]
        return p if not p.isNull() else None
    size = QImageReader(str(path)).size()
    if size.isValid() and size.width() > 0 and size.height() > 0:
        target = size.scaled(QSize(max_w, max_h), Qt.KeepAspectRatio)
    else:
        target = None
    pix = _decode(path, target)
    if pix is None:
        _PIX_CACHE[key] = QPixmap()
        return None
    _PIX_CACHE[key] = pix
    return pix


def cover_pixmap(path: str | Path | None, w: int, h: int) -> QPixmap | None:
    """裁剪填充为 w×h（头像、缩略图用）。"""
    if not path:
        return None
    key = (str(path), w, h)
    if key in _PIX_CACHE:
        p = _PIX_CACHE[key]
        return p if not p.isNull() else None
    size = QImageReader(str(path)).size()
    if size.isValid() and size.width() > 0 and size.height() > 0:
        scale = max(w / size.width(), h / size.height())
        target = QSize(max(1, int(size.width() * scale + 0.5)),
                       max(1, int(size.height() * scale + 0.5)))
    else:
        target = QSize(w, h)
    pix = _decode(path, target)
    if pix is None:
        _PIX_CACHE[key] = QPixmap()
        return None
    x = max(0, (pix.width() - w) // 2)
    y = max(0, (pix.height() - h) // 2)
    pix = pix.copy(x, y, min(w, pix.width()), min(h, pix.height()))
    _PIX_CACHE[key] = pix
    return pix


_PENDING_IMAGES: list[tuple[QLabel, str]] = []


def image_display_size(path: str | Path, max_w: int = 240, max_h: int = 300) -> QSize:
    """只读图片头拿尺寸（不解码像素），用于占位，避免渲染时卡顿。"""
    size = QImageReader(str(path)).size()
    if size.isValid() and size.width() > 0 and size.height() > 0:
        return size.scaled(QSize(max_w, max_h), Qt.KeepAspectRatio)
    return QSize(max_w, max_h)


def cached_pixmap(path: str | Path | None, size: int = 0) -> QPixmap | None:
    if not path:
        return None
    key = (str(path), size)
    hit = _PIX_CACHE.get(key)
    if hit is not None:
        return hit
    pix = QPixmap(str(path))
    if pix.isNull():
        _PIX_CACHE[key] = QPixmap()
        return None
    if size:
        pix = pix.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    _PIX_CACHE[key] = pix
    return pix


def color_for(name: str) -> str:
    h = 0
    for ch in (name or "?"):
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return PALETTE[h % len(PALETTE)]


def initial_of(name: str) -> str:
    return (name or "?").strip()[:1] or "?"


class Avatar(QWidget):
    """圆角头像：有真实头像就画图，否则用首字 + 配色。"""

    def __init__(self, name: str, path=None, size: int = 40, parent=None):
        super().__init__(parent)
        self._name = name
        self._pix: QPixmap | None = None
        if isinstance(path, QPixmap):
            self._pix = None if path.isNull() else path
        elif path:
            self._pix = cover_pixmap(path, size, size)
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def paintEvent(self, ev):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = QRectF(self.rect())
        radius = max(6.0, self.width() * 0.26)
        clip = QPainterPath()
        clip.addRoundedRect(rect, radius, radius)
        painter.setClipPath(clip)
        if self._pix is not None:
            scaled = self._pix.scaled(self.size(), Qt.KeepAspectRatioByExpanding,
                                      Qt.SmoothTransformation)
            painter.drawPixmap(rect.toRect(), scaled)
        else:
            painter.fillPath(clip, QColor(color_for(self._name)))
            font = QFont()
            font.setPixelSize(int(self.width() * 0.42))
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(self.rect(), Qt.AlignCenter, initial_of(self._name))
        painter.end()


class ConvDelegate(QStyledItemDelegate):
    """会话列表绘制委托：只画可见行，避免 277 个自定义控件带来的卡顿。"""

    NAME, PREVIEW, TIME, AVA, GROUP = (Qt.UserRole + 1, Qt.UserRole + 2,
                                      Qt.UserRole + 3, Qt.UserRole + 4,
                                      Qt.UserRole + 5)

    def sizeHint(self, option, index):
        return QSize(0, 62)

    def paint(self, painter: QPainter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rect = option.rect.adjusted(6, 2, -6, -2)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        if selected or hovered:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#ECF5FF" if selected else "#F5F7FA"))
            painter.drawRoundedRect(rect, 9, 9)

        name = index.data(self.NAME) or ""
        preview = index.data(self.PREVIEW) or ""
        ts = index.data(self.TIME) or 0
        ava = index.data(self.AVA)
        is_group = bool(index.data(self.GROUP))

        # 头像
        size, x, y = 42, rect.left() + 8, rect.top() + (rect.height() - 42) // 2
        av_rect = QRectF(x, y, size, size)
        clip = QPainterPath()
        clip.addRoundedRect(av_rect, 11, 11)
        painter.setClipPath(clip)
        pix = cover_pixmap(ava, size, size) if ava else None
        if pix is not None:
            painter.drawPixmap(av_rect.toRect(), pix)
        else:
            painter.fillPath(clip, QColor(color_for(name)))
            f = QFont()
            f.setPixelSize(17)
            f.setBold(True)
            painter.setFont(f)
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(av_rect.toRect(), Qt.AlignCenter, initial_of(name))
        painter.setClipping(False)

        text_left = x + size + 10
        right = rect.right() - 8
        time_text = ConvDelegate._fmt(ts)
        f_time = QFont()
        f_time.setPixelSize(11)
        painter.setFont(f_time)
        tw = painter.fontMetrics().horizontalAdvance(time_text)
        painter.setPen(QColor("#909399"))
        painter.drawText(QRectF(right - tw, rect.top() + 12, tw, 16),
                         Qt.AlignRight | Qt.AlignVCenter, time_text)

        f_name = QFont()
        f_name.setPixelSize(14)
        f_name.setWeight(QFont.Medium)
        painter.setFont(f_name)
        painter.setPen(QColor("#303133"))
        name_w = max(40, right - tw - 8 - text_left)
        painter.drawText(
            QRectF(text_left, rect.top() + 10, name_w, 20),
            Qt.AlignLeft | Qt.AlignVCenter,
            painter.fontMetrics().elidedText(name, Qt.ElideRight, int(name_w)))

        f_pv = QFont()
        f_pv.setPixelSize(12)
        painter.setFont(f_pv)
        painter.setPen(QColor("#909399"))
        if is_group:
            painter.setPen(QColor("#909399"))
        pv_w = max(40, right - text_left)
        painter.drawText(
            QRectF(text_left, rect.top() + 33, pv_w, 18),
            Qt.AlignLeft | Qt.AlignVCenter,
            painter.fontMetrics().elidedText(preview, Qt.ElideRight, int(pv_w)))
        painter.restore()

    @staticmethod
    def _fmt(ts: int) -> str:
        if not ts:
            return ""
        from datetime import datetime
        d = datetime.fromtimestamp(ts)
        now = datetime.now()
        if d.date() == now.date():
            return f"{d:%H:%M}"
        if d.year == now.year:
            return f"{d.month}月{d.day}日"
        return f"{d.year}/{d.month}/{d.day}"


class ClickableLabel(QLabel):
    clicked = Signal()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(ev)


class MessageRow(QWidget):
    """一条消息：头像 + 气泡（群聊带发言人）。"""

    def __init__(self, msg: dict, is_group: bool, img_path: Path | None,
                 avatar_path=None, on_image=None, max_bubble: int = 520, parent=None):
        super().__init__(parent)
        me = bool(msg.get("me"))
        who = msg.get("who") or ""
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 4)
        outer.setSpacing(10)

        av = Avatar("我" if me else who, avatar_path, 34)
        col = self._column(msg, is_group, img_path, on_image, max_bubble, me)
        if me:
            outer.addStretch(1)
            outer.addWidget(col)
            outer.addWidget(av, 0, Qt.AlignTop)
        else:
            outer.addWidget(av, 0, Qt.AlignTop)
            outer.addWidget(col)
            outer.addStretch(1)

    def _column(self, msg, is_group, img_path, on_image, max_bubble, me) -> QWidget:
        col = QWidget()
        col.setMaximumWidth(max_bubble + 60)
        col.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        lay = QVBoxLayout(col)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)

        if is_group and not me and msg.get("who"):
            name = QLabel(msg["who"])
            name.setObjectName("Sender")
            lay.addWidget(name, 0, Qt.AlignLeft)

        if img_path and Path(img_path).exists():
            size = image_display_size(img_path, 240, 300)
            label = ClickableLabel()
            label.setObjectName("ImgBubble")
            label.setFixedSize(size)
            label.setText("")
            label.setCursor(Qt.PointingHandCursor)
            if on_image:
                label.clicked.connect(lambda: on_image(msg))
            _PENDING_IMAGES.append((label, str(img_path)))
            lay.addWidget(label, 0, Qt.AlignLeft if not me else Qt.AlignRight)
            return col

        text = msg.get("text") or ""
        bubble = QLabel(text)
        bubble.setWordWrap(True)
        bubble.setTextInteractionFlags(Qt.TextSelectableByMouse)
        font = QFont()
        font.setPixelSize(14)
        bubble.setFont(font)
        fm = QFontMetrics(font)
        pad = 34
        one_line = fm.horizontalAdvance(text)
        if one_line + pad <= max_bubble:
            bubble.setFixedWidth(max(64, one_line + pad))
        else:
            bubble.setFixedWidth(max_bubble)
        bubble.setObjectName("Bubble")
        bubble.setProperty("me", "true" if me else "false")
        lay.addWidget(bubble, 0, Qt.AlignLeft if not me else Qt.AlignRight)
        return col


class SystemRow(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("SystemRow")
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)
        self.setMaximumWidth(640)


class ChatView(QScrollArea):
    """聊天区：日期分隔 + 消息行。"""

    load_more = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet("QScrollArea#ChatScroll{background:#FAFBFC;border:none;}")
        self.setObjectName("ChatScroll")
        self._inner = QWidget()
        self._inner.setObjectName("ChatInner")
        # 注意：必须带选择器，裸声明会级联到所有子控件，覆盖气泡背景色
        self._inner.setStyleSheet("QWidget#ChatInner{background:#FAFBFC;}")
        self._lay = QVBoxLayout(self._inner)
        self._lay.setContentsMargins(26, 14, 26, 18)
        self._lay.setSpacing(0)
        self._lay.addStretch(1)
        self.setWidget(self._inner)

        self._more_btn = QPushButton("加载更早的消息")
        self._more_btn.setObjectName("Text")
        self._more_btn.setCursor(Qt.PointingHandCursor)
        self._more_btn.clicked.connect(self.load_more.emit)
        self._more_btn.hide()
        self._lay.insertWidget(0, self._more_btn, 0, Qt.AlignHCenter)

        self._img_timer = QTimer(self)
        self._img_timer.setInterval(16)
        self._img_timer.timeout.connect(self._drain_images)

    def pause_images(self):
        """暂时解码（切到图片页时避免两边抢解码）。"""
        self._img_timer.stop()

    def resume_images(self):
        if _PENDING_IMAGES:
            self._img_timer.start()

    def _drain_images(self):
        for _ in range(3):
            if not _PENDING_IMAGES:
                self._img_timer.stop()
                return
            label, path = _PENDING_IMAGES.pop(0)
            try:
                pix = fit_pixmap(path, 240, 300)
            except RuntimeError:
                continue
            try:
                label.objectName()
            except RuntimeError:  # 控件已被销毁（切换会话/关闭窗口）
                continue
            if pix is None:
                label.setText("[图片无法显示]")
                label.setStyleSheet("color:#909399;font-size:12px;padding:12px;"
                                    "border:1px dashed #DCDFE6;border-radius:10px;")
                label.setFixedSize(140, 56)
                continue
            label.setPixmap(pix)
            label.setFixedSize(pix.size())

    def clear(self):
        _PENDING_IMAGES.clear()
        self._img_timer.stop()
        # 注意：takeAt 只把控件移出布局，控件仍是子对象、仍会显示；
        # 必须先 setParent(None) 再删除，否则切换会话会看到上一个会话的残影。
        while self._lay.count() > 2:
            item = self._lay.takeAt(1)
            w = item.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()

    def set_has_more(self, more: bool):
        self._more_btn.setVisible(more)

    def render(self, msgs, is_group, resolve_image, on_image,
               avatar_for=None, keep_bottom=True):
        bar = self.verticalScrollBar()
        old_max, old_val = bar.maximum(), bar.value()
        self._inner.setUpdatesEnabled(False)
        self.clear()
        insert_at = 1
        last_day, last_ts = "", 0
        for m in msgs:
            day = (m.get("t") or "")[:10]
            if day != last_day:
                sep = QLabel(day)
                sep.setObjectName("DaySep")
                sep.setAlignment(Qt.AlignCenter)
                self._lay.insertWidget(insert_at, sep)
                insert_at += 1
                last_day, last_ts = day, 0
            elif m.get("ts", 0) - last_ts > 300:
                sep = QLabel((m.get("t") or "")[11:16])
                sep.setObjectName("TimeSep")
                sep.setAlignment(Qt.AlignCenter)
                self._lay.insertWidget(insert_at, sep)
                insert_at += 1
            last_ts = m.get("ts", 0)

            if m.get("type") == "system":
                row = SystemRow(m.get("text") or "")
                self._lay.insertWidget(insert_at, row, 0, Qt.AlignHCenter)
                insert_at += 1
                continue
            img = resolve_image(m) if m.get("type") == "image" else None
            av = avatar_for(m.get("_uid") or m.get("who")) if avatar_for else None
            row = MessageRow(m, is_group, img, av, on_image)
            self._lay.insertWidget(insert_at, row)
            insert_at += 1

        self._inner.setUpdatesEnabled(True)
        self._inner.update()
        if _PENDING_IMAGES:
            self._img_timer.start()
        if keep_bottom:
            QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))
        else:
            QTimer.singleShot(0, lambda: bar.setValue(bar.maximum() - old_max + old_val))


class ImagesView(QWidget):
    """图片墙：懒加载 + 滚动到底自动加载下一页。"""

    open_image = Signal(int)

    PAGE_HINT = 400  # 距底部多少像素开始预加载

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(8)
        self.tip = QLabel("")
        self.tip.setStyleSheet(f"color:{TEXT_SECONDARY};font-size:12px;")
        lay.addWidget(self.tip)

        self.list = QListWidget()
        self.list.setObjectName("ImgList")
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.list.setSpacing(10)
        self.list.setIconSize(QSize(150, 150))
        self.list.setGridSize(QSize(176, 200))
        self.list.setWordWrap(True)
        self.list.setStyleSheet("QListWidget#ImgList{background:transparent;border:none;}")
        self.list.itemDoubleClicked.connect(lambda it: self.open_image.emit(self.list.row(it)))
        lay.addWidget(self.list, 1)

        self._pending: list[tuple[QListWidgetItem, str]] = []
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._load_batch)

        self.items: list[dict] = []
        self._fetch = None
        self._path_of = None
        self._has_more = False
        self._loading = False
        self._total = 0
        self.list.verticalScrollBar().valueChanged.connect(self._maybe_load)

    # ---------- 对外 ----------
    def reset(self, fetch_page, path_of):
        """fetch_page(before) -> {items, has_more, total}；path_of(msg) -> Path|None"""
        self.list.clear()
        self._pending.clear()
        self._timer.stop()
        self.items = []
        self._fetch = fetch_page
        self._path_of = path_of
        self._has_more = True
        self._loading = False
        self._total = 0
        self.tip.setText("正在加载图片…")
        self._load_next()

    # ---------- 分页 ----------
    def _load_next(self):
        if self._loading or not self._has_more or self._fetch is None:
            return
        self._loading = True
        before = self.items[-1]["ts"] if self.items else None
        QTimer.singleShot(0, lambda: self._do_load(before))

    def _do_load(self, before):
        page = None
        try:
            page = self._fetch(before)
        except Exception:  # noqa: BLE001
            page = None
        self._loading = False
        if not page or not page.get("items"):
            self._has_more = False
            self._update_tip()
            return
        self._total = page.get("total") or self._total
        self._has_more = bool(page.get("has_more"))
        self._append(page["items"])
        self._update_tip()
        # 内容不足一屏时继续加载
        QTimer.singleShot(60, self._maybe_load)

    def _append(self, items: list[dict]):
        placeholder = QPixmap(150, 150)
        placeholder.fill(QColor("#F5F7FA"))
        for m in items:
            text = f"{(m.get('t') or '')[5:16]}  {'我' if m.get('me') else m.get('who', '')}"
            item = QListWidgetItem(text)
            item.setIcon(placeholder)
            self.list.addItem(item)
            self.items.append(m)
            p = self._path_of(m) if self._path_of else None
            if p:
                self._pending.append((item, str(p)))
        if self._pending:
            self._timer.start()

    def _update_tip(self):
        shown, total = len(self.items), self._total or len(self.items)
        more = "，继续下滑加载更多" if self._has_more else ""
        self.tip.setText(f"共 {total} 张图片 · 已加载 {shown} 张{more}")

    def _maybe_load(self, *args):
        bar = self.list.verticalScrollBar()
        if bar.maximum() - bar.value() <= self.PAGE_HINT:
            self._load_next()

    def _load_batch(self):
        for _ in range(8):
            if not self._pending:
                self._timer.stop()
                return
            item, path = self._pending.pop(0)
            pix = cover_pixmap(path, 150, 150)
            if pix is None:
                continue
            item.setIcon(pix)


class Lightbox(QDialog):
    """看图：← → 翻页，Esc 关闭，另存为。"""

    def __init__(self, items: list[dict], index: int, path_of, parent=None):
        super().__init__(parent)
        self.setWindowTitle("查看图片")
        self.setStyleSheet("QDialog{background:#141414;}")
        self.resize(1040, 780)
        self._items = items
        self._idx = max(0, min(index, len(items) - 1))
        self._path_of = path_of

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.image, 1)

        bar = QHBoxLayout()
        bar.setContentsMargins(18, 8, 18, 14)
        self.caption = QLabel()
        self.caption.setStyleSheet("color:#C0C4CC;font-size:12px;")
        prev_btn = QPushButton("‹ 上一张")
        next_btn = QPushButton("下一张 ›")
        save = QPushButton("另存为…")
        for b in (prev_btn, next_btn, save):
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                "QPushButton{color:#E4E7ED;background:#262626;border:1px solid #3A3A3A;"
                "border-radius:4px;padding:5px 14px;}"
                "QPushButton:hover{background:#333;border-color:#555;}")
        prev_btn.clicked.connect(lambda: self.step(-1))
        next_btn.clicked.connect(lambda: self.step(1))
        save.clicked.connect(self.save_as)
        bar.addWidget(self.caption, 1)
        bar.addWidget(prev_btn)
        bar.addWidget(next_btn)
        bar.addWidget(save)
        lay.addLayout(bar)
        self._show()

    def _show(self):
        m = self._items[self._idx]
        p = self._path_of(m)
        if p:
            pix = QPixmap(str(p))
            if not pix.isNull():
                self.image.setPixmap(pix.scaled(self.width() - 40, self.height() - 96,
                                                Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.caption.setText(
            f"{m.get('t', '')} · {'我' if m.get('me') else m.get('who', '')} · "
            f"{self._idx + 1}/{len(self._items)}")

    def step(self, d: int):
        i = self._idx + d
        if 0 <= i < len(self._items):
            self._idx = i
            self._show()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self.close()
        elif ev.key() == Qt.Key_Left:
            self.step(-1)
        elif ev.key() == Qt.Key_Right:
            self.step(1)
        else:
            super().keyPressEvent(ev)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self._items:
            self._show()

    def save_as(self):
        p = self._path_of(self._items[self._idx])
        if not p:
            return
        default = str(Path.home() / "Pictures" / Path(p).name)
        target, _ = QFileDialog.getSaveFileName(self, "另存为", default,
                                                "图片 (*.jpg *.png *.gif *.webp *.bmp)")
        if target:
            shutil.copy2(p, target)
