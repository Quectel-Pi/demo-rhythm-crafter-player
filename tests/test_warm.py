"""常驻模型（wavemusic/warm.py + ai/model_server.py）测试。需要翻译模型与 MusicGen，缺少时自动跳过。

运行：.venv/bin/python -m unittest tests.test_warm -v
开发板（4GB）上两个模型会轮流常驻，测试也按这个方式进行，不会同时加载两个。
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wavemusic import config, warm  # noqa: E402

ENV = config.detect_ai_environment()
HAS_MODELS = bool(ENV["translate"]["available"] and ENV["compose"]["available"])


@unittest.skipUnless(HAS_MODELS, "需要翻译模型与 MusicGen（scripts/setup-translate.sh、scripts/setup-musicgen.sh）")
class WarmModelsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.models = warm.WarmModels(ENV, idle_seconds=300)

    def tearDown(self):
        self.models.shutdown()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def generate(self, name, **extra):
        request = {"prompt": "calm piano", "english": "calm piano", "seconds": 4, "seed": 3,
                   "output": str(self.tmp / name), **extra}
        return self.models.generate(request)

    def test_translate_cached_then_generate_warm(self):
        first = self.models.translate("下雨天的思念，钢琴")
        self.assertIn("piano", first["text"].lower())
        self.assertFalse(first["cached"])
        again = self.models.translate("下雨天的思念，钢琴")
        self.assertTrue(again["cached"])
        self.assertEqual(again["text"], first["text"])

        cold = self.generate("a")
        self.assertTrue(Path(cold["path"]).is_file())
        self.assertGreater(cold["load_seconds"], 0.2)              # 首次需要等待加载
        warm_result = self.generate("b")
        self.assertTrue(Path(warm_result["path"]).is_file())
        self.assertLess(warm_result["load_seconds"], 0.2)          # 已常驻：不再加载
        self.assertEqual(self.models.state()["musicgen"], "ready")

    def test_cancel_generation(self):
        stop = threading.Event()
        self.generate("warmup")                                    # 先加载，取消只针对生成本身
        threading.Timer(1.0, stop.set).start()
        started = time.time()
        with self.assertRaises(InterruptedError):
            self.models.generate({"english": "fast rock drums", "seconds": 8, "seed": 1,
                                  "output": str(self.tmp / "cancelled")}, should_stop=stop.is_set)
        self.assertLess(time.time() - started, 3.0)
        self.assertFalse((self.tmp / "cancelled" / "bgm.wav").exists())
        self.assertTrue(Path(self.generate("after")["path"]).is_file())   # 取消后进程仍可用

    def test_low_memory_swaps_idle_model(self):
        with mock.patch.object(warm, "mem_available_mb", return_value=500):
            self.models.translate("清晨的森林，长笛")
            self.assertEqual(self.models.state()["translate"], "ready")
            self.generate("swap")                                  # 内存不足：先结束空闲的翻译模型
            self.assertEqual(self.models.state(), {"translate": "off", "musicgen": "ready"})

    def test_preload_gives_up_while_other_in_use(self):
        with mock.patch.object(warm, "mem_available_mb", return_value=500):
            with self.models.use("translate"):
                self.models.preload("musicgen")
                time.sleep(1.0)
                self.assertEqual(self.models.state()["musicgen"], "off")    # 不抢正在使用的模型的内存
                self.assertEqual(self.models.state()["translate"], "ready")

    def test_idle_zero_releases_after_use(self):
        self.models.shutdown()
        self.models = warm.WarmModels(ENV, idle_seconds=0)
        self.models.translate("欢快的生日派对，木吉他")
        deadline = time.time() + 5
        while self.models.state()["translate"] != "off" and time.time() < deadline:
            time.sleep(0.1)
        self.assertEqual(self.models.state()["translate"], "off")

    def test_server_exits_when_parent_closes_stdin(self):
        server = self.models.servers["translate"]
        server.start()
        process = server.process
        process.stdin.close()                                      # 模拟播放器退出
        process.wait(timeout=30)
        self.assertIsNotNone(process.returncode)


if __name__ == "__main__":
    unittest.main()
