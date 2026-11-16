---
description: 启动桌面版并做一次冒烟验证
allowed-tools: Bash(.venv-pyside/Scripts/python -m wx4app:*), Bash(.venv-pyside/Scripts/python -c:*)
---

1. 先跑 `.\.venv-pyside\Scripts\python -m pytest` 保证基础健康
2. 启动 `.\.venv-pyside\Scripts\python -m wx4app`（GUI，注意不要在前台阻塞太久）
3. 无头验证可用 `QT_QPA_PLATFORM=offscreen` 跑一次 import 冒烟，
   或直接用 `win.grab().save(...)` 抓图（见 git 历史中的截图脚本思路）
4. 汇报启动耗时与关键界面是否正常
