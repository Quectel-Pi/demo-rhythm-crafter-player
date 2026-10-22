"""常驻模型管理：翻译模型与 MusicGen 各一个常驻子进程（ai/model_server.py），省去每次 8–16 秒的加载。

内存策略（开发板只有 4GB、没有交换分区）：
  - 启动模型前检查 MemAvailable；不够时先结束另一个空闲的模型进程（只有结束进程才能真正归还内存）。
    4GB 设备上两者轮流常驻（同时常驻峰值约 2.7GB），≥ 6GB 的设备上两者可以同时常驻。
  - 正在使用（pinned）的模型不会被结束；需要等待时，调用方可选择等它用完或放弃（预加载放弃）。
  - 空闲超过 idle_seconds 自动结束；人声分离开始前也会按需结束空闲模型（free_for）。
预加载由界面触发：打开 AI 作曲页 / 输入描述时加载翻译模型；译文预览完成后换成 MusicGen（在用户点“生成”之前完成加载）。
"""
from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import time
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

from .config import APP_DIR

SERVER = APP_DIR / "ai" / "model_server.py"
RESERVE_MB = 400            # 给界面、播放与系统留的余量


def mem_available_mb() -> int:
    try:
        with open("/proc/meminfo", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError):
        pass
    return 1 << 20


def log(message: str) -> None:
    print(f"[AI] {message}", file=sys.stderr, flush=True)


class ModelServer:
    """一个常驻模型子进程。请求串行执行（request 持有 request_lock）。"""

    def __init__(self, kind: str, command: list[str], need_mb: int, on_state: Callable[[], None]):
        self.kind = kind
        self.command = command
        self.need_mb = need_mb
        self.on_state = on_state
        self.process: subprocess.Popen | None = None
        self.state = "off"                       # off / loading / ready
        self.ready = threading.Event()
        self.failure: str | None = None
        self.load_seconds: float | None = None
        self.lock = threading.Lock()             # 保护 process / pins
        self.request_lock = threading.Lock()
        self.events: queue.Queue | None = None
        self.current_id = 0
        self.pins = 0
        self.last_used = time.time()
        self.stderr_tail: deque[str] = deque(maxlen=20)

    # ---------- 状态 ----------
    @property
    def running(self) -> bool:
        process = self.process
        return process is not None and process.poll() is None

    @property
    def busy(self) -> bool:
        return self.pins > 0 or self.request_lock.locked()

    def _set_state(self, state: str) -> None:
        if state != self.state:
            self.state = state
            self.on_state()

    def rss_mb(self) -> int:
        process = self.process
        try:
            with open(f"/proc/{process.pid}/status", encoding="ascii") as handle:
                for line in handle:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1]) // 1024
        except (OSError, ValueError, AttributeError):
            pass
        return 0

    # ---------- 启动 / 结束 ----------
    def start(self) -> None:
        with self.lock:
            if self.running:
                return
            self.ready.clear()
            self.failure = None
            self.stderr_tail.clear()
            process = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True, bufsize=1)
            self.process = process
            self.last_used = time.time()
        threading.Thread(target=self._read_stdout, args=(process,), name=f"{self.kind}-out", daemon=True).start()
        threading.Thread(target=self._read_stderr, args=(process,), name=f"{self.kind}-err", daemon=True).start()
        log(f"加载常驻{self._label()}模型（pid {process.pid}，可用内存 {mem_available_mb()}MB）")
        self._set_state("loading")

    def stop(self, reason: str = "") -> None:
        with self.lock:
            process, self.process = self.process, None
        if process is None:
            return
        try:
            process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        self.failure = "模型进程已结束"
        self.ready.set()
        pending = self.events
        if pending:
            pending.put({"event": "error", "message": self.failure})
        log(f"释放常驻{self._label()}模型{('：' + reason) if reason else ''}")
        self._set_state("off")

    def _label(self) -> str:
        return "翻译" if self.kind == "translate" else " MusicGen "

    def _read_stderr(self, process: subprocess.Popen) -> None:
        for line in process.stderr:
            if line.strip():
                self.stderr_tail.append(line.rstrip())
        process.stderr.close()

    def _read_stdout(self, process: subprocess.Popen) -> None:
        for line in process.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            event = message.get("event")
            if event == "ready":
                self.load_seconds = message.get("load_seconds")
                log(f"常驻{self._label()}模型已就绪：加载 {self.load_seconds}s，占用 {self.rss_mb()}MB")
                self.ready.set()
                self._set_state("ready")
            elif event == "fatal":
                self.failure = message.get("message") or "模型加载失败"
            else:
                pending = self.events
                if pending is not None and message.get("id") == self.current_id:
                    pending.put(message)
        process.stdout.close()
        code = process.wait()
        if self.process is not process:          # 主动结束（stop），已处理
            return
        with self.lock:
            if self.process is process:
                self.process = None
        if not self.failure:
            detail = self.stderr_tail[-1] if self.stderr_tail else f"退出码 {code}"
            self.failure = f"模型进程意外退出（{'可能内存不足' if code == -9 else detail}）"
        log(f"常驻{self._label()}模型进程退出：{self.failure}")
        self.ready.set()
        pending = self.events
        if pending:
            pending.put({"event": "error", "message": self.failure})
        self._set_state("off")

    # ---------- 使用 ----------
    def wait_ready(self, should_stop: Callable[[], bool] | None = None) -> None:
        while not self.ready.wait(0.2):
            if should_stop and should_stop():
                raise InterruptedError("已取消")
        if not self.running or self.state != "ready":
            raise RuntimeError(self.failure or "模型进程未运行")

    def _write(self, payload: dict) -> None:
        with self.lock:
            process = self.process
            if process is None:
                raise RuntimeError(self.failure or "模型进程未运行")
            try:
                process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
                process.stdin.flush()
            except (OSError, ValueError) as error:
                raise RuntimeError(f"模型进程不可用：{error}") from error

    def request(self, payload: dict, on_event: Callable[[dict], None] | None = None,
                should_stop: Callable[[], bool] | None = None) -> dict:
        """发送请求并等待结果；progress 事件交给 on_event。取消时抛 InterruptedError，失败抛 RuntimeError。"""
        with self.request_lock:
            self.wait_ready(should_stop)
            self.current_id += 1
            events: queue.Queue = queue.Queue()
            self.events = events
            self.last_used = time.time()
            try:
                self._write({**payload, "id": self.current_id})
                cancel_sent = False
                while True:
                    if should_stop and not cancel_sent and should_stop():
                        self._write({"cmd": "cancel"})
                        cancel_sent = True
                    try:
                        message = events.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    event = message.pop("event", None)
                    message.pop("id", None)
                    if event == "progress":
                        if on_event:
                            on_event(message)
                    elif event == "done":
                        return message
                    elif event == "cancelled":
                        raise InterruptedError("已取消")
                    elif event == "error":
                        raise RuntimeError(message.get("message") or "模型进程出错")
            finally:
                self.events = None
                self.last_used = time.time()


