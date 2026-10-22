#!/usr/bin/env python3
"""AI 作曲工作进程：提示词原样交给 MusicGen-small，生成 4 或 8 秒的音乐（模型 CC-BY-NC 4.0，仅限非商业用途）。

由播放器以子进程方式调用，也可以直接在命令行使用：
  .venv/bin/python ai/generate_worker.py --prompt "calm lo-fi piano, rainy night" --seconds 8 --output /tmp/bgm

输出：<out>/bgm.wav（44.1 kHz 立体声 16-bit，结尾自然淡出）与 meta.json
进度以 JSON 行写到 stdout：{"event": "progress", "stage": "...", "progress": 0.42}
MusicGen 的文本编码器只理解英文：描述含中文时，先用本地 Qwen2.5-Instruct 翻译成英文提示词（ai/translate.py），
翻译模型用完即释放，再加载 MusicGen，两者内存不叠加。界面预览过的译文可通过 --english 直接传入，保证“所见即所得”。
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import random
import sys
import time
import wave
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

SECONDS_CHOICES = (4, 8)


def emit(event: str, **payload) -> None:
    sys.stdout.write(json.dumps({"event": event, **payload}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def write_wav(path: Path, data) -> None:
    import numpy as np

    pcm = (np.clip(data.T, -1.0, 1.0) * 32767.0).astype("<i2")
    tmp = path.with_suffix(".tmp")
    with wave.open(str(tmp), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(44100)
        handle.writeframes(pcm.tobytes())
    os.replace(tmp, path)


def summary(seconds: int) -> str:
    return f"{seconds} 秒"


def translate_prompt(prompt: str, args) -> tuple[str, float | None]:
    """含中文的描述翻译成英文；返回 (英文提示词, 翻译用时；未翻译为 None)。"""
    import translate

    if not translate.has_chinese(prompt):
        return prompt, None
    if args.english and not translate.has_chinese(args.english):
        return args.english.strip(), 0.0
    model_dir = Path(args.translate_model_dir) if args.translate_model_dir else (
        translate.find_model_dir(APP_DIR / "models", "1.5b") or translate.find_model_dir(APP_DIR / "models", "0.5b"))
    if not model_dir:
        raise FileNotFoundError("中文描述需要翻译模型（运行 scripts/setup-translate.sh），或直接用英文描述")
    emit("progress", stage="translate", progress=0.03)
    started = time.time()
    translator = translate.Translator(model_dir, threads=args.threads, low_memory=args.translate_low_mem)
    result = translator.translate(prompt)
    del translator                      # 先释放翻译模型，再加载 MusicGen，内存不叠加
    gc.collect()
    emit("progress", stage="translate", progress=0.12, english=result["text"])
    if not result["text"]:
        raise RuntimeError("翻译结果为空，请换一种说法或直接用英文描述")
    return result["text"], round(time.time() - started, 3)     # 含模型加载


def main() -> int:
    parser = argparse.ArgumentParser(description="用 MusicGen 根据提示词生成一段无歌词音乐")
    parser.add_argument("--prompt", required=True, help="音乐描述（英文效果最好），原样交给模型")
    parser.add_argument("--seconds", type=int, choices=SECONDS_CHOICES, default=8)
    parser.add_argument("--seed", type=int, help="随机种子（默认随机）")
    parser.add_argument("--output", required=True, help="输出目录")
    parser.add_argument("--model-dir", help="模型目录（默认 models/musicgen-small-onnx）")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--low-mem", default="", help="低内存模式：prepack,arena,basic 中的若干项（4GB 内存设备用）")
    parser.add_argument("--english", help="已翻译好的英文提示词（界面预览的结果，跳过翻译）")
    parser.add_argument("--translate-low-mem", action="store_true",
                        help="翻译模型关闭内存池（省约 100MB，开发板上慢约 2.3 倍；默认不开）")
    parser.add_argument("--translate-model-dir", help="中文翻译模型目录（默认按大小自动查找 models/qwen2.5-*-instruct-onnx）")
    args = parser.parse_args()

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    prompt = args.prompt.strip()
    seed = args.seed if args.seed is not None else random.randrange(1, 2 ** 31)
    started = time.time()
    try:
        emit("progress", stage="load", progress=0.01, summary=summary(args.seconds))
        import musicgen

        model_dir = Path(args.model_dir) if args.model_dir else musicgen.find_model_dir(APP_DIR / "models")
        if not model_dir or not (Path(model_dir) / "tokenizer.json").is_file():
            raise FileNotFoundError("未找到 AI 作曲模型（运行 scripts/setup-musicgen.sh）")
        english, translate_seconds = translate_prompt(prompt, args)
        done = generate_to_dir(prompt, english, args.seconds, seed, out_dir, model_dir=model_dir, threads=args.threads,
                               low_memory=args.low_mem or False, translate_seconds=translate_seconds,
                               offset=0.12 if translate_seconds is not None else 0.0, started=started,
                               progress=lambda stage, value: emit("progress", stage=stage, progress=value))
        emit("done", **done)
        return 0
    except Exception as error:  # noqa: BLE001
        emit("error", message=error_message(error))
        return 1


def error_message(error: Exception) -> str:
    return str(error) if isinstance(error, (FileNotFoundError, InterruptedError)) else f"{type(error).__name__}: {error}"


def generate_to_dir(prompt: str, english: str, seconds: int, seed: int, out_dir: Path, *, model=None, model_dir=None,
                    threads: int = 4, low_memory: bool | str = False, translate_seconds: float | None = None,
                    offset: float = 0.0, started: float | None = None, progress=None, should_stop=None) -> dict:
    """英文提示词 → MusicGen → out_dir/bgm.wav + meta.json，返回 done 事件内容。
    命令行（每次加载模型）与常驻进程（model 为已加载的模型）共用；失败时删除不完整的输出并重新抛出异常。
    progress(stage, 0~1)：已按 offset 换算到整个任务的进度（offset 之前是翻译）。"""
    import musicgen

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = started or time.time()
    report = progress or (lambda stage, value: None)
    try:
        audio, stats = musicgen.generate_bgm(
            english, seconds, seed, model_dir, threads=threads, low_memory=low_memory, model=model,
            should_stop=should_stop,
            progress=lambda stage, value: report(stage, round(offset + (1 - offset) * value, 3)))
        report("write", 0.97)
        write_wav(out_dir / "bgm.wav", audio)
        meta = {
            "engine": "musicgen",
            "prompt": prompt,
            "prompt_en": english,
            "translate_seconds": translate_seconds,
            "summary": summary(seconds),
            "duration": seconds,
            "seed": seed,
            **stats,
            "elapsed": round(time.time() - started, 3),
            "created_at": time.time(),
        }
        (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
    except BaseException:
        for name in ("bgm.wav", "bgm.tmp", "meta.json"):
            (out_dir / name).unlink(missing_ok=True)
        raise
    return {"path": str(out_dir / "bgm.wav"), "summary": meta["summary"], "seconds": stats["seconds"],
            "elapsed": meta["elapsed"], "seed": seed, "prompt_en": english, "duration": seconds,
            "translate_seconds": translate_seconds or 0.0, "load_seconds": stats["musicgen"]["load_seconds"]}


if __name__ == "__main__":
    sys.exit(main())
