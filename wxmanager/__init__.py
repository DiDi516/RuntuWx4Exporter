"""wxmanager - 微信聊天记录管理器（个人数据备份/导出/检索/统计）。

仅处理本机已合法获取的微信数据，子模块：
- dat_decrypt : 微信 PC 端 .dat 加密图片批量解密导出
- chat_db     : 聊天记录数据库/JSON/CSV 读取与联系人解析
- exporter    : 会话导出 (txt / md / csv / json / html)
- search      : 全文检索（关键词/正则/时间/联系人/类型过滤）
- stats       : 聊天统计分析与年度报告
- privacy     : 导出脱敏（手机号/身份证/邮箱/卡号打码）
- merge       : 多数据库合并去重
- backup      : 增量备份
"""
__version__ = "0.1.0"
