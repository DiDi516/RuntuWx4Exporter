# CLAUDE.md

本文件是给 Claude Code 的项目说明书。**动代码前先读这里**，能避免 90% 的重复踩坑。

## 1. 项目是什么

**闰土微信记录导出器（RuntuWx4Exporter）**：只读本机微信 4.x（Weixin.exe）数据库，
在本地查看聊天记录，并把记录 / 图片 / 文件导出成可归档的格式。

> 仓库**只保留桌面版（`wx4app`）**：网页版与命令行导出器不在本版本范围内。
> `wx4view.live` 是桌面端的数据层，`wx4export.core` 只提供解码/图片工具，两者都不要当成独立应用。

## 2. 快速命令

```powershell
# 环境（独立 venv，勿装到系统 Python）
python -m venv .venv-pyside
.\.venv-pyside\Scripts\python -m pip install -r requirements-dev.txt

# 运行
.\.venv-pyside\Scripts\python -m wx4app               # 桌面版
.\.venv-pyside\Scripts\python -m wx4app --files-only  # 只看已导出目录

# 质量
.\scripts\lint.ps1          # ruff check
.\scripts\test.ps1          # pytest

# 打包
.\scripts\build.ps1         # -> dist\闰土微信记录导出器.exe
```

## 3. 架构与数据流

```
微信进程内存 ──(wxmanager.wx4keys)──► %LOCALAPPDATA%\wx4export\keys.json
      │
      ▼
db_storage/*.db ──(AES 解密)──► %LOCALAPPDATA%\wx4export\db_*
      │
      ▼
wx4view.live.LiveSource            ← 唯一数据源（桌面端不得绕过）
  ├─ sessions()                    会话列表（SessionTable + contact.db）
  ├─ messages(分页)                Msg_<md5(wxid)>，SQL LIMIT + before 游标
  ├─ images()/image_path           图片按 md5 解密，磁盘缓存
  ├─ export_images / export_files  支持时间范围 + layout(date|flat)
  ├─ export_chat                   txt + html(头像/图片/文件卡片) + json
  └─ export_all                    全部会话 + zip（可取消）
      │
      ▼
wx4app（PySide6）：QThread 调 LiveSource，主线程只渲染
```

关键点：
- **`LiveSource` 是线程安全的**：`_parse_rows` 每次新建 `zstd.ZstdDecompressor()`（C 扩展非线程安全），
  缓存读写走 `self._cache_lock`。
- **消息表名 = `Msg_` + md5(会话 username)**，分散在多个 `message_N.db` 分库里，
  发送者必须用**该库自己的 Name2Id**（不同库 rowid 会撞车）。
- 头像按 **wxid** 查 `head_image.db`，**不是昵称**；消息里的 `_uid` 就是 wxid。
- **配置**：`config.ini` 放在**应用目录**（打包后 = exe 同级；不可写则回退 `%LOCALAPPDATA%\wx4app`）。
  结构：`[general]` account_dir / workspace / export_dir / export_layout；
  `[logging]` enabled / dir / retention_days / level。旧 `config.json` 会自动迁移账号与布局。
- **工作空间**：`<应用目录>/workspace`，是导出默认目录；「设置」页可改。
- **日志**：`logging_setup.setup_logging()` 用 `TimedRotatingFileHandler` 按天滚动，
  `backupCount = retention_days`（默认 30）；默认 `<应用目录>/logs/app.log`，
  崩溃日志 `crash.log`（faulthandler）同目录。改配置后需重新调用 `setup_logging()`。
- 模块依赖链：`wx4app → wx4view.live → wx4export.core → wxmanager.wx4 / wx4keys`。
  删掉任何一层，exe 都打不开。

## 4. 代码约定

- Python ≥ 3.11，全部 `from __future__ import annotations` + 类型标注。
- 行宽 100，`ruff` 零告警（CI 会跑）；`E501` 已忽略。
- 纯函数（命名 / 大小 / 日期）放 `wx4view/naming.py`，**必须**可单测。
- UI 文案统一中文；变量/函数英文。不轻易加依赖，需加时说明理由与体积影响。
- Qt 规则：
  - 耗时操作（解析消息、导出、解密）→ `QThread`；主线程只渲染。
  - 线程对象必须被持有（`self._msg_workers` 列表），`finished` 后移除（否则段错误）。
  - 不要对每条消息 `setStyleSheet`，用 `objectName` + 类级 QSS。
  - 列表用 `QStyledItemDelegate`，不要 `setItemWidget` 造几百个控件。
  - 图片用 `QImageReader.setScaledSize` 按目标尺寸解码。

## 5. 测试

- `tests/test_naming.py`：安全目录名、大小格式、文件名归一化（含 `(1)` 后缀）。
- `tests/test_config.py`：微信目录归一化（账号目录 / db_storage / xwechat_files 根）。
- 新增纯逻辑 → 必须补测试；涉及文件系统用 `tmp_path`，不要依赖真实微信目录。
- CI（`.github/workflows/ci.yml`）只装 ruff + pytest，不装 PySide6，因此测试不得 import Qt。

## 6. 发布流程

1. `.\scripts\lint.ps1` + `.\scripts\test.ps1` 全绿
2. 改 `pyproject.toml` 版本号 + 更新 `CHANGELOG.md`
3. `.\scripts\build.ps1` 打包（内部已处理绝对路径与原子替换）
4. `git commit -m "feat(app): ..."`（Conventional Commits）
5. `git tag vX.Y.Z && git push --tags`

## 7. 已知坑（踩过就别再踩）

| 现象 | 原因 | 处理 |
|---|---|---|
| 聊天里全是首字头像 | 用昵称查头像 | 改用 `m["_uid"]`（wxid） |
| 切换会话有残影 | `takeAt` 只移出布局 | 先 `setParent(None)` 再 `deleteLater` |
| 气泡背景全白 | 父控件裸样式表级联 | 用 `#ObjectName{...}` 限定选择器 |
| 偶发 segfault | QThread 被覆盖 / zstd 共用 | 列表持有线程；每线程新建解压器 |
| 自动检测选错账号 | 按 `db_storage` 目录 mtime | 改按 `message_*.db` 最新写入时间 |
| exe 打包后资源丢失 | `--add-data` 相对路径 | 绝对路径 + `_MEIPASS` |
| 覆盖 exe 失败 | 本机 safe-delete 拦截 | 打到 `dist2` 再 `os.replace` |
| 点导出没反应 | 目录选择被取消 | 先弹目录选择，取消即中止 |

## 8. 与 Claude 协作的方式

- 常用命令已固化为 `/lint`、`/test`、`/build`、`/run`（见 `.claude/commands/`）。
- 需要严格审查时用 `code-reviewer` 子代理（`.claude/agents/`），它只读不改。
- 改 UI 前先看 `docs/images/` 截图，保持 Element 风格与圆角规范。
- 不确定微信表结构时，先写临时脚本打印 3 行样本再改代码；临时脚本不要提交。
- 不要提交 `微信导出/`、`*.db`、`keys.json` 或任何真实聊天截图。
