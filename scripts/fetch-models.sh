#!/usr/bin/env bash
# 下载 Spleeter 2stems（fp16，约 35MB）人声分离模型
#   ./scripts/fetch-models.sh               下载到 ~/.local/share/wave-music/models
#   ./scripts/fetch-models.sh ./models      下载到指定目录（如源码目录，开发时使用）
# 网络受限时可手动下载下面的 URL，解压到目标目录即可。
set -euo pipefail
DEST="${1:-${XDG_DATA_HOME:-$HOME/.local/share}/wave-music/models}"
NAME=sherpa-onnx-spleeter-2stems-fp16
URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/source-separation-models/$NAME.tar.bz2"
if [[ -f "$DEST/$NAME/vocals.fp16.onnx" && -f "$DEST/$NAME/accompaniment.fp16.onnx" ]]; then
  echo "模型已存在：$DEST/$NAME"; exit 0
fi
mkdir -p "$DEST"
TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
echo "下载 $URL"
curl -fL --retry 3 -o "$TMP" "$URL"
tar xjf "$TMP" -C "$DEST"
ls -la "$DEST/$NAME"
echo "模型已就绪：$DEST/$NAME"
