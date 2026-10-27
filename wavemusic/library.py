"""持久化曲库（SQLite）与音频元数据读取。

所有数据库操作都在 GTK 主线程执行；元数据读取在后台线程进行，结果通过回调交回主线程。
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import shutil
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable, Iterable

from .config import AUDIO_EXTENSIONS, DB_FILE, GENERATED_DIR, STEMS_DIR

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    path      TEXT NOT NULL UNIQUE,
    title     TEXT NOT NULL,
    artist    TEXT NOT NULL DEFAULT '',
    album     TEXT NOT NULL DEFAULT '',
    format    TEXT NOT NULL DEFAULT '',
    duration  REAL NOT NULL DEFAULT 0,
    size      INTEGER NOT NULL DEFAULT 0,
    mtime     REAL NOT NULL DEFAULT 0,
    added_at  REAL NOT NULL,
    position  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS playlists (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS playlist_tracks (
    playlist_id INTEGER NOT NULL,
    track_id    INTEGER NOT NULL,
    position    INTEGER NOT NULL,
    added_at    REAL NOT NULL,
    PRIMARY KEY (playlist_id, track_id)
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

UNKNOWN_ARTIST = "未知歌手"


def parse_filename(path: str) -> tuple[str, str]:
    """“歌手 - 歌名.mp3” → (歌名, 歌手)。"""
    base = re.sub(r"\.[^.]+$", "", os.path.basename(path)).replace("_", " ").strip()
    match = re.match(r"^(.+?)\s+-\s+(.+)$", base)
    if match:
        return match.group(2).strip(), match.group(1).strip()
    return base, UNKNOWN_ARTIST


def is_audio_file(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in AUDIO_EXTENSIONS and os.path.isfile(path)


def scan_paths(paths: Iterable[str]) -> list[str]:
    """展开文件夹（递归），返回去重后的音频文件路径。"""
    found: list[str] = []
    for raw in paths:
        path = os.path.abspath(os.path.expanduser(raw))
        if os.path.isdir(path):
            for root, dirs, files in os.walk(path):
                dirs[:] = sorted(d for d in dirs if not d.startswith("."))
                found.extend(os.path.join(root, f) for f in sorted(files) if is_audio_file(os.path.join(root, f)))
        elif is_audio_file(path):
            found.append(path)
    return list(dict.fromkeys(found))


def stems_key(path: str, size: int, mtime: float) -> str:
    """文件内容变化（大小/修改时间）后，旧的分离结果自动失效。"""
    return hashlib.sha1(f"{path}|{size}|{int(mtime)}".encode()).hexdigest()[:20]


def generated_dir_of(path: str) -> Path | None:
    """AI 作曲作品的目录（GENERATED_DIR/<任务>/bgm.wav）；不是作品时返回 None。"""
    try:
        parent = Path(path).resolve().parent
        if parent.parent == GENERATED_DIR.resolve():
            return parent
    except OSError:
        pass
    return None


class Library:
    def __init__(self, db_file: Path = DB_FILE):
        db_file.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(db_file))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    # ---------- 曲目 ----------
    def stems_dir(self, row) -> Path:
        return STEMS_DIR / stems_key(row["path"], row["size"], row["mtime"])

    def stems_info(self, row) -> dict:
        directory = self.stems_dir(row)
        vocals, accompaniment = directory / "vocals.wav", directory / "accompaniment.wav"
        if vocals.is_file() and accompaniment.is_file() and (directory / "meta.json").is_file():
            return {"status": "done", "vocals": vocals.as_uri(), "accompaniment": accompaniment.as_uri()}
        return {"status": "none"}

    def to_dict(self, row) -> dict:
        path = row["path"]
        return {
            "id": row["id"],
            "path": path,
            "uri": Path(path).as_uri(),
            "title": row["title"],
            "artist": row["artist"] or UNKNOWN_ARTIST,
            "album": row["album"],
            "format": row["format"],
            "duration": row["duration"],
            "missing": not os.path.isfile(path),
            "stems": self.stems_info(row),
            "generated": self.generated_info(path),
        }

    @staticmethod
    def generated_info(path: str) -> dict | None:
        """AI 作曲作品的生成信息（描述、参数、种子），来自同目录的 meta.json。"""
        directory = generated_dir_of(path)
        if directory is None:
            return None
        try:
            meta = json.loads((directory / "meta.json").read_text("utf-8"))
        except (OSError, ValueError):
            return {"prompt": "", "summary": "", "duration": 8}
        return {key: meta.get(key) for key in ("prompt", "prompt_en", "summary", "duration", "seed", "created_at", "engine", "lyrics")}

    def add_generated(self, path: str, title: str, artist: str, album: str, duration: float) -> dict:
        """把 AI 作曲的结果加入曲库（标题等信息直接写入，不再读取标签）。"""
        stat = os.stat(path)
        position = self.db.execute("SELECT COALESCE(MAX(position), 0) FROM tracks").fetchone()[0] + 1
        cursor = self.db.execute(
            "INSERT INTO tracks (path, title, artist, album, format, duration, size, mtime, added_at, position) "
            "VALUES (?, ?, ?, ?, 'AI', ?, ?, ?, ?, ?)",
            (path, title, artist, album, duration, stat.st_size, stat.st_mtime, time.time(), position),
        )
        self.db.commit()
        return self.to_dict(self.get(cursor.lastrowid))

    def get(self, track_id: int):
        return self.db.execute("SELECT * FROM tracks WHERE id = ?", (track_id,)).fetchone()

    def list(self) -> list[dict]:
        rows = self.db.execute("SELECT * FROM tracks ORDER BY position, id").fetchall()
        return [self.to_dict(row) for row in rows]

    def add(self, paths: Iterable[str]) -> list[dict]:
        """添加音频文件，返回新加入的曲目（已存在的会被忽略）。"""
        position = self.db.execute("SELECT COALESCE(MAX(position), 0) FROM tracks").fetchone()[0]
        added_ids = []
        for path in scan_paths(paths):
            try:
                stat = os.stat(path)
            except OSError:
                continue
            title, artist = parse_filename(path)
            position += 1
            cursor = self.db.execute(
                "INSERT OR IGNORE INTO tracks (path, title, artist, format, size, mtime, added_at, position) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (path, title, artist, os.path.splitext(path)[1][1:].upper() or "AUDIO",
                 stat.st_size, stat.st_mtime, time.time(), position),
            )
            if cursor.rowcount:
                added_ids.append(cursor.lastrowid)
        self.db.commit()
        return [self.to_dict(self.get(i)) for i in added_ids]

    def update_metadata(self, track_id: int, meta: dict) -> dict | None:
        row = self.get(track_id)
        if not row:
            return None
        fields = {k: v for k, v in meta.items() if k in ("title", "artist", "album", "duration") and v}
        if fields:
            assignments = ", ".join(f"{k} = ?" for k in fields)
            self.db.execute(f"UPDATE tracks SET {assignments} WHERE id = ?", (*fields.values(), track_id))
            self.db.commit()
        return self.to_dict(self.get(track_id))

    def remove(self, track_id: int, delete_stems: bool = True) -> None:
        row = self.get(track_id)
        if not row:
            return
        if delete_stems:
            shutil.rmtree(self.stems_dir(row), ignore_errors=True)
        self._delete_generated(row["path"])
        self.db.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
        self.db.execute("DELETE FROM playlist_tracks WHERE track_id = ?", (track_id,))
        self.db.commit()

    @staticmethod
    def _delete_generated(path: str) -> None:
        """AI 作曲的作品只存在于曲库中，移除时一并删除文件，避免数据目录里堆积孤儿文件。"""
        directory = generated_dir_of(path)
        if directory is not None:
            shutil.rmtree(directory, ignore_errors=True)

    def clear(self) -> None:
        for row in self.db.execute("SELECT * FROM tracks").fetchall():
            shutil.rmtree(self.stems_dir(row), ignore_errors=True)
            self._delete_generated(row["path"])
        self.db.execute("DELETE FROM tracks")
        self.db.execute("DELETE FROM playlist_tracks")
        self.db.commit()

    def delete_stems(self, track_id: int) -> None:
        row = self.get(track_id)
        if row:
            shutil.rmtree(self.stems_dir(row), ignore_errors=True)

    # ---------- 歌单（应用内自建，只保存曲目引用，不复制文件） ----------
    MAX_PLAYLIST_NAME = 40

    def _playlist_dict(self, playlist_id: int) -> dict | None:
        row = self.db.execute("SELECT * FROM playlists WHERE id = ?", (playlist_id,)).fetchone()
        if not row:
            return None
        ids = [r[0] for r in self.db.execute(
            "SELECT track_id FROM playlist_tracks WHERE playlist_id = ? ORDER BY position, added_at", (playlist_id,))]
        return {"id": row["id"], "name": row["name"], "created_at": row["created_at"], "track_ids": ids}

    def playlists(self) -> list[dict]:
        rows = self.db.execute("SELECT id FROM playlists ORDER BY created_at, id").fetchall()
        return [self._playlist_dict(r[0]) for r in rows]

    def _check_name(self, name: str, exclude: int | None = None) -> str:
        name = " ".join(str(name or "").split())
        if not name:
            raise ValueError("歌单名称不能为空")
        if len(name) > self.MAX_PLAYLIST_NAME:
            raise ValueError(f"歌单名称最多 {self.MAX_PLAYLIST_NAME} 个字")
        clash = self.db.execute("SELECT id FROM playlists WHERE name = ? AND id IS NOT ?", (name, exclude)).fetchone()
        if clash:
            raise ValueError(f"已经有名为「{name}」的歌单")
        return name

    def create_playlist(self, name: str) -> dict:
        name = self._check_name(name)
        cursor = self.db.execute("INSERT INTO playlists (name, created_at) VALUES (?, ?)", (name, time.time()))
        self.db.commit()
        return self._playlist_dict(cursor.lastrowid)

    def rename_playlist(self, playlist_id: int, name: str) -> dict:
        name = self._check_name(name, exclude=playlist_id)
        if not self.db.execute("UPDATE playlists SET name = ? WHERE id = ?", (name, playlist_id)).rowcount:
            raise ValueError("歌单不存在")
        self.db.commit()
        return self._playlist_dict(playlist_id)

    def delete_playlist(self, playlist_id: int) -> None:
        self.db.execute("DELETE FROM playlist_tracks WHERE playlist_id = ?", (playlist_id,))
        self.db.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))
        self.db.commit()

    def add_to_playlist(self, playlist_id: int, track_ids: Iterable[int]) -> dict:
        """追加到歌单末尾；已在歌单中的曲目忽略，不存在的曲目忽略。"""
        if not self._playlist_dict(playlist_id):
            raise ValueError("歌单不存在")
        position = self.db.execute("SELECT COALESCE(MAX(position), 0) FROM playlist_tracks WHERE playlist_id = ?",
                                   (playlist_id,)).fetchone()[0]
        for track_id in track_ids:
            if not self.get(int(track_id)):
                continue
            position += 1
            self.db.execute("INSERT OR IGNORE INTO playlist_tracks (playlist_id, track_id, position, added_at) "
                            "VALUES (?, ?, ?, ?)", (playlist_id, int(track_id), position, time.time()))
        self.db.commit()
        return self._playlist_dict(playlist_id)

    def remove_from_playlist(self, playlist_id: int, track_id: int) -> dict:
        self.db.execute("DELETE FROM playlist_tracks WHERE playlist_id = ? AND track_id = ?", (playlist_id, track_id))
        self.db.commit()
        return self._playlist_dict(playlist_id)

    # ---------- 设置 ----------
    def settings(self) -> dict:
        result = {}
        for row in self.db.execute("SELECT key, value FROM settings"):
            try:
                result[row["key"]] = json.loads(row["value"])
            except ValueError:
                pass
        return result

    def set_settings(self, values: dict) -> None:
        self.db.executemany(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            [(k, json.dumps(v, ensure_ascii=False)) for k, v in values.items()],
        )
        self.db.commit()

    def close(self) -> None:
        self.db.close()


class MetadataReader:
    """在后台线程用 GStreamer Discoverer 读取标签与时长。"""

    def __init__(self, on_result: Callable[[int, dict], None]):
        self.on_result = on_result
        self.jobs: queue.Queue = queue.Queue()
        self.thread = threading.Thread(target=self._run, name="metadata", daemon=True)
        self.thread.start()

    def submit(self, track_id: int, path: str) -> None:
        self.jobs.put((track_id, path))

    def _run(self) -> None:
        import gi
        gi.require_version("Gst", "1.0")
        gi.require_version("GstPbutils", "1.0")
        from gi.repository import Gst, GstPbutils

        Gst.init(None)
        discoverer = GstPbutils.Discoverer.new(8 * Gst.SECOND)
        while True:
            track_id, path = self.jobs.get()
            meta: dict = {}
            try:
                info = discoverer.discover_uri(Path(path).as_uri())
                duration = info.get_duration()
                if duration and duration != Gst.CLOCK_TIME_NONE:
                    meta["duration"] = duration / Gst.SECOND
                tags = info.get_tags()
                if tags:
                    for key, tag in (("title", Gst.TAG_TITLE), ("artist", Gst.TAG_ARTIST), ("album", Gst.TAG_ALBUM)):
                        ok, value = tags.get_string(tag)
                        if ok and value and value.strip():
                            meta[key] = value.strip()
            except Exception as error:  # noqa: BLE001 —— 单个文件失败不影响其他文件
                meta["error"] = str(error)
            self.on_result(track_id, meta)
