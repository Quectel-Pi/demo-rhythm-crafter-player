# Rhythm Crafter Player — Quectel PI M2 本地 AI 音乐播放器

[English](README_EN.md) | 简体中文

Rhythm Crafter Player 是一个面向 **Quectel PI M2** 智能主控板的本地 AI 音乐播放器。它把本地曲库、歌单、Web Audio 实时音效、人声与伴奏分离，以及文字生成音乐整合在一个桌面应用中。

应用基于 GTK3、WebKit2GTK、GStreamer、SQLite 和 Python 构建；AI 推理由 ONNX Runtime 与 sherpa-onnx 在设备端完成。运行时不启动 HTTP 服务，不需要登录账号，歌曲、提示词、分离结果和 AI 作品均保存在本机。

除一个**默认关闭**的可选功能外，所有处理都在本机完成：开启“云端歌曲”后，应用会把音乐描述发送到 Coze（字节跳动扣子）的工作流，用豆包音乐大模型生成一首带 AI 写词与人声演唱的完整歌曲，并按平台规则计费。该功能需要在 `config.json` 中手动开启并填写自己的令牌，详见[云端歌曲](#云端歌曲可选需要联网)。

## 为什么选择 Quectel PI M2

Quectel PI M2 基于 Rockchip RK3576，提供八核 64 位 CPU、4 GB LPDDR4X、64 GB eMMC、HDMI 2.1、音频接口和完整的 Debian 13 GNOME 桌面环境，适合展示端侧 AI、多媒体和桌面应用的组合能力。

本项目针对 4 GB 设备做了专门设计：

- AI 任务全局单并发，避免 Spleeter 与 MusicGen 同时争抢内存。
- 默认最多使用 4 个推理线程，给桌面和播放保留资源。
- 低于 6 GB 内存时，MusicGen 自动关闭 CPU 内存池，RK3576 实测峰值约从 1.63 GB 降至 1.33 GB，速度基本不变。
- 中文翻译默认选用 Qwen2.5-0.5B；不建议在标准 4 GB PI M2 上使用 1.5B 模型。
- 翻译模型和 MusicGen 由常驻子进程按需加载，在 4 GB 设备上根据可用内存轮换驻留。
- 模型空闲默认 5 分钟后释放，也可配置为每次用完立即释放。

当前模型通过 ONNX Runtime `CPUExecutionProvider` 在 RK3576 CPU 上运行。PI M2 集成的 6 TOPS NPU 尚未用于本项目；将模型转换为 RKNN 是后续优化方向。

- [Quectel PI M2 产品页](https://www.quectel.com.cn/quectel-pi/quectel-pi)
- [Quectel PI M2 官方支持清单](https://docs.quectel.com/zh/Quectel%20Pi/Quectel%20Pi%20M2/%E6%94%AF%E6%8C%81%E6%B8%85%E5%8D%95/%E6%94%AF%E6%8C%81%E6%B8%85%E5%8D%95.html)

## 功能

- **本地曲库**：添加单个文件、多个文件或整个文件夹，也可以把音频拖入窗口。
- **格式与标签**：支持 MP3、WAV、FLAC、OGG、Opus、M4A、AAC、AIFF、WMA、APE 等格式；使用 GStreamer 读取标题、歌手、专辑和时长。
- **播放控制**：播放全部、上一首、下一首、随机、单曲循环、进度拖动、音量、搜索和快捷键。
- **自建歌单**：创建、重命名、删除歌单，按歌单顺序播放，并在不删除源歌曲的情况下移除歌单项目。
- **正在播放**：黑胶唱片动画、实时频谱、歌曲和当前音效信息。
- **音效实验室**：原声、故障电波、深渊低语、空谷回声，以及 0.70×–1.30× 速度与音调调节。
- **AI 人声分离**：生成可复用的人声和伴奏缓存，支持播放中无缝切换。
- **伴奏模式**：K 歌伴奏、只改人声、只改伴奏、清唱人声；人声和伴奏音量可分别调节到 0–150%。
- **AI 作曲**：用中文或英文描述生成 4 秒或 8 秒无歌词音乐，作品自动进入曲库。
- **本地中文翻译**：中文描述由 Qwen2.5-Instruct 转成 MusicGen 使用的英文，并在生成前显示“模型将收到”的实际内容。
- **常驻模型**：预加载并复用翻译与生成模型，减少每次任务重复加载的等待。
- **云端歌曲（可选）**：在 AI 作曲页切换到“云端歌曲”模式，用一句描述生成 2 分钟左右的完整歌曲，自动写词、带人声演唱；歌名取歌词首句，歌词显示在“正在播放”页。默认关闭，需要联网和自己的扣子令牌。
- **中英文界面**：顶栏按钮一键在英文与中文之间切换，选择随设置保存；歌名、歌单名、提示词等用户内容不翻译。
- **离线与隐私**：本地曲库、播放、音效、人声分离与本地 AI 作曲均不上传任何数据；只有手动开启的云端歌曲会把描述发往 Coze。

界面默认英文，可切换到中文。后端发往界面的状态和错误信息由 `wavemusic/i18n.py` 统一转换，终端日志保留中文，便于开发调试。

## 快速开始

### 1. 安装系统依赖

在 Quectel PI M2 的 Debian 13 桌面终端执行：

```bash
sudo apt update
sudo apt install python3-gi python3-venv \
  gir1.2-gtk-3.0 gir1.2-webkit2-4.1 gir1.2-gst-plugins-base-1.0 \
  gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad gstreamer1.0-libav
```

如果系统仓库没有 `gir1.2-webkit2-4.1`，可改装 `gir1.2-webkit2-4.0`，程序会自动适配。

### 2. 直接运行播放器

```bash
cd demo-rhythm-crafter-player
./wave_music.py
```

不安装 AI 依赖时，曲库、歌单、播放、搜索和实时音效仍可正常使用；AI 页面会显示缺失项及准备方式。

### 3. 准备 AI 环境

```bash
./scripts/setup-ai.sh
```

脚本默认把用户级 Python 虚拟环境安装到 `~/.local/share/wave-music/venv`。需要 PyPI 镜像时：

```bash
PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple ./scripts/setup-ai.sh
```

### 4. 下载模型

```bash
./scripts/fetch-models.sh ./models  # Spleeter 人声分离模型
./scripts/setup-musicgen.sh         # MusicGen-small
./scripts/setup-translate.sh 0.5b   # PI M2 推荐的 Qwen2.5-0.5B
```

下载脚本支持 `HF_ENDPOINT`，可按网络环境切换 Hugging Face 镜像。

### 5. 推荐配置

创建 `~/.config/wave-music/config.json`：

```json
{
  "translate_model": "0.5b",
  "musicgen_low_memory": true,
  "translate_low_memory": false,
  "warm_idle_minutes": 5,
  "ai_threads": 4
}
```

在 ARM 设备上不要把 `musicgen_low_memory` 设置为 `"prepack,arena"`。关闭权重预打包会让 RK3576 的 INT8 解码速度下降约 6.5 倍；布尔值 `true` 只关闭内存池，对 PI M2 更合适。

## AI 人声分离

```text
本地音频
  -> GStreamer 解码为 44.1 kHz 双声道 float32
  -> 30 秒分块，1 秒重叠
  -> sherpa-onnx Spleeter 2stems
  -> 重叠区域交叉淡化
  -> vocals.wav + accompaniment.wav + meta.json
```

需要可用的 `sherpa-onnx`、`numpy`、Spleeter 模型、`gst-launch-1.0` 和对应音频解码插件。分离结果默认保存到 `~/.cache/wave-music/stems/`。

缓存键包含源文件路径、大小和修改时间；源文件变化后旧结果会自动失效。删除曲目或清空曲库时，对应缓存也会删除。

## AI 作曲（本地，离线）

AI 作曲使用 MusicGen-small 在本地生成 4 秒或 8 秒无歌词音乐。

```text
中文描述
  -> Qwen2.5-Instruct 本地翻译
  -> 英文提示词预览
  -> MusicGen T5 文本编码
  -> CFG + 四码本延迟排列 + top-k 采样 + KV cache
  -> EnCodec 解码为 32 kHz 单声道
  -> 去开头静音、44.1 kHz 重采样、响度统一、淡入淡出
  -> bgm.wav + meta.json
```

MusicGen 模型：

- 原始模型：[facebook/musicgen-small](https://huggingface.co/facebook/musicgen-small)
- ONNX 导出：[Xenova/musicgen-small](https://huggingface.co/Xenova/musicgen-small)

中文翻译模型：

- [Qwen2.5-Instruct](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct)
- ONNX INT8，Apache-2.0
- 翻译要求忠实保留乐器、情绪、场景、速度和风格，不添加原文没有的内容。
- 常见民族乐器和风格使用术语提示，固定指令与示例使用磁盘 KV 前缀缓存。

作品会自动加入曲库并标记为 `AI`。源码运行时保存到项目的 `generated/`，安装版保存到 `~/.local/share/wave-music/generated/`。从曲库删除 AI 作品时，其 WAV 和元数据会一并删除。

## 云端歌曲（可选，需要联网）

本地 MusicGen 只能生成无歌词的短音乐。如果需要在设备上得到一首**带歌词、有人声演唱的完整歌曲**，可以开启“云端歌曲”：本地模型做不到这一点（这类模型参数量在数十亿级，需要 8 GB 以上显存的 GPU），只能由云端模型完成。

这是项目中**唯一需要联网**的功能，默认关闭，不会自动上传任何数据。

### 工作方式

```text
音乐描述（如“一首关于夏天海边的欢快歌曲”）
  -> POST https://api.coze.cn/v1/workflow/run
       Authorization: Bearer <你的扣子令牌>
       {"workflow_id": "...", "parameters": {"prompt": "..."}}
  -> 云端工作流调用“Doubao-音乐生成”插件的 gen_song 工具
  -> 返回 AudioUrl / Lyrics / Duration（JSON 字符串）
  -> 下载音频到 generated/<日期时间-任务号>/
  -> 写 meta.json（含自动生成的歌词）
  -> 以 AI 曲目入库，歌名取歌词首句
```

云端歌曲与人声分离、本地 AI 作曲共用同一个单并发任务队列，因此不会出现多个 AI 任务同时抢内存的情况；进度、取消和失败提示也复用同一套事件。

### 一次性准备（在扣子平台完成，不在设备上）

1. 登录 [扣子（Coze）](https://www.coze.cn)，新建一个工作流。
2. 开始节点添加一个**字符串**输入参数 `prompt`。
3. 添加插件节点，搜索 **Doubao-音乐生成**，选择 `gen_song` 工具（按提示词自动写词并演唱），把 `prompt` 接过去。
4. 结束节点输出 `AudioUrl`、`Lyrics`、`Duration` 三个字段。
5. 试运行确认能拿到真实音频链接后**发布**工作流。
6. 记下工作流编排页 URL 中 `workflow_id=` 后面的数字。
7. 在“账号设置 → 扣子 API → 个人访问令牌”创建一个令牌（`pat_` 开头）。

### 在设备上开启

编辑 `~/.config/wave-music/config.json`，增加三个键：

```json
{
  "cloud_song_enabled": true,
  "cloud_song_workflow_id": "你的工作流 ID",
  "cloud_song_token": "pat_你的令牌"
}
```

也可以用环境变量 `WAVE_MUSIC_CLOUD_SONG_ENABLED`、`WAVE_MUSIC_CLOUD_SONG_WORKFLOW_ID`、`WAVE_MUSIC_CLOUD_SONG_TOKEN` 临时覆盖。

首次开启需要重启应用，“AI 作曲 → 云端歌曲”才会从“未配置”变为可用；之后换令牌或换工作流直接再点一次生成即可生效，无需重启。

### 使用与限制

- 在 AI 作曲页把模式切到 **Cloud song (vocals)**，输入描述后点生成。云端模式不使用 4/8 秒时长选择（时长由云端模型决定，实测 100~160 秒），也不做中文翻译预览（豆包直接接受中文描述）。
- 实测一次生成（产出约 2 分钟完整歌曲）约 35–65 秒，耗时主要取决于网络与云端排队；作为对比，本地 MusicGen 生成 8 秒纯音乐约需 58 秒。
- 歌名取自动化歌词的首句正文（跳过 `[verse]`/`[chorus]` 等结构标签）；完整歌词保存在 `meta.json` 的 `lyrics` 字段，并显示在“正在播放”页。
- 曲库中的云端作品歌手显示为 `Cloud Song`，与本地作品 `AI Compose` 区分。
- **计费**：按扣子平台的插件计费规则扣费。豆包音乐生成插件按输出音频秒数计费（约 ¥0.002/秒，另有累计约 120 秒的免费额度），一首 2 分钟的歌约 ¥0.24；具体价格与免费额度以扣子控制台当前展示为准。
- **内容审核**：描述与歌词会经过平台内容安全审核，违规内容会被拒绝。
- **令牌安全**：令牌以明文保存在用户配置目录的 `config.json` 中，不会进入版本库；请勿把带有真实令牌的配置提交或分享。
- 若你改动了工作流的输入参数名或输出字段名，需要同步修改 `ai/cloud_song.py` 中的 `parameters`、`AudioUrl`、`Lyrics`、`Duration` 字样。

## Quectel PI M2 性能与常驻模型

当前 RK3576 四线程实测参考：

| 项目 | 参考结果 |
|---|---:|
| MusicGen INT8 解码 | 约 10 步/秒 |
| 已常驻模型生成 4 秒音乐 | 约 28 秒 |
| 已常驻模型生成 8 秒音乐 | 约 58 秒 |
| Qwen2.5-0.5B 中文译文预览 | 约 19 秒 |
| MusicGen 低内存模式峰值 | 约 1.33 GB |

实际结果会受系统镜像、ONNX Runtime 版本、散热、CPU 调度和后台负载影响。长时间连续生成建议配置稳定电源与散热，并在目标镜像上重新执行基准测试。

为减少模型重复加载：

- 翻译和 MusicGen 各使用一个 `ai/model_server.py` 常驻子进程。
- 打开 AI 作曲页或输入中文描述时预加载翻译模型。
- 译文返回后，在用户确认提示词期间预加载 MusicGen。
- 4 GB 设备上如果可用内存不足，会先释放另一个空闲模型。
- 内存不少于 6 GB 时允许两个模型同时常驻。
- `warm_idle_minutes` 控制空闲释放时间；设置为 `0` 表示每次使用后立即释放。
- 人声分离开始前，常驻模型管理器会按预计需求主动释放空闲模型。

## 播放引擎

WebKitGTK 2.50 中，`<audio>` 接入 Web Audio 后存在暂停再播放卡死问题，`preservesPitch=false` 还可能导致页面进程崩溃。因此 Rhythm Crafter Player 使用整首 AudioBuffer 与自维护时间轴：

- 原曲、人声和伴奏共用同一个 AudioContext 时钟。
- 人声与伴奏在同一个计划时间启动，保持采样级同步。
- 暂停、跳转、变速和切换 stems 时重建一次性 AudioBufferSourceNode。
- 音效链由滤波器、WaveShaper、Delay、反馈、干湿混合、主音量和 Analyser 构成。
- 原曲约占 0.35 MB/秒；4 分钟约 85 MB，分离模式再增加约 170 MB。
- 超过 30 分钟的音频暂不支持。
- 当前速度调节会同时改变音调。

## 运行、安装与打包

```bash
./wave_music.py                    # 从源码运行
./install.sh                       # 安装到当前用户
sudo ./install.sh --system         # 安装到 /usr
./install.sh --uninstall           # 卸载用户安装
sudo ./install.sh --uninstall --system
./build-deb.sh                     # 构建不带模型的 Debian 包
WITH_MODELS=1 ./build-deb.sh       # 构建带模型的 Debian 包
```

用户级安装的程序位于 `~/.local/lib/wave-music`，系统级安装位于 `/usr/share/wave-music`。卸载会保留曲库、设置、模型和生成作品。

Debian 包输出到 `dist/wave-music_<版本>_all.deb`。

应用源码是架构无关的 Python 和 Web 资源，但 ONNX Runtime、sherpa-onnx 等虚拟环境依赖包含原生二进制。请在 Quectel PI M2 上创建 aarch64 虚拟环境，不要复制 x86_64 机器的 `.venv`。

调试模式：

```bash
WAVE_MUSIC_DEBUG=1 ./wave_music.py
```

## 数据位置

| 数据 | 默认位置 |
|---|---|
| 配置 | `~/.config/wave-music/config.json` |
| 曲库、歌单和设置 | `~/.local/share/wave-music/library.db` |
| 用户 AI 虚拟环境 | `~/.local/share/wave-music/venv/` |
| 用户模型 | `~/.local/share/wave-music/models/` |
| 人声分离缓存 | `~/.cache/wave-music/stems/` |
| 源码版 AI 作品 | `wave-music/generated/` |
| 安装版 AI 作品 | `~/.local/share/wave-music/generated/` |

## 配置项

配置可以写入 `config.json`，也可以使用同名的 `WAVE_MUSIC_*` 环境变量；环境变量优先。

| 键 | 说明 | 默认值 |
|---|---|---|
| `ai_python` | AI Python 解释器 | 自动查找项目 `.venv`、用户 venv、当前 Python |
| `models_dir` | 模型根目录 | 自动查找项目、用户和系统模型目录 |
| `ai_threads` | AI 推理线程数 | `min(4, CPU 核数)` |
| `translate_model` | `0.5b` 或 `1.5b` | 低于 8 GB 优先 `0.5b` |
| `translate_low_memory` | 翻译模型关闭内存池 | `false` |
| `musicgen_low_memory` | MusicGen 低内存策略 | 低于 6 GB 自动启用 `arena` |
| `warm_idle_minutes` | 常驻模型空闲释放时间 | `5` |
| `generated_dir` | AI 作品目录 | 源码版和安装版自动选择 |
| `cloud_song_enabled` | 开启云端歌曲（需联网、按量计费） | `false` |
| `cloud_song_workflow_id` | 扣子工作流 ID | 空 |
| `cloud_song_token` | 扣子个人访问令牌（`pat_` 开头） | 空 |

## 快捷键

| 快捷键 | 操作 |
|---|---|
| `Space` | 播放 / 暂停 |
| `Ctrl+Left` / `Ctrl+Right` | 上一首 / 下一首 |
| `Ctrl+O` | 添加音乐 |
| `Ctrl+F` | 搜索 |
| `Delete` | 移除选中曲目 |
| `Ctrl+Q` | 退出 |

## 项目结构

```text
wave_music.py              应用入口
wavemusic/app.py           GTK、WebView、JS↔Python 桥与业务命令
wavemusic/config.py        路径、配置、模型和运行环境探测
wavemusic/library.py       SQLite 曲库、歌单、设置与 GStreamer 元数据
wavemusic/jobs.py          AI 单并发任务队列
wavemusic/warm.py          常驻模型加载、内存轮换与空闲释放
wavemusic/i18n.py          后端 UI 消息英文化
ai/separate_worker.py      Spleeter 人声与伴奏分离
ai/model_server.py         Qwen / MusicGen 常驻模型进程
ai/generate_worker.py      AI 作曲公共流程与命令行入口
ai/musicgen.py             MusicGen ONNX 推理与后处理
ai/translate.py            Qwen 中文提示词翻译与 KV 前缀缓存
ai/cloud_song.py           云端歌曲：扣子工作流调用与音频下载
ui/                        Web 界面、播放引擎和实时音效
tests/                     单元、模型、常驻进程与 GUI 测试
scripts/                   AI 环境与模型准备脚本
packaging/                 桌面入口与图标
```


## 测试

运行全部单元与模型测试：

```bash
.venv/bin/python -m unittest discover -s tests -v
```

按模块运行：

```bash
.venv/bin/python -m unittest \
  tests.test_library tests.test_i18n tests.test_musicgen \
  tests.test_translate tests.test_warm -v
```

GUI 端到端测试需要桌面会话：

```bash
python3 tests/e2e_gui.py
```

MusicGen 基准测试：

```bash
.venv/bin/python scripts/musicgen_bench.py --seconds 8
```

## 许可证说明

云端歌曲不包含任何本地模型，但它依赖第三方服务：扣子平台的服务条款、豆包音乐生成插件的内容审核、计费规则与生成内容的商用授权，均以扣子当前的官方说明为准，与本项目许可证无关。


