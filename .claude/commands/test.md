---
description: 运行单元测试并总结结果
allowed-tools: Bash(.venv-pyside/Scripts/python -m pytest:*)
---

1. 运行 `.\.venv-pyside\Scripts\python -m pytest`
2. 若有失败：先判断是测试用例问题还是代码回归，修复后重跑
3. 汇报：通过数 / 失败项 / 修复点
