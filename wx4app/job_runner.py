"""导出子进程执行器。

把导出放到独立进程里执行，优点：
1. 完全不阻塞 UI（Qt 事件循环只负责画进度）；
2. 彻底隔离 SQLite/解码库与 Qt 的线程问题（曾导致 access violation）。
父进程通过 stdout 的 JSON 行获取进度，最后一行是结果。
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

_PROGRESS_PATH: str | None = None


def _emit(payload: dict) -> None:
    """把 JSON 行写到进度文件（windowed 的 exe 没有可用的 stdout）。"""
    line = json.dumps(payload, ensure_ascii=False)
    if _PROGRESS_PATH:
        try:
            with open(_PROGRESS_PATH, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            return
        except OSError:
            pass
    print(line, flush=True)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        _emit({"ok": False, "error": "缺少任务文件参数"})
        return 2

    spec_path = Path(argv[0])
    global _PROGRESS_PATH
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        _PROGRESS_PATH = spec.get("progress_path")
    except (OSError, ValueError) as exc:
        _emit({"ok": False, "error": f"读取任务失败: {exc}"})
        return 2

    try:
        from wx4view.live import LiveSource

        src = LiveSource(spec.get("account"))
        out = Path(spec["out_root"])
        start_ts = int(spec.get("start_ts") or 0)
        end_ts = int(spec.get("end_ts") or 0)
        layout = spec.get("layout") or "date"
        kind = spec.get("kind", "chat")

        def progress(i: int, t: int, label: str = "") -> None:
            _emit({"p": i, "t": t, "label": label})

        if kind == "chat":
            cid = spec["cid"]
            res: dict = {"count": 0, "images": 0, "files": 0, "dir": str(out)}
            img_map: dict = {}
            file_map: dict = {}
            if spec.get("do_images"):
                r = src.export_images(cid, out, progress=lambda i, t: progress(i, t, "图片"),
                                      start_ts=start_ts, end_ts=end_ts, layout=layout)
                img_map = r.get("files") or {}
                res.update({k: v for k, v in r.items() if k != "files"})
                res["images"] = r.get("count", 0)
                res["missing"] = r.get("missing", 0)
            if spec.get("do_files"):
                r = src.export_files(cid, out, progress=lambda i, t: progress(i, t, "文件"),
                                     start_ts=start_ts, end_ts=end_ts, layout=layout)
                file_map = r.get("files") or {}
                res["files"] = r.get("count", 0)
                res["missing_files"] = r.get("missing", 0)
            if spec.get("do_chat"):
                c = src.export_chat(cid, out, start_ts, end_ts,
                                    images_map=img_map, files_map=file_map)
                res["count"] = c.get("count", 0)
                res["dir"] = c.get("dir", res["dir"])
            _emit({"ok": True, "result": res})
            return 0

        # kind == "all"
        r = src.export_all(
            out,
            include_images=bool(spec.get("do_images")),
            include_files=bool(spec.get("do_files")),
            start_ts=start_ts, end_ts=end_ts, layout=layout,
            progress=lambda i, t, name: progress(i, t, name))
        r.pop("files", None) if not isinstance(r.get("files"), int) else None
        _emit({"ok": True, "result": r})
        return 0

    except Exception as exc:  # noqa: BLE001
        _emit({"ok": False, "error": f"{type(exc).__name__}: {exc}",
               "trace": traceback.format_exc()[-2000:]})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
