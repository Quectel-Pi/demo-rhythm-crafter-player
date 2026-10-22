"""路径、配置文件与 AI 运行环境探测。

用户配置文件：~/.config/wave-music/config.json，可选字段：
  ai_python    —— 装有 sherpa-onnx 与 numpy 的 Python 解释器路径
  models_dir   —— 模型目录（内含 sherpa-onnx-spleeter-2stems-fp16/）
  ai_threads   —— 分离时使用的 CPU 线程数
  cloud_song_enabled      —— 是否开启云端「提示词转歌曲」（Coze，默认 false，需联网且按量计费）
  cloud_song_workflow_id  —— Coze 工作流 ID（见 ai/cloud_song.py 搭建说明）
  cloud_song_token        —— Coze 个人访问令牌（PAT）
同名环境变量（大写、WAVE_MUSIC_ 前缀）优先级最高。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

APP_NAME = "Rhythm Crafter Player"          # 窗口标题与应用名（界面为英文）
APP_ID = "io.github.wavemusic"
APP_DIR = Path(__file__).resolve().parent.parent

_XDG = lambda var, default: Path(os.environ.get(var) or (Path.home() / default))  # noqa: E731
CONFIG_DIR = _XDG("XDG_CONFIG_HOME", ".config") / "wave-music"
DATA_DIR = _XDG("XDG_DATA_HOME", ".local/share") / "wave-music"
CACHE_DIR = _XDG("XDG_CACHE_HOME", ".cache") / "wave-music"
CONFIG_FILE = CONFIG_DIR / "config.json"
DB_FILE = DATA_DIR / "library.db"
STEMS_DIR = CACHE_DIR / "stems"

SPLEETER_MODEL = "sherpa-onnx-spleeter-2stems-fp16"
SPLEETER_FILES = ("vocals.fp16.onnx", "accompaniment.fp16.onnx")
MUSICGEN_MODEL = "musicgen-small-onnx"
MUSICGEN_FILES = ("tokenizer.json", "config.json", "onnx/text_encoder_int8.onnx",
                  "onnx/decoder_model_merged_int8.onnx", "onnx/encodec_decode.onnx")

AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".aac", ".aif", ".aiff", ".wma", ".ape",
}


def load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def _setting(cfg: dict, key: str):
    return os.environ.get(f"WAVE_MUSIC_{key.upper()}") or cfg.get(key)


def _generated_dir() -> Path:
    """AI 作曲作品目录：config.json 的 generated_dir / 环境变量 WAVE_MUSIC_GENERATED_DIR 优先；
    从源码目录运行（有 .git）时放在项目文件夹下的 generated/；安装版放在用户数据目录，避免重装、卸载程序时被删。"""
    override = _setting(load_config(), "generated_dir")
    if override:
        return Path(override).expanduser()
    if (APP_DIR / ".git").exists():
        return APP_DIR / "generated"
    return DATA_DIR / "generated"


GENERATED_DIR = _generated_dir()


def find_ui_dir() -> Path | None:
    for candidate in (os.environ.get("WAVE_MUSIC_UI"), APP_DIR / "ui", Path("/usr/share/wave-music/ui")):
        if candidate and (Path(candidate) / "index.html").is_file():
            return Path(candidate)
    return None


def find_icon() -> str | None:
    for path in (APP_DIR / "packaging" / "wave-music.svg", APP_DIR / "wave-music.svg"):
        if path.is_file():
            return str(path)
    return None


def _model_roots(cfg: dict) -> list[Path]:
    roots = [_setting(cfg, "models_dir"), APP_DIR / "models", DATA_DIR / "models", Path("/usr/share/wave-music/models")]
    return [Path(r).expanduser() for r in roots if r]


def find_musicgen_dir(cfg: dict) -> Path | None:
    for base in _model_roots(cfg):
        model_dir = base / MUSICGEN_MODEL
        if all((model_dir / name).is_file() for name in MUSICGEN_FILES):
            return model_dir
    return None


TRANSLATE_MODELS = {"0.5b": "qwen2.5-0.5b-instruct-onnx", "1.5b": "qwen2.5-1.5b-instruct-onnx"}


def find_translate_dir(cfg: dict) -> tuple[Path | None, str | None]:
    """中文描述翻译模型（Qwen2.5-Instruct int8）。config translate_model：0.5b / 1.5b；
    默认物理内存 ≥ 8GB 且有 1.5B 时用 1.5B（翻译更准，约 4GB 内存），否则 0.5B（约 1.7GB，开发板可用）。"""
    wanted = str(_setting(cfg, "translate_model") or "").lower()
    order = [wanted] if wanted in TRANSLATE_MODELS else (["1.5b", "0.5b"] if total_memory_gb() >= 8 else ["0.5b", "1.5b"])
    for size in order:
        for base in _model_roots(cfg):
            model_dir = base / TRANSLATE_MODELS[size]
            if (model_dir / "tokenizer.json").is_file() and (model_dir / "onnx" / "model_int8.onnx").is_file():
                return model_dir, size
    return None, None


def total_memory_gb() -> float:
    try:
        with open("/proc/meminfo", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / 1024 / 1024
    except (OSError, ValueError):
        pass
    return 0.0


def musicgen_low_memory(cfg: dict) -> str:
    """MusicGen 低内存模式：只关闭 CPU 内存池（RK3576 实测峰值 1.63GB → 1.33GB，速度不变）。
    配置 musicgen_low_memory：true / false / "arena" / "prepack,arena"；默认按物理内存自动（< 6GB 开启）。
    注意："prepack"（关闭权重预打包）在 ARM 上会让 int8 解码慢约 6.5 倍（RK3576：9.9 → 1.5 步/秒），
    x86 上只慢约 20%；只在内存确实不够时手动指定。"""
    value = _setting(cfg, "musicgen_low_memory")
    if isinstance(value, str) and value.lower() in ("true", "1", "yes"):
        value = True
    elif isinstance(value, str) and value.lower() in ("false", "0", "no", ""):
        value = False
    if value is None:
        value = 0 < total_memory_gb() < 6
    if value is True:
        return "arena"
    return value or ""


def find_spleeter_dir(cfg: dict) -> Path | None:
    candidates = [
        _setting(cfg, "models_dir"),
        APP_DIR / "models",
        DATA_DIR / "models",
        Path("/usr/share/wave-music/models"),
    ]
    for base in candidates:
        if not base:
            continue
        model_dir = Path(base).expanduser() / SPLEETER_MODEL
        if all((model_dir / name).is_file() for name in SPLEETER_FILES):
            return model_dir
    return None


def _python_ok(python: str, check: str = "import numpy, sherpa_onnx; sherpa_onnx.OfflineSourceSeparation") -> bool:
    try:
        result = subprocess.run(
            [python, "-c", check],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _python_candidates(cfg: dict) -> list[str]:
    candidates = [
        _setting(cfg, "ai_python"),
        str(APP_DIR / ".venv" / "bin" / "python"),
        str(DATA_DIR / "venv" / "bin" / "python"),
        sys.executable,
    ]
    seen, result = set(), []
    for python in candidates:
        if not python:
            continue
        python = os.path.expanduser(python)
        if python in seen or not os.path.exists(python):
            continue
        seen.add(python)
        result.append(python)
    return result


def find_ai_python(cfg: dict) -> str | None:
    for python in _python_candidates(cfg):
        if _python_ok(python):
            return python
    return None


def find_numpy_python(cfg: dict, preferred: str | None = None) -> str | None:
    """AI 作曲只需要 numpy；优先复用人声分离的解释器。"""
    for python in ([preferred] if preferred else []) + _python_candidates(cfg):
        if _python_ok(python, "import numpy"):
            return python
    return None


def ai_threads(cfg: dict) -> int:
    value = _setting(cfg, "ai_threads")
    try:
        if value:
            return max(1, int(value))
    except ValueError:
        pass
    # RK3576 为 4 大核 + 4 小核，默认只用 4 线程，避免抢占界面与播放
    return max(1, min(4, os.cpu_count() or 2))


def translate_info(cfg: dict, python: str | None, runtime_ok: bool) -> dict:
    model_dir, size = find_translate_dir(cfg)
    reason = ""
    if not model_dir:
        reason = "未找到中文翻译模型（运行 scripts/setup-translate.sh）"
    elif not runtime_ok:
        reason = "缺少 onnxruntime / tokenizers"
    return {"available": not reason, "python": python, "model_dir": str(model_dir) if model_dir else None,
            "size": size, "low_memory": translate_low_memory(cfg), "reason": reason}


def warm_idle_minutes(cfg: dict) -> float:
    """常驻模型（翻译 / MusicGen）空闲多少分钟后释放内存；0 表示每次用完立即释放（不常驻）。默认 5 分钟。"""
    value = _setting(cfg, "warm_idle_minutes")
    try:
        return max(0.0, float(value)) if value is not None and value != "" else 5.0
    except (TypeError, ValueError):
        return 5.0


def translate_low_memory(cfg: dict) -> bool:
    """翻译模型低内存模式（只关闭内存池）。默认关闭：逐词前向时关闭内存池，RK3576 实测慢 2.3 倍（27 → 53 秒），
    只省约 100MB；与 MusicGen 不同时驻留内存，不需要跟随 musicgen_low_memory。"""
    value = _setting(cfg, "translate_low_memory")
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return bool(value)


def cloud_song_info(cfg: dict) -> dict:
    """云端「提示词转歌曲」的可用状态（发给界面，不带 token）。Coze 工作流 + Doubao-音乐生成插件
    gen_song 工具，详见 ai/cloud_song.py。
    默认关闭（需要用户自己在 Coze 平台搭工作流并在 config.json 里配置），开启后每次生成都会把
    描述发送到 Coze（字节）服务器，按量计费，不再是本机推理。
    config.json 字段：cloud_song_enabled（bool）、cloud_song_workflow_id、cloud_song_token。"""
    enabled, workflow_id, token = _cloud_song_raw(cfg)
    reason = ""
    if not enabled:
        reason = "云端生成默认关闭（config.json 设置 cloud_song_enabled=true 后开启）"
    elif not workflow_id or not token:
        reason = "未配置 cloud_song_workflow_id / cloud_song_token（见 config.json）"
    return {"available": enabled and bool(workflow_id) and bool(token), "reason": reason}


def _cloud_song_raw(cfg: dict) -> tuple[bool, str | None, str | None]:
    enabled = _setting(cfg, "cloud_song_enabled")
    enabled = enabled.lower() in ("true", "1", "yes") if isinstance(enabled, str) else bool(enabled)
    return enabled, _setting(cfg, "cloud_song_workflow_id"), _setting(cfg, "cloud_song_token")


def cloud_song_credentials(cfg: dict) -> tuple[str, str] | None:
    """实际发起请求时调用：返回 (workflow_id, token)，未开启/未配置返回 None。不进入发往界面的数据。"""
    enabled, workflow_id, token = _cloud_song_raw(cfg)
    if enabled and workflow_id and token:
        return str(workflow_id), str(token)
    return None


def detect_ai_environment() -> dict:
    """返回分离功能的可用状态（可能耗时数秒，应在后台线程调用）。"""
    cfg = load_config()
    python = find_ai_python(cfg)
    model = find_spleeter_dir(cfg)
    gst = any((Path(p) / "gst-launch-1.0").exists() for p in os.environ.get("PATH", "/usr/bin").split(":"))
    reasons = []
    if not python:
        reasons.append("未找到装有 sherpa-onnx 的 Python（运行 scripts/setup-ai.sh 或在 config.json 设置 ai_python）")
    if not model:
        reasons.append("未找到 Spleeter 模型（运行 scripts/fetch-models.sh）")
    if not gst:
        reasons.append("缺少 gst-launch-1.0（sudo apt install gstreamer1.0-tools）")
    compose_python = find_numpy_python(cfg, python)
    compose_reasons = []
    musicgen_dir = find_musicgen_dir(cfg)
    if not musicgen_dir:
        compose_reasons.append("未找到 AI 作曲模型（运行 scripts/setup-musicgen.sh）")
    if not compose_python or not _python_ok(compose_python, "import numpy, onnxruntime, tokenizers"):
        compose_reasons.append("缺少装有 numpy / onnxruntime / tokenizers 的 Python（运行 scripts/setup-ai.sh）")
    return {
        "available": not reasons,
        "python": python,
        "model_dir": str(model) if model else None,
        "threads": ai_threads(cfg),
        "warm_idle_minutes": warm_idle_minutes(cfg),
        "reason": "；".join(reasons),
        "translate": translate_info(cfg, compose_python, not compose_reasons),
        "compose": {
            "available": not compose_reasons,
            "python": compose_python,
            "model_dir": str(musicgen_dir) if musicgen_dir else None,
            "low_memory": musicgen_low_memory(cfg),
            "generated_dir": str(GENERATED_DIR),
            "reason": "；".join(compose_reasons),
        },
        "cloud_song": cloud_song_info(cfg),
    }
