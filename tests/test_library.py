"""曲库与自建歌单的测试（不需要图形界面与模型）。

运行：python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class PlaylistTest(unittest.TestCase):
    def setUp(self):
        from wavemusic.library import Library

        self.tmp = Path(tempfile.mkdtemp())
        music = self.tmp / "music"
        music.mkdir()
        for name in ("a.mp3", "b.flac", "c.wav"):
            (music / name).write_bytes(b"\0" * 16)
        self.lib = Library(self.tmp / "library.db")
        self.tracks = [t["id"] for t in self.lib.add([str(music)])]

    def tearDown(self):
        self.lib.close()

    def test_create_and_validate_name(self):
        p = self.lib.create_playlist("  我的   最爱 ")
        self.assertEqual((p["name"], p["track_ids"]), ("我的 最爱", []))
        for bad in ("", "   ", "我的 最爱", "x" * 41):
            with self.assertRaises(ValueError):
                self.lib.create_playlist(bad)

    def test_rename(self):
        a = self.lib.create_playlist("A")
        b = self.lib.create_playlist("B")
        self.assertEqual(self.lib.rename_playlist(b["id"], "C")["name"], "C")
        self.assertEqual(self.lib.rename_playlist(b["id"], "C")["name"], "C")     # 改成自己的名字不算重名
        with self.assertRaises(ValueError):
            self.lib.rename_playlist(b["id"], "A")
        with self.assertRaises(ValueError):
            self.lib.rename_playlist(999, "D")

    def test_add_remove_order(self):
        p = self.lib.create_playlist("P")
        p = self.lib.add_to_playlist(p["id"], [self.tracks[2], self.tracks[0]])
        p = self.lib.add_to_playlist(p["id"], [self.tracks[0], self.tracks[1], 999])   # 重复与不存在的忽略
        self.assertEqual(p["track_ids"], [self.tracks[2], self.tracks[0], self.tracks[1]])
        p = self.lib.remove_from_playlist(p["id"], self.tracks[0])
        self.assertEqual(p["track_ids"], [self.tracks[2], self.tracks[1]])
        self.assertEqual(len(self.lib.list()), 3)                                      # 只从歌单移除，曲目还在

    def test_library_sync(self):
        p = self.lib.create_playlist("P")
        self.lib.add_to_playlist(p["id"], self.tracks)
        self.lib.remove(self.tracks[0])
        self.assertEqual(self.lib.playlists()[0]["track_ids"], self.tracks[1:])
        self.lib.clear()
        self.assertEqual(self.lib.playlists()[0]["track_ids"], [])
        self.assertEqual(len(self.lib.playlists()), 1)                                  # 清空曲库保留歌单本身

    def test_delete_and_persist(self):
        from wavemusic.library import Library

        keep = self.lib.create_playlist("保留")
        self.lib.add_to_playlist(keep["id"], self.tracks[:1])
        gone = self.lib.create_playlist("删除")
        self.lib.add_to_playlist(gone["id"], self.tracks)
        self.lib.delete_playlist(gone["id"])
        self.lib.close()
        self.lib = Library(self.tmp / "library.db")                                     # 重新打开
        self.assertEqual([(p["name"], p["track_ids"]) for p in self.lib.playlists()], [("保留", self.tracks[:1])])
        count = self.lib.db.execute("SELECT COUNT(*) FROM playlist_tracks").fetchone()[0]
        self.assertEqual(count, 1)                                                      # 被删歌单的引用已清理


if __name__ == "__main__":
    unittest.main()
