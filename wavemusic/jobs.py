"""AI 任务队列：人声分离与 AI 作曲共用，一次只运行一个子进程（开发板 CPU / 内存有限）。

每个任务以 (kind, id) 标识，kind 为 "stems"（人声分离，id = 曲目 id）或 "bgm"（AI 作曲，id = 作曲任务号）。
事件名为 "<kind>.queued / progress / done / error / cancelled"，通过 emit 回调交给调用方（工作线程中调用）。
子进程按 JSON 行汇报：{"event": "progress", ...} / {"event": "done", ...} / {"event": "error", "message": ...}
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import APP_DIR

SEPARATE_WORKER = APP_DIR / "ai" / "separate_worker.py"
GENERATE_WORKER = APP_DIR / "ai" / "generate_worker.py"


@dataclass
class Job:
    kind: str
    id: int
    command: list[str]
    out_dir: Path
    cleanup: tuple[str, ...] = ()       # 取消时删除的文件
    remove_dir: bool = False            # 取消 / 失败时删除整个输出目录
    extra: dict = field(default_factory=dict)  # 原样带回 done 事件
    # 不启动子进程，而是在队列线程中调用 runner(progress, should_stop) → done 内容（常驻模型进程用）；
    # 取消时 should_stop() 返回 True，runner 应抛出 InterruptedError
    runner: Callable[[Callable[[dict], None], Callable[[], bool]], dict] | None = None

    @property
    def key(self) -> tuple[str, int]:
        return self.kind, self.id


class AIJobQueue:
    def __init__(self, emit: Callable[[str, dict], None], prepare: Callable[[Job], None] | None = None):
        """emit(event, payload) 会在工作线程中调用，调用方需自行切回主线程。
        prepare(job) 在每个任务开始前于工作线程中调用（例如为人声分离释放空闲的常驻模型）。"""
        self.emit = emit
        self.prepare = prepare
        self.pending: deque[Job] = deque()
        self.current: Job | None = None
        self.process: subprocess.Popen | None = None
        self.cancelled: set[tuple[str, int]] = set()
        self.lock = threading.Lock()
        self.wakeup = threading.Event()
        self.stopping = False
        self.thread = threading.Thread(target=self._run, name="ai-jobs", daemon=True)
        self.thread.start()

    # ---------- 提交 ----------
    def submit_separation(self, track_id: int, source: str, out_dir: Path, env: dict) -> bool:
        command = [
            env["python"], str(SEPARATE_WORKER), "--input", source, "--output", str(out_dir),
            "--model-dir", env["model_dir"], "--threads", str(env["threads"]),
        ]
        cleanup = ("vocals.wav", "accompaniment.wav", "meta.json", "vocals.tmp", "accompaniment.tmp")
        return self.submit(Job("stems", track_id, command, out_dir, cleanup=cleanup))

    def submit_generation(self, job_id: int, prompt: str, seconds: int, out_dir: Path, python: str,
                          extra: dict | None = None, extra_args: list[str] | None = None) -> bool:
        command = [python, str(GENERATE_WORKER), "--prompt", prompt, "--seconds", str(seconds),
                   "--output", str(out_dir), *(extra_args or [])]
        return self.submit(Job("bgm", job_id, command, out_dir, remove_dir=True, extra=extra or {}))

    def submit_runner(self, kind: str, job_id: int, runner, out_dir: Path, extra: dict | None = None) -> bool:
        return self.submit(Job(kind, job_id, [], out_dir, remove_dir=True, extra=extra or {}, runner=runner))

    def submit(self, job: Job) -> bool:
        with self.lock:
            if (self.current and self.current.key == job.key) or any(j.key == job.key for j in self.pending):
                return False
            self.cancelled.discard(job.key)
            self.pending.append(job)
        self.emit(f"{job.kind}.queued", {"id": job.id})
        self.wakeup.set()
        return True

    # ---------- 状态 / 取消 ----------
    def status(self) -> dict:
        """兼容旧格式：running / queued 为人声分离；bgm 为作曲任务。"""
        with self.lock:
            def of(kind):
                running = self.current.id if self.current and self.current.kind == kind else None
                return running, [j.id for j in self.pending if j.kind == kind]
            stems_running, stems_queued = of("stems")
            bgm_running, bgm_queued = of("bgm")
        return {"running": stems_running, "queued": stems_queued,
                "bgm": {"running": bgm_running, "queued": bgm_queued}}

    def cancel(self, kind: str, job_id: int) -> None:
        key = (kind, job_id)
        removed = None
        with self.lock:
            for job in self.pending:
                if job.key == key:
                    removed = job
            if removed:
                self.pending.remove(removed)
            if self.current and self.current.key == key:
                # 进程可能还没启动（已出队、尚未 Popen）：先记下，_execute 启动前 / 启动后都会检查
                self.cancelled.add(key)
                if self.process:
                    self.process.terminate()
        if removed:
            if removed.remove_dir:
                shutil.rmtree(removed.out_dir, ignore_errors=True)
            self.emit(f"{kind}.cancelled", {"id": job_id})

    def shutdown(self) -> None:
        self.stopping = True
        with self.lock:
            self.pending.clear()
            if self.process:
                self.process.kill()
        self.wakeup.set()

    # ---------- 工作线程 ----------
    def _run(self) -> None:
        while not self.stopping:
            self.wakeup.wait()
            with self.lock:
                if not self.pending:
                    self.wakeup.clear()
                    continue
                job = self.pending.popleft()
                self.current = job
            try:
                self._execute(job)
            except Exception as error:  # noqa: BLE001 —— 单个任务异常不能让队列线程退出
                self.emit(f"{job.kind}.error", {"id": job.id, "message": f"内部错误：{error}"})
            finally:
                with self.lock:
                    self.current = None
                    self.process = None

    def _execute(self, job: Job) -> None:
        self.emit(f"{job.kind}.progress", {"id": job.id, "progress": 0.0, "stage": "start"})
        if self.prepare:
            try:
                self.prepare(job)
            except Exception as error:  # noqa: BLE001
                print(f"[AI] 任务准备失败：{error}", file=sys.stderr)
        if job.runner:
            self._execute_runner(job)
            return
        try:
            with self.lock:
                if job.key in self.cancelled:     # 出队后、启动前就被取消
                    self.cancelled.discard(job.key)
                    cancelled_early = True
                else:
                    cancelled_early = False
                    self.process = subprocess.Popen(
                        job.command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1,
                    )
            if cancelled_early:
                self._cleanup(job)
                self.emit(f"{job.kind}.cancelled", {"id": job.id})
                return
            process = self.process
        except OSError as error:
            self.emit(f"{job.kind}.error", {"id": job.id, "message": f"无法启动 AI 进程：{error}"})
            return

        result: dict | None = None
        for line in process.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            event = message.pop("event", None)
            if event == "progress":
                self.emit(f"{job.kind}.progress", {"id": job.id, **message})
            elif event in ("done", "error"):
                result = {"event": event, **message}
        stderr = process.stderr.read()
        process.wait()

        if job.key in self.cancelled:
            self.cancelled.discard(job.key)
            self._cleanup(job)
            self.emit(f"{job.kind}.cancelled", {"id": job.id})
        elif result and result["event"] == "done":
            self.emit(f"{job.kind}.done", {"id": job.id, "meta": result, **job.extra})
        else:
            if stderr.strip():
                print(stderr.strip()[-2000:], file=sys.stderr)
            if job.remove_dir:
                self._cleanup(job)
            message = (result or {}).get("message") or (stderr.strip().splitlines() or ["AI 进程异常退出"])[-1]
            self.emit(f"{job.kind}.error", {"id": job.id, "message": message})

    def _execute_runner(self, job: Job) -> None:
        def progress(message: dict) -> None:
            self.emit(f"{job.kind}.progress", {"id": job.id, **message})

        try:
            result = job.runner(progress, lambda: job.key in self.cancelled or self.stopping)
        except InterruptedError:
            self.cancelled.discard(job.key)
            self._cleanup(job)
            self.emit(f"{job.kind}.cancelled", {"id": job.id})
            return
        except Exception as error:  # noqa: BLE001
            self.cancelled.discard(job.key)
            self._cleanup(job)
            self.emit(f"{job.kind}.error", {"id": job.id, "message": str(error) or type(error).__name__})
            return
        if job.key in self.cancelled:                 # 完成的同时被取消：按取消处理
            self.cancelled.discard(job.key)
            self._cleanup(job)
            self.emit(f"{job.kind}.cancelled", {"id": job.id})
            return
        self.emit(f"{job.kind}.done", {"id": job.id, "meta": {"event": "done", **result}, **job.extra})

    @staticmethod
    def _cleanup(job: Job) -> None:
        if job.remove_dir:
            shutil.rmtree(job.out_dir, ignore_errors=True)
        for name in job.cleanup:
            (job.out_dir / name).unlink(missing_ok=True)