class WarmModels:
    def __init__(self, env: dict, idle_seconds: float = 300, on_state: Callable[[dict], None] | None = None):
        self.idle_seconds = max(0.0, float(idle_seconds))
        self.on_state = on_state or (lambda state: None)
        self.servers: dict[str, ModelServer] = {}
        self.lock = threading.Lock()                     # 启动 / 腾内存的决策串行
        self.translate_lock = threading.Lock()           # 翻译串行：同一句只翻一次（预览与生成共用结果）
        self.cache: dict[str, str] = {}
        threads = str(env.get("threads") or 4)
        translate = env.get("translate") or {}
        if translate.get("available"):
            command = [translate["python"], str(SERVER), "translate", "--model-dir", translate["model_dir"],
                       "--threads", threads] + (["--low-mem"] if translate.get("low_memory") else [])
            need = 4300 if translate.get("size") == "1.5b" else 1800
            self.servers["translate"] = ModelServer("translate", command, need, self._state_changed)
        compose = env.get("compose") or {}
        if compose.get("available"):
            low = compose.get("low_memory") or ""
            command = [compose["python"], str(SERVER), "musicgen", "--model-dir", compose["model_dir"],
                       "--threads", threads] + (["--low-mem", str(low)] if low else [])
            self.servers["musicgen"] = ModelServer("musicgen", command, 1500 if low else 2100, self._state_changed)
        self.stopping = threading.Event()
        threading.Thread(target=self._idle_loop, name="warm-idle", daemon=True).start()

    # ---------- 状态 ----------
    def state(self) -> dict:
        return {kind: server.state for kind, server in self.servers.items()}

    def _state_changed(self) -> None:
        self.on_state(self.state())

    def has(self, kind: str) -> bool:
        return kind in self.servers

    # ---------- 启动与内存 ----------
    def _make_room(self, kind: str, need_mb: int) -> bool:
        """结束其他空闲模型直到可用内存足够；返回是否足够（或已无可结束的模型）。"""
        for other_kind, other in self.servers.items():
            if other_kind == kind or not other.running or other.busy:
                continue
            available = mem_available_mb()
            if available >= need_mb:
                return True
            other.stop(f"为{'翻译' if kind == 'translate' else ' MusicGen '}腾出内存（可用 {available}MB，需要约 {need_mb}MB）")
        if mem_available_mb() >= need_mb:
            return True
        # 仍不够：若有正在使用的其他模型，告诉调用方稍后再试；否则只能直接启动（与以前每次新开进程相同）
        return not any(o.running and o.busy for k, o in self.servers.items() if k != kind)

    def _start(self, kind: str, wait: bool, should_stop: Callable[[], bool] | None) -> ModelServer | None:
        server = self.servers.get(kind)
        if server is None:
            return None
        while True:
            with self.lock:
                if server.running:
                    server.last_used = time.time()
                    return server
                if self._make_room(kind, server.need_mb + RESERVE_MB):
                    server.start()
                    return server
            if not wait:
                return None
            if should_stop and should_stop():
                raise InterruptedError("已取消")
            time.sleep(0.5)                                # 等另一个模型用完（例如生成中又输入了新描述）

    @contextmanager
    def use(self, kind: str, should_stop: Callable[[], bool] | None = None):
        """取得已就绪的常驻模型；期间不会被结束（内存不够时等待另一个模型用完）。"""
        server = self.servers.get(kind)
        if server is None:
            raise RuntimeError("中文翻译不可用" if kind == "translate" else "AI 作曲不可用")
        with server.lock:
            server.pins += 1
        try:
            self._start(kind, True, should_stop)
            server.wait_ready(should_stop)
            yield server
        finally:
            with server.lock:
                server.pins -= 1
            server.last_used = time.time()
            if self.idle_seconds == 0:
                threading.Thread(target=self._stop_idle, daemon=True).start()

    def preload(self, kind: str) -> None:
        """后台预加载（不等待）；内存被正在使用的模型占着时放弃。"""
        if kind in self.servers and not self.servers[kind].running:
            threading.Thread(target=self._start, args=(kind, False, None), name=f"preload-{kind}", daemon=True).start()

    def free_for(self, need_mb: int) -> None:
        """为其他任务（人声分离）腾内存：结束空闲模型直到可用内存 ≥ need_mb。"""
        with self.lock:
            for server in self.servers.values():
                if mem_available_mb() >= need_mb + RESERVE_MB:
                    return
                if server.running and not server.busy:
                    server.stop("为人声分离腾出内存")

    def _stop_idle(self) -> None:
        with self.lock:
            now = time.time()
            for server in self.servers.values():
                if server.running and not server.busy and now - server.last_used >= self.idle_seconds:
                    server.stop(f"空闲超过 {self.idle_seconds / 60:g} 分钟" if self.idle_seconds else "")

    def _idle_loop(self) -> None:
        while not self.stopping.wait(15):
            self._stop_idle()

    def shutdown(self) -> None:
        self.stopping.set()
        for server in self.servers.values():
            server.stop()

    # ---------- 业务 ----------
    def translate(self, text: str, should_stop: Callable[[], bool] | None = None) -> dict:
        """返回 {"text", "seconds", "cached"}；同一句只翻译一次。"""
        with self.translate_lock:
            if text in self.cache:
                return {"text": self.cache[text], "seconds": 0.0, "cached": True}
            if should_stop and should_stop():
                raise InterruptedError("已取消")
            with self.use("translate", should_stop) as server:
                result = server.request({"cmd": "translate", "text": text}, should_stop=should_stop)
            if result.get("text"):
                self.cache[text] = result["text"]
            return {**result, "cached": False}

    def generate(self, request: dict, on_event: Callable[[dict], None] | None = None,
                 should_stop: Callable[[], bool] | None = None) -> dict:
        started = time.time()
        with self.use("musicgen", should_stop) as server:
            waited = time.time() - started                 # 等待模型加载（已常驻时约为 0）
            result = server.request({"cmd": "generate", **request}, on_event=on_event, should_stop=should_stop)
        result["load_seconds"] = round(waited, 3)
        return result
