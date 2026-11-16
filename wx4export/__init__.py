"""wx4export - 微信 4.x 定向导出（输入群名/昵称 → 聊天记录 + 全部图片）

用法::

    python -m wx4export --name "Alex" --out "D:/导出"
    python -m wx4export --list                 # 只列出可导出的会话
    python -m wx4export --name "项目群" --account "E:/.../wxid_xxx_d04f"

图片按 图片/年/月/日/时间_哈希.jpg 存放，聊天记录同时导出 txt 与 html。
"""
__version__ = "1.0.0"
