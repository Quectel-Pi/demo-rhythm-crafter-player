"""界面文案的英文化：后端发往界面的消息（错误提示、AI 未就绪原因等）在这里统一译成英文。

后端源码与终端日志保留原来的中文；只有经过消息桥发给页面的内容（回复错误、推送事件、app.init / ai.status
返回的 AI 环境）才调用 ui_text / localize。新增发往界面的中文消息时，请在 RULES 中补充对应的译文
（tests/test_i18n.py 会检查已知消息都能译成英文）。
"""
from __future__ import annotations

import copy
import re

CJK = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")

# (正则, 英文模板)。按顺序匹配整条消息；模板中的 {1}、{2} 为捕获组，捕获内容会继续递归翻译；
# {=1} 表示原样保留（用户输入的内容，例如歌单名）。
RULES: list[tuple[re.Pattern, str]] = [(re.compile(pattern, re.S), template) for pattern, template in [
    # 应用与消息桥
    (r"曲目不存在", "Track not found"),
    (r"AI 环境检测中，请稍候再试", "Checking the AI environment, please try again in a moment"),
    (r"源文件不存在", "Source file not found"),
    (r"该曲目已在处理队列中", "This track is already in the queue"),
    (r"中文翻译不可用", "Chinese translation is unavailable"),
    (r"AI 作曲不可用", "AI Compose is unavailable"),
    (r"请先输入音乐描述", "Please enter a music description first"),
    (r"翻译结果为空，请换一种说法或直接用英文描述",
     "The translation came back empty. Try rephrasing, or describe the music in English"),
    (r"未知命令：(.*)", "Unknown command: {1}"),
    (r"内部错误：(.*)", "Internal error: {1}"),
    (r"无法加入曲库：(.*)", "Could not add to the library: {1}"),
    # 云端歌词转歌曲（config.py cloud_song_info / ai/cloud_song.py）
    (r"云端生成不可用", "Cloud song generation is unavailable"),
    (r"云端生成默认关闭（config\.json 设置 cloud_song_enabled=true 后开启）",
     "Cloud song generation is off by default (set cloud_song_enabled=true in config.json to turn it on)"),
    (r"未配置 cloud_song_workflow_id / cloud_song_token（见 config\.json）",
     "cloud_song_workflow_id / cloud_song_token is not configured (see config.json)"),
    (r"Coze 接口请求失败（HTTP (.*)）：(.*)", "Coze API request failed (HTTP {=1}): {=2}"),
    (r"无法连接 Coze 服务（(.*)），请检查网络", "Could not reach the Coze service ({=1}); check your network"),
    (r"Coze 接口响应超时（超过 90 秒），请稍后重试", "The Coze API timed out (over 90 seconds); please try again later"),
    (r"下载生成的音频失败（(.*)）", "Failed to download the generated audio ({=1})"),
    (r"Coze 工作流执行失败：(.*)", "The Coze workflow failed: {=1}"),
    (r"Coze 返回的数据格式不对，请检查工作流结束节点是否输出了 AudioUrl",
     "The data Coze returned has the wrong shape; check that the workflow's End node outputs AudioUrl"),
    (r"Coze 未返回音频链接，可能触发了内容安全审核，换一种描述再试",
     "Coze did not return an audio link (it may have been blocked by content moderation); try a different description"),
    # AI 环境探测（config.py）
    (r"未找到中文翻译模型（运行 scripts/setup-translate\.sh）",
     "Chinese translation model not found (run scripts/setup-translate.sh)"),
    (r"缺少 onnxruntime / tokenizers", "onnxruntime / tokenizers is missing"),
    (r"未找到装有 sherpa-onnx 的 Python（运行 scripts/setup-ai\.sh 或在 config\.json 设置 ai_python）",
     "No Python with sherpa-onnx found (run scripts/setup-ai.sh, or set ai_python in config.json)"),
    (r"未找到 Spleeter 模型（运行 scripts/fetch-models\.sh）", "Spleeter model not found (run scripts/fetch-models.sh)"),
    (r"缺少 gst-launch-1\.0（sudo apt install gstreamer1\.0-tools）",
     "gst-launch-1.0 is missing (sudo apt install gstreamer1.0-tools)"),
    (r"未找到 AI 作曲模型（运行 scripts/setup-musicgen\.sh）", "AI Compose model not found (run scripts/setup-musicgen.sh)"),
    (r"缺少装有 numpy / onnxruntime / tokenizers 的 Python（运行 scripts/setup-ai\.sh）",
     "No Python with numpy / onnxruntime / tokenizers found (run scripts/setup-ai.sh)"),
    # 歌单（library.py）
    (r"歌单名称不能为空", "Playlist name cannot be empty"),
    (r"歌单名称最多 (.+) 个字", "Playlist name can be at most {=1} characters"),
    (r"已经有名为「(.*)」的歌单", "A playlist named \u201c{=1}\u201d already exists"),
    (r"歌单不存在", "Playlist not found"),
    # 任务队列与工作进程
    (r"无法启动 AI 进程：(.*)", "Could not start the AI process: {1}"),
    (r"AI 进程异常退出", "The AI process exited unexpectedly"),
    (r"已取消", "Cancelled"),
    (r"中文描述需要翻译模型（运行 scripts/setup-translate\.sh），或直接用英文描述",
     "Chinese descriptions need the translation model (run scripts/setup-translate.sh), or describe the music in English"),
    (r"解码失败：(.*)", "Decoding failed: {1}"),
    (r"未知错误", "unknown error"),
    (r"模型配置无效：(.*)", "Invalid model configuration: {1}"),
    (r"音频过短或无法解码", "The audio is too short or cannot be decoded"),
    # 常驻模型（warm.py / model_server.py）
    (r"模型进程未运行", "The model process is not running"),
    (r"模型进程不可用：(.*)", "The model process is unavailable: {1}"),
    (r"模型进程出错", "The model process reported an error"),
    (r"模型进程已结束", "The model process was stopped"),
    (r"模型进程意外退出（可能内存不足）", "The model process exited unexpectedly (possibly out of memory)"),
    (r"模型进程意外退出（(.*)）", "The model process exited unexpectedly ({1})"),
    (r"退出码 (-?\d+)", "exit code {1}"),
    (r"模型加载失败：(.*)", "Failed to load the model: {1}"),
    (r"模型加载失败", "Failed to load the model"),
    (r"不支持的请求：(.*)（(.*) 进程）", "Unsupported request: {1} ({2} process)"),
]]

UI_KEYS = ("message", "reason", "error")      # 事件 / 返回值中需要翻译的字段


def ui_text(text):
    """把一条后端消息译成英文；不认识的消息原样返回。多条原因以“；”连接时逐条翻译。"""
    if not isinstance(text, str) or not CJK.search(text):
        return text
    for pattern, template in RULES:
        match = pattern.fullmatch(text.strip())
        if match:
            result = template
            for index, group in enumerate(match.groups(), start=1):
                result = result.replace(f"{{={index}}}", group or "").replace(f"{{{index}}}", ui_text(group or ""))
            return result
    if "；" in text:
        return "; ".join(ui_text(part) for part in text.split("；"))
    return text


def localize(data):
    """返回 data 的副本，其中 message / reason / error 字段（任意深度）已译成英文。"""
    if isinstance(data, dict):
        return {key: ui_text(value) if key in UI_KEYS and isinstance(value, str) else localize(value)
                for key, value in data.items()}
    if isinstance(data, list):
        return [localize(item) for item in data]
    return copy.copy(data)
