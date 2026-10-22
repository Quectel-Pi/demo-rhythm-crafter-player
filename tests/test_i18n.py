"""界面英文化测试：后端发往界面的中文消息都能译成英文；终端日志与用户数据不受影响。

运行：.venv/bin/python -m unittest tests.test_i18n -v
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wavemusic.i18n import CJK, localize, ui_text  # noqa: E402

# 发往界面的消息在源码中的写法：raise X("…")、BridgeError("…")、reasons.append("…")、message=f"…"、failure = "…" 等
UI_MESSAGE = re.compile(
    r"""(?:raise\s+\w+\(\s*|BridgeError\(\s*|reasons?\.append\(\s*|reason\s*=\s*|message=|failure\s*=\s*|"""
    r"""self\.failure\s+or\s+|get\("message"\)\s+or\s+|\)\s+or\s+|\bor\s+|"message":\s*|_reply\([^,]+,\s*False,\s*)"""
    r"""f?(["'])(?P<text>(?:(?!\1).)*[\u3400-\u9fff](?:(?!\1).)*)\1""")
SOURCES = sorted([*ROOT.glob("wavemusic/*.py"), *ROOT.glob("ai/*.py")])
SKIP_FILES = {"i18n.py"}
SKIP_LINES = ("title = title or", "title = self._derive_title(")        # 作品标题的兜底值属于曲目数据，不是提示消息


def source_messages() -> list[tuple[str, str]]:
    found = []
    for path in SOURCES:
        if path.name in SKIP_FILES:
            continue
        for line in path.read_text("utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith(("#", "print(", "log(", '"""', "'''")) or "print(" in stripped or stripped.startswith(SKIP_LINES):
                continue
            for match in UI_MESSAGE.finditer(line):
                text = re.sub(r"\{[^}]*\}", "X", match.group("text"))    # f-string 占位换成示例值
                found.append((f"{path.name}: {stripped[:80]}", text))
    return found


class UiTextTest(unittest.TestCase):
    def test_source_messages_translated(self):
        messages = source_messages()
        self.assertGreater(len(messages), 30)                     # 确认扫描本身有效
        untranslated = [(where, text, ui_text(text)) for where, text in messages if CJK.search(ui_text(text))]
        self.assertEqual(untranslated, [], "以下发往界面的消息缺少英文译文（在 wavemusic/i18n.py 的 RULES 中补充）")

    def test_joined_reasons_and_nesting(self):
        self.assertEqual(ui_text("未找到 Spleeter 模型（运行 scripts/fetch-models.sh）；缺少 gst-launch-1.0（sudo apt install gstreamer1.0-tools）"),
                         "Spleeter model not found (run scripts/fetch-models.sh); "
                         "gst-launch-1.0 is missing (sudo apt install gstreamer1.0-tools)")
        self.assertEqual(ui_text("内部错误：模型进程意外退出（退出码 1）"),
                         "Internal error: The model process exited unexpectedly (exit code 1)")

    def test_user_content_kept(self):
        # 歌单名是用户输入：原样保留，不翻译、不按“；”拆分
        self.assertEqual(ui_text("已经有名为「已取消；收藏」的歌单"), "A playlist named \u201c已取消；收藏\u201d already exists")
        # 不认识的、或本来就是英文的消息原样返回
        self.assertEqual(ui_text("RuntimeError: boom"), "RuntimeError: boom")

    def test_localize_only_message_fields(self):
        track = {"id": 1, "title": "下雨天", "artist": "未知歌手", "path": "/音乐/下雨天.mp3"}
        env = {"available": False, "reason": "源文件不存在", "translate": {"reason": "缺少 onnxruntime / tokenizers"}}
        self.assertEqual(localize({"track": track}), {"track": track})                 # 曲目数据不变
        out = localize({"ai": env, "tracks": [track]})
        self.assertEqual(out["ai"]["reason"], "Source file not found")
        self.assertEqual(out["ai"]["translate"]["reason"], "onnxruntime / tokenizers is missing")
        self.assertEqual(out["tracks"][0], track)
        self.assertEqual(env["reason"], "源文件不存在")                                 # 原对象（日志使用）不被修改


if __name__ == "__main__":
    unittest.main()
