"""中文描述翻译（Qwen2.5-Instruct ONNX）的测试。模型不存在时，模型相关测试自动跳过。

运行：.venv/bin/python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "ai")]

import translate  # noqa: E402

MODEL_DIR = translate.find_model_dir(ROOT / "models", "0.5b") or translate.find_model_dir(ROOT / "models", "1.5b")
MUSICGEN_DIR = ROOT / "models" / "musicgen-small-onnx"
try:
    import onnxruntime  # noqa: F401
    import tokenizers  # noqa: F401
    HAS_MODEL = MODEL_DIR is not None
except ImportError:
    HAS_MODEL = False


class HelperTest(unittest.TestCase):
    def test_has_chinese(self):
        self.assertTrue(translate.has_chinese("Lo-fi 钢琴"))
        self.assertFalse(translate.has_chinese("calm lo-fi piano, 80 bpm"))

    def test_term_hints(self):
        self.assertEqual(translate.term_hints("星空下的冥想，八音盒"), "八音盒 = music box")
        self.assertEqual(translate.term_hints("二胡和二胡"), "二胡 = erhu")          # 去重
        self.assertEqual(translate.term_hints("轻松的午后"), "")

    def test_clean(self):
        self.assertEqual(translate.clean('"calm piano."\nExplanation: ...'), "calm piano")
        self.assertEqual(translate.clean("English prompt: rainy night, piano"), "rainy night, piano")

    def test_prompt_prefix_is_stable(self):
        """前缀缓存的前提：前缀单独分词与整段分词的开头一致。"""
        if not HAS_MODEL:
            self.skipTest("翻译模型未下载")
        from tokenizers import Tokenizer
        tok = Tokenizer.from_file(str(MODEL_DIR / "tokenizer.json"))
        suffix = "<|im_start|>user\n<|im_end|>\n<|im_start|>assistant\n"
        prefix = tok.encode(translate.build_prompt("")[: -len(suffix)]).ids
        for text in ("下雨天的思念，钢琴", "Lo-fi 风格", "a"):
            full = tok.encode(translate.build_prompt(text)).ids
            self.assertEqual(full[: len(prefix)], prefix)


@unittest.skipUnless(HAS_MODEL, "翻译模型未下载（scripts/setup-translate.sh）")
class TranslatorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.translator = translate.Translator(MODEL_DIR, threads=4)

    def test_english_passthrough(self):
        self.assertEqual(self.translator.translate("calm lo-fi piano")["text"], "calm lo-fi piano")

    def test_translate(self):
        result = self.translator.translate("慵懒的爵士酒吧，萨克斯")
        self.assertFalse(translate.has_chinese(result["text"]))
        self.assertIn("saxophone", result["text"].lower())
        self.assertIn("jazz", result["text"].lower())

    def test_deterministic(self):
        a = self.translator.translate("古筝和琵琶合奏")["text"]
        b = self.translator.translate("古筝和琵琶合奏")["text"]
        self.assertEqual(a, b)
        self.assertIn("guzheng", a.lower())

    def test_prefix_cache_file(self):
        self.translator.translate("测试")
        self.assertTrue(list(MODEL_DIR.glob("prefix-cache-*.npz")))


@unittest.skipUnless(HAS_MODEL and (MUSICGEN_DIR / "tokenizer.json").is_file(), "翻译或 MusicGen 模型未下载")
class WorkerTest(unittest.TestCase):
    def run_worker(self, *extra):
        tmp = tempfile.mkdtemp()
        result = subprocess.run([sys.executable, str(ROOT / "ai" / "generate_worker.py"), "--seconds", "4",
                                 "--output", tmp, "--translate-model-dir", str(MODEL_DIR), *extra],
                                capture_output=True, text=True, timeout=240)
        return result, Path(tmp)

    def test_chinese_prompt_translated(self):
        result, out = self.run_worker("--prompt", "欢快的口琴曲")
        self.assertEqual(result.returncode, 0, result.stderr[-500:])
        meta = json.loads((out / "meta.json").read_text("utf-8"))
        self.assertEqual(meta["prompt"], "欢快的口琴曲")
        self.assertFalse(translate.has_chinese(meta["prompt_en"]))
        self.assertIn("harmonica", meta["prompt_en"].lower())
        events = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertTrue(any(e.get("stage") == "translate" and e.get("english") for e in events))

    def test_english_given(self):
        result, out = self.run_worker("--prompt", "欢快的口琴曲", "--english", "cheerful harmonica tune")
        self.assertEqual(result.returncode, 0, result.stderr[-500:])
        meta = json.loads((out / "meta.json").read_text("utf-8"))
        self.assertEqual((meta["prompt_en"], meta["translate_seconds"]), ("cheerful harmonica tune", 0.0))

    def test_missing_translator(self):
        tmp = tempfile.mkdtemp()
        result = subprocess.run([sys.executable, str(ROOT / "ai" / "generate_worker.py"), "--prompt", "欢快的口琴曲",
                                 "--seconds", "4", "--output", tmp, "--translate-model-dir", "/nonexistent"],
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
