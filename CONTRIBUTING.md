# 贡献指南

## 开发环境

```powershell
python -m venv .venv-pyside
.\.venv-pyside\Scripts\python -m pip install -r requirements-dev.txt
```

## 提交前自检

```powershell
.\.venv-pyside\Scripts\python -m ruff check .
.\.venv-pyside\Scripts\python -m pytest
```

## 分支与提交

- 分支：`main` 保护，功能分支 `feat/xxx`、修复 `fix/xxx`。
- 提交信息用 [Conventional Commits](https://www.conventionalcommits.org/)：
  `feat(app): 支持按类型筛选`、`fix(export): 修正平铺文件名冲突`、`docs: 补充构建说明`。
- 一个提交只做一件事；不要混入格式化全文件的 diff。

## 代码风格

- 4 空格缩进，行宽 100（`ruff` 强制）。
- 公共函数写 docstring（中文即可），复杂分支加简短注释解释「为什么」。
- 纯逻辑抽到 `wx4view/naming.py` 之类可测模块，不要直接写进 Qt 槽函数。
- 新增依赖需在 PR 描述里说明用途与体积影响。

## 测试

- 新增纯函数 → 在 `tests/` 补参数化测试。
- 涉及文件系统的逻辑用 `tmp_path`，不要依赖本机微信目录。

## 不要做的事

- 不要提交任何个人聊天数据、数据库、密钥、导出目录。
- 不要在 UI 线程做数据库查询或图片解码。
- 不要为了让代码「看起来统一」而重排整个文件。