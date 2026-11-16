"""Element UI 风格主题（配色 / QSS / 阴影工具）。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget

CHECK_ICON = (Path(__file__).resolve().parent / "assets" / "check.png").as_posix()

PRIMARY = "#409EFF"
PRIMARY_HOVER = "#66B1FF"
PRIMARY_ACTIVE = "#3A8EE6"
PRIMARY_LIGHT = "#ECF5FF"
SUCCESS = "#67C23A"
WARNING = "#E6A23C"
DANGER = "#F56C6C"
INFO = "#909399"

TEXT_PRIMARY = "#303133"
TEXT_REGULAR = "#606266"
TEXT_SECONDARY = "#909399"
TEXT_PLACEHOLDER = "#C0C4CC"
BORDER = "#DCDFE6"
BORDER_LIGHT = "#E4E7ED"
BORDER_LIGHTER = "#EBEEF5"
FILL = "#F5F7FA"
WHITE = "#FFFFFF"

QSS = f"""
/* 注意：不要用 * 通配符设字体/颜色——它会让每个控件都参与样式匹配，
   几百个消息控件时明显拖慢渲染。字体统一在 QApplication.setFont 设置。 */
QMainWindow, QDialog {{ background: {FILL}; }}
QWidget {{ color: {TEXT_REGULAR}; }}

/* ---------- 无边框圆角窗口 ---------- */
#WindowCard {{
    background: {FILL};
    border: 1px solid {BORDER_LIGHT};
    border-radius: 14px;
}}
#WindowCard[maximized="true"] {{ border-radius: 0; border: none; }}

#WinBtn, #WinBtnClose {{
    background: transparent; border: none; color: {TEXT_SECONDARY};
    font-size: 13px; border-radius: 6px;
}}
#WinBtn:hover {{ background: #E9ECF2; color: {TEXT_PRIMARY}; }}
#WinBtnClose:hover {{ background: #F56C6C; color: white; }}

/* ---------- 顶栏 ---------- */
#AppBar {{
    background: {WHITE};
    border-bottom: 1px solid {BORDER_LIGHTER};
    border-top-left-radius: 13px; border-top-right-radius: 13px;
}}
#AppLogo {{
    background: {PRIMARY}; color: white; border-radius: 10px;
    font-size: 16px; font-weight: 600;
}}
#AppTitle {{ color: {TEXT_PRIMARY}; font-size: 16px; font-weight: 600; }}
#AppSub {{ color: {TEXT_SECONDARY}; font-size: 12px; }}
#AppVersion {{
    color: {TEXT_SECONDARY}; font-size: 11px;
    background: #F2F3F5; border-radius: 8px; padding: 1px 7px;
}}
#AppBar QLabel {{ background: transparent; }}

/* ---------- 卡片 ---------- */
QFrame#Card {{
    background: {WHITE};
    border: 1px solid {BORDER_LIGHTER};
    border-radius: 12px;
}}
QFrame#Card QLabel {{ background: transparent; }}
#CardHead {{ border-bottom: 1px solid {BORDER_LIGHTER}; background: transparent; }}
#ConvTitle {{ color: {TEXT_PRIMARY}; font-size: 15px; font-weight: 600; }}
#ConvMeta {{ color: {TEXT_SECONDARY}; font-size: 12px; }}
#SectionLabel {{ color: {TEXT_SECONDARY}; font-size: 12px; }}
#CardFoot {{ color: {TEXT_PLACEHOLDER}; font-size: 11px;
    border-top: 1px solid {BORDER_LIGHTER}; background: transparent; }}

/* ---------- 输入 ---------- */
QLineEdit {{
    background: {WHITE}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 7px 12px; color: {TEXT_PRIMARY}; selection-background-color: {PRIMARY_LIGHT};
    selection-color: {PRIMARY};
}}
QLineEdit:hover {{ border-color: #C0C4CC; }}
QLineEdit:focus {{ border-color: {PRIMARY}; }}
QLineEdit:disabled {{ background: {FILL}; color: {TEXT_PLACEHOLDER}; }}

/* ---------- 按钮 ---------- */
QPushButton#Primary {{
    background: {PRIMARY}; color: white; border: none; border-radius: 8px;
    padding: 8px 18px; font-size: 13px;
}}
QPushButton#Primary:hover {{ background: {PRIMARY_HOVER}; }}
QPushButton#Primary:pressed {{ background: {PRIMARY_ACTIVE}; }}
QPushButton#Primary:disabled {{ background: #A0CFFF; color: #F2F6FC; }}

QPushButton#Plain {{
    background: {PRIMARY_LIGHT}; color: {PRIMARY};
    border: 1px solid #B3D8FF; border-radius: 8px; padding: 7px 16px;
}}
QPushButton#Plain:hover {{ background: {PRIMARY}; color: white; }}
QPushButton#Plain:disabled {{ background: {FILL}; border-color: {BORDER_LIGHT};
    color: {TEXT_PLACEHOLDER}; }}

