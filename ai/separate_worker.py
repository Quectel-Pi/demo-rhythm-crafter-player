#!/usr/bin/env python3
"""人声 / 伴奏分离工作进程。

由播放器以子进程方式调用，运行在装有 sherpa-onnx + numpy 的 Python 环境中（不依赖 GTK）。
  解码：gst-launch-1.0 → 44.1 kHz 立体声 float32
  分离：sherpa-onnx Spleeter 2stems，按 30 秒分段处理（控制内存、汇报进度），段间交叉淡化
  输出：<out>/vocals.wav、<out>/accompaniment.wav（16-bit PCM）与 meta.json
进度以 JSON 行写到 stdout：{"event": "progress", "stage": "...", "progress": 0.42}
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np

SAMPLE_RATE = 44100
CHUNK_SECONDS = 30
OVERLAP_SECONDS = 1


def emit(event: str, **payload) -> None:
    sys.stdout.write(json.dumps({"event": event, **payload}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def decode(path: str) -> np.ndarray:
    """用 GStreamer 解码任意格式音频，返回形状为 (2, N) 的 float32 数组。"""
    caps = f"audio/x-raw,format=F32LE,rate={SAMPLE_RATE},channels=2,layout=interleaved"
    command = [
        "gst-launch-1.0", "-q", "uridecodebin", f"uri={Path(path).resolve().as_uri()}", "!",
        "audioconvert", "!", "audioresample", "!", caps, "!", "fdsink", "fd=1",
    ]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0 or not result.stdout:
        message = result.stderr.decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError("解码失败：" + (message[-1] if message else "未知错误"))
    data = np.frombuffer(result.stdout, dtype=np.float32)
    data = data[: len(data) // 2 * 2]
    return np.ascontiguousarray(data.reshape(-1, 2).T)


def build_separator(model_dir: Path, threads: int):
    import sherpa_onnx

    config = sherpa_onnx.OfflineSourceSeparationConfig(
        model=sherpa_onnx.OfflineSourceSeparationModelConfig(
            spleeter=sherpa_onnx.OfflineSourceSeparationSpleeterModelConfig(
                vocals=str(model_dir / "vocals.fp16.onnx"),
                accompaniment=str(model_dir / "accompaniment.fp16.onnx"),
            ),
            num_threads=threads,
        )
    )
    if not config.validate():
        raise RuntimeError(f"模型配置无效：{model_dir}")
    return sherpa_onnx.OfflineSourceSeparation(config)


def separate_chunk(separator, chunk: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """处理一段音频；Spleeter 输出会比输入略短，这里补齐到输入长度。"""
    length = chunk.shape[1]
    padded = np.pad(chunk, ((0, 0), (0, SAMPLE_RATE // 2)))
    output = separator.process(sample_rate=SAMPLE_RATE, samples=np.ascontiguousarray(padded))
    stems = []
    for stem in output.stems[:2]:
        data = np.asarray(stem.data, dtype=np.float32)
        if data.shape[1] < length:
            data = np.pad(data, ((0, 0), (0, length - data.shape[1])))
        stems.append(data[:, :length])
    return stems[0], stems[1]


def separate(separator, audio: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    total = audio.shape[1]
    chunk = CHUNK_SECONDS * SAMPLE_RATE
    overlap = OVERLAP_SECONDS * SAMPLE_RATE
    vocals = np.zeros_like(audio)
    accompaniment = np.zeros_like(audio)
    fade_in = np.linspace(0.0, 1.0, overlap, dtype=np.float32)

    start = 0
    while start < total:
        begin = max(0, start - overlap)
        end = min(total, start + chunk)
        voc, acc = separate_chunk(separator, audio[:, begin:end])
        head = start - begin  # 与上一段重叠的样本数
        if head:
            ramp = fade_in[:head]
            vocals[:, begin:start] = vocals[:, begin:start] * (1 - ramp) + voc[:, :head] * ramp
            accompaniment[:, begin:start] = accompaniment[:, begin:start] * (1 - ramp) + acc[:, :head] * ramp
        vocals[:, start:end] = voc[:, head:]
        accompaniment[:, start:end] = acc[:, head:]
        start = end
        emit("progress", stage="separate", progress=round(0.1 + 0.8 * start / total, 3))
    return vocals, accompaniment


def write_wav(path: Path, data: np.ndarray) -> None:
    pcm = (np.clip(data.T, -1.0, 1.0) * 32767.0).astype("<i2")
    tmp = path.with_suffix(".tmp")
    with wave.open(str(tmp), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm.tobytes())
    os.replace(tmp, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    try:
        emit("progress", stage="load", progress=0.01)
        separator = build_separator(Path(args.model_dir), args.threads)
        emit("progress", stage="decode", progress=0.03)
        audio = decode(args.input)
        if audio.shape[1] < SAMPLE_RATE // 10:
            raise RuntimeError("音频过短或无法解码")
        emit("progress", stage="separate", progress=0.1)
        vocals, accompaniment = separate(separator, audio)
        emit("progress", stage="write", progress=0.92)
        write_wav(out_dir / "vocals.wav", vocals)
        write_wav(out_dir / "accompaniment.wav", accompaniment)
        elapsed = time.time() - started
        duration = audio.shape[1] / SAMPLE_RATE
        meta = {
            "source": os.path.abspath(args.input),
            "model": "spleeter-2stems-fp16",
            "duration": duration,
            "elapsed": round(elapsed, 2),
            "rtf": round(elapsed / duration, 4),
            "threads": args.threads,
            "created_at": time.time(),
        }
        (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
        emit("done", **meta)
        return 0
    except Exception as error:  # noqa: BLE001
        for name in ("vocals.wav", "accompaniment.wav", "meta.json"):
            (out_dir / name).unlink(missing_ok=True)
        emit("error", message=str(error))
        return 1


if __name__ == "__main__":
    sys.exit(main())
