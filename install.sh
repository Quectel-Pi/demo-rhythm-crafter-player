#!/usr/bin/env bash
# 安装 / 卸载 Rhythm Crafter Player
#   ./install.sh                 安装到当前用户：程序 ~/.local/lib/wave-music，无需 root
#   sudo ./install.sh --system   安装到 /usr（所有用户）：程序 /usr/share/wave-music
#   ./install.sh --uninstall [--system]
#
# 注意：用户数据（曲库 library.db、设置、下载的模型、AI venv）位于
#   ${XDG_DATA_HOME:-~/.local/share}/wave-music，与程序目录分开，卸载时不会删除。
set -euo pipefail
cd "$(dirname "$0")"

MODE=user
ACTION=install
for arg in "$@"; do
  case "$arg" in
    --system) MODE=system ;;
    --user) MODE=user ;;
    --uninstall) ACTION=uninstall ;;
    *) echo "未知参数：$arg"; exit 1 ;;
  esac
done

USER_DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
if [[ $MODE == system ]]; then
  APP_HOME=/usr/share/wave-music
  BIN_DIR=/usr/bin
  XDG_SHARE=/usr/share
else
  APP_HOME="$HOME/.local/lib/wave-music"
  BIN_DIR="$HOME/.local/bin"
  XDG_SHARE="$USER_DATA"
fi
DATA_DIR="$USER_DATA/wave-music"   # 运行时数据目录（曲库等），安装/卸载都不能整体删除
DESKTOP="$XDG_SHARE/applications/wave-music.desktop"
ICON="$XDG_SHARE/icons/hicolor/scalable/apps/wave-music.svg"

# 安全保护：程序目录绝不能与用户数据目录重合
if [[ "$(realpath -m "$APP_HOME")" == "$(realpath -m "$DATA_DIR")" ]]; then
  echo "错误：程序目录与用户数据目录相同（$APP_HOME），已中止。"; exit 1
fi

refresh() {
  command -v update-desktop-database >/dev/null && update-desktop-database -q "$XDG_SHARE/applications" 2>/dev/null || true
  command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t "$XDG_SHARE/icons/hicolor" 2>/dev/null || true
}

# 旧版本（≤0.3.0）用户安装会把程序文件放进数据目录；只清理这些程序文件，保留曲库、设置与模型
cleanup_legacy() {
  [[ $MODE == user && -f "$DATA_DIR/wave_music.py" ]] || return 0
  rm -rf "$DATA_DIR/wavemusic" "$DATA_DIR/ui" "$DATA_DIR/ai"
  rm -f "$DATA_DIR/wave_music.py" "$DATA_DIR/wave-music.svg"
  echo "已清理旧版本遗留在 $DATA_DIR 中的程序文件（曲库与模型已保留）"
}

if [[ $ACTION == uninstall ]]; then
  rm -rf "$APP_HOME"
  rm -f "$BIN_DIR/wave-music" "$DESKTOP" "$ICON"
  cleanup_legacy
  refresh
  echo "已卸载 Rhythm Crafter Player。用户数据保留在 $DATA_DIR（如需彻底清除请手动删除，另有缓存 ${XDG_CACHE_HOME:-~/.cache}/wave-music）。"
  exit 0
fi

# 依赖检查
if ! python3 - <<'PY' 2>/dev/null
import gi
gi.require_version("Gtk", "3.0")
try:
    gi.require_version("WebKit2", "4.1")
except ValueError:
    gi.require_version("WebKit2", "4.0")
from gi.repository import Gtk, WebKit2
gi.require_version("GstPbutils", "1.0")
from gi.repository import GstPbutils
PY
then
  echo "缺少运行依赖，请先执行："
  echo "  sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1 gir1.2-gst-plugins-base-1.0 \\"
  echo "       gstreamer1.0-tools gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-libav"
  echo "（较旧系统上若无 gir1.2-webkit2-4.1，可改用 gir1.2-webkit2-4.0）"
  exit 1
fi

