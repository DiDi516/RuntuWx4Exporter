---
description: 打包 Windows 单文件 exe（含资源与图标）
allowed-tools: Bash(.venv-pyside/Scripts/python -m PyInstaller:*), Bash(.venv-pyside/Scripts/python -c:*), Read
---

按 `docs/BUILD.md` 执行打包：

1. 先确认 `wx4app/assets/logo.png` 与 `logo.ico` 存在
2. 用**绝对路径**传 `--icon` 与 `--add-data`（相对路径会因 `--specpath` 解析失败）
3. 输出到 `dist2`，成功后用 `os.replace` 覆盖 `dist\闰土微信记录导出器.exe`
   （本机安全策略会拦截直接删除 exe）
4. 打包完成后跑一次 `python -c "import os;print(os.path.getsize(...))"` 确认体积
5. 提醒用户：EXE 未签名，首次运行 Windows 可能提示「未知发布者」
