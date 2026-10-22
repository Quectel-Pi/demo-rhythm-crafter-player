"""中文音乐描述 → 英文提示词（Qwen2.5-Instruct，Apache-2.0；ONNX 版 onnx-community/Qwen2.5-*-Instruct，int8）。

MusicGen 的文本编码器只理解英文，中文描述先由本地小型语言模型翻译成英文提示词。
只依赖 onnxruntime + numpy + tokenizers（不需要 torch）：
  ChatML 模板（系统指令 + 少量示例 + 用户描述）→ 首次整段前向（预填充）→ 逐词贪心解码（KV 缓存，GQA）
  贪心解码保证同一句中文每次得到相同译文；遇到换行或结束符停止。
指令要求“忠实翻译、不添加原文没有的内容、只输出一行英文”，即仍由用户的描述决定音乐。
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

import numpy as np

MODEL_NAMES = {"0.5b": "qwen2.5-0.5b-instruct-onnx", "1.5b": "qwen2.5-1.5b-instruct-onnx"}
CJK = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")

SYSTEM = (
    "You translate Chinese descriptions of music into concise English prompts for a text-to-music model. "
    "Translate faithfully: keep every instrument, mood, scene, tempo and style that is mentioned, "
    "use standard English music terms, and do not add anything that is not in the original. "
    "Output only the English prompt on a single line, without quotes or explanations."
)
# 少量示例（不与测试句重复），让小模型稳定输出“简洁的英文音乐描述”格式
EXAMPLES = [
    ("欢快的口哨和尤克里里，夏天的海滩", "cheerful whistling and ukulele, summer beach"),
    ("深夜的城市，孤独的萨克斯，慢节奏", "late night city, lonely saxophone, slow tempo"),
    ("激烈的摇滚，电吉他和鼓", "intense rock, electric guitar and drums"),
    ("清晨的森林，鸟鸣，长笛", "morning forest, birdsong, flute"),
]


# 术语提示：小模型常译错的乐器、风格与情绪词。描述中出现时，在用户消息末尾附上“Terms: 中文 = 英文”供模型参考，
# 只帮助翻译准确，不添加原文没有的内容。
TERMS = {
    "八音盒": "music box", "音乐盒": "music box", "二胡": "erhu", "古筝": "guzheng", "古琴": "guqin", "琵琶": "pipa",
    "扬琴": "yangqin", "唢呐": "suona", "笛子": "bamboo flute", "竹笛": "bamboo flute", "箫": "xiao flute", "笙": "sheng",
    "马头琴": "morin khuur", "葫芦丝": "hulusi", "编钟": "chime bells", "木鱼": "wooden fish", "锣鼓": "gongs and drums",
    "萨克斯": "saxophone", "口琴": "harmonica", "手风琴": "accordion", "马林巴": "marimba", "钢片琴": "celesta",
    "架子鼓": "drum kit", "鼓点": "drum beat", "贝斯": "bass guitar", "合成器": "synthesizer", "电钢琴": "electric piano",
    "古风": "ancient Chinese style", "国风": "Chinese style", "中国风": "Chinese style", "赛博朋克": "cyberpunk",
    "思念": "longing", "嘈杂": "noisy", "空灵": "ethereal", "治愈": "soothing", "史诗": "epic", "出征": "march to war",
}
_TERM_PATTERN = re.compile("|".join(sorted(map(re.escape, TERMS), key=len, reverse=True)))


def term_hints(text: str) -> str:
    found = list(dict.fromkeys(_TERM_PATTERN.findall(text)))
    return "; ".join(f"{t} = {TERMS[t]}" for t in found)


def has_chinese(text: str) -> bool:
    return bool(CJK.search(text or ""))


def find_model_dir(models_root: Path, size: str = "0.5b") -> Path | None:
    directory = Path(models_root) / MODEL_NAMES[size]
    if (directory / "tokenizer.json").is_file() and (directory / "onnx" / "model_int8.onnx").is_file():
        return directory
    return None


def build_prompt(text: str) -> str:
    parts = [f"<|im_start|>system\n{SYSTEM}<|im_end|>\n"]
    for chinese, english in EXAMPLES:
        parts.append(f"<|im_start|>user\n{chinese}<|im_end|>\n<|im_start|>assistant\n{english}<|im_end|>\n")
    parts.append(f"<|im_start|>user\n{text}<|im_end|>\n<|im_start|>assistant\n")
    return "".join(parts)


def clean(text: str) -> str:
    text = text.strip().splitlines()[0] if text.strip() else ""
    text = text.strip().strip("\"'“”‘’`").strip()
    text = re.sub(r"^(english( prompt)?|prompt|translation)\s*[:：]\s*", "", text, flags=re.I)
    return text.rstrip("。.").strip()


class Translator:
    def __init__(self, model_dir: str | Path, threads: int = 4, low_memory: bool = False):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self.dir = Path(model_dir)
        config = json.loads((self.dir / "config.json").read_text("utf-8"))
        generation = json.loads((self.dir / "generation_config.json").read_text("utf-8"))
        self.layers = int(config["num_hidden_layers"])
        self.kv_heads = int(config["num_key_value_heads"])
        self.head_dim = int(config["hidden_size"]) // int(config["num_attention_heads"])
        eos = generation.get("eos_token_id", config.get("eos_token_id"))
        self.stop_ids = set(eos if isinstance(eos, list) else [eos])
        self.tokenizer = Tokenizer.from_file(str(self.dir / "tokenizer.json"))
        self.newline_ids = {i for t, i in self.tokenizer.get_vocab().items() if "Ċ" in t}   # 含换行的词

        options = ort.SessionOptions()
        options.intra_op_num_threads = max(1, int(threads))
        options.inter_op_num_threads = 1
        if low_memory:
            # 只关内存池；不关权重预打包（ARM 上关闭预打包会让 int8 推理慢 3 倍以上）
            options.enable_cpu_mem_arena = False
            options.enable_mem_pattern = False
        started = time.time()
        self.session = ort.InferenceSession(str(self.dir / "onnx" / "model_int8.onnx"), options,
                                            providers=["CPUExecutionProvider"])
        self.load_seconds = time.time() - started
        self.outputs = [o.name for o in self.session.get_outputs()]
        self._prefix: tuple[int, dict] | None = None   # 固定前缀（系统指令 + 示例）的 KV 缓存
        self._should_stop = None                       # 常驻进程中用于取消过时的预览翻译

    def _forward(self, token_ids: list[int], position: int, past: dict) -> tuple[np.ndarray, dict]:
        """逐词前向（int8 动态量化按整次调用统一缩放激活值，一次喂入长序列会严重失真，因此每次只喂 1 个词）。"""
        logits = None
        for token in token_ids:
            if self._should_stop and self._should_stop():
                raise InterruptedError("已取消")
            feeds = {
                "input_ids": np.array([[token]], dtype=np.int64),
                "attention_mask": np.ones((1, position + 1), dtype=np.int64),
                "position_ids": np.array([[position]], dtype=np.int64),
                **past,
            }
            out = dict(zip(self.outputs, self.session.run(None, feeds)))
            past = {name.replace("present", "past_key_values"): value for name, value in out.items()
                    if name.startswith("present")}
            logits = out["logits"][0, -1]
            position += 1
        return logits, past

    def _prefix_cache(self) -> tuple[int, dict]:
        """固定前缀只算一次：内存中复用，并缓存到磁盘（几 MB），下次启动直接加载。"""
        if self._prefix is None:
            prefix_ids = self.tokenizer.encode(build_prompt("")[: -len("<|im_start|>user\n<|im_end|>\n<|im_start|>assistant\n")]).ids
            digest = hashlib.sha1(json.dumps([SYSTEM, EXAMPLES], ensure_ascii=False).encode("utf-8")).hexdigest()[:12]
            key = f"{len(prefix_ids)}-{digest}"   # 稳定的键（Python 内置 hash 每个进程都不同）
            cache = self.dir / f"prefix-cache-{key}.npz"
            past = None
            if cache.is_file():
                try:
                    with np.load(cache) as data:
                        past = {name: data[name] for name in data.files}
                except (OSError, ValueError):
                    past = None
            if past is None:
                empty = {f"past_key_values.{i}.{kv}": np.zeros((1, self.kv_heads, 0, self.head_dim), dtype=np.float32)
                         for i in range(self.layers) for kv in ("key", "value")}
                _, past = self._forward(prefix_ids, 0, empty)
                try:
                    np.savez(cache, **past)
                except OSError:
                    pass
            self._prefix = (len(prefix_ids), past)
        return self._prefix

    def translate(self, text: str, max_new_tokens: int = 64, should_stop=None) -> dict:
        """返回 {"text": 英文提示词, "seconds": 用时}。不含中文时原样返回。
        should_stop：返回 True 时中止（InterruptedError）。"""
        self._should_stop = should_stop
        try:
            return self._translate(text, max_new_tokens)
        finally:
            self._should_stop = None

    def _translate(self, text: str, max_new_tokens: int) -> dict:
        started = time.time()
        text = re.sub(r"\s+", " ", (text or "").strip())
        if not text or not has_chinese(text):
            return {"text": text, "seconds": 0.0}
        english = self._translate_once(text, max_new_tokens)
        if has_chinese(english):                      # 仍有残留中文：再翻译一次
            english = self._translate_once(english, max_new_tokens)
        if has_chinese(english):                      # 还有就按术语表替换，其余汉字去掉
            english = _TERM_PATTERN.sub(lambda m: f" {TERMS[m.group(0)]} ", english)
            english = re.sub(r"\s+", " ", CJK.sub(" ", english)).strip(" ,")
        english = re.sub(r"\s+([,.;])", r"\1", english)
        return {"text": english, "seconds": round(time.time() - started, 3)}

    def _translate_once(self, text: str, max_new_tokens: int) -> str:
        hints = term_hints(text)
        message = f"{text}\n(Terms: {hints})" if hints else text
        full = self.tokenizer.encode(build_prompt(message)).ids
        position, past = self._prefix_cache()
        logits, past = self._forward(full[position:], position, past)     # 只需处理用户描述部分
        position = len(full)
        generated = []
        for _ in range(max_new_tokens):
            token = int(np.argmax(logits))
            if token in self.stop_ids or (token in self.newline_ids and generated):
                break
            generated.append(token)
            logits, past = self._forward([token], position, past)
            position += 1
        return clean(self.tokenizer.decode(generated, skip_special_tokens=True))


def main() -> int:
    """命令行 / 子进程入口：输出一行 JSON {"text": 英文, "seconds": 用时} 或 {"error": 原因}。"""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="中文音乐描述 → 英文提示词")
    parser.add_argument("--text", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--low-mem", action="store_true")
    args = parser.parse_args()
    try:
        result = Translator(args.model_dir, threads=args.threads, low_memory=args.low_mem).translate(args.text)
    except Exception as error:  # noqa: BLE001
        print(json.dumps({"error": f"{type(error).__name__}: {error}"}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
