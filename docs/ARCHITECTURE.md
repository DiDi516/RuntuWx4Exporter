# 架构说明

## 1. 分层

```
┌──────────────────────────── UI 层 ────────────────────────────┐
│  wx4app (PySide6)  ← 唯一应用入口（打包为 exe）                │
└───────────────────────────────┬───────────────────────────────┘
                                │ 只调用 LiveSource，不直接读 DB
┌──────────────────────────── 数据层 ───────────────────────────┐
│  wx4view.live.LiveSource                                      │
│   sessions / messages / images / files / export_*             │
└───────────────────────────────┬───────────────────────────────┘
┌──────────────────────────── 基础层 ───────────────────────────┐
│  wxmanager.wx4keys  取密钥、解密 db → %LOCALAPPDATA%           │
│  wxmanager.wx4      账号目录、图片类型判断                     │
│  wx4export.core     历史 CLI 导出实现（复用其解码/图片工具）    │
└───────────────────────────────┬───────────────────────────────┘
                                │
                       微信 4.x 本地文件
```

## 2. 微信 4.x 数据要点

| 位置 | 内容 |
|---|---|
| `db_storage/contact/contact.db` | 联系人（`username/remark/nick_name`） |
| `db_storage/session/session.db` | `SessionTable`（会话、最后一条摘要、时间） |
| `db_storage/message/message_N.db` | 消息分库，每个会话一张 `Msg_<md5(username)>` |
| `db_storage/head_image/head_image.db` | 头像（`username → JPEG`） |
| `msg/attach/<md5>/<YYYY-MM>/Img` | 图片/视频缩略（`.dat` 加密） |
| `msg/file/<YYYY-MM>/` | 聊天文件（原文件名） |

消息表关键列：`local_id, server_id, local_type, create_time, real_sender_id, message_content, packed_info_data`。

- `local_type & 0xFFFFFFFF` 是基础类型（1 文本 / 3 图片 / 34 语音 / 43 视频 / 49 应用消息 / 10000 系统）。
- `local_type >> 32` 是子类型（49 且子类型 6 = 文件）。
- **`Name2Id` 是分库独立的**：同一个 `real_sender_id` 在不同 `message_N.db` 里可能指向不同人，
  解析必须使用「该行所在库」的映射。
- `message_content` 可能是 zstd 压缩（以 `28 b5 2f fd` 开头）。

## 3. LiveSource 设计

```python
sessions()            # SessionTable + contact.db 名称，按最后消息时间排序
messages(uid, limit, before)   # SQL: WHERE create_time < ? ORDER BY create_time DESC LIMIT ?
images(uid)           # WHERE (local_type & 0xFFFFFFFF)=3
export_images(...)    # 时间范围 + layout(date|flat)，返回 md5 → 相对路径
export_files(...)     # 同上，按 名称/(1)后缀/大小 匹配本地文件
export_chat(...)      # txt + html(带头像/图片/文件卡片) + messages.json
export_all(...)       # 全量导出 + zip（可取消）
```

要点：

1. **分页而非整表**：只 `LIMIT limit+1` 取当页，`has_more` 用是否多取到一条判断。
2. **计数走聚合 SQL**：`count/min/max/sum(case when type=3)`，不进 Python 循环。
3. **图片/文件按需解密/复制**：图片缓存到 `%LOCALAPPDATA%\wx4export\img\<md5>.<ext>`。
4. **线程安全**：`_cache_lock` 保护缓存；`zstd.ZstdDecompressor()` 每线程新建（C 扩展非线程安全）。
5. **头像转 base64 一次**：HTML 用 CSS 类去重，577 条记录 99 KB（逐条内嵌会到 6.8 MB）。

## 4. UI 线程模型

- 主线程：只做控件创建/绘制。
- `MessagesWorker(QThread)`：调用 `LiveSource.messages`，完成后 emit 回主线程渲染。
- `ExportWorker` / `ExportAllWorker`：导出与 zip，进度通过 signal 上报到进度条。
- 线程对象用 `self._msg_workers` 列表持有，`finished` 时移除；窗口退出等待所有线程（`_shutdown`）。

## 5. 渲染性能

| 手段 | 说明 |
|---|---|
| `QStyledItemDelegate` | 会话列表只画可见行，避免上百个 widget |
| 条目复用 | 列表只建一次，筛选改 `setHidden` |
| 类级 QSS | 气泡用 `objectName` + 属性选择器，避免每条消息 `setStyleSheet` |
| 图片按目标解码 | `QImageReader.setScaledSize`，避免全图解码后缩放 |
| 图片异步填充 | 先用图片头尺寸占位，`QTimer` 批量解码回填 |
| `setUpdatesEnabled(False)` | 批量插入控件时冻结重绘 |

## 6. 扩展点

- **新增导出格式**：在 `LiveSource` 加 `export_xxx()`，UI 侧在 `export_dialog` 加选项即可。
- **新增消息类型**：`_kind_of` 增加映射；`MessageRow` 增加渲染分支。
- **换 UI 框架**：只要复用 `LiveSource`，即可替换 `wx4app`。
- 本版本只包含桌面版；`wx4export/core.py` 只作为解码/图片工具库被桌面端复用。