QPushButton#Text {{
    background: transparent; border: none; color: {PRIMARY}; padding: 4px 8px;
}}
QPushButton#Text:hover {{ color: {PRIMARY_HOVER}; }}

QPushButton#Chip {{
    background: {WHITE}; border: 1px solid {BORDER}; border-radius: 16px;
    padding: 5px 16px; color: {TEXT_REGULAR}; font-size: 12px;
}}
QPushButton#Chip:hover {{ border-color: #C6E2FF; color: {PRIMARY}; }}
QPushButton#Chip:checked {{
    background: {PRIMARY}; border-color: {PRIMARY}; color: white;
}}

/* ---------- 列表 ---------- */
QListWidget {{ background: transparent; border: none; outline: none; }}
QListWidget#ConvList::item {{
    border-radius: 10px; margin: 3px 8px;
}}
QListWidget#ConvList::item:hover {{ background: {FILL}; }}
QListWidget#ConvList::item:selected {{ background: {PRIMARY_LIGHT}; }}
QListWidget#ImgList::item {{
    background: {WHITE}; border: 1px solid {BORDER_LIGHTER}; border-radius: 4px;
    color: {TEXT_SECONDARY};
}}
QListWidget#ImgList::item:hover {{ border-color: #C6E2FF; }}
QListWidget#ImgList::item:selected {{ border-color: {PRIMARY}; }}

/* ---------- 下拉框 ---------- */
QComboBox {{
    background: {WHITE}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 6px 10px; color: {TEXT_REGULAR}; min-width: 84px;
}}
QComboBox:hover {{ border-color: #C0C4CC; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    border: 1px solid {BORDER_LIGHT}; border-radius: 8px; background: {WHITE};
    selection-background-color: {PRIMARY_LIGHT}; selection-color: {PRIMARY};
    outline: none; padding: 4px;
}}

/* ---------- 滚动条 ---------- */
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #C0C4CC; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {INFO}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #C0C4CC; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* ---------- 聊天内容（用类级选择器，避免每条消息 setStyleSheet 造成样式重算） ---------- */
QLabel#Bubble {{
    background: #F4F4F5; color: #303133;
    border: 1px solid {BORDER_LIGHTER}; border-radius: 12px;
    padding: 9px 12px; font-size: 14px;
}}
QLabel#Bubble[me="true"] {{
    background: {PRIMARY}; color: #FFFFFF; border: 1px solid {PRIMARY};
}}
QLabel#Sender {{ color: {TEXT_SECONDARY}; font-size: 11px; background: transparent; }}
QLabel#DaySep {{ color: {TEXT_SECONDARY}; font-size: 11px; padding: 12px 0 6px; background: transparent; }}
QLabel#TimeSep {{ color: {TEXT_PLACEHOLDER}; font-size: 11px; padding: 6px 0 2px; background: transparent; }}
QLabel#SystemRow {{
    color: {INFO}; font-size: 11px; background: #F4F4F5;
    border-radius: 10px; padding: 4px 12px;
}}
QLabel#ImgBubble {{
    border: 1px solid {BORDER_LIGHTER}; border-radius: 10px; background: #FFFFFF;
}}

/* ---------- 弹窗 ---------- */
QDialog#Setup {{ background: transparent; }}
#SetupTitle {{ color: {TEXT_PRIMARY}; font-size: 17px; font-weight: 600; }}
#SetupSub {{ color: {TEXT_SECONDARY}; font-size: 12px; }}
#SetupHint {{ color: {TEXT_SECONDARY}; font-size: 12px; }}
QCheckBox {{ color: {TEXT_REGULAR}; spacing: 6px; }}
QCheckBox::indicator {{
    width: 15px; height: 15px; border: 1px solid {BORDER}; border-radius: 5px;
    background: {WHITE};
}}
QCheckBox::indicator:checked {{
    background: {PRIMARY}; border-color: {PRIMARY};
    image: url("{CHECK_ICON}");
}}

#ProgArea {{ background: #FAFBFC; border-top: 1px solid {BORDER_LIGHTER}; }}
#ProgArea QLabel {{ background: transparent; }}
QProgressBar {{
    border: 1px solid {BORDER_LIGHT}; border-radius: 8px; background: {FILL};
    text-align: center; color: {TEXT_REGULAR}; height: 16px;
}}
QProgressBar::chunk {{ background: {PRIMARY}; border-radius: 6px; }}

QToolTip {{
    background: {TEXT_PRIMARY}; color: white; border: none; padding: 6px 10px;
    border-radius: 8px;
}}
"""


def add_shadow(widget: QWidget, blur: int = 16, dy: int = 2, alpha: int = 22) -> None:
    """Element 卡片式阴影。"""
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setOffset(0, dy)
    eff.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(eff)
