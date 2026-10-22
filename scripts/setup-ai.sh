#!/usr/bin/env bash
# 为 AI 人声分离准备 Python 环境（sherpa-onnx + numpy），安装到 ~/.local/share/wave-music/venv
#   ./scripts/setup-ai.sh                       使用 PyPI
#   PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple ./scripts/setup-ai.sh   使用国内镜像
# 已有装好 sherpa-onnx 的环境时，也可以不运行本脚本，直接在
# ~/.config/wave-music/config.json 中写 {"ai_python": "/path/to/python"}
set -euo pipefail
VENV="${XDG_DATA_HOME:-$HOME/.local/share}/wave-music/venv"
if ! python3 -m venv --help >/dev/null 2>&1; then
  echo "缺少 venv 模块：sudo apt install python3-venv"; exit 1
fi
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip ${PIP_INDEX:+-i "$PIP_INDEX"}
"$VENV/bin/pip" install "sherpa-onnx>=1.12.0" "numpy>=1.23" "onnxruntime>=1.17" "tokenizers>=0.15" ${PIP_INDEX:+-i "$PIP_INDEX"}
"$VENV/bin/python" -c "import sherpa_onnx, numpy; sherpa_onnx.OfflineSourceSeparation; print('sherpa-onnx', sherpa_onnx.__version__, 'OK')"
echo "AI 环境已就绪：$VENV（播放器会自动发现）"
