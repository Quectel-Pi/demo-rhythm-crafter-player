#!/usr/bin/env python3
"""Rhythm Crafter Player 端到端界面测试：真实 GTK + WebKit 窗口，注入脚本模拟用户操作。

  python3 tests/e2e_gui.py            # 需要图形桌面（DISPLAY / WAYLAND_DISPLAY）

使用临时的数据 / 缓存目录，不影响真实曲库；测试结束后打印每一项结果，有失败时退出码为 1。
覆盖：播放 / 暂停 / 跳转 / 音效 / 变速 / AI 人声分离与伴奏模式 / 切歌 / 搜索 / 移除 / AI 作曲（MusicGen：
生成、进度、取消、换一首、4/8 秒、中文提示、播完自动暂停、删除作品时删除文件、重启后作品仍在曲库）。
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="wave-e2e-"))
os.environ["XDG_DATA_HOME"] = str(TMP / "data")
os.environ["XDG_CACHE_HOME"] = str(TMP / "cache")
os.environ["WAVE_MUSIC_GENERATED_DIR"] = str(TMP / "generated")   # 不写入项目文件夹下的 generated/
sys.path.insert(0, str(ROOT))

from gi.repository import GLib  # noqa: E402

from wavemusic import app as A  # noqa: E402
from wavemusic.config import DB_FILE, GENERATED_DIR  # noqa: E402
from wavemusic.library import Library  # noqa: E402

WebKit2 = A.WebKit2
MUSIC = TMP / "music"
MUSIC.mkdir()
song = next(iter(sorted((ROOT / "test").glob("*.flac"))), None)
if song:
    shutil.copy(song, MUSIC / song.name)
else:  # 没有测试歌曲时生成一段 20 秒的 FLAC
    subprocess.run(["gst-launch-1.0", "-q", "audiotestsrc", "num-buffers=860", "freq=330", "!", "audioconvert", "!",
                    "flacenc", "!", "filesink", f"location={MUSIC / 'tone.flac'}"], check=True)
subprocess.run(["gst-launch-1.0", "-q", "audiotestsrc", "num-buffers=400", "!", "audioconvert", "!", "lamemp3enc", "!",
                "id3v2mux", "!", "filesink", f"location={MUSIC / '测试歌手 - 测试歌曲.mp3'}"], check=True)
library = Library(DB_FILE)
library.add([str(MUSIC)])
library.close()

TEST_JS = r"""
(async () => {
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => [...document.querySelectorAll(s)];
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const log = (k, v, ok) => window.webkit.messageHandlers.testlog.postMessage(JSON.stringify({k, v, ok}));
  const check = (k, ok, v = ok) => log(k, v, Boolean(ok));
  const waitFor = async (fn, ms = 15000) => { const t = Date.now(); while (Date.now() - t < ms) { try { if (fn()) return true; } catch (e) {} await sleep(100); } return false; };
  const secs = () => { const [m, s] = $('#currentTime').textContent.split(':').map(Number); return m * 60 + s; };
  const click = (el) => el.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  const row = (fmt) => $$('#trackList .track-row').find(r => r.querySelector('.row-format').textContent === fmt);
  // 不再替换 window.confirm：删除 / 清空使用页面内的自绘确认框，测试走真实流程
  try {
    check('曲库加载 2 首', await waitFor(() => $$('.track-row').length === 2), $$('.track-row').length);
    check('AI 检测完成', await waitFor(() => window.__waveDebug.state.ai !== null), Boolean(window.__waveDebug.state.ai));
    check('就绪时不显示状态徽标', $('#aiState').hidden === Boolean(window.__waveDebug.state.ai.available)
          && $('#bgmState').hidden === Boolean(window.__waveDebug.state.ai.compose.available), `${$('#aiState').hidden}/${$('#bgmState').hidden}`);
    const visibleText = (el) => el.innerText || el.textContent;
    // 界面文案应全部为英文：去掉用户数据（歌名、歌手、歌单名、提示词等）后，文字与 title / placeholder / aria-label 中不能有中文
    const DATA_SEL = '.track-row, .bgm-name, #playlistNav .nav-item, #playlistName, #trackTitle, #trackArtist, #miniTitle, #miniArtist, '
                   + '#stemsTrack, #confirmMessage, #confirmInput, #toast, #bgmPrompt, #playlistMenu';
    const uiCJK = () => {
      const root = document.body.cloneNode(true);
      root.querySelectorAll(DATA_SEL + ', script, style').forEach((e) => e.remove());
      const attrs = [...root.querySelectorAll('[title],[placeholder],[aria-label]')]
        .flatMap((e) => [e.getAttribute('title'), e.getAttribute('placeholder'), e.getAttribute('aria-label')]);
      return [root.textContent, ...attrs].join(' ').match(/[\u3400-\u9fff]+/g) || [];
    };
    check('界面文案为英文（曲库页）', uiCJK().length === 0, uiCJK().join('、') || '无中文');
    const emoji = (document.body.textContent.match(/\p{Extended_Pictographic}/gu) || []);
    check('界面不含 emoji（开发板缺少彩色 emoji 字体会显示成方框）', emoji.length === 0, emoji.join(' ') || '无');
    check('窗口标题为英文', document.title === 'Rhythm Crafter Player' || !/[\u3400-\u9fff]/.test(document.title.replace(/^.* · /, '')), document.title);
    check('用户音乐的标签原样显示', row('MP3').querySelector('.row-title, .track-title, span:nth-child(2)').textContent.includes('测试歌曲')
          && row('MP3').querySelector('.row-artist').textContent === '测试歌手', row('MP3').textContent.trim().slice(0, 60));
    const banned = ['MusicGen', '非商业', '自动暂停', '一并删除文件', 'DSP', '后续版本', '本地 AI 就绪', '线程', '实时声音', '在本机处理', '在本机生成'];
    for (const view of ['effects', 'compose']) {
      const text = $(`#view-${view}`).textContent;
      const hit = banned.filter((w) => text.includes(w));
      check(`文案已清理（${view}）`, hit.length === 0, hit.join('、') || '无');
    }
    const vol = $('#volumeSlider'); vol.value = 0; vol.dispatchEvent(new Event('input', {bubbles: true}));  // 静音测试

    // ---------- 原有功能 ----------
    click(row('FLAC').querySelector('[data-action=play]'));
    check('播放', await waitFor(() => $('#playBtn').title === 'Pause'));
    await sleep(2200); const a = secs(); check('播放计时前进', a >= 1, a);
    click($('#playBtn')); await sleep(1200); const b = secs();
    check('暂停后时间静止', $('#playBtn').title === 'Play' && b === secs(), b);
    click($('#playBtn')); await sleep(2200); check('暂停后可继续播放', secs() > b, secs());
    const seek = $('#seekBar'); seek.value = 500; seek.dispatchEvent(new Event('input', {bubbles: true}));
    await sleep(800); check('跳转到 50%', secs() > 5, $('#currentTime').textContent);
    for (const fx of ['glitch', 'demon', 'echo', 'clean']) click($(`.effect-card[data-effect=${fx}]`));
    await sleep(300); check('音效切换', $('#fxBadge').textContent === 'Original', $('#fxBadge').textContent);
    const sep = row('FLAC').querySelector('[data-action=separate]');
    check('列表中有“分离”按钮', sep);
    if (sep) {
      click(sep);
      check('AI 人声分离完成', await waitFor(() => row('FLAC').querySelector('.ai-tag.done'), 90000));
      click($('.chip[data-preset=karaoke]'));
      check('K歌伴奏模式', await waitFor(() => !$('#stemBadge').hidden, 15000), $('#stemBadge').textContent);
      click($('#sourceSeg button[data-value=original]')); await sleep(500);
    }
    const si = $('#searchInput'); si.value = '测试歌曲'; si.dispatchEvent(new Event('input', {bubbles: true})); await sleep(200);
    check('搜索', $$('#trackList .track-row').length === 1, $$('#trackList .track-row').length);
    si.value = ''; si.dispatchEvent(new Event('input', {bubbles: true}));

    // ---------- 自建歌单 ----------
    const S = window.__waveDebug.state;
    const dialogInput = async (value) => {
      await waitFor(() => !$('#confirmDialog').hidden && !$('#confirmInput').hidden, 2000);
      $('#confirmInput').value = value; click($('#confirmOk')); await sleep(400);
    };
    const menuPick = async (rowEl, name) => {
      click(rowEl.querySelector('[data-action=add]'));
      await waitFor(() => !$('#playlistMenu').hidden, 2000);
      const item = $$('#playlistMenu [data-playlist]').find((b) => b.textContent.includes(name));
      click(item); await sleep(400);
    };
    check('侧栏“+”是新建歌单', $('#createPlaylistBtn').title === 'New playlist' && $('#playlistNav').textContent.includes('create a playlist'), $('#playlistNav').textContent.trim());
    click($('#createPlaylistBtn'));
    check('新建歌单弹出命名框（不是选择文件夹）', await waitFor(() => !$('#confirmDialog').hidden && !$('#confirmInput').hidden, 2000), $('#confirmInput').value);
    await dialogInput('  我的   最爱 ');
    check('创建并进入歌单页', $('#view-playlist').classList.contains('active') && $('#playlistName').textContent === '我的 最爱', $('#playlistName').textContent);
    check('侧栏显示新歌单', $$('#playlistNav .nav-item').length === 1 && $('#playlistNav .nav-item em').textContent === '0');
    check('空歌单提示', !$('#playlistEmpty').hidden);
    click($('#createPlaylistBtn')); await dialogInput('我的 最爱');
    check('重名被拒绝（后端提示译成英文）', $('#toast').textContent === 'A playlist named \u201c我的 最爱\u201d already exists' && S.playlists.length === 1, $('#toast').textContent);
    click($('.nav-item[data-view=library]')); await sleep(200);
    await menuPick(row('FLAC'), '我的 最爱');
    check('从曲库加入歌单', S.playlists[0].track_ids.length === 1 && $('#playlistNav .nav-item em').textContent === '1');
    await menuPick(row('MP3'), 'New playlist…'); await dialogInput('跑步');
    check('菜单里新建歌单并加入', S.playlists.length === 2 && S.playlists[1].name === '跑步' && S.playlists[1].track_ids.length === 1,
          S.playlists.map((p) => `${p.name}:${p.track_ids.length}`).join(' '));
    await menuPick(row('MP3'), '我的 最爱');
    click(row('MP3').querySelector('[data-action=add]')); await waitFor(() => !$('#playlistMenu').hidden);
    check('已加入的歌单显示“已添加”', $$('#playlistMenu [data-playlist]').find((b) => b.textContent.includes('我的 最爱')).textContent.includes('Added'));
    document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); await sleep(200);
    check('Esc 关闭菜单', $('#playlistMenu').hidden);
    click($$('#playlistNav .nav-item')[0]); await sleep(300);
    check('歌单页列出歌曲', $$('#playlistTracks .track-row').length === 2 && $('#playlistCount').textContent === '2');
    click($('#plPlayAll'));
    const flacId = Number(row('FLAC').dataset.id), mp3Id = Number(row('MP3').dataset.id);
    check('播放全部（按歌单顺序）', await waitFor(() => S.currentId === flacId && $('#playBtn').title === 'Pause', 10000));
    click($('#nextBtn'));
    check('下一首：歌单内第 2 首', await waitFor(() => S.currentId === mp3Id, 10000));
    click($('#nextBtn'));
    check('再下一首：回到歌单第 1 首', await waitFor(() => S.currentId === flacId, 10000));
    click($('#plRename')); await dialogInput('收藏');
    check('重命名', $('#playlistName').textContent === '收藏' && $('#playlistNav').textContent.includes('收藏'));
    click($$('#playlistTracks .track-row')[1].querySelector('[data-action=unlist]')); await sleep(400);
    check('从歌单移除（曲库仍保留）', $$('#playlistTracks .track-row').length === 1 && S.tracks.some((t) => t.id === mp3Id));
    click($$('#playlistNav .nav-item')[1]); await sleep(300);
    click($('#plDelete'));
    await waitFor(() => !$('#confirmDialog').hidden, 2000);
    check('删除歌单确认框', $('#confirmMessage').textContent.includes('跑步') && $('#confirmInput').hidden);
    click($('#confirmOk')); await sleep(400);
    check('删除歌单', S.playlists.length === 1 && $('#view-library').classList.contains('active') && S.tracks.length === 2);
    click($('#playBtn')); await sleep(200);

    // ---------- AI 作曲（MusicGen，提示词原样交给模型） ----------
    click($('.nav-item[data-view=compose]')); await sleep(300);
    check('进入 AI 作曲页', $('#view-compose').classList.contains('active'));
    const hasMusicgen = Boolean(window.__waveDebug.state.ai?.compose?.available);
    check('已移除生成方式 / 风格 / 结尾选项', !$('#bgmEngine') && !$('#bgmStyle') && !$('#bgmLoop'));
    check('时长只有 4 秒 / 8 秒，默认 8 秒',
          $$('#bgmDuration button').map(b => b.dataset.value).join(',') === '4,8' && $('#bgmDuration button.on').dataset.value === '8');
    const prompt = $('#bgmPrompt');
    prompt.value = ''; click($('#bgmGenerate')); await sleep(300);
    check('空描述不生成并提示', $('#toast').textContent.includes('Please enter') && $$('.bgm-item').length === 0, $('#toast').textContent);
    const hasTranslate = Boolean(window.__waveDebug.state.ai?.translate?.available);
    prompt.focus(); prompt.value = '下雨天的思念，钢琴'; prompt.dispatchEvent(new Event('input', {bubbles: true}));
    check('中文：显示“模型将收到”', !$('#bgmTranslation').hidden && $('#bgmEnglish').textContent.startsWith('Translating'), $('#bgmEnglish').textContent);
    if (hasTranslate) {
      check('中文：实时翻译预览', await waitFor(() => !$('#bgmEnglish').textContent.startsWith('Translating')
                                              && !/[\u3400-\u9fff]/.test($('#bgmEnglish').textContent)
                                              && $('#bgmEnglish').textContent.length > 3, 90000), $('#bgmEnglish').textContent);
      check('预览含“piano”', $('#bgmEnglish').textContent.toLowerCase().includes('piano'), $('#bgmEnglish').textContent);
      click($('#bgmUseEnglish'));
      check('改用英文编辑', !/[\u3400-\u9fff]/.test(prompt.value) && prompt.value.length > 3 && $('#bgmTranslation').hidden, prompt.value);
    }
    prompt.value = 'sad solo piano on a rainy day'; prompt.dispatchEvent(new Event('input', {bubbles: true}));
    check('英文不显示翻译', $('#bgmTranslation').hidden);
    const playingBefore = window.__waveDebug.engine.playing;
    prompt.dispatchEvent(new KeyboardEvent('keydown', {key: ' ', code: 'Space', bubbles: true}));
    await sleep(300); check('输入框内空格不触发播放/暂停', window.__waveDebug.engine.playing === playingBefore, playingBefore);
    const preview8 = $('#bgmPreview').textContent;
    click($('#bgmDuration button[data-value="4"]'));
    const preview4 = $('#bgmPreview').textContent;
    check('说明只显示生成用时，且随时长变化', /^About \d+ s to generate$/.test(preview4) && /^About \d+ s to generate$/.test(preview8)
          && parseInt(preview4.replace(/\D+/g, '')) < parseInt(preview8.replace(/\D+/g, '')), `${preview8} → ${preview4}`);
    check('示例只保留两条', $$('#bgmExamples .chip').map(c => c.textContent).join('|') === 'Lazy jazz bar, electric piano and saxophone|Cyberpunk electronic music, synthesizer',
          $$('#bgmExamples .chip').map(c => c.textContent).join('|'));

    if (hasMusicgen) {
      let t0 = performance.now();
      prompt.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', ctrlKey: true, bubbles: true}));
      check('生成进度条', await waitFor(() => !$('#bgmProgress').hidden && parseInt($('#bgmPercent').textContent) > 5, 30000), $('#bgmPercent').textContent);
      check('Ctrl+Enter 生成并加入作品列表', await waitFor(() => $$('.bgm-item').length === 1, 90000), $$('.bgm-item').length);
      log('生成 4 秒耗时（界面）', Math.round(performance.now() - t0) + 'ms', true);
      check('生成后自动播放', await waitFor(() => $('#playBtn').title === 'Pause' && $('#miniTitle').textContent === 'sad solo piano on a rainy day'), $('#miniTitle').textContent);
      const work = window.__waveDebug.state.tracks.find(t => t.generated);
      check('提示词原样保存', work.generated.prompt === 'sad solo piano on a rainy day' && work.generated.engine === 'musicgen', work.generated.prompt);
      check('作品摘要（不含模型名）', $('.bgm-desc').textContent === '4 s', $('.bgm-desc').textContent);
      check('时长约 4 秒', Math.abs(work.duration - 4) < 0.1, work.duration);
      check('曲库中出现 AI 曲目', row('AI') && row('AI').querySelector('.row-artist').textContent === 'AI Compose');
      check('侧栏作品数', $('#sideBgmCount').textContent === '1', $('#sideBgmCount').textContent);
      check('播完自动暂停（不切下一首）', await waitFor(() => !window.__waveDebug.engine.playing, 8000)
            && window.__waveDebug.state.currentId === work.id && $('#playBtn').title === 'Play', $('#miniTitle').textContent);

      let count = 1;
      if (hasTranslate) {
        // 生成时才翻译：输入中文后立即生成（未等预览），由生成任务自己翻译
        prompt.value = '赛博朋克风格的电子音乐，合成器';
        click($('#bgmGenerate'));
        check('中文描述直接生成', await waitFor(() => $$('.bgm-item').length === 2, 120000), $('.bgm-name').textContent);
        const cyber = window.__waveDebug.state.tracks.find(t => t.generated?.prompt?.startsWith('赛博朋克'));
        check('生成时自动翻译', cyber && !/[\u3400-\u9fff]/.test(cyber.generated.prompt_en || '中')
              && /cyberpunk/i.test(cyber.generated.prompt_en), cyber?.generated?.prompt_en);
        check('作品显示中文标题与英文译文', $$('.bgm-name')[0].textContent.startsWith('赛博朋克') && /cyberpunk/i.test($$('.bgm-desc')[0].textContent),
              $$('.bgm-desc')[0].textContent);
        click($$('.bgm-item')[0].querySelector('[data-action=reroll]'));
        check('换一首', await waitFor(() => $$('.bgm-item').length === 3, 120000));
        check('换一首沿用提示词与时长', $$('.bgm-name')[0].textContent.startsWith('赛博朋克') && $$('.bgm-desc')[0].textContent.startsWith('4 s'),
              $$('.bgm-name')[0].textContent);
        // 预览后再生成：使用的译文与预览一致
        prompt.value = '星空下的冥想，八音盒'; prompt.dispatchEvent(new Event('input', {bubbles: true}));
        await waitFor(() => !$('#bgmEnglish').textContent.startsWith('Translating')
                            && !/[\u3400-\u9fff]/.test($('#bgmEnglish').textContent) && $('#bgmEnglish').textContent.length > 3, 90000);
        const previewed = $('#bgmEnglish').textContent;
        click($('#bgmGenerate'));
        check('预览后生成', await waitFor(() => $$('.bgm-item').length === 4, 120000));
        const star = window.__waveDebug.state.tracks.find(t => t.generated?.prompt === '星空下的冥想，八音盒');
        check('所见即所得：使用预览的译文', star?.generated?.prompt_en === previewed, `${star?.generated?.prompt_en} / ${previewed}`);
        count = 4;
      }
      await waitFor(() => !window.__waveDebug.engine.playing, 8000);   // 等“换一首”自动播放的作品播完自动暂停
      click($$('.bgm-item')[0].querySelector('[data-action=play]')); await sleep(300);
      check('作品列表播放按钮可播放', await waitFor(() => window.__waveDebug.engine.playing, 5000));
      click($$('.bgm-item')[0].querySelector('[data-action=play]')); await sleep(300);
      check('再点暂停', !window.__waveDebug.engine.playing);

      // 中途取消：8 秒的生成，进度起来后取消
      click($('#bgmDuration button[data-value="8"]'));
      prompt.value = 'epic orchestral heroic theme'; prompt.dispatchEvent(new Event('input', {bubbles: true}));
      click($('#bgmGenerate'));
      check('长任务已开始', await waitFor(() => !$('#bgmProgress').hidden && !$('#bgmCancel').hidden
                                        && parseInt($('#bgmPercent').textContent) >= 10, 60000), $('#bgmPercent').textContent);
      click($('#bgmCancel'));
      check('取消生成', await waitFor(() => $('#bgmProgress').hidden && !$('#bgmGenerate').disabled, 15000));
      await sleep(500);
      check('取消后作品数不变', $$('.bgm-item').length === count, $$('.bgm-item').length);

      // 删除确认框：播放中打开，页面不能被阻塞（时间继续走）；Esc 取消不删除；点“删除”后 1 秒内完成
      click($$('.bgm-item')[0].querySelector('[data-action=play]'));
      await waitFor(() => window.__waveDebug.engine.playing, 5000);
      const victim = $$('.bgm-name')[count - 1].textContent;
      click($$('.bgm-item')[count - 1].querySelector('[data-action=remove]'));
      check('删除确认框', await waitFor(() => !$('#confirmDialog').hidden, 2000) && $('#confirmMessage').textContent.includes(victim.replace('…', '')),
            $('#confirmMessage').textContent);
      const posBefore = window.__waveDebug.position();
      await sleep(1200);
      check('确认框打开时页面不阻塞', window.__waveDebug.position() > posBefore + 0.5, `${posBefore.toFixed(1)}s → ${window.__waveDebug.position().toFixed(1)}s`);
      document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
      await sleep(300);
      check('Esc 取消不删除', $('#confirmDialog').hidden && $$('.bgm-item').length === count, $$('.bgm-item').length);
      click($$('.bgm-item')[count - 1].querySelector('[data-action=remove]'));
      await waitFor(() => !$('#confirmDialog').hidden, 2000);
      const tDel = performance.now();
      click($('#confirmOk'));
      check('删除作品', await waitFor(() => $$('.bgm-item').length === count - 1, 3000), $$('.bgm-item').length);
      check('删除后 1 秒内完成（不再卡顿）', performance.now() - tDel < 1000, Math.round(performance.now() - tDel) + 'ms');
      check('曲库总数', window.__waveDebug.state.tracks.length === count + 1, window.__waveDebug.state.tracks.length);
      check('界面文案为英文（作曲页，含作品列表）', uiCJK().length === 0, uiCJK().join('、') || '无中文');
    }
  } catch (e) { log('EXCEPTION', String(e && e.stack || e), false); }
  log('DONE', true, true);
})();
"""

ERROR_HOOK = """
const __post = (k, v) => window.webkit.messageHandlers.testlog.postMessage(JSON.stringify({k, v, ok: false}));
window.addEventListener('error', e => __post('JS 错误', e.message + ' @' + e.lineno));
window.addEventListener('unhandledrejection', e => __post('未处理的 Promise 拒绝', String(e.reason)));
"""

RESULTS: list[dict] = []
orig_create = A.PlayerWindow._create_webview


def create(self):
    webview = orig_create(self)
    manager = webview.get_user_content_manager()
    manager.add_script(WebKit2.UserScript.new(ERROR_HOOK, WebKit2.UserContentInjectedFrames.TOP_FRAME,
                                              WebKit2.UserScriptInjectionTime.START, None, None))
    manager.register_script_message_handler("testlog")

    def on_log(_manager, result):
        value = result.get_js_value() if hasattr(result, "get_js_value") else result
        message = json.loads(value.to_string())
        if message["k"] == "DONE":
            GLib.timeout_add(500, lambda: self.app.quit())
            return
        RESULTS.append(message)
        print(f"  {'✅' if message['ok'] else '❌'} {message['k']:<28} {message['v']}", flush=True)

    manager.connect("script-message-received::testlog", on_log)
    webview.connect("load-changed", lambda w, ev: ev == WebKit2.LoadEvent.FINISHED and GLib.timeout_add(
        1500, lambda: (self.run_js(TEST_JS), False)[1]))
    return webview


def main() -> int:
    A.APP_ID = "io.github.wavemusic.e2etest"  # 独立的应用 ID：用户正在运行的播放器不会把测试实例“吸收”掉
    A.PlayerWindow._create_webview = create
    GLib.timeout_add_seconds(600, lambda: (RESULTS.append({"k": "超时", "v": "600s", "ok": False}),
                                           A.Gtk.Application.get_default().quit()))
    A.main()

    # 重启后的持久化检查：歌单
    db = sqlite3.connect(str(DB_FILE))
    playlists = db.execute("SELECT p.name, COUNT(t.track_id) FROM playlists p LEFT JOIN playlist_tracks t ON t.playlist_id = p.id "
                           "GROUP BY p.id").fetchall()
    db.close()
    ok = playlists == [("收藏", 1)]
    RESULTS.append({"k": "重启后歌单仍在（收藏：1 首）", "v": str(playlists), "ok": ok})
    print(f"  {'✅' if ok else '❌'} {RESULTS[-1]['k']:<28} {RESULTS[-1]['v']}")

    # 重启后的持久化检查：作品仍在曲库、文件存在；被删除的作品文件已删除
    db = sqlite3.connect(str(DB_FILE))
    rows = db.execute("SELECT title, path FROM tracks WHERE format = 'AI'").fetchall()
    db.close()
    dirs = sorted(p.name for p in GENERATED_DIR.iterdir()) if GENERATED_DIR.exists() else []
    from wavemusic.config import detect_ai_environment
    env = detect_ai_environment()
    works = (3 if env["translate"]["available"] else 0) if env["compose"]["available"] else 0
    ok = len(rows) == works and all(os.path.isfile(p) for _, p in rows) and len(dirs) == works
    RESULTS.append({"k": f"重启后作品仍在曲库（{works} 首，取消的不残留）", "v": f"{len(rows)} 首 / {len(dirs)} 个目录", "ok": ok})
    print(f"  {'✅' if ok else '❌'} {RESULTS[-1]['k']:<28} {RESULTS[-1]['v']}")
    referenced = {Path(p).parent.name for _, p in rows}
    for name in dirs:
        if name not in referenced:
            files = sorted(f.name for f in (GENERATED_DIR / name).iterdir())
            meta = GENERATED_DIR / name / "meta.json"
            info = json.loads(meta.read_text("utf-8")).get("summary") if meta.exists() else ""
            print(f"     未被曲库引用的目录：{name} 文件={files} {info}")

    failed = [r for r in RESULTS if not r["ok"]]
    print(f"\n共 {len(RESULTS)} 项，失败 {len(failed)} 项")
    shutil.rmtree(TMP, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
