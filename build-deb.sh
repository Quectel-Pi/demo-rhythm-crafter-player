#!/usr/bin/env bash
# 构建 Debian 安装包：./build-deb.sh  →  dist/wave-music_<版本>_all.deb
set -euo pipefail
cd "$(dirname "$0")"

VERSION="${VERSION:-$(python3 -c "import wavemusic;print(wavemusic.__version__)")}"
PKG=wave-music
BUILD="$(mktemp -d)"
ROOT="$BUILD/${PKG}_${VERSION}_all"
trap 'rm -rf "$BUILD"' EXIT

install -d "$ROOT/DEBIAN" "$ROOT/usr/bin" "$ROOT/usr/share/$PKG/ui" "$ROOT/usr/share/$PKG/wavemusic" "$ROOT/usr/share/$PKG/ai" \
  "$ROOT/usr/share/applications" "$ROOT/usr/share/icons/hicolor/scalable/apps"
install -m 755 wave_music.py "$ROOT/usr/share/$PKG/wave_music.py"
install -m 644 wavemusic/*.py "$ROOT/usr/share/$PKG/wavemusic/"
install -m 755 ai/*.py "$ROOT/usr/share/$PKG/ai/"
install -m 644 ui/index.html ui/style.css ui/app.js "$ROOT/usr/share/$PKG/ui/"
# WITH_MODELS=1 ./build-deb.sh 会把 Spleeter 模型（约 38MB）打进安装包
if [[ "${WITH_MODELS:-0}" == 1 ]]; then
  install -d "$ROOT/usr/share/$PKG/models/sherpa-onnx-spleeter-2stems-fp16"
  install -m 644 models/sherpa-onnx-spleeter-2stems-fp16/*.onnx "$ROOT/usr/share/$PKG/models/sherpa-onnx-spleeter-2stems-fp16/"
  if [[ -f models/musicgen-small-onnx/onnx/decoder_model_merged_int8.onnx ]]; then
    # MusicGen 完整生成（只装运行所需文件，约 0.6GB；CC-BY-NC，仅限非商业用途）
    install -d "$ROOT/usr/share/$PKG/models/musicgen-small-onnx/onnx"
    for f in text_encoder_int8.onnx decoder_model_merged_int8.onnx encodec_decode.onnx; do
      install -m 644 "models/musicgen-small-onnx/onnx/$f" "$ROOT/usr/share/$PKG/models/musicgen-small-onnx/onnx/"
    done
    for f in config.json generation_config.json tokenizer.json tokenizer_config.json special_tokens_map.json SOURCE.txt; do
      [[ -f models/musicgen-small-onnx/$f ]] && install -m 644 "models/musicgen-small-onnx/$f" "$ROOT/usr/share/$PKG/models/musicgen-small-onnx/"
    done
  fi
  for size in 0.5b 1.5b; do
    # 中文描述翻译模型（Qwen2.5-Instruct int8，Apache-2.0）：有哪个装哪个，连同前缀缓存
    src="models/qwen2.5-$size-instruct-onnx"
    [[ -f "$src/onnx/model_int8.onnx" ]] || continue
    install -d "$ROOT/usr/share/$PKG/$src/onnx"
    install -m 644 "$src/onnx/model_int8.onnx" "$ROOT/usr/share/$PKG/$src/onnx/"
    for f in "$src"/*.json "$src"/*.npz "$src"/SOURCE.txt; do
      [[ -f "$f" ]] && install -m 644 "$f" "$ROOT/usr/share/$PKG/$src/"
    done
  done
fi
install -m 644 packaging/wave-music.svg "$ROOT/usr/share/$PKG/wave-music.svg"
install -m 644 packaging/wave-music.svg "$ROOT/usr/share/icons/hicolor/scalable/apps/wave-music.svg"
install -m 644 packaging/wave-music.desktop "$ROOT/usr/share/applications/wave-music.desktop"
printf '#!/bin/sh\nexec /usr/bin/python3 /usr/share/%s/wave_music.py "$@"\n' "$PKG" > "$ROOT/usr/bin/wave-music"
chmod 755 "$ROOT/usr/bin/wave-music"

SIZE=$(du -sk "$ROOT/usr" | cut -f1)
cat > "$ROOT/DEBIAN/control" <<CTRL
Package: $PKG
Version: $VERSION
Section: sound
Priority: optional
Architecture: all
Installed-Size: $SIZE
Depends: python3 (>= 3.7), python3-gi, gir1.2-gtk-3.0, gir1.2-webkit2-4.1 | gir1.2-webkit2-4.0, gir1.2-gst-plugins-base-1.0, gstreamer1.0-tools, gstreamer1.0-plugins-base, gstreamer1.0-plugins-good
Recommends: gstreamer1.0-libav, gstreamer1.0-plugins-bad
Maintainer: Rhythm Crafter Player <noreply@localhost>
Description: Rhythm Crafter Player - 本地音乐播放器
 基于 GTK3 + WebKit2GTK 的 Linux 桌面音乐播放器，
 支持持久化本地曲库、实时趣味音效、频谱显示，
 以及基于 sherpa-onnx Spleeter 的本地 AI 人声/伴奏分离（伴奏模式、只改人声）。
CTRL

cat > "$ROOT/DEBIAN/postinst" <<'POST'
#!/bin/sh
set -e
command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/share/applications || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true
POST
cp "$ROOT/DEBIAN/postinst" "$ROOT/DEBIAN/postrm"
chmod 755 "$ROOT/DEBIAN/postinst" "$ROOT/DEBIAN/postrm"

mkdir -p dist
dpkg-deb --root-owner-group --build "$ROOT" "dist/${PKG}_${VERSION}_all.deb" >/dev/null
echo "已生成 dist/${PKG}_${VERSION}_all.deb"
echo "安装：sudo apt install ./dist/${PKG}_${VERSION}_all.deb"
