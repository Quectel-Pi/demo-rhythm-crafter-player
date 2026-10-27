"""云端"提示词转歌曲"（Coze 工作流 + Doubao-音乐生成插件 gen_song 工具）。

和本机的 MusicGen 不一样：这里不做本地推理，而是把提示词发送到 Coze（字节跳动）的服务器，
用 Doubao 音乐大模型生成一首带自动编写歌词、真人声演唱的完整歌曲，再把结果下载回本地。
默认关闭（config.json 的 cloud_song_enabled），开启后每次生成都会联网、按量计费，
配置和隐私说明见 README.md 的“云端歌曲”章节。

准备工作（一次性，在 https://www.coze.cn 完成，不在本程序里做）：
  1. 新建一个工作流：开始节点加一个 `prompt`（字符串）输入参数；
     添加插件节点 → 搜索"Doubao-音乐生成" → 选 gen_song 工具，把 prompt 接过去；
     结束节点接出 AudioUrl / Lyrics / Duration。试运行确认能跑出真实音频链接后发布。
  2. 工作流编排页面 URL 里 workflow_id= 后面的数字就是 workflow_id。
  3. 账号设置 → 扣子 API → 个人访问令牌，创建一个 PAT。
  4. 在 ~/.config/wave-music/config.json 里填：
     {"cloud_song_enabled": true, "cloud_song_workflow_id": "...", "cloud_song_token": "你的令牌"}

接口文档：https://docs.coze.cn/developer_guides_workflow_run（非流式，90 秒超时）。
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

API_URL = "https://api.coze.cn/v1/workflow/run"
TIMEOUT = 90  # 官方文档：非流式接口 90 秒未收到响应即断开


def _post(workflow_id: str, token: str, prompt: str) -> dict:
    body = json.dumps({"workflow_id": workflow_id, "parameters": {"prompt": prompt}}).encode("utf-8")
    request = urllib.request.Request(API_URL, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "ignore")[:200]
        raise RuntimeError(f"Coze 接口请求失败（HTTP {error.code}）：{detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"无法连接 Coze 服务（{error.reason}），请检查网络") from error
    except TimeoutError as error:
        raise RuntimeError("Coze 接口响应超时（超过 90 秒），请稍后重试") from error


def _download(url: str, out_dir: Path) -> Path:
    suffix = ".wav" if url.lower().split("?")[0].endswith(".wav") else ".mp3"
    path = out_dir / f"bgm{suffix}"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response, open(path, "wb") as handle:
            while True:
                chunk = response.read(1 << 16)
                if not chunk:
                    break
                handle.write(chunk)
    except urllib.error.URLError as error:
        raise RuntimeError(f"下载生成的音频失败（{error.reason}）") from error
    return path


def generate_song(prompt: str, workflow_id: str, token: str, out_dir: Path,
                  progress: Callable[[str, float], None] | None = None,
                  should_stop: Callable[[], bool] | None = None) -> dict:
    """返回 done 事件内容（与本地 MusicGen 的 generate_to_dir 同形状，可直接 library.add_generated()）：
    {"path", "summary", "seconds", "prompt_en", "duration", "elapsed"}；meta.json 额外存生成的歌词。"""
    report = progress or (lambda stage, value: None)
    started = time.time()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    report("cloud_request", 0.05)
    payload = _post(workflow_id, token, prompt)
    if should_stop and should_stop():
        raise InterruptedError("已取消")
    if payload.get("code"):
        raise RuntimeError(f"Coze 工作流执行失败：{payload.get('msg') or payload.get('code')}")

    try:
        data = json.loads(payload["data"])
    except (KeyError, ValueError, TypeError) as error:
        raise RuntimeError("Coze 返回的数据格式不对，请检查工作流结束节点是否输出了 AudioUrl") from error
    audio_url = data.get("AudioUrl")
    if not audio_url:
        raise RuntimeError("Coze 未返回音频链接，可能触发了内容安全审核，换一种描述再试")

    report("download", 0.6)
    audio_path = _download(audio_url, out_dir)
    if should_stop and should_stop():
        raise InterruptedError("已取消")

    seconds = float(data.get("Duration") or 0.0)
    lyrics = data.get("Lyrics") or ""
    summary = f"{seconds:.0f} s (cloud song)" if seconds else "cloud song"
    meta = {
        "engine": "coze-doubao-song", "prompt": prompt, "prompt_en": prompt, "lyrics": lyrics,
        "summary": summary, "duration": round(seconds), "seed": None,
        "elapsed": round(time.time() - started, 3), "created_at": time.time(),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
    report("done", 0.97)
    return {"path": str(audio_path), "summary": summary, "seconds": seconds, "duration": round(seconds),
            "prompt_en": prompt, "lyrics": lyrics, "elapsed": meta["elapsed"], "engine": "coze-doubao-song"}
