# 安全与隐私说明

## 工具会接触什么数据

| 数据 | 用途 | 存放位置 |
|---|---|---|
| 数据库密钥 | 解密微信 4.x 本地库 | `%LOCALAPPDATA%\wx4export\keys.json` |
| 解密后的数据库 | 查询会话/消息 | `%LOCALAPPDATA%\wx4export\db_*\` |
| 图片/头像缓存 | 渲染与导出 | `%LOCALAPPDATA%\wx4export\img\` |
| 应用配置 | 记住账号与导出目录 | `%LOCALAPPDATA%\wx4app\config.json` |
| 导出结果 | 用户主动导出 | 用户选择的目录 |

以上全部留在本机，**不联网、不上传**。网页版仅监听 `127.0.0.1`。

## 使用边界

- 仅用于导出**本人账号**的数据；
- 不要将本工具用于获取他人隐私或绕过他人设备权限；
- 导出的数据可能包含敏感信息，分享前请自行脱敏。

## 报告问题

发现安全问题时请勿公开提交 issue，可通过 GitHub 私信维护者。

## 清理痕迹

```powershell
# 删除密钥缓存与解密库（不影响微信本身）
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\wx4export"
# 删除应用配置
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\wx4app"
```
