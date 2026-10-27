#!/usr/bin/env python3
"""常驻模型进程：只加载一次翻译模型或 MusicGen，之后按请求反复使用，省去每次 8–16 秒的模型加载。

由播放器启动（wavemusic/warm.py），也可以手动调试：
  python ai/model_server.py translate --model-dir models/qwen2.5-0.5b-instruct-onnx [--threads 4] [--low-mem]
  python ai/model_server.py musicgen  --model-dir models/musicgen-small-onnx [--threads 4] [--low-mem arena]

协议：stdin 每行一个 JSON 请求，stdout 每行一个 JSON 事件。
  启动    → {"event": "ready", "load_seconds": 8.1, "pid": 123}；加载失败 → {"event": "fatal", "message": ...} 并退出
  {"id": 1, "cmd": "translate", "text": "下雨天，钢琴"}
          → {"id": 1, "event": "done", "text": "rainy day, piano", "seconds": 17.2}
  {"id": 2, "cmd": "generate", "prompt": "原始描述", "english": "rainy day, piano", "seconds": 4, "seed": 7,
   "output": "/目录", "translate_seconds": 0, "offset": 0.12, "started": 1700000000.0}
          → {"id": 2, "event": "progress", "stage": "generate", "progress": 0.4} …
          → {"id": 2, "event": "done", "path": ".../bgm.wav", ...}（与 generate_worker 的 done 相同）
  失败    → {"id": …, "event": "error", "message": ...}；取消 → {"id": …, "event": "cancelled"}
  {"cmd": "cancel"}  立即取消正在处理的请求（由读取线程处理，不排队）
请求按顺序逐个处理。stdin 关闭（播放器退出或崩溃）时立即退出，不会留下占用内存的孤儿进程。
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

_out_lock = threading.Lock()


def send(**payload) -> None:
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    with _out_lock:
        sys.stdout.write(line)
        sys.stdout.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description="常驻模型进程（翻译 / MusicGen）")
    parser.add_argument("kind", choices=["translate", "musicgen"])
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--low-mem", nargs="?", const="1", default="",
                        help="translate：开关；musicgen：prepack,arena,basic 中的若干项")
    args = parser.parse_args()

    requests: queue.Queue = queue.Queue()
    cancel = threading.Event()

    def reader():
        for line in sys.stdin:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if message.get("cmd") == "cancel":
                cancel.set()
            else:
                requests.put(message)
        os._exit(0)          # stdin 关闭：播放器已退出

    threading.Thread(target=reader, name="stdin", daemon=True).start()

    started = time.time()
    try:
        if args.kind == "translate":
            import translate
            model = translate.Translator(args.model_dir, threads=args.threads, low_memory=bool(args.low_mem))
        else:
            import musicgen
            model = musicgen.MusicGen(args.model_dir, threads=args.threads, low_memory=args.low_mem or False)
    except Exception as error:  # noqa: BLE001
        send(event="fatal", message=f"模型加载失败：{type(error).__name__}: {error}")
        return 1
    send(event="ready", load_seconds=round(time.time() - started, 3), pid=os.getpid())

    import generate_worker

    while True:
        request = requests.get()
        rid = request.get("id")
        cancel.clear()
        try:
            if request.get("cmd") == "translate" and args.kind == "translate":
                result = model.translate(str(request.get("text") or ""), should_stop=cancel.is_set)
                send(id=rid, event="done", **result)
            elif request.get("cmd") == "generate" and args.kind == "musicgen":
                done = generate_worker.generate_to_dir(
                    request.get("prompt") or request["english"], request["english"], int(request["seconds"]),
                    int(request["seed"]), Path(request["output"]), model=model, threads=args.threads,
                    low_memory=args.low_mem or False, translate_seconds=request.get("translate_seconds"),
                    offset=float(request.get("offset") or 0.0), started=request.get("started"),
                    should_stop=cancel.is_set,
                    progress=lambda stage, value: send(id=rid, event="progress", stage=stage, progress=value))
                send(id=rid, event="done", **done)
            else:
                send(id=rid, event="error", message=f"不支持的请求：{request.get('cmd')}（{args.kind} 进程）")
        except InterruptedError:
            send(id=rid, event="cancelled")
        except Exception as error:  # noqa: BLE001
            send(id=rid, event="error", message=generate_worker.error_message(error))


if __name__ == "__main__":
    sys.exit(main())
