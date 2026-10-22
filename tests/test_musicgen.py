"""MusicGen（ONNX）推理与后处理的测试。模型不存在时，模型相关测试自动跳过。

运行：.venv/bin/python -m unittest discover -s tests -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "ai")]

import numpy as np  # noqa: E402

import musicgen  # noqa: E402

MODEL_DIR = ROOT / "models" / musicgen.MODEL_NAME
try:
    import onnxruntime  # noqa: F401
    import tokenizers  # noqa: F401
    HAS_MODEL = musicgen.find_model_dir(ROOT / "models") is not None and \
        (MODEL_DIR / "onnx" / "decoder_model_merged_int8.onnx").is_file()
except ImportError:
    HAS_MODEL = False


class PostprocessTest(unittest.TestCase):
    def test_delay_mask(self):
        """与 transformers build_delay_pattern_mask 一致：第 k 个码本开头延迟 k+1 位、结尾补齐。"""
        model = musicgen.MusicGen.__new__(musicgen.MusicGen)
        model.codebooks, model.pad_id = 4, 2048
        mask = model.delay_mask(10)
        expected_free = {0: range(1, 7), 1: range(2, 8), 2: range(3, 9), 3: range(4, 10)}
        for cb, free in expected_free.items():
            self.assertEqual([j for j in range(10) if mask[cb, j] == -1], list(free))
        self.assertTrue(((mask == -1) | (mask == 2048)).all())

    def test_resample(self):
        tone = np.sin(2 * np.pi * 440 * np.arange(32000) / 32000)
        out = musicgen.resample(tone)
        self.assertEqual(len(out), 44100)
        spectrum = np.abs(np.fft.rfft(out))
        self.assertAlmostEqual(np.argmax(spectrum) * 44100 / len(out), 440, delta=1)

    def test_trim_leading_silence(self):
        sr = musicgen.SAMPLE_RATE
        audio = np.concatenate([np.zeros(sr // 2), np.random.default_rng(0).uniform(-0.5, 0.5, sr * 3)])
        out = musicgen.trim_leading_silence(audio, 2.0)
        self.assertEqual(len(out), 2 * sr)
        self.assertGreater(np.abs(out[: sr // 10]).max(), 0.1)   # 已跳过开头静音

    def test_postprocess_natural_ending(self):
        rng = np.random.default_rng(1)
        t = np.arange(musicgen.SAMPLE_RATE * 4) / musicgen.SAMPLE_RATE
        audio = (np.sin(2 * np.pi * 220 * t) * 0.3 + rng.normal(0, 0.01, len(t))).astype(np.float32)
        out = musicgen.postprocess(audio)
        self.assertEqual(out.shape[0], 2)
        self.assertAlmostEqual(out.shape[1] / musicgen.OUT_RATE, 4.0, delta=0.01)    # 时长不变
        self.assertLessEqual(np.abs(out).max(), 0.951)
        self.assertLess(np.abs(out[0, -50:]).max(), 0.01)                            # 结尾淡出到静音
        self.assertLess(np.abs(out[0, :5]).max(), 0.05)                              # 开头淡入，无爆音


@unittest.skipUnless(HAS_MODEL, "MusicGen 模型未下载（scripts/setup-musicgen.sh）")
class MusicGenModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = musicgen.MusicGen(MODEL_DIR, threads=4, low_memory="arena")

    def test_generate_short(self):
        result = self.model.generate("calm piano", seconds=1.0, seed=3)
        audio = result["audio"]
        self.assertEqual(result["frames"], 50)
        self.assertEqual(len(audio), 50 * 640)
        self.assertTrue(np.isfinite(audio).all())
        self.assertGreater(float(np.sqrt(np.mean(audio ** 2))), 0.005)

    def test_deterministic(self):
        a = self.model.generate("happy guitar", seconds=0.5, seed=7)["audio"]
        b = self.model.generate("happy guitar", seconds=0.5, seed=7)["audio"]
        c = self.model.generate("happy guitar", seconds=0.5, seed=8)["audio"]
        np.testing.assert_allclose(a, b, atol=1e-5)
        self.assertFalse(np.allclose(a, c, atol=1e-3))

    def test_cancel(self):
        with self.assertRaises(InterruptedError):
            self.model.generate("calm piano", seconds=2.0, seed=1, should_stop=lambda: True)

    def test_generate_bgm(self):
        for seconds in (4, 8):
            audio, stats = musicgen.generate_bgm("calm lo-fi piano", seconds, 1, MODEL_DIR, low_memory="arena")
            self.assertEqual(audio.shape[0], 2)
            self.assertAlmostEqual(stats["seconds"], seconds, delta=0.05)

    def test_worker_cli(self):
        import json
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            prompt = "upbeat happy acoustic guitar, party"
            result = subprocess.run([sys.executable, str(ROOT / "ai" / "generate_worker.py"), "--prompt", prompt,
                                     "--seconds", "4", "--seed", "5", "--low-mem", "arena", "--output", tmp],
                                    capture_output=True, text=True, timeout=180)
            self.assertEqual(result.returncode, 0, result.stderr[-500:])
            done = json.loads(result.stdout.splitlines()[-1])
            self.assertEqual((done["event"], done["seed"], done["summary"]), ("done", 5, "4 秒"))
            meta = json.loads((Path(tmp) / "meta.json").read_text("utf-8"))
            self.assertEqual((meta["engine"], meta["prompt"], meta["duration"]), ("musicgen", prompt, 4))   # 提示词原样保存
            self.assertEqual(meta["musicgen"]["low_memory"], "arena")
            self.assertAlmostEqual(meta["seconds"], 4.0, delta=0.05)


class WorkerErrorTest(unittest.TestCase):
    def test_missing_model_reports_error(self):
        import json
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run([sys.executable, str(ROOT / "ai" / "generate_worker.py"), "--prompt", "calm piano",
                                     "--model-dir", "/nonexistent", "--output", tmp],
                                    capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 1)
            error = json.loads(result.stdout.splitlines()[-1])
            self.assertEqual(error["event"], "error")
            self.assertIn("AI 作曲模型", error["message"])
            self.assertFalse((Path(tmp) / "bgm.wav").exists())

    def test_rejects_other_lengths(self):
        result = subprocess_run(["--prompt", "x", "--seconds", "12", "--output", "/tmp/never"])
        self.assertNotEqual(result.returncode, 0)


def subprocess_run(args):
    import subprocess
    return subprocess.run([sys.executable, str(ROOT / "ai" / "generate_worker.py"), *args],
                          capture_output=True, text=True, timeout=60)


if __name__ == "__main__":
    unittest.main()
