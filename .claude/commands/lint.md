---
description: 运行 ruff 静态检查（自动修复可修问题）
allowed-tools: Bash(.venv-pyside/Scripts/python -m ruff check:*), Bash(.venv-pyside/Scripts/python -m ruff format:*)
---

1. 运行 `.\.venv-pyside\Scripts\python -m ruff check . --fix`
2. 若仍有告警，逐条修复（不要用 `# noqa` 掩盖，除非是 Qt 不可避免的写法）
3. 再跑一次 `ruff check .` 确认零告警
4. 把修了什么用一句话汇报给用户
