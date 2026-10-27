"""MusicGen-small 推理（ONNX，Xenova/musicgen-small 导出；模型 CC-BY-NC 4.0，仅限非商业用途）。

只依赖 onnxruntime + numpy + tokenizers，与 transformers 的 MusicgenForConditionalGeneration.generate 等价：
  1. T5 文本编码器 → encoder_hidden_states
  2. 无分类器引导（CFG，guidance_scale=3）：条件与“空条件”（全零隐藏状态、全零掩码）拼成批大小 2
  3. 4 个码本按延迟排列（第 k 个码本延迟 k 帧），每步对 4 个码本同时 top-k=250 采样
  4. 合并版解码器：首步 use_cache_branch=False，之后只喂最后一帧并复用 KV 缓存
  5. 去掉延迟填充 → EnCodec 解码 → 32 kHz 单声道波形
帧率 50 Hz：N 秒音频需要 50·N + 3 步。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

import numpy as np

MODEL_NAME = "musicgen-small-onnx"
SAMPLE_RATE = 32000
FRAME_RATE = 50


def find_model_dir(models_root: Path) -> Path | None:
    directory = Path(models_root) / MODEL_NAME
    if (directory / "tokenizer.json").is_file() and (directory / "onnx" / "encodec_decode.onnx").is_file():
        return directory
    return None


class MusicGen:
    def __init__(self, model_dir: str | Path, decoder: str = "int8", text_encoder: str = "int8", threads: int = 4,
                 low_memory: bool | str = False):
        """decoder: int8 | q4；text_encoder: int8 | fp32。EnCodec 固定用 fp32（int8 版含 ConvInteger，CPU 不支持）。
        low_memory：关闭内存池与权重预打包、只做基础图优化，用于 4GB 内存的开发板。"""
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self.dir = Path(model_dir)
        config = json.loads((self.dir / "config.json").read_text("utf-8"))
        dec = config["decoder"]
        self.codebooks = int(dec["num_codebooks"])
        self.layers = int(dec["num_hidden_layers"])
        self.heads = int(dec["num_attention_heads"])
        self.head_dim = int(dec["hidden_size"]) // self.heads
        self.pad_id = int(dec.get("pad_token_id", 2048))
        self.tokenizer = Tokenizer.from_file(str(self.dir / "tokenizer.json"))

        options = ort.SessionOptions()
        options.intra_op_num_threads = max(1, int(threads))
        options.inter_op_num_threads = 1
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        # low_memory：True 等于 "prepack,arena,basic"；也可以只给其中几项，用逗号分隔
        flags = {"prepack", "arena", "basic"} if low_memory is True else set(filter(None, str(low_memory or "").split(",")))
        if "basic" in flags:
            options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
        if "arena" in flags:
            options.enable_cpu_mem_arena = False
            options.enable_mem_pattern = False
        if "prepack" in flags:
            options.add_session_config_entry("session.disable_prepacking", "1")
        onnx_dir = self.dir / "onnx"

        def session(name):
            return ort.InferenceSession(str(onnx_dir / name), options, providers=["CPUExecutionProvider"])

        started = time.time()
        self.text_encoder = session("text_encoder_int8.onnx" if text_encoder == "int8" else "text_encoder.onnx")
        self.decoder = session(f"decoder_model_merged_{decoder}.onnx")
        self.encodec = session("encodec_decode.onnx")
        self.load_seconds = time.time() - started
        self.decoder_inputs = {i.name for i in self.decoder.get_inputs()}
        self.decoder_outputs = [o.name for o in self.decoder.get_outputs()]
        self.kv_dtype = np.float32

    # ---------- 延迟排列（与 transformers build_delay_pattern_mask 等价） ----------
    def delay_mask(self, max_length: int) -> np.ndarray:
        """(码本数, max_length)：-1 表示该位置由模型预测，否则为强制的填充值。"""
        k = self.codebooks
        mask = np.full((k, max_length), -1, dtype=np.int64)
        for cb in range(k):
            mask[cb, : cb + 1] = self.pad_id                    # 开头延迟
            mask[cb, max_length - k + 1 + cb:] = self.pad_id    # 结尾补齐
        return mask

    @staticmethod
    def _top_k_sample(logits: np.ndarray, rng: np.random.Generator, top_k: int, temperature: float) -> np.ndarray:
        """logits: (行, 词表)，逐行 top-k 采样。"""
        logits = logits.astype(np.float64) / max(temperature, 1e-4)
        k = min(top_k, logits.shape[1])
        idx = np.argpartition(-logits, k - 1, axis=1)[:, :k]
        top = np.take_along_axis(logits, idx, axis=1)
        probs = np.exp(top - top.max(axis=1, keepdims=True))
        probs /= probs.sum(axis=1, keepdims=True)
        u = rng.random((logits.shape[0], 1))
        choice = (probs.cumsum(axis=1) < u).sum(axis=1).clip(0, k - 1)
        return idx[np.arange(logits.shape[0]), choice]

    def _empty_past(self, batch: int) -> dict:
        shape = (batch, self.heads, 0, self.head_dim)
        return {f"past_key_values.{i}.{part}.{kv}": np.zeros(shape, dtype=self.kv_dtype)
                for i in range(self.layers) for part in ("decoder", "encoder") for kv in ("key", "value")}

    def generate(self, text: str, seconds: float = 8.0, seed: int = 0, guidance_scale: float = 3.0,
                 top_k: int = 250, temperature: float = 1.0,
                 progress: Callable[[float], None] | None = None,
                 should_stop: Callable[[], bool] | None = None) -> dict:
        """返回 {"audio": float32 单声道 32 kHz, "frames", "steps", "seconds": {...各阶段耗时}}。"""
        rng = np.random.default_rng(seed)
        timing = {}
        t0 = time.time()

        # 1. 文本编码；CFG：条件 + 空条件（全零隐藏状态与掩码）
        encoding = self.tokenizer.encode(text)
        input_ids = np.array([encoding.ids], dtype=np.int64)
        attention = np.ones_like(input_ids)
        hidden = self.text_encoder.run(None, {"input_ids": input_ids, "attention_mask": attention})[0]
        cfg = guidance_scale > 1.0
        if cfg:
            hidden = np.concatenate([hidden, np.zeros_like(hidden)], axis=0)
            attention = np.concatenate([attention, np.zeros_like(attention)], axis=0)
        batch = hidden.shape[0]
        timing["text"] = time.time() - t0

        # 2. 自回归生成
        t1 = time.time()
        k = self.codebooks
        frames = max(1, int(round(seconds * FRAME_RATE)))
        max_length = frames + k                                  # 起始帧 + frames + (k-1) 帧延迟
        mask = self.delay_mask(max_length)
        ids = np.full((k, max_length), self.pad_id, dtype=np.int64)   # 条件分支的码本序列（第 0 位是起始符）
        past = self._empty_past(batch)
        use_cache = False
        for position in range(1, max_length):
            if use_cache:
                step_ids = ids[:, position - 1:position]
            else:
                step_ids = ids[:, :position]
            feed_ids = np.tile(step_ids, (batch, 1))             # (batch*k, 长度)：条件、空条件各一份
            feeds = {"input_ids": feed_ids, "encoder_hidden_states": hidden,
                     "encoder_attention_mask": attention, "use_cache_branch": np.array([use_cache]), **past}
            outputs = dict(zip(self.decoder_outputs, self.decoder.run(None, feeds)))
            logits = outputs["logits"][:, -1, :]                  # (batch*k, 2048)
            if cfg:
                cond, uncond = logits[:k], logits[k:]
                logits = uncond + (cond - uncond) * guidance_scale
            token = self._top_k_sample(logits, rng, top_k, temperature)
            ids[:, position] = np.where(mask[:, position] == -1, token, mask[:, position])
            # 自注意力缓存每步更新；交叉注意力缓存只在首步得到一次
            # （合并版解码器在缓存分支里只输出形状为 (0,16,1,64) 的占位值，不能拿来覆盖）
            for name, value in outputs.items():
                if name.startswith("present") and (not use_cache or ".decoder." in name):
                    past[name.replace("present", "past_key_values")] = value
            use_cache = True
            if progress and position % 10 == 0:
                progress(position / max_length)
            if should_stop and should_stop():
                raise InterruptedError("已取消")
        timing["decoder"] = time.time() - t1

        # 3. 去掉延迟填充，EnCodec 解码
        t2 = time.time()
        codes = np.stack([ids[cb, cb + 1: cb + 1 + frames] for cb in range(k)])   # (k, frames)
        audio = self.encodec.run(None, {"audio_codes": codes[None, None].astype(np.int64)})[0]
        timing["encodec"] = time.time() - t2
        timing["total"] = time.time() - t0
        return {
            "audio": np.asarray(audio, dtype=np.float32).reshape(-1),
            "frames": frames,
            "steps": max_length - 1,
            "seconds": {key: round(value, 3) for key, value in timing.items()},
        }


# ============================== 后处理与整体流程 ==============================
OUT_RATE = 44100


def resample(audio: np.ndarray, src: int = SAMPLE_RATE, dst: int = OUT_RATE) -> np.ndarray:
    """FFT 带限重采样（整段一次完成，适合几秒到几十秒的片段）。"""
    n_out = int(round(len(audio) * dst / src))
    spectrum = np.fft.rfft(audio)
    out_bins = n_out // 2 + 1
    resized = np.zeros(out_bins, dtype=complex)
    count = min(len(spectrum), out_bins)
    resized[:count] = spectrum[:count]
    return (np.fft.irfft(resized, n_out) * (n_out / len(audio))).astype(np.float32)


def trim_leading_silence(audio: np.ndarray, target_seconds: float, max_trim: float = 1.5) -> np.ndarray:
    """MusicGen 开头常有一小段静音：找到能量起来的位置（比整体 RMS 低 24 dB 以上视为静音），
    从该处开始截取 target_seconds 秒（最多跳过 max_trim 秒）。"""
    window = int(0.05 * SAMPLE_RATE)
    frames = len(audio) // window
    if frames == 0:
        return audio
    energy = np.sqrt(np.mean(audio[: frames * window].reshape(frames, window) ** 2, axis=1))
    threshold = float(np.sqrt(np.mean(audio ** 2))) * 10 ** (-24 / 20)
    loud = np.nonzero(energy > threshold)[0]
    start = min(int(loud[0]) * window if len(loud) else 0, int(max_trim * SAMPLE_RATE))
    start = max(0, start - int(0.02 * SAMPLE_RATE))
    need = int(target_seconds * SAMPLE_RATE)
    start = min(start, max(0, len(audio) - need))
    return audio[start: start + need]


def postprocess(audio: np.ndarray, fade_out: float = 0.5) -> np.ndarray:
    """32 kHz 单声道 → 44.1 kHz 立体声；响度统一 + 软限幅；开头 10 毫秒淡入、结尾 fade_out 秒淡出（自然结尾）。"""
    x = resample(audio.astype(np.float64))
    x -= x.mean()
    fade = min(int(fade_out * OUT_RATE), len(x) // 4)
    x[-fade:] *= np.linspace(1, 0, fade) ** 2
    attack = int(0.01 * OUT_RATE)
    x[:attack] *= np.linspace(0, 1, attack)
    rms = float(np.sqrt(np.mean(x ** 2))) or 1.0
    x = np.tanh(x * (0.16 / rms) * 1.2) / 1.2
    peak = float(np.max(np.abs(x))) or 1.0
    if peak > 0.95:
        x *= 0.95 / peak
    return np.stack([x, x]).astype(np.float32)


def generate_bgm(prompt: str, seconds: float, seed: int, model_dir: str | Path, threads: int = 4,
                 decoder: str = "int8", low_memory: bool | str = False,
                 progress: Callable[[str, float], None] | None = None,
                 model: "MusicGen | None" = None,
                 should_stop: Callable[[], bool] | None = None) -> tuple[np.ndarray, dict]:
    """提示词原样交给 MusicGen → 跳过开头静音 → 后处理。返回 (立体声 44.1 kHz, 统计)。
    model：已加载的模型（常驻进程复用，不再加载）；should_stop：返回 True 时中止（InterruptedError）。"""
    report = progress or (lambda stage, value: None)
    report("load", 0.02)
    warm = model is not None
    if model is None:
        model = MusicGen(model_dir, decoder=decoder, threads=threads, low_memory=low_memory)
    margin = 1.0                                                      # 多生成 1 秒，用于跳过开头静音
    result = model.generate(prompt, seconds=seconds + margin, seed=int(seed) % (2 ** 32),
                            progress=lambda value: report("generate", 0.05 + 0.85 * value), should_stop=should_stop)
    report("mix", 0.92)
    trimmed = trim_leading_silence(result["audio"], seconds)
    audio = postprocess(trimmed)
    stats = {
        "seconds": round(audio.shape[1] / OUT_RATE, 3),
        "musicgen": {"decoder": decoder, "low_memory": low_memory, "threads": threads, "warm": warm,
                     "trimmed_seconds": round((len(result["audio"]) - len(trimmed)) / SAMPLE_RATE, 2),
                     "load_seconds": 0.0 if warm else round(model.load_seconds, 3), **result["seconds"],
                     "steps": result["steps"]},
    }
    return audio, stats
