#!/usr/bin/env bash
# 下载 MusicGen-small 的 ONNX 版本（Xenova/musicgen-small，CC-BY-NC 4.0，仅限非商业用途）
#
#   ./scripts/setup-musicgen.sh
#   HF_ENDPOINT=https://hf-mirror.com ./scripts/setup-musicgen.sh      # 国内镜像
#
# 输出到 models/musicgen-small-onnx/（约 1.5GB，支持断点续传，重复运行会跳过已下载的文件）：
#   文本编码器  text_encoder.onnx（fp32）/ text_encoder_int8.onnx
#   解码器      decoder_model_merged_int8.onnx / decoder_model_merged_q4.onnx（带 KV 缓存的合并版）
#   音频解码    encodec_decode.onnx（fp32）/ encodec_decode_int8.onnx
#   其他        build_delay_pattern_mask.onnx、tokenizer.json、config.json 等
# 运行时只需要 onnxruntime + tokenizers + numpy（与 Textune 相同，不需要 torch）。
set -euo pipefail
cd "$(dirname "$0")/.."

REPO=Xenova/musicgen-small
BASE="${HF_ENDPOINT:-https://huggingface.co}/$REPO/resolve/main"
OUT=models/musicgen-small-onnx
mkdir -p "$OUT/onnx"

FILES=(
  config.json generation_config.json preprocessor_config.json tokenizer.json tokenizer_config.json special_tokens_map.json
  onnx/build_delay_pattern_mask.onnx
  onnx/text_encoder_int8.onnx onnx/text_encoder.onnx
  onnx/encodec_decode_int8.onnx onnx/encodec_decode.onnx
  onnx/decoder_model_merged_q4.onnx onnx/decoder_model_merged_int8.onnx
)

echo "下载到 $OUT（来源 $BASE）"
for f in "${FILES[@]}"; do
  target="$OUT/$f"
  if [[ -s "$target" && ! -f "$target.part" ]]; then
    printf "  ✓ %-40s 已存在\n" "$f"
    continue
  fi
  start=$(date +%s)
  if ! curl -fsSL --retry 3 --retry-delay 2 -C - -o "$target.part" "$BASE/$f"; then
    echo "  ❌ 下载失败：$f（可重新运行本脚本断点续传，或设置 HF_ENDPOINT 镜像）"
    exit 1
  fi
  mv "$target.part" "$target"
  size=$(du -h "$target" | cut -f1)
  printf "  ✓ %-40s %6s  %ss\n" "$f" "$size" "$(( $(date +%s) - start ))"
done
cat > "$OUT/SOURCE.txt" <<'TXT'
facebook/musicgen-small (Meta, Copet et al. 2023, "Simple and Controllable Music Generation")
ONNX export: https://huggingface.co/Xenova/musicgen-small
License: CC-BY-NC 4.0 —— 仅限非商业用途
TXT

echo
echo "================ 摘要（请把以下内容发给我）================"
du -sh "$OUT" | sed 's/^/总大小 /'
.venv/bin/python - "$OUT" <<'PY'
import sys
from pathlib import Path
import onnxruntime as ort

out = Path(sys.argv[1]) / "onnx"
def brief(items, limit=5):
    names = [f"{i.name}{list(i.shape)}" for i in items]
    return ", ".join(names[:limit]) + (f" …共{len(names)}个，最后 {names[-1]}" if len(names) > limit else "")
for name in ["build_delay_pattern_mask.onnx", "text_encoder_int8.onnx", "encodec_decode_int8.onnx",
             "decoder_model_merged_int8.onnx", "decoder_model_merged_q4.onnx"]:
    try:
        s = ort.InferenceSession(str(out / name), providers=["CPUExecutionProvider"])
        print(f"[{name}]\n  输入: {brief(s.get_inputs())}\n  输出: {brief(s.get_outputs(), 3)}")
    except Exception as error:  # noqa: BLE001
        print(f"[{name}] 加载失败：{type(error).__name__}: {str(error)[:200]}")
print("onnxruntime", ort.__version__)
PY
echo "==========================================================="