cleanup_legacy
# 覆盖安装：先清掉旧程序文件，避免残留已删除的模块
rm -rf "$APP_HOME/wavemusic" "$APP_HOME/ui" "$APP_HOME/ai"
install -d "$APP_HOME/ui" "$APP_HOME/wavemusic" "$APP_HOME/ai" "$BIN_DIR" "$(dirname "$DESKTOP")" "$(dirname "$ICON")"
install -m 755 wave_music.py "$APP_HOME/wave_music.py"
install -m 644 wavemusic/*.py "$APP_HOME/wavemusic/"
install -m 755 ai/*.py "$APP_HOME/ai/"
install -m 644 ui/index.html ui/style.css ui/app.js "$APP_HOME/ui/"
# 若源码目录已下载模型，一并安装（否则运行 scripts/fetch-models.sh）
if [[ -d models/sherpa-onnx-spleeter-2stems-fp16 ]]; then
  install -d "$APP_HOME/models/sherpa-onnx-spleeter-2stems-fp16"
  install -m 644 models/sherpa-onnx-spleeter-2stems-fp16/*.onnx "$APP_HOME/models/sherpa-onnx-spleeter-2stems-fp16/"
fi
# 若源码目录有可用的 AI 环境（.venv，含 sherpa-onnx），一并复制，安装版可直接使用人声分离
AI_NOTE=""
if [[ -x .venv/bin/python ]] && .venv/bin/python -c "import numpy, sherpa_onnx" 2>/dev/null; then
  rm -rf "$APP_HOME/.venv"
  cp -a .venv "$APP_HOME/.venv"
  find "$APP_HOME/.venv" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
  AI_NOTE="已复制 AI 环境（.venv）"
fi
if [[ -f models/musicgen-small-onnx/onnx/decoder_model_merged_int8.onnx ]]; then
  # MusicGen 完整生成（只装运行所需文件，约 0.6GB；CC-BY-NC，仅限非商业用途）
  install -d "$APP_HOME/models/musicgen-small-onnx/onnx"
  for f in text_encoder_int8.onnx decoder_model_merged_int8.onnx encodec_decode.onnx; do
    install -m 644 "models/musicgen-small-onnx/onnx/$f" "$APP_HOME/models/musicgen-small-onnx/onnx/"
  done
  for f in config.json generation_config.json tokenizer.json tokenizer_config.json special_tokens_map.json SOURCE.txt; do
    [[ -f models/musicgen-small-onnx/$f ]] && install -m 644 "models/musicgen-small-onnx/$f" "$APP_HOME/models/musicgen-small-onnx/"
  done
fi
for size in 0.5b 1.5b; do
  # 中文描述翻译模型（Qwen2.5-Instruct int8，Apache-2.0）：有哪个装哪个，连同前缀缓存
  src="models/qwen2.5-$size-instruct-onnx"
  [[ -f "$src/onnx/model_int8.onnx" ]] || continue
  install -d "$APP_HOME/$src/onnx"
  install -m 644 "$src/onnx/model_int8.onnx" "$APP_HOME/$src/onnx/"
  for f in "$src"/*.json "$src"/*.npz "$src"/SOURCE.txt; do
    [[ -f "$f" ]] && install -m 644 "$f" "$APP_HOME/$src/"
  done
done
install -m 644 packaging/wave-music.svg "$APP_HOME/wave-music.svg"
install -m 644 packaging/wave-music.svg "$ICON"
install -m 644 packaging/wave-music.desktop "$DESKTOP"
printf '#!/bin/sh\nexec python3 "%s/wave_music.py" "$@"\n' "$APP_HOME" > "$BIN_DIR/wave-music"
chmod 755 "$BIN_DIR/wave-music"
refresh

echo "安装完成：程序位于 $APP_HOME，可在应用菜单中找到「Rhythm Crafter Player」，或在终端运行 wave-music"
if [[ -n $AI_NOTE ]]; then
  echo "$AI_NOTE"
else
  echo "AI 人声分离还需要：scripts/setup-ai.sh（安装 sherpa-onnx）与 scripts/fetch-models.sh（下载模型）"
fi
[[ $MODE == user && ":$PATH:" != *":$BIN_DIR:"* ]] && echo "提示：$BIN_DIR 不在 PATH 中，终端命令需写完整路径。"
exit 0
