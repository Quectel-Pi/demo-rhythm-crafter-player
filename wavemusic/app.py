"""GTK 窗口、WebView 与 JS ↔ Python 消息桥。

前端调用：window.webkit.messageHandlers.bridge.postMessage(JSON.stringify({id, cmd, args}))
后端回复：window.__waveBridge.reply(id, ok, data)
后端推送：window.__waveBridge.emit(event, data)
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
import threading
import time
import traceback
from pathlib import Path
from urllib.parse import unquote, urlparse

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
for _webkit_version in ("4.1", "4.0"):
    try:
        gi.require_version("WebKit2", _webkit_version)
        break
    except ValueError:
        continue
else:
    sys.exit("缺少 WebKit2GTK：请执行 sudo apt install gir1.2-webkit2-4.1")

from gi.repository import Gdk, Gio, GLib, Gtk, WebKit2  # noqa: E402

from . import __version__  # noqa: E402
from .config import (APP_DIR, APP_ID, APP_NAME, AUDIO_EXTENSIONS, GENERATED_DIR, cloud_song_credentials,  # noqa: E402
                     detect_ai_environment, find_icon, find_ui_dir, load_config)
from .i18n import localize, ui_text  # noqa: E402
from .jobs import AIJobQueue, Job  # noqa: E402
from .library import Library, MetadataReader  # noqa: E402
from .warm import WarmModels  # noqa: E402

sys.path.insert(0, str(APP_DIR / "ai"))  # noqa: E402
import cloud_song  # noqa: E402

CJK = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")
STEMS_NEED_MB = 1600        # 人声分离子进程峰值内存（RK3576 实测约 1.4GB）

DEBUG = bool(os.environ.get("WAVE_MUSIC_DEBUG"))


class BridgeError(Exception):
    """返回给前端的可读错误。"""


class PlayerWindow(Gtk.ApplicationWindow):
    def __init__(self, app: "WaveMusicApp", ui_dir: Path):
        super().__init__(application=app, title=APP_NAME)
        self.app = app
        self.ui_dir = ui_dir
        self.set_default_size(1180, 760)
        self.set_size_request(720, 520)
        self.set_position(Gtk.WindowPosition.CENTER)
        icon_path = find_icon()
        if icon_path:
            try:
                self.set_icon_from_file(icon_path)
            except GLib.Error:
                pass
        else:
            self.set_icon_name("wave-music")

        self.webview = self._create_webview()
        self.add(self.webview)
        self.webview.load_uri((ui_dir / "index.html").as_uri())
        self.show_all()

    # ---------- WebView ----------
    def _create_webview(self) -> WebKit2.WebView:
        manager = WebKit2.UserContentManager()
        manager.register_script_message_handler("bridge")
        manager.connect("script-message-received::bridge", self._on_bridge_message)
        kwargs = {"user_content_manager": manager}
        if hasattr(WebKit2, "WebsitePolicies") and hasattr(WebKit2, "AutoplayPolicy"):
            kwargs["website_policies"] = WebKit2.WebsitePolicies(autoplay=WebKit2.AutoplayPolicy.ALLOW)
        webview = WebKit2.WebView(**kwargs)

        settings = webview.get_settings()
        for name, value in (
            ("enable-webaudio", True),
            ("enable-media", True),
            ("enable-mediasource", True),
            ("media-playback-requires-user-gesture", False),
            ("allow-file-access-from-file-urls", True),
            ("allow-universal-access-from-file-urls", True),  # 允许 Web Audio 处理本地 file:// 音频
            ("enable-developer-extras", DEBUG),
            ("enable-back-forward-navigation-gestures", False),
            ("enable-smooth-scrolling", True),
            ("hardware-acceleration-policy", WebKit2.HardwareAccelerationPolicy.ON_DEMAND),
        ):
            if settings.find_property(name) is not None:
                settings.set_property(name, value)

        bg = Gdk.RGBA()
        bg.parse("#ffffff")
        webview.set_background_color(bg)
        webview.connect("context-menu", lambda *_: not DEBUG)
        webview.connect("decide-policy", self._on_decide_policy)
        webview.connect("notify::title", self._on_title_changed)
        webview.connect("web-process-terminated", self._on_crash)
        # 拖放：网页里拿不到文件路径，在 GTK 层读取 URI 列表
        self._drag_uris: list[str] = []
        webview.connect("drag-data-received", self._on_drag_data)
        webview.connect("drag-drop", self._on_drag_drop)
        return webview

    def _on_drag_data(self, _widget, _context, _x, _y, data, _info, _time):
        uris = data.get_uris() if data is not None else None
        if uris:
            self._drag_uris = list(uris)
        return False

    def _on_drag_drop(self, _widget, _context, _x, _y, _time):
        uris, self._drag_uris = self._drag_uris, []
        if uris:
            GLib.idle_add(self._add_uris, uris)
        return False

    def _add_uris(self, uris: list[str]):
        paths = [unquote(urlparse(u).path) for u in uris if u.startswith("file://")]
        self.emit_event("library.added", {"tracks": self.app.add_paths(paths)})
        return False

    def _on_decide_policy(self, _webview, decision, decision_type):
        if decision_type == WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
            uri = decision.get_navigation_action().get_request().get_uri()
            if not uri.startswith(self.ui_dir.as_uri()) and not uri.startswith("about:"):
                # 拖入窗口的音频文件会触发导航：改为加入曲库
                if uri.startswith("file://"):
                    GLib.idle_add(self._add_dropped_uri, uri)
                decision.ignore()
                return True
        elif decision_type == WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION:
            decision.ignore()
            return True
        return False

    def _add_dropped_uri(self, uri: str):
        return self._add_uris([uri])

    def _on_title_changed(self, webview, _pspec):
        self.set_title(webview.get_title() or APP_NAME)

    def _on_crash(self, webview, _reason):
        print("界面进程异常退出，正在重新加载…", file=sys.stderr)
        GLib.timeout_add(500, lambda: (webview.reload(), False)[1])

    # ---------- 消息桥 ----------
    def run_js(self, script: str) -> None:
        if hasattr(self.webview, "evaluate_javascript"):
            self.webview.evaluate_javascript(script, -1, None, None, None, None, None)
        else:
            self.webview.run_javascript(script, None, None, None)

    def emit_event(self, event: str, data) -> None:
        data = localize(data)                     # 发往界面的提示译成英文（终端日志不受影响）
        self.run_js(f"window.__waveBridge&&window.__waveBridge.emit({json.dumps(event)},{json.dumps(data)})")

    def _reply(self, msg_id, ok: bool, data) -> None:
        data = localize(data) if ok else ui_text(data)
        self.run_js(f"window.__waveBridge&&window.__waveBridge.reply({json.dumps(msg_id)},{json.dumps(ok)},{json.dumps(data)})")

    def _on_bridge_message(self, _manager, result):
        value = result.get_js_value() if hasattr(result, "get_js_value") else result
        try:
            message = json.loads(value.to_string())
            msg_id, cmd, args = message.get("id"), message.get("cmd"), message.get("args") or {}
        except (ValueError, AttributeError):
            return
        handler = getattr(self.app, "cmd_" + str(cmd).replace(".", "_"), None)
        if handler is None:
            self._reply(msg_id, False, f"未知命令：{cmd}")
            return
        try:
            self._reply(msg_id, True, handler(**args))
        except BridgeError as error:
            self._reply(msg_id, False, str(error))
        except Exception as error:  # noqa: BLE001
            traceback.print_exc()
            self._reply(msg_id, False, f"内部错误：{error}")

    # ---------- 原生对话框 ----------
    def choose_files(self, folder: bool) -> list[str]:
        action = Gtk.FileChooserAction.SELECT_FOLDER if folder else Gtk.FileChooserAction.OPEN
        dialog = Gtk.FileChooserNative.new("Add Folder" if folder else "Add Music", self, action, "_Add", "_Cancel")
        dialog.set_select_multiple(True)
        music_dir = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_MUSIC)
        if music_dir and os.path.isdir(music_dir):
            dialog.set_current_folder(music_dir)
        if not folder:
            audio_filter = Gtk.FileFilter()
            audio_filter.set_name("Audio files")
            audio_filter.add_mime_type("audio/*")
            for ext in AUDIO_EXTENSIONS:
                audio_filter.add_pattern(f"*{ext}")
                audio_filter.add_pattern(f"*{ext.upper()}")
            all_filter = Gtk.FileFilter()
            all_filter.set_name("All files")
            all_filter.add_pattern("*")
            dialog.add_filter(audio_filter)
            dialog.add_filter(all_filter)
        paths = []
        if dialog.run() == Gtk.ResponseType.ACCEPT:
            paths = [f.get_path() for f in dialog.get_files() if f.get_path()]
        dialog.destroy()
        return paths


class WaveMusicApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.window: PlayerWindow | None = None
        self.library: Library | None = None
        self.metadata: MetadataReader | None = None
        self.jobs: AIJobQueue | None = None
        self.bgm_seq = 0
        self.translations: dict[str, str] = {}        # 中文描述 → 英文提示词（预览与生成共用）
        self.preview_seq = 0                          # 译文预览序号：新的预览会取消旧的
        self.preview_prompt: str | None = None
        self.warm: WarmModels | None = None           # 常驻模型（翻译 / MusicGen）
        self.ai_env: dict | None = None

    # ---------- 生命周期 ----------
    def do_startup(self):
        Gtk.Application.do_startup(self)
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Primary>q"])

        self.library = Library()
        self.metadata = MetadataReader(lambda tid, meta: GLib.idle_add(self._on_metadata, tid, meta))
        self.jobs = AIJobQueue(lambda ev, data: GLib.idle_add(self._on_job_event, ev, data), prepare=self._prepare_job)
        threading.Thread(target=self._detect_ai, name="ai-detect", daemon=True).start()
        for track in self.library.list():
            if not track["duration"] and not track["missing"]:
                self.metadata.submit(track["id"], track["path"])

    def do_activate(self):
        if self.window is None:
            ui_dir = find_ui_dir()
            if ui_dir is None:
                sys.exit("找不到界面资源 ui/index.html")
            self.window = PlayerWindow(self, ui_dir)
        self.window.present()

    def do_shutdown(self):
        if self.jobs:
            self.jobs.shutdown()
        if self.warm:
            self.warm.shutdown()
        if self.library:
            self.library.close()
        Gtk.Application.do_shutdown(self)

    def emit_event(self, event: str, data) -> None:
        if self.window:
            self.window.emit_event(event, data)

    # ---------- 后台回调（主线程） ----------
    def _detect_ai(self):
        env = detect_ai_environment()
        GLib.idle_add(self._on_ai_env, env)

    def _on_ai_env(self, env: dict):
        self.ai_env = env
        if env["available"]:
            print(f"[AI] 人声分离可用：python={env['python']} model={env['model_dir']} threads={env['threads']}")
        else:
            print(f"[AI] 人声分离不可用：{env['reason']}", file=sys.stderr)
        translate = env["translate"]
        if translate["available"]:
            print(f"[AI] 中文翻译（Qwen2.5-{translate['size']}）可用：{translate['model_dir']}")
        else:
            print(f"[AI] 中文翻译不可用：{translate['reason']}", file=sys.stderr)
        compose = env["compose"]
        if compose["available"]:
            mode = f"，低内存模式 {compose['low_memory']}" if compose.get("low_memory") else ""
            print(f"[AI] AI 作曲（MusicGen）可用：{compose['model_dir']}{mode}；作品目录 {compose['generated_dir']}")
        else:
            print(f"[AI] AI 作曲（MusicGen）不可用：{compose['reason']}", file=sys.stderr)
        cloud = env.get("cloud_song") or {}
        if cloud.get("available"):
            print("[AI] 云端歌词转歌曲（Coze）已开启：每次生成会联网并按量计费")
        else:
            print(f"[AI] 云端歌词转歌曲（Coze）未开启：{cloud.get('reason')}")
        if translate["available"] or compose["available"]:
            minutes = env.get("warm_idle_minutes", 5)
            self.warm = WarmModels(env, idle_seconds=minutes * 60,
                                   on_state=lambda state: GLib.idle_add(self._emit_warm_state, state))
            print(f"[AI] 常驻模型：按需加载，空闲 {minutes:g} 分钟后释放" if minutes else "[AI] 常驻模型：已关闭（每次用完立即释放）")
        self.emit_event("ai.status", env)
        return False

    def _emit_warm_state(self, state: dict):
        self.emit_event("bgm.warm", state)
        return False

    def _prepare_job(self, job: Job) -> None:
        """人声分离开始前：内存不够时先释放空闲的常驻模型（工作线程中调用）。"""
        if job.kind == "stems" and self.warm:
            self.warm.free_for(STEMS_NEED_MB)

    def _on_metadata(self, track_id: int, meta: dict):
        if "error" in meta:
            print(f"[元数据] {track_id}: {meta['error']}", file=sys.stderr)
        track = self.library.update_metadata(track_id, meta)
        if track:
            self.emit_event("library.updated", {"track": track})
        return False

    def _on_job_event(self, event: str, data: dict):
        if event == "stems.done":
            row = self.library.get(data["id"])
            if row:
                data["track"] = self.library.to_dict(row)
                meta = data.get("meta", {})
                print(f"[AI] 分离完成 #{data['id']}：{meta.get('duration', 0):.0f}s 音频，用时 {meta.get('elapsed')}s（RTF {meta.get('rtf')}）")
        elif event == "stems.error":
            print(f"[AI] 分离失败 #{data['id']}：{data.get('message')}", file=sys.stderr)
        elif event == "bgm.done":
            data = self._finish_bgm(data)
            if data is None:
                return False
        elif event == "bgm.error":
            print(f"[AI] 作曲失败 #{data['id']}：{data.get('message')}", file=sys.stderr)
        self.emit_event(event, data)
        return False

    @staticmethod
    def _derive_title(prompt: str, lyrics: str | None) -> str:
        """标题优先用歌词第一句正文（跳过 [verse]/[chorus] 这类结构标签），没有歌词时（本地纯音乐）用提示词。"""
        for line in (lyrics or "").splitlines():
            line = line.strip()
            if line and not re.fullmatch(r"\[[^\]]*\]", line):
                return line if len(line) <= 40 else line[:39] + "…"
        return prompt if len(prompt) <= 40 else prompt[:39] + "…"

    def _finish_bgm(self, data: dict) -> dict | None:
        """作曲完成（本地或云端）：把生成的 wav 加入曲库，并把曲目信息随事件一起发给前端。"""
        meta = data.get("meta", {})
        prompt = (data.get("prompt") or "").strip()
        if meta.get("prompt_en") and meta["prompt_en"] != prompt:
            self.translations.setdefault(prompt, meta["prompt_en"])
        title = self._derive_title(prompt, meta.get("lyrics")) or "AI 作曲"
        artist = "AI 作曲（云端）" if meta.get("engine") == "coze-doubao-song" else "AI 作曲"
        try:
            track = self.library.add_generated(meta["path"], title, artist, meta.get("summary", ""),
                                               float(meta.get("seconds", 0)))
        except (OSError, KeyError) as error:
            self.emit_event("bgm.error", {"id": data["id"], "message": f"无法加入曲库：{error}"})
            return None
        note = f"（AI 旋律失败，已改用规则旋律：{meta['fallback']}）" if meta.get("fallback") else ""
        print(f"[AI] 作曲完成 #{data['id']}：{meta.get('summary')}，用时 {meta.get('elapsed')}s{note}")
        return {"id": data["id"], "track": track, "meta": meta}

    # ---------- 业务 ----------
    def add_paths(self, paths: list[str]) -> list[dict]:
        added = self.library.add(paths)
        for track in added:
            self.metadata.submit(track["id"], track["path"])
        return added

    def _row(self, track_id):
        row = self.library.get(int(track_id))
        if not row:
            raise BridgeError("曲目不存在")
        return row

    # ---------- 前端命令（cmd_<模块>_<动作>） ----------
    def cmd_app_init(self):
        return {
            "version": __version__,
            "tracks": self.library.list(),
            "settings": self.library.settings(),
            "ai": self.ai_env,
            "jobs": self.jobs.status(),
            "playlists": self.library.playlists(),
            "warm": self.warm.state() if self.warm else {},
        }

    def cmd_library_add_dialog(self, folder: bool = False):
        paths = self.window.choose_files(bool(folder))
        return {"added": self.add_paths(paths), "selected": len(paths)}

    def cmd_library_add_uris(self, uris: list):
        paths = [unquote(urlparse(u).path) for u in uris if str(u).startswith("file://")]
        return {"added": self.add_paths(paths)}

    def cmd_library_remove(self, id):  # noqa: A002
        self.jobs.cancel("stems", int(id))
        self.library.remove(int(id))
        return True

    def cmd_library_clear(self):
        for track in self.library.list():
            self.jobs.cancel("stems", track["id"])
        self.library.clear()
        return True

    def cmd_library_set_duration(self, id, duration):  # noqa: A002
        track = self.library.update_metadata(int(id), {"duration": float(duration)})
        return track

    # ---------- 歌单 ----------
    def _playlist_call(self, func, *args):
        try:
            return func(*args)
        except ValueError as error:
            raise BridgeError(str(error)) from error

    def cmd_playlist_create(self, name: str = "", track_ids: list | None = None):
        playlist = self._playlist_call(self.library.create_playlist, name)
        if track_ids:
            playlist = self.library.add_to_playlist(playlist["id"], track_ids)
        return playlist

    def cmd_playlist_rename(self, id, name: str = ""):  # noqa: A002
        return self._playlist_call(self.library.rename_playlist, int(id), name)

    def cmd_playlist_delete(self, id):  # noqa: A002
        self.library.delete_playlist(int(id))
        return True

    def cmd_playlist_add(self, id, track_ids: list):  # noqa: A002
        return self._playlist_call(self.library.add_to_playlist, int(id), [int(t) for t in track_ids])

    def cmd_playlist_remove(self, id, track_id):  # noqa: A002
        return self.library.remove_from_playlist(int(id), int(track_id))

    def cmd_settings_set(self, values: dict):
        self.library.set_settings(values)
        return True

    def cmd_ai_status(self):
        return {"ai": self.ai_env, "jobs": self.jobs.status()}

    def cmd_stems_separate(self, id):  # noqa: A002
        row = self._row(id)
        if self.ai_env is None:
            raise BridgeError("AI 环境检测中，请稍候再试")
        if not self.ai_env["available"]:
            raise BridgeError(self.ai_env["reason"])
        if not os.path.isfile(row["path"]):
            raise BridgeError("源文件不存在")
        self.library.delete_stems(row["id"])
        if not self.jobs.submit_separation(row["id"], row["path"], self.library.stems_dir(row), self.ai_env):
            raise BridgeError("该曲目已在处理队列中")
        return True

    def cmd_stems_cancel(self, id):  # noqa: A002
        self.jobs.cancel("stems", int(id))
        return True

    def cmd_stems_delete(self, id):  # noqa: A002
        row = self._row(id)
        self.jobs.cancel("stems", row["id"])
        self.library.delete_stems(row["id"])
        return self.library.to_dict(row)

    # ---------- AI 作曲（MusicGen，提示词原样交给模型） ----------
    def _needs_translation(self, prompt: str) -> bool:
        return bool(CJK.search(prompt)) and prompt not in self.translations

    def cmd_bgm_warm(self, prompt: str = ""):
        """界面提示即将使用 AI 作曲（打开作曲页 / 输入描述）：预加载接下来要用的模型。
        需要翻译（含中文且未翻译，或还没输入——示例都是中文）时先加载翻译模型，否则加载 MusicGen。"""
        if not self.warm:
            return {}
        prompt = str(prompt or "").strip()[:300]
        if (not prompt or self._needs_translation(prompt)) and self.warm.has("translate"):
            self.warm.preload("translate")
        else:
            self.warm.preload("musicgen")
        return self.warm.state()

    def cmd_bgm_translate(self, prompt: str = ""):
        """中文描述 → 英文提示词（常驻翻译模型，结果通过 bgm.translated 事件返回；同一描述只翻译一次）。"""
        prompt = str(prompt or "").strip()[:300]
        if prompt in self.translations:
            return {"cached": True, "english": self.translations[prompt]}
        translate = (self.ai_env or {}).get("translate") or {}
        if not translate.get("available") or not self.warm:
            raise BridgeError(translate.get("reason") or "中文翻译不可用")
        self.preview_seq += 1
        self.preview_prompt = prompt
        threading.Thread(target=self._translate_worker, args=(prompt, self.preview_seq), name="translate",
                         daemon=True).start()
        return {"cached": False}

    def _translate_worker(self, prompt: str, seq: int):
        stale = lambda: self.preview_seq != seq    # noqa: E731 —— 有更新的预览请求时放弃
        try:
            result = self.warm.translate(prompt, should_stop=stale)
        except InterruptedError:
            return
        except Exception as error:  # noqa: BLE001
            result = {"error": str(error)}
        if result.get("text"):
            self.translations[prompt] = result["text"]
            if not stale():
                self.warm.preload("musicgen")      # 译文已出：趁用户确认译文时换上 MusicGen
        payload = {"prompt": prompt, "english": result.get("text", ""), "error": result.get("error"),
                   "seconds": result.get("seconds")}
        GLib.idle_add(lambda: (self.emit_event("bgm.translated", payload), False)[1])

    def cmd_bgm_generate(self, prompt: str = "", seconds=8):
        compose = (self.ai_env or {}).get("compose")
        if self.ai_env is None:
            raise BridgeError("AI 环境检测中，请稍候再试")
        if not compose or not compose["available"] or not self.warm:
            raise BridgeError((compose or {}).get("reason") or "AI 作曲不可用")
        prompt = str(prompt or "").strip()[:300]
        if not prompt:
            raise BridgeError("请先输入音乐描述")
        seconds = 4 if int(seconds or 8) <= 4 else 8
        if self.preview_prompt != prompt:
            # 其他描述的译文预览已无用：取消，避免与生成争抢 CPU 与内存；同一描述的预览保留，生成直接等它的结果
            self.preview_seq += 1
            self.preview_prompt = None
        self.bgm_seq += 1
        job_id = self.bgm_seq
        out_dir = GENERATED_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{job_id}"
        runner = lambda progress, should_stop: self._run_bgm(prompt, seconds, out_dir, progress, should_stop)  # noqa: E731
        self.jobs.submit_runner("bgm", job_id, runner, out_dir, extra={"prompt": prompt})
        return {"job": job_id}

    def _run_bgm(self, prompt: str, seconds: int, out_dir: Path, progress, should_stop) -> dict:
        """作曲任务（队列线程）：必要时用常驻翻译模型翻译 → 常驻 MusicGen 生成。"""
        started = time.time()
        english, translate_seconds = self.translations.get(prompt), None
        if english is None and CJK.search(prompt):
            progress({"stage": "translate", "progress": 0.03})
            begin = time.time()
            english = self.warm.translate(prompt, should_stop=should_stop).get("text")
            translate_seconds = round(time.time() - begin, 3)
            if not english:
                raise RuntimeError("翻译结果为空，请换一种说法或直接用英文描述")
            self.translations[prompt] = english
            progress({"stage": "translate", "progress": 0.12, "english": english})
        offset = 0.12 if translate_seconds is not None else 0.0
        progress({"stage": "load", "progress": offset + 0.01})
        request = {"prompt": prompt, "english": english or prompt, "seconds": seconds,
                   "seed": random.randrange(1, 2 ** 31), "output": str(out_dir), "translate_seconds": translate_seconds,
                   "offset": offset, "started": started}
        return self.warm.generate(request, on_event=progress, should_stop=should_stop)

    def cmd_bgm_cancel(self, job):
        self.jobs.cancel("bgm", int(job))
        return True

    # ---------- AI 作曲（云端： Coze 工作流 + Doubao-音乐生成插件，提示词自动写词+作曲+演唱）
    def cmd_cloud_song_generate(self, prompt: str = ""):
        if self.ai_env is None:
            raise BridgeError("AI 环境检测中，请稍候再试")
        cloud = self.ai_env.get("cloud_song") or {}
        credentials = cloud_song_credentials(load_config())
        if not cloud.get("available") or not credentials:
            raise BridgeError(cloud.get("reason") or "云端生成不可用")
        prompt = str(prompt or "").strip()[:300]
        if not prompt:
            raise BridgeError("请先输入音乐描述")
        workflow_id, token = credentials
        self.bgm_seq += 1
        job_id = self.bgm_seq
        out_dir = GENERATED_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{job_id}"
        runner = lambda progress, should_stop: self._run_cloud_song(  # noqa: E731
            prompt, workflow_id, token, out_dir, progress, should_stop)
        self.jobs.submit_runner("bgm", job_id, runner, out_dir, extra={"prompt": prompt})
        return {"job": job_id}

    def _run_cloud_song(self, prompt: str, workflow_id: str, token: str, out_dir: Path, progress, should_stop) -> dict:
        """云端作曲任务（队列线程）：把 prompt 发到 Coze 工作流，下载生成的歌曲。"""
        return cloud_song.generate_song(
            prompt, workflow_id, token, out_dir,
            progress=lambda stage, value: progress({"stage": stage, "progress": value}),
            should_stop=should_stop)


def _proc_file_seekable(path: str) -> bool:
    try:
        with open(path, "rb", buffering=0) as handle:
            handle.read(1)
            handle.seek(0)
        return True
    except OSError:
        return False


def main() -> int:
    # 中文 MP3 的 ID3 标签常为 GBK 编码
    sys.stdout.reconfigure(line_buffering=True)
    os.environ.setdefault("GST_ID3_TAG_ENCODING", "GBK:UTF-8")
    # 部分厂商内核（如 RK3576 的 6.1-rt）的 /proc/meminfo 不支持 seek：WebKit 的内存压力监视器每次轮询都失败，
    # 并在终端反复打印 “Failed to get the memory usage”。它在这类系统上本就无法工作，直接关闭。
    if not _proc_file_seekable("/proc/meminfo"):
        os.environ.setdefault("WEBKIT_DISABLE_MEMORY_PRESSURE_MONITOR", "1")
    GLib.set_prgname("wave-music")
    GLib.set_application_name(APP_NAME)
    return WaveMusicApp().run(sys.argv[:1])
