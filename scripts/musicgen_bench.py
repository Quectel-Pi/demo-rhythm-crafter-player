#!/usr/bin/env python3
"""MusicGen 推理基准：速度、内存峰值（本机与开发板通用，每次一个独立进程，内存统计才准确）。

  .venv/bin/python scripts/musicgen_bench.py --decoder int8 --threads 4 --seconds 4
  .venv/bin/python scripts/musicgen_bench.py --decoder q4 --threads 4 --seconds 4 --low-mem
  .venv/bin/python scripts/musicgen_bench.py --save /tmp/out.wav --prompt "calm piano"

输出一行 JSON：加载 / 文本编码 / 解码 / EnCodec 用时，步数/秒，实时率（RTF），内存峰值。
"""
from __future__ import annotations

import argparse
import json
import resource
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ai"))

import numpy as np  # noqa: E402

import musicgen  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", default=str(ROOT / "models" / musicgen.MODEL_NAME))
    parser.add_argument("--decoder", choices=["int8", "q4"], default="int8")
    parser.add_argument("--text-encoder", choices=["int8", "fp32"], default="int8")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--seconds", type=float, default=4)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--low-mem", nargs="?", const=True, default=False,
                        help="低内存模式：不带值 = 全部（prepack,arena,basic）；或指定其中几项，如 --low-mem prepack,arena")
    parser.add_argument("--prompt", default="calm lo-fi piano melody, soft drums, relaxing, instrumental")
    parser.add_argument("--save", help="保存生成的 wav（32 kHz 单声道）")
    args = parser.parse_args()

    started = time.time()
    model = musicgen.MusicGen(args.model_dir, decoder=args.decoder, text_encoder=args.text_encoder,
                              threads=args.threads, low_memory=args.low_mem)
    rss_loaded = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    result = model.generate(args.prompt, seconds=args.seconds, seed=args.seed)
    audio = result["audio"]
    if args.save:
        with wave.open(args.save, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(musicgen.SAMPLE_RATE)
            handle.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
    t = result["seconds"]
    print(json.dumps({
        "decoder": args.decoder, "text_encoder": args.text_encoder, "threads": args.threads, "low_mem": args.low_mem,
        "audio_s": round(len(audio) / musicgen.SAMPLE_RATE, 2), "load_s": round(model.load_seconds, 2),
        "text_s": t["text"], "decoder_s": t["decoder"], "encodec_s": t["encodec"],
        "steps_per_s": round(result["steps"] / t["decoder"], 1), "rtf": round(t["total"] / args.seconds, 3),
        "rss_after_load_mb": round(rss_loaded), "rss_peak_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024),
        "wall_s": round(time.time() - started, 2), "peak": round(float(np.abs(audio).max()), 3),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
