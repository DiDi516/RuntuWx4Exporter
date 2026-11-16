"""PyInstaller 打包入口：wx4desk（PySide6 桌面版）。"""
import sys

from wx4app.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
