#!/usr/bin/env bash
# 下载中文 → 英文翻译用的小型语言模型 Qwen2.5-Instruct（ONNX，onnx-community，Apache-2.0）
# 用于把中文音乐描述翻译成英文提示词后交给 MusicGen（MusicGen 只理解英文）。
#
#   ./scripts/setup-translate.sh            # 只下载 0.5B（512MB，开发板也能用，默认）
#   ./scripts/setup-translate.sh all        # 同时下载 0.5B 与 1.5B（共约 2.1GB，用于对比翻译质量）
#   ./scripts/setup-translate.sh 1.5b       # 只下载 1.5B（1.58GB）
#   HF_ENDPOINT=https://hf-mirror.com ./scripts/setup-translate.sh all     # 国内镜像
#
# 输出到 models/qwen2.5-<大小>-instruct-onnx/（int8 动态量化；支持断点续传，重复运行会跳过已下载的文件）
# 运行时只需要 onnxruntime + tokenizers + numpy（不需要 torch）。
set -euo pipefail
cd "$(dirname "$0")/.."

case "${1:-0.5b}" in
  0.5b) SIZES=(0.5B) ;;
  1.5b) SIZES=(1.5B) ;;
  all) SIZES=(0.5B 1.5B) ;;
  *) echo "用法：$0 [0.5b|1.5b|all]"; exit 1 ;;
esac

FILES=(config.json generation_config.json tokenizer.json tokenizer_config.json onnx/model_int8.onnx)

for size in "${SIZES[@]}"; do
  REPO="onnx-community/Qwen2.5-$size-Instruct"
  BASE="${HF_ENDPOINT:-https://huggingface.co}/$REPO/resolve/main"
  OUT="models/qwen2.5-$(echo "$size" | tr 'A-Z' 'a-z')-instruct-onnx"
  mkdir -p "$OUT/onnx"
  echo "下载 $REPO 到 $OUT"
  for f in "${FILES[@]}"; do
    target="$OUT/$f"
    if [[ -s "$target" && ! -f "$target.part" ]]; then
      printf "  ✓ %-28s 已存在\n" "$f"
      continue
    fi
    start=$(date +%s)
    if ! curl -fsSL --retry 3 --retry-delay 2 -C - -o "$target.part" "$BASE/$f"; then
      echo "  ❌ 下载失败：$f（可重新运行本脚本断点续传，或设置 HF_ENDPOINT 镜像）"
      exit 1
    fi
    mv "$target.part" "$target"
    printf "  ✓ %-28s %6s  %ss\n" "$f" "$(du -h "$target" | cut -f1)" "$(( $(date +%s) - start ))"
  done
  printf 'Qwen/Qwen2.5-%s-Instruct（Alibaba Cloud，Apache-2.0）\nONNX: https://huggingface.co/%s（int8 动态量化）\n' "$size" "$REPO" > "$OUT/SOURCE.txt"
done

echo
echo "================ 摘要（请把以下内容发给我）================"
.venv/bin/python - "${SIZES[@]}" <<'PY'
import json, sys
from pathlib import Path
import onnxruntime as ort
from tokenizers import Tokenizer

for size in sys.argv[1:]:
    out = Path(f"models/qwen2.5-{size.lower()}-instruct-onnx")
    total = sum(f.stat().st_size for f in out.rglob("*") if f.is_file()) / 1e6
    cfg = json.loads((out / "config.json").read_text())
    gen = json.loads((out / "generation_config.json").read_text())
    print(f"[Qwen2.5-{size}] 总大小 {total:.0f}MB")
    print("  config:", {k: cfg.get(k) for k in ("num_hidden_layers", "num_attention_heads", "num_key_value_heads",
                                                "hidden_size", "bos_token_id", "eos_token_id", "vocab_size")})
    print("  generation:", {k: gen.get(k) for k in ("eos_token_id", "pad_token_id", "temperature", "top_p", "repetition_penalty")})
    try:
        s = ort.InferenceSession(str(out / "onnx" / "model_int8.onnx"), providers=["CPUExecutionProvider"])
        ins = [f"{i.name}{list(i.shape)}" for i in s.get_inputs()]
        outs = [f"{o.name}{list(o.shape)}" for o in s.get_outputs()]
        print(f"  输入({len(ins)}): {', '.join(ins[:5])} … 最后 {ins[-1]}")
        print(f"  输出({len(outs)}): {', '.join(outs[:2])} …")
    except Exception as error:  # noqa: BLE001
        print(f"  模型加载失败：{type(error).__name__}: {str(error)[:200]}")
    try:
        tok = Tokenizer.from_file(str(out / "tokenizer.json"))
        e = tok.encode("<|im_start|>user\n下雨天的思念，钢琴<|im_end|>")
        print("  分词器:", e.tokens[:12], e.ids[:12])
    except Exception as error:  # noqa: BLE001
        print("  分词器加载失败：", type(error).__name__, str(error)[:200])
PY
echo "==========================================================="
