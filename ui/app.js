(() => {
  'use strict';

  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => document.querySelectorAll(selector);
  const APP_NAME = 'Rhythm Crafter Player';   // 品牌名：不翻译，中英文界面均显示原名
  const trackList = $('#trackList');
  const seekBar = $('#seekBar');
  const playButton = $('#playBtn');
  const volumeSlider = $('#volumeSlider');
  const speedSlider = $('#speedSlider');
  const searchInput = $('#searchInput');

  const EFFECT_NAMES = { clean: 'Original', glitch: 'Glitch Radio', demon: 'Abyss Whisper', echo: 'Canyon Echo' };
  const TARGET_NAMES = { all: 'Whole song', vocals: 'Vocals only', accompaniment: 'Backing only' };
  const PRESETS = {
    karaoke: { vocalGain: 0, accGain: 1, fxTarget: 'all' },
    vocalfx: { vocalGain: 1, accGain: 1, fxTarget: 'vocals', effect: 'demon' },
    bgmfx: { vocalGain: 1, accGain: 1, fxTarget: 'accompaniment', effect: 'glitch' },
    acapella: { vocalGain: 1, accGain: 0, fxTarget: 'all' },
  };
  // 后端为没有歌手信息的歌曲、AI 作品填写的占位歌手名（存在曲库中，不修改数据），界面上显示为英文
  const ARTIST_PLACEHOLDERS = { '未知歌手': 'Unknown artist', 'AI 作曲': 'AI Compose', 'AI 作曲（云端）': 'Cloud Song' };
  const artistOf = (track) => t(ARTIST_PLACEHOLDERS[track?.artist] || track?.artist || '');
  const STAGE_NAMES = { start: 'Starting', load: 'Loading model', decode: 'Decoding audio', separate: 'Splitting', write: 'Writing files' };
  const DEFAULT_SETTINGS = {
    volume: 0.75, effect: 'clean', speed: 1, shuffle: false, repeatOne: false,
    stemSource: 'original', fxTarget: 'all', vocalGain: 1, accGain: 1, lastTrackId: null, composeMode: 'local',
    lang: 'en',
  };

  /* ======================= 界面中英文切换 ======================= */
  // 词典以英文原文为 key，覆盖静态界面文案、常见动态提示以及部分后端状态原因（后端只输出英文，这里再反译一次）。
  const ZH = {
    // 顶栏 / 导航
    'Search local music': '搜索本地音乐', 'Back': '返回', 'Forward': '前进',
    'My Music': '我的音乐', 'Local Music': '本地音乐', 'Now Playing': '正在播放', 'Sound Lab': '音效实验室',
    'AI Compose': 'AI 作曲', 'My Playlists': '我的歌单', 'New playlist': '新建歌单', 'Main navigation': '主导航',
    'Switch language': '切换语言',
    // 本地曲库
    'Playlist': '歌单', 'Local Library': '本地曲库', 'Local user': '本地用户', 'Me': '我',
    'Library saved automatically · Audio and AI processing run entirely on this device': '曲库自动保存 · 音频和 AI 处理均在本机完成',
    'Play All': '全部播放', 'Add Music': '添加音乐', 'Add Folder': '添加文件夹', 'Clear List': '清空列表',
    'Songs:': '歌曲数：', 'Total duration:': '总时长：', 'Songs': '歌曲', 'Title': '标题', 'Artist': '歌手',
    'Format': '格式', 'Duration': '时长', 'AI Split': 'AI 分轨',
    'No local music yet': '还没有本地音乐', 'Add audio files or a whole folder, or drag files into the window': '添加音频文件或整个文件夹，也可以直接拖到窗口里',
    'Choose Audio Files': '选择音频文件',
    // 歌单
    'Rename': '重命名', 'Delete Playlist': '删除歌单', 'This playlist is empty': '这个歌单还是空的',
    'In Local Music, click + next to a song to add it to this playlist': '在本地音乐里，点歌曲旁边的 + 就能加进这个歌单',
    'Click + to create a playlist': '点 + 创建一个歌单', 'Add to playlist': '加到歌单', 'New playlist…': '新建歌单…',
    // 正在播放
    'Nothing playing': '没有播放任何内容', 'Artist:': '歌手：', 'Format:': '格式：', 'Source:': '来源：',
    'No lyrics for local music': '本地音乐没有歌词', 'Current effect · Original': '当前音效 · 原声', 'Audio spectrum': '音频频谱',
    '—': '—',
    // 音效实验室
    'AI Vocal Split · Karaoke Mode': 'AI 人声分离 · K 歌模式',
    'Split a song into vocals and accompaniment, then apply effects to the vocals only': '把一首歌分成人声和伴奏，只对人声加效果',
    'Current song': '当前歌曲', 'No song selected': '未选择歌曲', 'Start Split': '开始分离', 'Cancel': '取消',
    'Delete Split Tracks': '删除分轨', 'Retry Split': '重试分离', 'Split Again': '再次分离',
    'Playback source': '播放源', 'Original': '原声', 'Split tracks': '分轨', 'Quick modes': '快捷模式',
    'Karaoke': 'K 歌', 'Vocals FX': '人声特效', 'Backing FX': '伴奏特效', 'A cappella': '清唱',
    'Apply effect to': '特效作用于', 'Whole song': '整首歌', 'Vocals only': '仅人声', 'Backing only': '仅伴奏',
    'Vocal volume': '人声音量', 'Backing volume': '伴奏音量', 'Fun Effects': '有趣音效', 'Choose an effect': '选择一个音效',
    'No processing, just the original sound': '不处理，保持原声', 'Glitch Radio': '故障收音机',
    'Distortion and crackle like an old radio': '像老收音机一样的失真和噪音', 'Abyss Whisper': '深渊低语',
    'A deep, heavy monster voice': '深沉沉重的怪物声音', 'Canyon Echo': '峡谷回音', 'Layered echoes in an empty valley': '空谷里层层叠加的回声',
    'Speed / Pitch': '变速 / 变调', 'Deep 0.70×': '沉稳 0.70×', 'Normal': '正常', 'Sharp 1.30×': '明亮 1.30×',
    'Reset Speed': '重置速度', 'AI not ready': 'AI 未就绪', 'Unavailable': '不可用', 'Checking…': '检测中…',
    'Processing': '处理中', 'Last split failed': '上次分离失败', 'Not split': '未分离',
    'Split-track mode: this song has not been split yet, playing the original': '分轨模式：这首歌还没分轨，正在播放原声',
    'Current effect · {effect}{target}': '当前音效 · {effect}{target}', 'AI split tracks · {label}': 'AI 分轨 · {label}',
    // AI 作曲
    'Turn one sentence into a short instrumental piece, or a full cloud song with vocals': '一句话生成一段短音乐，或一首带人声的完整云端歌曲',
    'Describe the music you want': '描述你想要的音乐', 'Include style, mood, instruments and tempo. Chinese works too': '包含风格、情绪、乐器和节奏，中文描述也行',
    'Mode': '模式', 'Local instrumental': '本地纯音乐', 'Cloud song (vocals)': '云端歌曲（人声）',
    'Cloud mode': '云端模式',
    'Sends your description to a cloud service over the internet to generate a full song with AI-written lyrics and vocals. Usage is billed by the cloud provider.':
      '会把你的描述通过网络发送到云端服务，生成一首带 AI 自动写词和人声演唱的完整歌曲，按用量计费。',
    'e.g. rainy day nostalgia, piano, slow tempo (Chinese is translated to English automatically; Ctrl+Enter to generate)':
      '例如：雨天的思念，钢琴，慢节奏（Ctrl+Enter 生成）',
    'Model will receive': '模型将收到', 'Edit in English': '改成英文编辑',
    'Put the English translation into the input box so you can keep editing': '把英文译文填入输入框，方便继续修改',
    'Try these': '试试这些', 'Lazy jazz bar, electric piano and saxophone': '懒洋洋的爵士酒吧，电钢琴和小号',
    'Cyberpunk electronic music, synthesizer': '赛博朋克电子音乐，合成器', 'Length': '时长', 'Note': '注',
    'About 11 s to generate': '大约 11 秒生成', 'Cancel ': '取消', 'Generate': '生成',
    'Cloud songs usually take 30–90 s and include AI-written lyrics': '云端歌曲通常需要 30~90 秒，包含 AI 自动写的歌词',
    'Queued…': '排队中…', 'Generating…': '生成中…', 'My Creations': '我的作品',
    'No creations yet. Try typing a description above': '还没有作品，在上面输入一段描述试试',
    'Compose not ready': '作曲功能未就绪', 'Cloud song not configured': '云端歌曲未配置',
    'Translating…': '翻译中…', 'Translating… (starts automatically when you stop typing)': '翻译中…（停止输入后自动开始）',
    'Chinese translation is unavailable': '中文翻译不可用', '; you can describe the music in English instead': '；你可以直接用英文描述',
    'piece': '首', 'pieces': '首',
    // 底部播放栏
    'Hear music differently': '换个方式听音乐', 'Open Now Playing': '打开正在播放', 'Shuffle': '随机播放',
    'Previous': '上一首', 'Play': '播放', 'Next': '下一首', 'Repeat all': '循环播放全部', 'Repeat one': '单曲循环',
    'AI vocal split': 'AI 人声分离', 'Mute': '静音', 'Playback position': '播放进度', 'Volume': '音量', 'Shuffle on': '随机播放已开',
    'Play in order': '按顺序播放',
    // 弹窗 / 确认框
    'OK': '确定', 'Delete': '删除', 'Create': '创建', 'Save': '保存', 'Rename playlist': '重命名歌单',
    'Clear the library? (Music files on disk are kept, but AI split tracks and AI Compose creations are deleted.)':
      '清空曲库？（磁盘上的音乐文件会保留，但 AI 分轨和 AI 作曲作品会被删除。）',
    // 提示 / 错误
    'Please start the app with wave_music.py': '请用 wave_music.py 启动程序',
    'Could not read the split tracks. Please split the song again': '读取分轨文件失败，请重新分离',
    'Cannot decode this file; a decoder may be missing': '无法解码这个文件，可能缺少解码器',
    'File not found or has been moved': '文件不存在或已被移动', 'Audio longer than 30 minutes is not supported yet': '暂不支持超过 30 分钟的音频',
    'The selected songs are already in the library or are not audio files': '选中的歌曲已在曲库中，或不是音频文件',
    'The dropped files are already in the library or are not audio files': '拖入的文件已在曲库中，或不是音频文件',
    'Renamed': '已重命名', 'Split tracks deleted': '分轨已删除',
    'This song has not been split yet; splitting started automatically': '这首歌还没分轨，已自动开始分离',
    'AI environment is not ready': 'AI 环境未就绪', 'Generating, please wait': '正在生成，请稍候',
    'Please enter a music description first': '请先输入音乐描述', 'Generation cancelled': '已取消生成',
    // 未知歌手 / 作曲占位
    'Unknown artist': '未知歌手', 'Cloud Song': '云端歌曲',
    // 分离进度阶段
    'Starting': '开始', 'Loading model': '加载模型', 'Decoding audio': '解码音频', 'Splitting': '分离中', 'Writing files': '写入文件',
    // 常见后端状态原因（已译成英文的后端消息，这里再反译成中文）
    'AI Compose model not found (run scripts/setup-musicgen.sh)': '未找到 AI 作曲模型（运行 scripts/setup-musicgen.sh）',
    'No Python with numpy / onnxruntime / tokenizers found (run scripts/setup-ai.sh)': '未找到装有 numpy / onnxruntime / tokenizers 的 Python（运行 scripts/setup-ai.sh）',
    'Cloud song generation is off by default (set cloud_song_enabled=true in config.json to turn it on)': '云端生成默认关闭（config.json 设置 cloud_song_enabled=true 后开启）',
    'cloud_song_workflow_id / cloud_song_token is not configured (see config.json)': '未配置 cloud_song_workflow_id / cloud_song_token（见 config.json）',
    'Spleeter model not found (run scripts/fetch-models.sh)': '未找到 Spleeter 模型（运行 scripts/fetch-models.sh）',
    'gst-launch-1.0 is missing (sudo apt install gstreamer1.0-tools)': '缺少 gst-launch-1.0（sudo apt install gstreamer1.0-tools）',
    'onnxruntime / tokenizers is missing': '缺少 onnxruntime / tokenizers',
    'Chinese translation model not found (run scripts/setup-translate.sh)': '未找到中文翻译模型（运行 scripts/setup-translate.sh）',
    'No Python with sherpa-onnx found (run scripts/setup-ai.sh, or set ai_python in config.json)': '未找到装有 sherpa-onnx 的 Python（运行 scripts/setup-ai.sh，或在 config.json 设置 ai_python）',
  };
  const t = (text) => (state.settings?.lang === 'zh' && ZH[text]) ? ZH[text] : text;
  /** 带占位符的文案（{xxx}），vars 里的值不再翻译（歌曲名/歌单名等用户内容）。 */
  function tf(template, vars) {
    let text = t(template);
    for (const key of Object.keys(vars || {})) text = text.split(`{${key}}`).join(vars[key]);
    return text;
  }
  const TPL = {
    addedSongs: (n) => (state.settings.lang === 'zh' ? `已添加 ${n} 首歌曲` : `Added ${n} ${n === 1 ? 'song' : 'songs'}`),
    newPlaylistName: (n) => (state.settings.lang === 'zh' ? `新建歌单 ${n}` : `New playlist ${n}`),
    addedToPlaylist: (name) => tf('Added to playlist “{name}”', { name }),
    createdPlaylist: (name) => tf('Created playlist “{name}”', { name }),
    alreadyInPlaylist: (name) => tf('Already in playlist “{name}”', { name }),
    deletedPlaylist: (name) => tf('Deleted playlist “{name}”', { name }),
    confirmDeletePlaylist: (name) => tf('Delete playlist “{name}”? Its songs stay in Local Music.', { name }),
    confirmDeleteCreation: (title) => tf('Delete the AI creation “{title}”? Its audio file will be deleted too.', { title }),
    queuedSplitting: (title) => tf('Queued for splitting: {title}', { title }),
    splitFailed: (title, message) => (title ? tf('Split failed: {title} ({message})', { title, message }) : tf('Split failed ({message})', { message })),
    splitComplete: (title, elapsed) => tf('Split complete: {title} (took {elapsed} s)', { title, elapsed }),
    generationFailed: (message) => tf('Generation failed: {message}', { message }),
    generated: (title, seconds, elapsed) => tf('Generated: {title} ({seconds} s, took {elapsed} s)', { title, seconds, elapsed }),
    fileNotFound: (path) => tf('File not found: {path}', { path }),
    createdOn: (date) => tf('Created {date}', { date }),
  };
  Object.assign(ZH, {
    'Added to playlist “{name}”': '已添加到歌单“{name}”', 'Created playlist “{name}”': '已创建歌单“{name}”',
    'Already in playlist “{name}”': '已在歌单“{name}”里', 'Deleted playlist “{name}”': '已删除歌单“{name}”',
    'Delete playlist “{name}”? Its songs stay in Local Music.': '删除歌单“{name}”？里面的歌曲会保留在本地音乐里。',
    'Delete the AI creation “{title}”? Its audio file will be deleted too.': '删除 AI 作品“{title}”？音频文件也会一起删除。',
    'Queued for splitting: {title}': '已加入分离队列：{title}',
    'Split failed: {title} ({message})': '分离失败：{title}（{message}）', 'Split failed ({message})': '分离失败（{message}）',
    'Split complete: {title} (took {elapsed} s)': '分离完成：{title}（用时 {elapsed} 秒）',
    'Generation failed: {message}': '生成失败：{message}',
    'Generated: {title} ({seconds} s, took {elapsed} s)': '已生成：{title}（{seconds} 秒，用时 {elapsed} 秒）',
    'File not found: {path}': '文件不存在：{path}', 'Created {date}': '创建于 {date}', 'About {n} s to generate': '大约 {n} 秒生成',
    'Play': '播放', 'Retry': '重试', 'Queued': '排队中', 'Failed': '失败', 'Split': '分离',
    'Vocals and accompaniment are ready': '人声和伴奏已就绪', 'AI-split vocals and accompaniment': 'AI 分离人声和伴奏',
    'Add to playlist': '加到歌单', 'Remove from library': '从曲库移除',
    'Remove from playlist (the song stays in your library)': '从歌单移除（歌曲仍保留在曲库里）',
    'Added': '已添加', 'Clear': '清空', 'Pause': '暂停',
    '{n} piece': '{n} 首', '{n} pieces': '{n} 首',
    'Generate another one with the same prompt and length': '用同样的描述和时长再生成一首', 'Another': '再来一首', 'Delete creation': '删除作品',
    'Add to playlist': '加到歌单', 'Added': '已添加',
  });

  /** 页面加载时就扫描一次静态文本节点/属性，记下原始英文；切语言时直接按词典替换。
   *  只处理页面加载时就已存在的静态元素；后续由 JS 重新赋值的文本由对应的 render/update 函数通过 t() 自己处理。 */
  const I18N_NODES = [];
  function collectI18nNodes() {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        const parent = node.parentElement;
        if (!parent || parent.closest('script,style')) return NodeFilter.FILTER_REJECT;
        return node.textContent.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      },
    });
    let node;
    while ((node = walker.nextNode())) I18N_NODES.push({ node, kind: 'text', original: node.textContent });
    document.querySelectorAll('[title],[placeholder],[aria-label]').forEach((el) => {
      ['title', 'placeholder', 'aria-label'].forEach((attr) => {
        const value = el.getAttribute(attr);
        if (value && /[A-Za-z]/.test(value)) I18N_NODES.push({ node: el, kind: attr, original: value });
      });
    });
  }
  collectI18nNodes();
  function refreshNowPlayingLabels() {
    const track = state.currentId ? trackById(state.currentId) : null;
    updateLyrics(track);
    if (!track) return;
    $('#trackArtist').textContent = artistOf(track);
    $('#miniArtist').textContent = artistOf(track);
    document.title = `${track.title} - ${artistOf(track)} · ${APP_NAME}`;
  }
  function applyLanguage(lang) {
    state.settings.lang = lang;
    document.documentElement.lang = lang;
    for (const { node, kind, original } of I18N_NODES) {
      const trimmed = original.trim();
      const translated = lang === 'zh' && ZH[trimmed] ? original.replace(trimmed, ZH[trimmed]) : original;
      if (kind === 'text') node.textContent = translated; else node.setAttribute(kind, translated);
    }
    $('#langToggle').textContent = lang === 'zh' ? '中' : 'EN';
    saveSettings({ lang });
    renderTracks(); renderPlaylistNav(); renderBgmList(); updateComposePanel(); updateStemsPanel(); updateModeLabels();
    updateCounts(); refreshNowPlayingLabels();
    if (state.view.startsWith('playlist:')) renderPlaylistView();
  }

  const state = {
    tracks: [],
    currentId: null,
    selectedId: null,
    ai: null,          // AI 环境检测结果；null 表示检测中
    warm: {},          // 常驻模型状态：{ translate, musicgen } → off / loading / ready
    jobs: {},          // trackId → { status: queued|running|error, progress, stage, message }
    settings: { ...DEFAULT_SETTINGS },
    stemsActive: false,
    view: 'library',   // library / player / effects / compose / playlist:<id>
    playlists: [],     // 自建歌单 [{ id, name, created_at, track_ids }]
    queue: null,       // 播放队列（从歌单播放时为歌单曲目；null 表示按本地曲库顺序）
  };
  const backStack = [];
  const forwardStack = [];

  /* ======================= 消息桥 ======================= */
  const bridge = (() => {
    let seq = 0;
    const pending = new Map();
    const listeners = {};
    window.__waveBridge = {
      reply(id, ok, data) {
        const entry = pending.get(id);
        if (!entry) return;
        pending.delete(id);
        ok ? entry.resolve(data) : entry.reject(new Error(data));
      },
      emit(name, data) { (listeners[name] || []).forEach((fn) => fn(data)); },
    };
    const handler = window.webkit?.messageHandlers?.bridge;
    return {
      available: Boolean(handler),
      call(cmd, args = {}) {
        if (!handler) return Promise.reject(new Error('Please start the app with wave_music.py'));
        return new Promise((resolve, reject) => {
          const id = ++seq;
          pending.set(id, { resolve, reject });
          handler.postMessage(JSON.stringify({ id, cmd, args }));
        });
      },
      on(name, fn) { (listeners[name] ||= []).push(fn); },
    };
  })();

  /* ======================= 工具 ======================= */
  const icon = (name) => `<svg><use href="#i-${name}"/></svg>`;
  const escapeHtml = (text) => String(text).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const formatTime = (seconds) => {
    if (!Number.isFinite(seconds) || seconds < 0) return '00:00';
    const minutes = Math.floor(seconds / 60);
    const rest = Math.floor(seconds % 60);
    return `${String(minutes).padStart(2, '0')}:${String(rest).padStart(2, '0')}`;
  };
  const hueOf = (text) => {
    let hash = 0;
    for (const ch of text) hash = (hash * 31 + ch.codePointAt(0)) >>> 0;
    return hash % 360;
  };
  const trackById = (id) => state.tracks.find((t) => t.id === id);
  const currentTrack = () => trackById(state.currentId);

  let toastTimer;
  function toast(message, ms = 1800) {
    const el = $('#toast');
    el.textContent = t(message);
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, ms);
  }
  const fail = (error) => toast(error?.message || String(error), 3000);

  function setSliderFill(slider) {
    const min = Number(slider.min || 0);
    const max = Number(slider.max || 1);
    slider.style.setProperty('--p', `${((Number(slider.value) - min) / (max - min)) * 100}%`);
  }

  let saveTimer;
  const dirty = {};
  function saveSettings(values) {
    Object.assign(state.settings, values);
    Object.assign(dirty, values);
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      const payload = { ...dirty };
      Object.keys(dirty).forEach((k) => delete dirty[k]);
      bridge.call('settings.set', { values: payload }).catch(() => {});
    }, 400);
  }

  /* ======================= 视图 ======================= */
  function showView(view, record = true) {
    if (view === state.view) return;
    if (record) { backStack.push(state.view); forwardStack.length = 0; }
    if (view.startsWith('playlist:') && !playlistById(Number(view.slice(9)))) view = 'library';   // 歌单已被删除
    state.view = view;
    const section = view.startsWith('playlist:') ? 'playlist' : view;
    $$('.view').forEach((el) => el.classList.toggle('active', el.id === `view-${section}`));
    if (section === 'playlist') renderPlaylistView();
    let marked = false;
    $$('.nav-item').forEach((el) => {
      const on = !marked && el.dataset.view === view;
      if (on) marked = true;
      el.classList.toggle('active', on);
    });
    $('#backBtn').disabled = !backStack.length;
    $('#forwardBtn').disabled = !forwardStack.length;
    if (view === 'compose') warmModels();
  }
  $$('.nav-item').forEach((el) => el.addEventListener('click', () => showView(el.dataset.view)));
  $('#backBtn').addEventListener('click', () => {
    if (!backStack.length) return;
    forwardStack.push(state.view);
    showView(backStack.pop(), false);
  });
  $('#forwardBtn').addEventListener('click', () => {
    if (!forwardStack.length) return;
    backStack.push(state.view);
    showView(forwardStack.pop(), false);
  });
  $('#miniCover').addEventListener('click', () => showView(state.view === 'player' ? 'library' : 'player'));
  $('#fxBadge').addEventListener('click', () => showView('effects'));
  $('#stemBadge').addEventListener('click', () => showView('effects'));

  /* ======================= 播放引擎（纯 Web Audio） =======================
   * 注意：WebKitGTK 2.50 中，<audio> 接入 Web Audio（MediaElementAudioSourceNode）后，
   * 暂停再播放会永久卡死；因此整首解码为 AudioBuffer，用 BufferSource 播放，
   * 暂停/跳转/变速由引擎自己维护时间轴。原曲与分离音轨共用同一时钟，严格同步。
   *   原曲：original ─────→ origGain ──────────────→ fxIn
   *   分离：vocals ───────→ vocalGain ─┬→ fxIn / bypass（取决于“音效作用于”）
   *         accompaniment → accGain ───┘
   *   fxIn → 滤波 → 失真 → 干/湿(回声) → fxOut ─┐
   *                                 bypass ─────┴→ master → analyser → 扬声器
   */
  const MAX_DECODE_SECONDS = 30 * 60;  // 整首解码约 0.35 MB/秒，限制超长音频避免占满内存
  let audioContext;
  let nodes;
  const engine = {
    trackId: null,
    original: null,     // 原曲 AudioBuffer
    stems: null,        // { vocals, accompaniment }
    sources: [],
    playing: false,
    offset: 0,          // 媒体时间（暂停位置 / 上次启动位置）
    startedAt: 0,       // 上次启动时的 audioContext 时间
    rate: 1,
    loadToken: 0,
  };

  function initAudioGraph() {
    if (audioContext) return;
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) return;
    audioContext = new AudioContextClass();
    const ctx = audioContext;
    const n = {
      origGain: ctx.createGain(),
      vocalGain: ctx.createGain(),
      accGain: ctx.createGain(),
      fxIn: ctx.createGain(),
      filter: ctx.createBiquadFilter(),
      shaper: ctx.createWaveShaper(),
      delay: ctx.createDelay(1.5),
      feedback: ctx.createGain(),
      dry: ctx.createGain(),
      wet: ctx.createGain(),
      fxOut: ctx.createGain(),
      bypass: ctx.createGain(),
      master: ctx.createGain(),
      analyser: ctx.createAnalyser(),
    };
    n.filter.type = 'lowpass';
    n.filter.frequency.value = 20000;
    n.shaper.oversample = '4x';
    n.delay.delayTime.value = 0.28;
    n.analyser.fftSize = 256;
    n.analyser.smoothingTimeConstant = 0.82;

    n.fxIn.connect(n.filter);
    n.filter.connect(n.shaper);
    n.shaper.connect(n.dry);
    n.dry.connect(n.fxOut);
    n.shaper.connect(n.delay);
    n.delay.connect(n.wet);
    n.delay.connect(n.feedback);
    n.feedback.connect(n.delay);
    n.wet.connect(n.fxOut);
    n.fxOut.connect(n.master);
    n.bypass.connect(n.master);
    n.master.connect(n.analyser);
    n.analyser.connect(ctx.destination);
    n.master.gain.value = Number(volumeSlider.value);
    nodes = n;
    applyRouting();
    applyEffect(state.settings.effect, false);
  }

  function applyRouting() {
    if (!nodes) return;
    const { origGain, vocalGain, accGain, fxIn, bypass } = nodes;
    [origGain, vocalGain, accGain].forEach((node) => node.disconnect());
    const target = state.settings.fxTarget;
    origGain.connect(fxIn);
    vocalGain.connect(target === 'all' || target === 'vocals' ? fxIn : bypass);
    accGain.connect(target === 'all' || target === 'accompaniment' ? fxIn : bypass);
    applyStemGains();
  }

  function applyStemGains() {
    if (!nodes) return;
    const now = audioContext.currentTime;
    nodes.vocalGain.gain.setTargetAtTime(state.settings.vocalGain, now, 0.03);
    nodes.accGain.gain.setTargetAtTime(state.settings.accGain, now, 0.03);
  }

  function distortionCurve(amount) {
    if (!amount) return null;
    const samples = 44100;
    const curve = new Float32Array(samples);
    for (let i = 0; i < samples; i++) {
      const x = (i * 2) / samples - 1;
      curve[i] = ((3 + amount) * x * 20 * (Math.PI / 180)) / (Math.PI + amount * Math.abs(x));
    }
    return curve;
  }

  function effectiveRate() {
    const value = Number(speedSlider.value);
    return state.settings.effect === 'demon' ? Math.min(value, 0.82) : value;
  }

  function applyEffect(effect, save = true) {
    if (save) saveSettings({ effect });
    else state.settings.effect = effect;
    $$('.effect-card').forEach((card) => card.classList.toggle('selected', card.dataset.effect === effect));
    setRate(effectiveRate());
    updateModeLabels();
    if (!nodes) return;

    const now = audioContext.currentTime;
    const set = (param, value) => param.setTargetAtTime(value, now, 0.035);
    nodes.filter.type = 'lowpass';
    set(nodes.filter.frequency, 20000);
    set(nodes.filter.Q, 0.7);
    set(nodes.dry.gain, 1);
    set(nodes.wet.gain, 0);
    set(nodes.feedback.gain, 0.2);
    set(nodes.delay.delayTime, 0.28);
    nodes.shaper.curve = null;

    if (effect === 'glitch') {
      nodes.filter.type = 'bandpass';
      set(nodes.filter.frequency, 1250);
      set(nodes.filter.Q, 0.85);
      nodes.shaper.curve = distortionCurve(45);
      set(nodes.dry.gain, 0.82);
      set(nodes.wet.gain, 0.2);
      set(nodes.delay.delayTime, 0.11);
      set(nodes.feedback.gain, 0.32);
    } else if (effect === 'demon') {
      set(nodes.filter.frequency, 520);
      set(nodes.filter.Q, 1.1);
      nodes.shaper.curve = distortionCurve(18);
      set(nodes.dry.gain, 0.92);
    } else if (effect === 'echo') {
      nodes.filter.type = 'highpass';
      set(nodes.filter.frequency, 140);
      set(nodes.wet.gain, 0.38);
      set(nodes.delay.delayTime, 0.36);
      set(nodes.feedback.gain, 0.43);
    }
  }

  /* ---------- 时间轴 ---------- */
  function position() {
    if (!engine.playing || !audioContext) return engine.offset;
    return engine.offset + Math.max(0, audioContext.currentTime - engine.startedAt) * engine.rate;
  }
  function duration() {
    return engine.original?.duration || engine.stems?.vocals.duration || currentTrack()?.duration || 0;
  }

  async function decodeUri(uri) {
    const response = await fetch(uri);
    if (!response.ok && response.status !== 0) throw new Error(`Failed to read: ${uri}`);
    return audioContext.decodeAudioData(await response.arrayBuffer());
  }

  function stopSources() {
    engine.sources.forEach((source) => {
      source.onended = null;
      try { source.stop(); } catch { /* 已停止 */ }
      source.disconnect();
    });
    engine.sources = [];
  }

  function startSources() {
    stopSources();
    if (!engine.playing || !nodes) return;
    const useStems = state.stemsActive && engine.stems;
    const pairs = useStems
      ? [[engine.stems.vocals, nodes.vocalGain], [engine.stems.accompaniment, nodes.accGain]]
      : engine.original ? [[engine.original, nodes.origGain]] : [];
    const when = audioContext.currentTime + 0.03;
    pairs.forEach(([buffer, destination], index) => {
      const source = audioContext.createBufferSource();
      source.buffer = buffer;
      source.playbackRate.value = engine.rate;
      source.connect(destination);
      if (index === 0) source.onended = () => { if (engine.sources[0] === source) onEnded(); };
      source.start(when, Math.min(engine.offset, buffer.duration));
      engine.sources.push(source);
    });
    engine.startedAt = when;
  }

  function onEnded() {
    engine.playing = false;
    engine.offset = 0;
    stopSources();
    updatePlayButton();
    if (currentTrack()?.generated) { updateProgress(); return; }  // AI 作品播放完自动暂停（回到开头），不切下一首
    if (state.settings.repeatOne) play();
    else nextTrack(1);
  }

  async function play() {
    const track = currentTrack();
    if (!track) return;
    initAudioGraph();
    if (audioContext.state === 'suspended') await audioContext.resume();
    if (!engine.original && !(state.stemsActive && engine.stems)) return;  // 仍在加载
    if (engine.offset >= duration() - 0.05) engine.offset = 0;
    engine.playing = true;
    startSources();
    updatePlayButton();
  }

  function pause() {
    if (!engine.playing) return;
    engine.offset = position();
    engine.playing = false;
    stopSources();
    updatePlayButton();
  }

  function seek(time) {
    engine.offset = Math.max(0, Math.min(time, Math.max(0, duration() - 0.05)));
    if (engine.playing) startSources();
    updateProgress();
  }

  function setRate(rate) {
    if (engine.playing && audioContext) {
      engine.offset = position();
      engine.startedAt = audioContext.currentTime;
      engine.sources.forEach((source) => source.playbackRate.setValueAtTime(rate, audioContext.currentTime));
    }
    engine.rate = rate;
  }

  /* ======================= 播放控制 ======================= */
  function updatePlayButton() {
    const playing = engine.playing;
    playButton.innerHTML = icon(playing ? 'pause' : 'play');
    playButton.title = playing ? 'Pause' : 'Play';
    playButton.setAttribute('aria-label', playButton.title);
    document.body.classList.toggle('playing', playing);
    if (bgmPrompt) renderBgmList();
  }

  function setLoading(on) {
    playButton.classList.toggle('loading', on);
    if (on) playButton.title = 'Loading…';
    else updatePlayButton();  // 恢复“播放 / 暂停”提示（否则会一直停留在“加载中…”）
  }

  async function togglePlayback() {
    if (!currentTrack()) {
      if (state.tracks.length) loadTrack(visibleOrder()[0] ?? state.tracks[0].id, true);
      else addFiles(false);
      return;
    }
    if (engine.playing) pause();
    else await play();
  }

  function stemsReady(track) {
    return Boolean(track && track.stems?.status === 'done');
  }

  function updateProgress() {
    const total = duration();
    const now = Math.min(position(), total || Infinity);
    if (!seeking && total > 0) {
      seekBar.value = Math.round((now / total) * Number(seekBar.max));
      setSliderFill(seekBar);
    }
    $('#currentTime').textContent = formatTime(now);
  }

  /** 按设置加载所需的音频缓冲区，并决定是否使用分离音轨（切换无缝、保持位置） */
  async function syncStemMode() {
    const track = currentTrack();
    if (!track) { state.stemsActive = false; updateStemsPanel(); return; }
    const want = state.settings.stemSource === 'stems' && stemsReady(track);
    const stillCurrent = () => state.currentId === track.id && engine.trackId === track.id;
    try {
      if (want && !engine.stems) {
        setLoading(true);
        const [vocals, accompaniment] = await Promise.all([decodeUri(track.stems.vocals), decodeUri(track.stems.accompaniment)]);
        if (!stillCurrent()) return;
        engine.stems = { vocals, accompaniment };
      } else if (!want && !engine.original) {
        setLoading(true);
        const original = await decodeUri(track.uri);
        if (!stillCurrent()) return;
        engine.original = original;
      }
    } catch (error) {
      console.warn(error);
      if (stillCurrent()) toast(want ? 'Could not read the split tracks. Please split the song again' : 'Cannot decode this file; a decoder may be missing', 3000);
      return;
    } finally {
      if (stillCurrent()) setLoading(false);
    }
    if (want !== state.stemsActive) {
      if (engine.playing) { engine.offset = position(); }
      state.stemsActive = want;
      if (engine.playing) startSources();
    }
    updateStemsPanel();
  }

  function updateLyrics(track) {
    const lyrics = track?.generated?.lyrics;
    const box = $('#lyricsText').closest('.lyric-box');
    if (lyrics) {
      $('#lyricsText').textContent = lyrics;
      $('#lyricsText').hidden = false;
      $('#lyricHint').hidden = true;
      box.classList.add('has-lyrics');
    } else {
      $('#lyricsText').hidden = true;
      $('#lyricsText').textContent = '';
      $('#lyricHint').hidden = false;
      $('#lyricHint').textContent = t('No lyrics for local music');
      box.classList.remove('has-lyrics');
    }
  }

  async function loadTrack(id, autoplay = false) {
    const track = trackById(id);
    if (!track) return;
    if (track.missing) { toast('File not found or has been moved'); return; }
    if (track.duration > MAX_DECODE_SECONDS) { toast('Audio longer than 30 minutes is not supported yet', 3000); return; }
    initAudioGraph();
    const token = ++engine.loadToken;
    engine.playing = false;
    stopSources();
    engine.offset = 0;
    if (engine.trackId !== id) {
      engine.trackId = id;
      engine.original = null;
      engine.stems = null;
    }
    state.currentId = id;
    state.stemsActive = false;
    saveSettings({ lastTrackId: id });

    $('#trackTitle').textContent = track.title;
    $('#trackArtist').textContent = artistOf(track);
    $('#formatLabel').textContent = track.format;
    $('#miniTitle').textContent = track.title;
    $('#miniArtist').textContent = artistOf(track);
    $('#duration').textContent = formatTime(track.duration);
    document.title = `${track.title} - ${artistOf(track)} · ${APP_NAME}`;
    document.documentElement.style.setProperty('--hue', hueOf(track.path));
    updateLyrics(track);
    updatePlayButton();
    updateProgress();
    renderTracks();
    updateStemsPanel();

    await syncStemMode();
    if (token !== engine.loadToken) return;
    const total = duration();
    $('#duration').textContent = formatTime(total);
    if (total && Math.abs((track.duration || 0) - total) > 0.5) {
      track.duration = total;
      bridge.call('library.set_duration', { id, duration: total }).catch(() => {});
      renderTracks();
      updateCounts();
    }
    if (autoplay) play();
  }

  function resetPlayer() {
    engine.loadToken++;
    engine.playing = false;
    stopSources();
    Object.assign(engine, { trackId: null, original: null, stems: null, offset: 0 });
    state.currentId = null;
    state.stemsActive = false;
    $('#trackTitle').textContent = 'Nothing playing';
    $('#trackArtist').textContent = '—';
    $('#formatLabel').textContent = '—';
    $('#miniTitle').textContent = APP_NAME;
    $('#miniArtist').textContent = 'Hear music differently';
    $('#currentTime').textContent = '00:00';
    $('#duration').textContent = '00:00';
    document.title = APP_NAME;
    document.documentElement.style.setProperty('--hue', 0);
    updateLyrics(null);
    seekBar.value = 0;
    setSliderFill(seekBar);
    setLoading(false);
    updatePlayButton();
    updateStemsPanel();
  }

  function playable() {
    return state.tracks.filter((t) => !t.missing).map((t) => t.id);
  }

  /** 当前播放队列：从歌单播放时按歌单顺序，否则按本地曲库顺序 */
  function queueIds() {
    if (state.queue) {
      const ids = state.queue.filter((id) => { const t = trackById(id); return t && !t.missing; });
      if (ids.length) return ids;
    }
    return playable();
  }

  function nextTrack(direction = 1) {
    const ids = queueIds();
    if (!ids.length) return;
    let id;
    if (state.settings.shuffle && ids.length > 1) {
      do { id = ids[Math.floor(Math.random() * ids.length)]; } while (id === state.currentId);
    } else {
      const index = ids.indexOf(state.currentId);
      id = ids[(index + direction + ids.length) % ids.length];
    }
    loadTrack(id, true);
  }

  /* ======================= 曲库 ======================= */
  async function addFiles(folder) {
    try {
      const { added, selected } = await bridge.call('library.add_dialog', { folder });
      onTracksAdded(added, selected);
    } catch (error) { fail(error); }
  }

  function onTracksAdded(added, selected = added.length) {
    if (!added.length) {
      if (selected) toast('The selected songs are already in the library or are not audio files');
      return;
    }
    state.tracks.push(...added);
    updateCounts();
    renderTracks();
    toast(TPL.addedSongs(added.length));
    if (!currentTrack()) loadTrack(added[0].id, false);
  }

  /* 自绘确认框（异步）：WebKitGTK 自带的 window.confirm() 关闭后会让网页脚本卡住约 4.5 秒，界面像卡死一样 */
  let confirmResolve = null;
  /** 确认框；inputValue 不为 null 时带输入框：确定返回输入的文字，取消返回 null；否则返回 true / false */
  function askConfirm(message, okText = 'OK', inputValue = null) {
    if (confirmResolve) closeConfirm(false);
    const input = $('#confirmInput');
    $('#confirmMessage').textContent = t(message);
    $('#confirmOk').textContent = t(okText);
    input.hidden = inputValue === null;
    input.value = inputValue ?? '';
    $('#confirmDialog').hidden = false;
    if (inputValue === null) $('#confirmOk').focus();
    else { input.focus(); input.select(); }
    return new Promise((resolve) => { confirmResolve = resolve; });
  }
  function closeConfirm(result) {
    if (!confirmResolve) return;
    const input = $('#confirmInput');
    $('#confirmDialog').hidden = true;
    const resolve = confirmResolve;
    confirmResolve = null;
    if (!input.hidden) resolve(result ? input.value.trim() : null);
    else resolve(result);
  }
  $('#confirmOk').addEventListener('click', () => closeConfirm(true));
  $('#confirmCancel').addEventListener('click', () => closeConfirm(false));
  $('#confirmDialog').addEventListener('click', (event) => { if (event.target.id === 'confirmDialog') closeConfirm(false); });

  async function removeTrack(id) {
    const target = trackById(id);
    if (target?.generated && !(await askConfirm(TPL.confirmDeleteCreation(target.title), 'Delete'))) return;
    try {
      await bridge.call('library.remove', { id });
    } catch (error) { fail(error); return; }
    const wasCurrent = id === state.currentId;
    state.tracks = state.tracks.filter((t) => t.id !== id);
    state.playlists.forEach((p) => { p.track_ids = p.track_ids.filter((t) => t !== id); });
    renderPlaylistNav();
    delete state.jobs[id];
    if (wasCurrent) resetPlayer();
    updateCounts();
    renderTracks();
  }

  async function clearLibrary() {
    if (!state.tracks.length) return;
    if (!(await askConfirm('Clear the library? (Music files on disk are kept, but AI split tracks and AI Compose creations are deleted.)', 'Clear'))) return;
    try {
      await bridge.call('library.clear');
    } catch (error) { fail(error); return; }
    state.tracks = [];
    state.playlists.forEach((p) => { p.track_ids = []; });
    renderPlaylistNav();
    state.jobs = {};
    resetPlayer();
    updateCounts();
    renderTracks();
  }

  function replaceTrack(track) {
    const index = state.tracks.findIndex((t) => t.id === track.id);
    if (index < 0) return;
    state.tracks[index] = track;
    if (track.id === state.currentId) {
      $('#trackTitle').textContent = track.title;
      $('#trackArtist').textContent = artistOf(track);
      $('#miniTitle').textContent = track.title;
      $('#miniArtist').textContent = artistOf(track);
      if (!duration()) $('#duration').textContent = formatTime(track.duration);
    }
  }

  function visibleOrder() {
    const query = searchInput.value.trim().toLowerCase();
    return state.tracks
      .filter((t) => !query || `${t.title} ${t.artist} ${artistOf(t)} ${t.album} ${t.path}`.toLowerCase().includes(query))
      .map((t) => t.id);
  }

  function aiCellHtml(track) {
    const job = state.jobs[track.id];
    if (job?.status === 'running') return `<span class="ai-tag running">${Math.round((job.progress || 0) * 100)}%</span>`;
    if (job?.status === 'queued') return `<span class="ai-tag queued">${t('Queued')}</span>`;
    if (job?.status === 'error') return `<span class="ai-tag error" title="${escapeHtml(job.message || '')}">${t('Failed')}</span><button class="ai-btn" data-action="separate" title="${t('Retry')}">${icon('split')}${t('Retry')}</button>`;
    if (stemsReady(track)) return `<span class="ai-tag done" title="${t('Vocals and accompaniment are ready')}">${t('Split')}</span>`;
    if (track.missing || !state.ai?.available) return '';
    return `<button class="ai-btn" data-action="separate" title="${t('AI-split vocals and accompaniment')}">${icon('split')}${t('Split')}</button>`;
  }

  function updateRowAi(id) {
    const cell = trackList.querySelector(`.track-row[data-id="${id}"] .row-ai`);
    const track = trackById(id);
    if (cell && track) cell.innerHTML = aiCellHtml(track);
  }

  function renderTracks() {
    trackList.querySelectorAll('.track-row').forEach((row) => row.remove());
    $('#emptyState').hidden = state.tracks.length > 0;
    const fragment = document.createDocumentFragment();
    const visible = new Set(visibleOrder());
    state.tracks.forEach((track, index) => {
      if (!visible.has(track.id)) return;
      const row = document.createElement('div');
      row.className = 'track-row';
      row.dataset.id = track.id;
      if (track.id === state.currentId) row.classList.add('active');
      if (track.id === state.selectedId) row.classList.add('selected');
      if (track.missing) row.classList.add('missing');
      row.tabIndex = 0;
      row.title = track.missing ? TPL.fileNotFound(track.path) : track.path;
      row.innerHTML = `
        <span class="track-num"><span class="num">${String(index + 1).padStart(2, '0')}</span><button class="row-play" data-action="play" title="${t('Play')}">${icon(track.id === state.currentId ? 'speaker' : 'play')}</button></span>
        <span class="row-title">${escapeHtml(track.title)}</span>
        <span class="row-artist">${escapeHtml(artistOf(track))}</span>
        <span class="row-format"><em>${escapeHtml(track.format)}</em></span>
        <span class="row-duration">${formatTime(track.duration)}</span>
        <span class="row-ai">${aiCellHtml(track)}</span>
        <span class="row-actions"><button class="row-add" data-action="add" title="${t('Add to playlist')}">${icon('plus')}</button><button class="row-remove" data-action="remove" title="${t('Remove from library')}">${icon('close')}</button></span>`;
      fragment.appendChild(row);
    });
    trackList.appendChild(fragment);
    renderBgmList();
    if (state.view.startsWith('playlist:')) renderPlaylistView();
  }

  trackList.addEventListener('click', (event) => {
    const row = event.target.closest('.track-row');
    if (!row) return;
    const id = Number(row.dataset.id);
    const action = event.target.closest('[data-action]')?.dataset.action;
    if (action === 'play') { state.queue = null; loadTrack(id, true); return; }
    if (action === 'remove') { removeTrack(id); return; }
    if (action === 'separate') { separate(id); return; }
    if (action === 'add') { openPlaylistMenu(event.target.closest('[data-action]'), [id]); return; }
    state.selectedId = id;
    trackList.querySelectorAll('.track-row.selected').forEach((el) => el.classList.remove('selected'));
    row.classList.add('selected');
  });
  trackList.addEventListener('dblclick', (event) => {
    const row = event.target.closest('.track-row');
    if (row && !event.target.closest('[data-action]')) { state.queue = null; loadTrack(Number(row.dataset.id), true); }
  });
  trackList.addEventListener('keydown', (event) => {
    const row = event.target.closest('.track-row');
    if (row && event.key === 'Enter') { event.preventDefault(); state.queue = null; loadTrack(Number(row.dataset.id), true); }
    if (row && event.key === 'Delete') { event.preventDefault(); removeTrack(Number(row.dataset.id)); }
  });

  function updateCounts() {
    $('#sideTrackCount').textContent = state.tracks.length;
    $('#libraryCount').textContent = state.tracks.length;
    $('#totalDuration').textContent = formatTime(state.tracks.reduce((sum, t) => sum + (t.duration || 0), 0));
  }


  /* ======================= 自建歌单 ======================= */
  const playlistById = (id) => state.playlists.find((p) => p.id === id);
  const currentPlaylistId = () => (state.view.startsWith('playlist:') ? Number(state.view.slice(9)) : null);

  function renderPlaylistNav() {
    const nav = $('#playlistNav');
    if (!state.playlists.length) {
      nav.innerHTML = `<div class="playlist-empty">${t('Click + to create a playlist')}</div>`;
      return;
    }
    nav.innerHTML = state.playlists.map((p) => `
      <button class="nav-item playlist${state.view === `playlist:${p.id}` ? ' active' : ''}" data-view="playlist:${p.id}" title="${escapeHtml(p.name)}">
        ${icon('list')}<span>${escapeHtml(p.name)}</span><em>${p.track_ids.length}</em></button>`).join('');
  }
  $('#playlistNav').addEventListener('click', (event) => {
    const item = event.target.closest('.nav-item');
    if (item) showView(item.dataset.view);
  });

  function renderPlaylistView() {
    const playlist = playlistById(currentPlaylistId());
    if (!playlist) return;
    const tracks = playlist.track_ids.map(trackById).filter(Boolean);
    $('#playlistName').textContent = playlist.name;
    $('#playlistCreated').textContent = TPL.createdOn(new Date(playlist.created_at * 1000).toLocaleDateString(state.settings.lang === 'zh' ? 'zh-CN' : 'en-US'));
    $('#playlistCount').textContent = tracks.length;
    $('#playlistDuration').textContent = formatTime(tracks.reduce((sum, tr) => sum + (tr.duration || 0), 0));
    $('#playlistEmpty').hidden = tracks.length > 0;
    $('#plPlayAll').disabled = !tracks.length;
    $('#playlistTracks').innerHTML = tracks.map((tr, i) => {
      const current = tr.id === state.currentId;
      return `
      <div class="track-row${current ? ' active' : ''}${tr.missing ? ' missing' : ''}" data-id="${tr.id}" tabindex="0" title="${escapeHtml(tr.path)}">
        <span class="track-num"><span class="num">${String(i + 1).padStart(2, '0')}</span><button class="row-play" data-action="play" title="${t('Play')}">${icon(current ? 'speaker' : 'play')}</button></span>
        <span class="row-title">${escapeHtml(tr.title)}</span>
        <span class="row-artist">${escapeHtml(artistOf(tr))}</span>
        <span class="row-format"><em>${escapeHtml(tr.format)}</em></span>
        <span class="row-duration">${formatTime(tr.duration)}</span>
        <span></span>
        <span class="row-actions"><button class="row-remove" data-action="unlist" title="${t('Remove from playlist (the song stays in your library)')}">${icon('close')}</button></span>
      </div>`;
    }).join('');
  }

  function updatePlaylist(playlist) {
    const index = state.playlists.findIndex((p) => p.id === playlist.id);
    if (index >= 0) state.playlists[index] = playlist;
    else state.playlists.push(playlist);
    renderPlaylistNav();
    if (currentPlaylistId() === playlist.id) renderPlaylistView();
  }

  function playFromPlaylist(trackId) {
    const playlist = playlistById(currentPlaylistId());
    if (!playlist) return;
    state.queue = [...playlist.track_ids];
    loadTrack(trackId, true);
  }

  async function createPlaylist(trackIds = []) {
    closePlaylistMenu();
    let n = state.playlists.length + 1;
    while (state.playlists.some((p) => p.name === TPL.newPlaylistName(n))) n++;
    const name = await askConfirm('New playlist', 'Create', TPL.newPlaylistName(n));
    if (name === null) return;
    try {
      const playlist = await bridge.call('playlist.create', { name, track_ids: trackIds });
      updatePlaylist(playlist);
      if (trackIds.length) toast(TPL.addedToPlaylist(playlist.name));
      else { showView(`playlist:${playlist.id}`); toast(TPL.createdPlaylist(playlist.name)); }
    } catch (error) { fail(error); }
  }

  async function addToPlaylist(playlistId, trackIds) {
    closePlaylistMenu();
    const playlist = playlistById(playlistId);
    if (!playlist) return;
    if (trackIds.every((id) => playlist.track_ids.includes(id))) { toast(TPL.alreadyInPlaylist(playlist.name)); return; }
    try {
      updatePlaylist(await bridge.call('playlist.add', { id: playlistId, track_ids: trackIds }));
      toast(TPL.addedToPlaylist(playlist.name));
    } catch (error) { fail(error); }
  }

  let menuTracks = [];
  function openPlaylistMenu(anchor, trackIds) {
    menuTracks = trackIds;
    const menu = $('#playlistMenu');
    const items = state.playlists.map((p) => {
      const added = trackIds.every((id) => p.track_ids.includes(id));
      return `<button data-playlist="${p.id}" class="${added ? 'added' : ''}">${icon('list')}<span>${escapeHtml(p.name)}</span><em>${added ? t('Added') : p.track_ids.length}</em></button>`;
    }).join('');
    menu.innerHTML = `<div class="menu-title">${t('Add to playlist')}</div>${items}${items ? '<div class="menu-sep"></div>' : ''}<button data-playlist="new">${icon('plus')}<span>${t('New playlist…')}</span></button>`;
    menu.hidden = false;
    const rect = anchor.getBoundingClientRect();
    const box = menu.getBoundingClientRect();
    const left = Math.max(8, Math.min(rect.right - box.width, window.innerWidth - box.width - 8));
    const top = rect.bottom + 4 + box.height > window.innerHeight ? rect.top - box.height - 4 : rect.bottom + 4;
    menu.style.left = `${left}px`;
    menu.style.top = `${Math.max(8, top)}px`;
  }
  function closePlaylistMenu() { $('#playlistMenu').hidden = true; }
  $('#playlistMenu').addEventListener('click', (event) => {
    const item = event.target.closest('[data-playlist]');
    if (!item) return;
    if (item.dataset.playlist === 'new') createPlaylist(menuTracks);
    else addToPlaylist(Number(item.dataset.playlist), menuTracks);
  });
  document.addEventListener('mousedown', (event) => {
    if (!$('#playlistMenu').hidden && !event.target.closest('#playlistMenu') && !event.target.closest('[data-action=add]')) closePlaylistMenu();
  });
  $('.main').addEventListener('scroll', closePlaylistMenu);

  $('#playlistTracks').addEventListener('click', async (event) => {
    const row = event.target.closest('.track-row');
    const action = event.target.closest('[data-action]')?.dataset.action;
    if (!row || !action) return;
    const id = Number(row.dataset.id);
    if (action === 'play') playFromPlaylist(id);
    else if (action === 'unlist') {
      try { updatePlaylist(await bridge.call('playlist.remove', { id: currentPlaylistId(), track_id: id })); } catch (error) { fail(error); }
    }
  });
  $('#playlistTracks').addEventListener('dblclick', (event) => {
    const row = event.target.closest('.track-row');
    if (row && !event.target.closest('[data-action]')) playFromPlaylist(Number(row.dataset.id));
  });
  $('#playlistTracks').addEventListener('keydown', (event) => {
    const row = event.target.closest('.track-row');
    if (row && event.key === 'Enter') { event.preventDefault(); playFromPlaylist(Number(row.dataset.id)); }
  });
  $('#plPlayAll').addEventListener('click', () => {
    const playlist = playlistById(currentPlaylistId());
    if (!playlist) return;
    state.queue = [...playlist.track_ids];
    const ids = queueIds();
    if (!ids.length) return;
    loadTrack(state.settings.shuffle ? ids[Math.floor(Math.random() * ids.length)] : ids[0], true);
  });
  $('#plRename').addEventListener('click', async () => {
    const playlist = playlistById(currentPlaylistId());
    if (!playlist) return;
    const name = await askConfirm('Rename playlist', 'Save', playlist.name);
    if (name === null || name === playlist.name) return;
    try { updatePlaylist(await bridge.call('playlist.rename', { id: playlist.id, name })); toast('Renamed'); } catch (error) { fail(error); }
  });
  $('#plDelete').addEventListener('click', async () => {
    const playlist = playlistById(currentPlaylistId());
    if (!playlist) return;
    if (!(await askConfirm(TPL.confirmDeletePlaylist(playlist.name), 'Delete'))) return;
    try {
      await bridge.call('playlist.delete', { id: playlist.id });
      state.playlists = state.playlists.filter((p) => p.id !== playlist.id);
      const gone = `playlist:${playlist.id}`;
      [backStack, forwardStack].forEach((stack) => { for (let i = stack.length - 1; i >= 0; i--) if (stack[i] === gone) stack.splice(i, 1); });
      renderPlaylistNav();
      showView('library', false);
      toast(TPL.deletedPlaylist(playlist.name));
    } catch (error) { fail(error); }
  });

  /* ======================= AI 人声分离 ======================= */
  async function separate(id) {
    const track = trackById(id);
    if (!track) return;
    try {
      await bridge.call('stems.separate', { id });
      toast(TPL.queuedSplitting(track.title));
    } catch (error) { fail(error); }
  }

  function setJob(id, job) {
    if (job) state.jobs[id] = job;
    else delete state.jobs[id];
    updateRowAi(id);
    if (id === state.currentId) updateStemsPanel();
  }

  bridge.on('ai.status', (env) => {
    state.ai = env; renderTracks(); updateStemsPanel(); updateComposePanel(); updateTranslation();
    if (state.view === 'compose') warmModels();
  });
  bridge.on('stems.queued', ({ id }) => setJob(id, { status: 'queued', progress: 0 }));
  bridge.on('stems.progress', ({ id, progress, stage }) => setJob(id, { status: 'running', progress, stage }));
  bridge.on('stems.cancelled', ({ id }) => setJob(id, null));
  bridge.on('stems.error', ({ id, message }) => {
    setJob(id, { status: 'error', message });
    const track = trackById(id);
    toast(TPL.splitFailed(track?.title, message), 4000);
  });
  bridge.on('stems.done', ({ id, track, meta }) => {
    if (track) replaceTrack(track);
    setJob(id, null);
    const done = trackById(id);
    toast(TPL.splitComplete(done?.title || '', meta?.elapsed ?? '?'), 2600);
    if (id === state.currentId) syncStemMode();
  });

  /* ======================= AI 作曲（MusicGen，提示词原样交给模型） ======================= */
  var bgmPrompt = $('#bgmPrompt');  // var：updatePlayButton 可能在本段执行前被调用（const 会触发暂时性死区）
  const bgm = { job: null, status: null, progress: 0, seconds: 8, mode: 'local', translateTimer: null };
  const hasChinese = (text) => /[\u3400-\u9fff]/.test(text);
  const translations = {};   // 中文描述 → { english, error }

  /** 输入含中文时：停止输入约 0.9 秒后在后台翻译，显示“模型将收到”的英文提示词 */
  function updateTranslation() {
    const text = bgmPrompt.value.trim();
    const box = $('#bgmTranslation');
    box.hidden = bgm.mode === 'cloud' || !hasChinese(text);
    if (box.hidden) { clearTimeout(bgm.translateTimer); return; }
    const done = translations[text];
    const available = state.ai?.translate?.available;
    box.classList.toggle('pending', !done && available !== false);
    box.classList.toggle('bad', Boolean(done?.error) || (Boolean(state.ai) && !available));
    $('#bgmUseEnglish').hidden = !done?.english;
    if (done) { $('#bgmEnglish').textContent = done.english || done.error; return; }
    if (state.ai && !available) {
      $('#bgmEnglish').textContent = t(state.ai.translate?.reason || 'Chinese translation is unavailable') + t('; you can describe the music in English instead');
      return;
    }
    $('#bgmEnglish').textContent = t('Translating… (starts automatically when you stop typing)');
    clearTimeout(bgm.translateTimer);
    bgm.translateTimer = setTimeout(async () => {
      if (!state.ai || bgmPrompt.value.trim() !== text) return;
      try {
        const result = await bridge.call('bgm.translate', { prompt: text });
        if (result.cached) { translations[text] = { english: result.english }; updateTranslation(); updateComposePanel(); }
      } catch (error) { translations[text] = { error: error.message }; updateTranslation(); }
    }, 900);
  }
  bridge.on('bgm.translated', ({ prompt, english, error }) => {
    translations[prompt] = english ? { english } : { error: `Translation failed: ${error || 'unknown error'}` };
    if (bgmPrompt.value.trim() === prompt) { updateTranslation(); updateComposePanel(); }
  });

  /** 预加载接下来要用的模型（打开作曲页 / 输入描述时）；后端按内存决定加载哪个、是否先释放另一个 */
  var warmTimer;  // var：showView 可能在本段执行前被调用
  function warmModels() {
    clearTimeout(warmTimer);
    warmTimer = setTimeout(() => {
      if (bgm.mode === 'local' && state.ai?.compose?.available) bridge.call('bgm.warm', { prompt: bgmPrompt.value.trim() }).catch(() => {});
    }, 300);
  }
  bridge.on('bgm.warm', (warm) => { state.warm = warm || {}; updateComposePanel(); });

  /** 生成用时估算：优先用本机实测（开发板与 x86 相差数倍），分为生成、模型加载、翻译三部分；
   *  MusicGen 已常驻时不计加载。没有实测时按 x86 经验值。 */
  function estimateBgmSeconds(seconds, translating) {
    const s = state.settings;
    const cost = s.bgmGenCost || {};
    let generate = cost[seconds];
    if (!generate) {
      const other = Object.keys(cost).map(Number).find((k) => cost[k] > 0);
      generate = other ? cost[other] * (seconds / other) : seconds * 1.3 + 1;
    }
    const load = state.warm.musicgen === 'ready' ? 0 : Number(s.bgmLoadCost) || 0;
    const translate = translating ? (Number(s.bgmTranslateCost) || 4) : 0;
    return Math.round(generate + load + translate);
  }
  function recordBgmCost(meta) {
    const elapsed = Number(meta?.elapsed);
    const duration = Number(meta?.duration);
    if (!(elapsed > 0) || ![4, 8].includes(duration)) return;
    const translate = Number(meta.translate_seconds) || 0;
    const load = Number(meta.load_seconds) || 0;
    const values = { bgmGenCost: { ...(state.settings.bgmGenCost || {}), [duration]: Math.round(elapsed - translate - load) } };
    if (translate > 0) values.bgmTranslateCost = Math.round(translate);
    if (load > 2) values.bgmLoadCost = Math.round(load);     // 冷启动时的加载用时
    saveSettings(values);
  }

  /** 模式切换：本地纯音乐 / 云端有人声歌曲。云端模式不用时长按钮、不用中文翻译预览，换成联网/计费提示。 */
  function setComposeMode(mode) {
    bgm.mode = mode;
    $$('#composeMode button').forEach((b) => b.classList.toggle('on', b.dataset.value === mode));
    $('#cloudNotice').hidden = mode !== 'cloud';
    $('#bgmDurationRow').hidden = mode === 'cloud';
    if (mode === 'cloud') $('#bgmTranslation').hidden = true; else updateTranslation();
    saveSettings({ composeMode: mode });
    updateComposePanel();
  }
  $$('#composeMode button').forEach((b) => b.addEventListener('click', () => setComposeMode(b.dataset.value)));

  function updateComposePanel() {
    const cloud = bgm.mode === 'cloud';
    const active = cloud ? state.ai?.cloud_song : state.ai?.compose;
    const badge = $('#bgmState');
    badge.className = 'ai-state';
    badge.title = '';
    // 只在出问题时显示状态（检测中 / 未就绪）；就绪时不显示
    badge.hidden = Boolean(active?.available);
    if (!bridge.available) { badge.textContent = t('Unavailable'); badge.classList.add('bad'); }
    else if (!state.ai) badge.textContent = t('Checking…');
    else if (!active?.available) { badge.textContent = cloud ? t('Cloud song not configured') : t('Compose not ready'); badge.classList.add('bad'); badge.title = t(active?.reason) || ''; }

    $$('#bgmDuration button').forEach((b) => b.classList.toggle('on', Number(b.dataset.value) === bgm.seconds));
    if (cloud) {
      $('#bgmPreview').textContent = t('Cloud songs usually take 30–90 s and include AI-written lyrics');
    } else {
      const translating = hasChinese(bgmPrompt.value) && !translations[bgmPrompt.value.trim()];
      const estimate = estimateBgmSeconds(bgm.seconds, translating);
      $('#bgmPreview').textContent = tf('About {n} s to generate', { n: estimate });
    }

    const busy = bgm.job !== null;
    $('#bgmProgress').hidden = !busy;
    $('#bgmCancel').hidden = !busy;
    const button = $('#bgmGenerate');
    button.disabled = busy || !active?.available;
    button.querySelector('span').textContent = busy ? (bgm.status === 'queued' ? t('Queued…') : t('Generating…')) : t('Generate');
    if (busy) {
      const pct = Math.round((bgm.progress || 0) * 100);
      $('#bgmBar').style.width = `${pct}%`;
      $('#bgmPercent').textContent = `${pct}%`;
    }
  }
  const schedulePreview = updateComposePanel;

  async function generateBgm(prompt = bgmPrompt.value.trim(), seconds = bgm.seconds) {
    if (bgm.job !== null) { toast('Generating, please wait'); return; }
    if (!prompt) { toast('Please enter a music description first'); bgmPrompt.focus(); return; }
    try {
      const { job } = bgm.mode === 'cloud'
        ? await bridge.call('cloud_song.generate', { prompt })
        : await bridge.call('bgm.generate', { prompt, seconds });
      if (bgm.job === null) Object.assign(bgm, { job, status: 'queued', progress: 0 });
      updateComposePanel();
    } catch (error) { fail(error); }
  }

  function generatedTracks() {
    return state.tracks.filter((t) => t.generated).sort((a, b) => b.id - a.id);
  }

  function renderBgmList() {
    const items = generatedTracks();
    $('#bgmCount').textContent = items.length ? tf(items.length === 1 ? '{n} piece' : '{n} pieces', { n: items.length }) : '';
    $('#sideBgmCount').textContent = items.length || '';
    const list = $('#bgmList');
    if (!items.length) {
      list.innerHTML = `<div class="bgm-empty">${t('No creations yet. Try typing a description above')}</div>`;
      return;
    }
    list.innerHTML = items.map((tr) => {
      const current = tr.id === state.currentId;
      const prompt = tr.generated.prompt || tr.title;
      const english = tr.generated.prompt_en && tr.generated.prompt_en !== prompt ? ` · ${tr.generated.prompt_en}` : '';
      return `
      <div class="bgm-item${current ? ' active' : ''}" data-id="${tr.id}">
        <button class="bgm-cover" data-action="play" style="--h:${hueOf(tr.path)}" title="${current && engine.playing ? t('Pause') : t('Play')}">${icon(current && engine.playing ? 'pause' : 'play')}</button>
        <div class="bgm-text"><div class="bgm-name" title="${escapeHtml(prompt)}">${escapeHtml(tr.title)}</div><div class="bgm-desc" title="${escapeHtml(tr.generated.prompt_en || '')}">${escapeHtml(`${tr.generated.duration || Math.round(tr.duration)} s` + english)}</div></div>
        <span class="bgm-time">${formatTime(tr.duration)}</span>
        <button class="ai-btn" data-action="reroll" title="${t('Generate another one with the same prompt and length')}">${icon('refresh')}${t('Another')}</button>
        <button class="row-remove" data-action="remove" title="${t('Delete creation')}">${icon('close')}</button>
      </div>`;
    }).join('');
  }

  $('#bgmList').addEventListener('click', (event) => {
    const item = event.target.closest('.bgm-item');
    const action = event.target.closest('[data-action]')?.dataset.action;
    if (!item || !action) return;
    const id = Number(item.dataset.id);
    const track = trackById(id);
    if (!track) return;
    if (action === 'play') {
      if (id === state.currentId) togglePlayback();
      else { state.queue = null; loadTrack(id, true); }
    } else if (action === 'reroll') {
      generateBgm(track.generated.prompt || track.title, Number(track.generated.duration) || 8);
    } else if (action === 'remove') {
      removeTrack(id);
    }
  });
  $('#bgmGenerate').addEventListener('click', () => generateBgm());
  $('#bgmCancel').addEventListener('click', () => {
    if (bgm.job !== null) bridge.call('bgm.cancel', { job: bgm.job }).catch(fail);
  });
  bgmPrompt.addEventListener('input', () => { updateComposePanel(); updateTranslation(); warmModels(); });
  $('#bgmUseEnglish').addEventListener('click', () => {
    const done = translations[bgmPrompt.value.trim()];
    if (!done?.english) return;
    bgmPrompt.value = done.english;
    bgmPrompt.focus();
    updateComposePanel();
    updateTranslation();
  });
  bgmPrompt.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); generateBgm(); }
  });
  $$('#bgmExamples .chip').forEach((chip) => chip.addEventListener('click', () => {
    bgmPrompt.value = chip.textContent;
    updateComposePanel();
    updateTranslation();
    generateBgm();
  }));
  $$('#bgmDuration button').forEach((b) => b.addEventListener('click', () => {
    bgm.seconds = Number(b.dataset.value);
    saveSettings({ bgmSeconds: bgm.seconds });
    updateComposePanel();
  }));

  bridge.on('bgm.queued', ({ id }) => { Object.assign(bgm, { job: id, status: 'queued', progress: 0 }); updateComposePanel(); });
  bridge.on('bgm.progress', ({ id, progress, english }) => {
    if (english) {   // 生成时才翻译（未预览过）：把译文也记下来并显示
      const text = bgmPrompt.value.trim();
      if (hasChinese(text) && !translations[text]) { translations[text] = { english }; updateTranslation(); }
    }
    Object.assign(bgm, { job: id, status: 'running', progress: progress || 0 });
    updateComposePanel();
  });
  bridge.on('bgm.cancelled', ({ id }) => {
    if (bgm.job === id) bgm.job = null;
    updateComposePanel();
    toast('Generation cancelled');
  });
  bridge.on('bgm.error', ({ id, message }) => {
    if (bgm.job === id) bgm.job = null;
    updateComposePanel();
    toast(TPL.generationFailed(message), 4000);
  });
  bridge.on('bgm.done', ({ id, track, meta }) => {
    if (bgm.job === id) bgm.job = null;
    recordBgmCost(meta);
    updateComposePanel();
    if (!track) return;
    if (!trackById(track.id)) {
      state.tracks.push(track);
      updateCounts();
      renderTracks();
    }
    toast(TPL.generated(track.title, Number(meta?.seconds || track.duration).toFixed(1), meta?.elapsed ?? '?'), 2600);
    loadTrack(track.id, true);
  });

  function modeLabel() {
    const s = state.settings;
    if (s.vocalGain === 0) return t('Karaoke');
    if (s.accGain === 0) return t('A cappella');
    if (s.fxTarget === 'vocals') return t('Vocals FX');
    if (s.fxTarget === 'accompaniment') return t('Backing FX');
    return t('Split tracks');
  }

  function matchingPreset() {
    const s = state.settings;
    return Object.keys(PRESETS).find((key) => {
      const p = PRESETS[key];
      return s.stemSource === 'stems' && s.vocalGain === p.vocalGain && s.accGain === p.accGain && s.fxTarget === p.fxTarget;
    });
  }

  function updateModeLabels() {
    const badge = $('#fxBadge');
    const effect = state.settings.effect;
    badge.textContent = t(EFFECT_NAMES[effect]);
    badge.classList.toggle('on', effect !== 'clean');

    const stemBadge = $('#stemBadge');
    stemBadge.hidden = !state.stemsActive;
    stemBadge.textContent = modeLabel();
    stemBadge.classList.toggle('on', state.stemsActive);

    const target = state.stemsActive ? `（${t(TARGET_NAMES[state.settings.fxTarget])}）` : '';
    $('#npEffect').textContent = tf('Current effect · {effect}{target}', { effect: t(EFFECT_NAMES[effect]), target });
    let mode = '';
    if (state.stemsActive) mode = tf('AI split tracks · {label}', { label: modeLabel() });
    else if (state.settings.stemSource === 'stems' && currentTrack()) mode = t('Split-track mode: this song has not been split yet, playing the original');
    $('#npMode').textContent = mode;
  }

  function updateStemsPanel() {
    const ai = state.ai;
    const aiState = $('#aiState');
    aiState.className = 'ai-state';
    aiState.hidden = Boolean(ai?.available);   // 就绪时不显示，只在检测中 / 未就绪时提示
    if (!bridge.available) { aiState.textContent = t('Unavailable'); aiState.classList.add('bad'); }
    else if (!ai) aiState.textContent = t('Checking…');
    else if (!ai.available) { aiState.textContent = t('AI not ready'); aiState.classList.add('bad'); aiState.title = t(ai.reason); }
    $('#stemsSubtitle').textContent = ai && !ai.available ? t(ai.reason) : t('Split a song into vocals and accompaniment, then apply effects to the vocals only');

    const track = currentTrack();
    const job = track ? state.jobs[track.id] : null;
    const busy = job && (job.status === 'running' || job.status === 'queued');
    const done = stemsReady(track);
    $('#stemsTrack').textContent = track
      ? `${track.title} · ${done ? t('Split') : busy ? (job.status === 'queued' ? t('Queued') : t(STAGE_NAMES[job.stage]) || t('Processing')) : job?.status === 'error' ? t('Last split failed') : t('Not split')}`
      : t('No song selected');

    const progress = $('#stemsProgress');
    progress.hidden = !busy;
    if (busy) {
      const pct = Math.round((job.progress || 0) * 100);
      $('#stemsBar').style.width = `${pct}%`;
      $('#stemsPercent').textContent = `${pct}%`;
    }
    const run = $('#stemsRun');
    run.hidden = Boolean(busy);
    run.disabled = !track || track.missing || !ai?.available;
    run.querySelector('span').textContent = done ? t('Split Again') : job?.status === 'error' ? t('Retry Split') : t('Start Split');
    $('#stemsCancel').hidden = !busy;
    $('#stemsDelete').hidden = !done || Boolean(busy);

    const s = state.settings;
    $$('#sourceSeg button').forEach((b) => b.classList.toggle('on', b.dataset.value === s.stemSource));
    $$('#targetSeg button').forEach((b) => b.classList.toggle('on', b.dataset.value === s.fxTarget));
    const preset = matchingPreset();
    $$('.chip[data-preset]').forEach((c) => c.classList.toggle('on', c.dataset.preset === preset));
    for (const [id, key] of [['vocalGain', 'vocalGain'], ['accGain', 'accGain']]) {
      const slider = $(`#${id}`);
      slider.value = s[key];
      setSliderFill(slider);
      $(`#${id}Value`).textContent = `${Math.round(s[key] * 100)}%`;
    }
    updateModeLabels();
  }

  $('#stemsRun').addEventListener('click', () => { if (state.currentId) separate(state.currentId); });
  $('#stemsCancel').addEventListener('click', () => {
    if (state.currentId) bridge.call('stems.cancel', { id: state.currentId }).catch(fail);
  });
  $('#stemsDelete').addEventListener('click', async () => {
    const id = state.currentId;
    if (!id) return;
    try {
      const track = await bridge.call('stems.delete', { id });
      replaceTrack(track);
      updateRowAi(id);
      if (id === state.currentId) { engine.stems = null; syncStemMode(); }
      toast('Split tracks deleted');
    } catch (error) { fail(error); }
  });

  function setStemSource(source) {
    saveSettings({ stemSource: source });
    const track = currentTrack();
    if (source === 'stems' && track && !stemsReady(track)) {
      const job = state.jobs[track.id];
      if (!job || job.status === 'error') {
        if (state.ai?.available) { toast('This song has not been split yet; splitting started automatically'); separate(track.id); }
        else toast(state.ai?.reason || 'AI environment is not ready', 3500);
      }
    }
    syncStemMode();
  }

  $$('#sourceSeg button').forEach((b) => b.addEventListener('click', () => setStemSource(b.dataset.value)));
  $$('#targetSeg button').forEach((b) => b.addEventListener('click', () => {
    saveSettings({ fxTarget: b.dataset.value });
    applyRouting();
    updateStemsPanel();
  }));
  $$('.chip[data-preset]').forEach((chip) => chip.addEventListener('click', () => {
    const { effect, ...values } = PRESETS[chip.dataset.preset];
    saveSettings(values);
    if (effect && state.settings.effect === 'clean') { initAudioGraph(); applyEffect(effect); }
    setStemSource('stems');
    applyStemGains();
    updateStemsPanel();
  }));
  for (const id of ['vocalGain', 'accGain']) {
    const slider = $(`#${id}`);
    slider.addEventListener('input', () => {
      saveSettings({ [id]: Number(slider.value) });
      applyStemGains();
      updateStemsPanel();
    });
  }

  /* ======================= 其他控件 ======================= */
  $('#addFilesBtn').addEventListener('click', () => addFiles(false));
  $('#addFolderBtn').addEventListener('click', () => addFiles(true));
  $('#createPlaylistBtn').addEventListener('click', () => createPlaylist());
  $('#emptyAddBtn').addEventListener('click', () => addFiles(false));
  $('#clearBtn').addEventListener('click', clearLibrary);
  $('#playAllBtn').addEventListener('click', () => {
    const ids = playable();
    if (!ids.length) { addFiles(false); return; }
    state.queue = null;
    loadTrack(state.settings.shuffle ? ids[Math.floor(Math.random() * ids.length)] : ids[0], true);
  });

  playButton.addEventListener('click', togglePlayback);
  $('#nextBtn').addEventListener('click', () => nextTrack(1));
  $('#prevBtn').addEventListener('click', () => {
    if (position() > 3) { seek(0); return; }
    nextTrack(-1);
  });

  function applyShuffle(on) {
    const btn = $('#shuffleBtn');
    btn.classList.toggle('active', on);
    btn.title = on ? 'Shuffle: on' : 'Shuffle';
  }
  function applyRepeat(on) {
    const btn = $('#repeatBtn');
    btn.innerHTML = icon(on ? 'loop-one' : 'loop');
    btn.classList.toggle('active', on);
    btn.title = on ? 'Repeat one' : 'Repeat all';
  }
  $('#shuffleBtn').addEventListener('click', () => {
    saveSettings({ shuffle: !state.settings.shuffle });
    applyShuffle(state.settings.shuffle);
    toast(state.settings.shuffle ? 'Shuffle on' : 'Play in order');
  });
  $('#repeatBtn').addEventListener('click', () => {
    saveSettings({ repeatOne: !state.settings.repeatOne });
    applyRepeat(state.settings.repeatOne);
    toast(state.settings.repeatOne ? 'Repeat one' : 'Repeat all');
  });

  $$('.effect-card').forEach((card) => card.addEventListener('click', () => {
    initAudioGraph();
    applyEffect(card.dataset.effect);
  }));

  function setSpeed(value, save = true) {
    speedSlider.value = value;
    $('#speedValue').textContent = `${Number(value).toFixed(2)}×`;
    setSliderFill(speedSlider);
    if (save) saveSettings({ speed: Number(value) });
    setRate(effectiveRate());
  }
  speedSlider.addEventListener('input', () => setSpeed(speedSlider.value));
  $('#speedReset').addEventListener('click', () => setSpeed(1));

  let lastVolume = 0.75;
  function setVolume(value, save = true) {
    volumeSlider.value = value;
    $('#volumeValue').textContent = Math.round(value * 100);
    setSliderFill(volumeSlider);
    $('#muteBtn').innerHTML = icon(Number(value) === 0 ? 'mute' : 'volume');
    if (save) saveSettings({ volume: Number(value) });
    if (nodes) nodes.master.gain.setTargetAtTime(Number(value), audioContext.currentTime, 0.03);
  }
  volumeSlider.addEventListener('input', () => {
    setVolume(volumeSlider.value);
    if (Number(volumeSlider.value) > 0) lastVolume = Number(volumeSlider.value);
  });
  $('#muteBtn').addEventListener('click', () => setVolume(Number(volumeSlider.value) > 0 ? 0 : (lastVolume || 0.75)));

  var seeking = false;  // var：updateProgress 在声明前可能被调用
  seekBar.addEventListener('pointerdown', () => { seeking = true; });
  seekBar.addEventListener('pointerup', () => { seeking = false; });
  seekBar.addEventListener('input', () => {
    setSliderFill(seekBar);
    if (duration() > 0) seek((Number(seekBar.value) / Number(seekBar.max)) * duration());
  });

  searchInput.addEventListener('input', () => {
    if (state.view !== 'library') showView('library');
    renderTracks();
  });

  setInterval(() => { if (engine.playing) updateProgress(); }, 250);

  /* ---------- 拖放：文件路径由 GTK 层读取并加入曲库 ---------- */
  let dragDepth = 0;
  const hasFiles = (event) => Array.from(event.dataTransfer?.types || []).includes('Files');
  window.addEventListener('dragenter', (event) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    dragDepth++;
    document.body.classList.add('dragging');
  });
  window.addEventListener('dragover', (event) => { if (hasFiles(event)) event.preventDefault(); });
  window.addEventListener('dragleave', (event) => {
    if (!hasFiles(event)) return;
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) document.body.classList.remove('dragging');
  });
  window.addEventListener('drop', (event) => {
    event.preventDefault();
    dragDepth = 0;
    document.body.classList.remove('dragging');
  });
  bridge.on('library.added', ({ tracks }) => {
    const fresh = tracks.filter((t) => !trackById(t.id));
    if (fresh.length) onTracksAdded(fresh);
    else toast('The dropped files are already in the library or are not audio files');
  });
  bridge.on('library.updated', ({ track }) => {
    replaceTrack(track);
    renderTracks();
    updateCounts();
  });

  /* ---------- 快捷键 ---------- */
  window.addEventListener('keydown', (event) => {
    if (!$('#playlistMenu').hidden && event.key === 'Escape') { closePlaylistMenu(); return; }
    if (confirmResolve) {   // 确认框打开时只处理 Enter / Esc，其他快捷键不生效
      if (event.key === 'Escape') { event.preventDefault(); closeConfirm(false); }
      else if (event.key === 'Enter') { event.preventDefault(); closeConfirm(true); }
      else if (event.code === 'Space' && document.activeElement?.tagName !== 'BUTTON') event.preventDefault();
      return;
    }
    const el = document.activeElement;
    if ((el?.tagName === 'INPUT' && el.type !== 'range') || el?.tagName === 'TEXTAREA' || el?.tagName === 'SELECT') return;
    const key = event.key.toLowerCase();
    if (event.code === 'Space' && el?.tagName !== 'BUTTON') { event.preventDefault(); togglePlayback(); }
    else if (event.ctrlKey && event.key === 'ArrowRight') { event.preventDefault(); nextTrack(1); }
    else if (event.ctrlKey && event.key === 'ArrowLeft') { event.preventDefault(); nextTrack(-1); }
    else if (event.ctrlKey && key === 'o') { event.preventDefault(); addFiles(false); }
    else if (event.ctrlKey && key === 'f') { event.preventDefault(); searchInput.focus(); }
  });

  /* ---------- 时钟 ---------- */
  function updateClock() {
    $('#clock').textContent = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit' });
  }
  updateClock();
  setInterval(updateClock, 15000);

  /* ---------- 频谱 ---------- */
  const canvas = $('#visualizer');
  const canvasCtx = canvas.getContext('2d');
  let freqData;
  function drawVisualizer() {
    requestAnimationFrame(drawVisualizer);
    if (state.view !== 'player') return;
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const width = Math.max(1, Math.floor(rect.width * dpr));
    const height = Math.max(1, Math.floor(rect.height * dpr));
    if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
    canvasCtx.clearRect(0, 0, width, height);
    const live = nodes && engine.playing;
    if (live) {
      if (!freqData) freqData = new Uint8Array(nodes.analyser.frequencyBinCount);
      nodes.analyser.getByteFrequencyData(freqData);
    }
    const barCount = 48;
    const gap = 4 * dpr;
    const barWidth = Math.max(1, (width - gap * (barCount - 1)) / barCount);
    const radius = Math.min(barWidth / 2, 3 * dpr);
    canvasCtx.fillStyle = 'rgba(236, 65, 65, 0.75)';
    for (let i = 0; i < barCount; i++) {
      const sample = live
        ? freqData[Math.floor((i / barCount) * freqData.length * 0.8)] / 255
        : 0.04 + Math.abs(Math.sin(Date.now() / 700 + i * 0.35)) * 0.05;
      const barHeight = Math.max(3 * dpr, sample * height * 0.95);
      const x = i * (barWidth + gap);
      const y = height - barHeight;
      canvasCtx.beginPath();
      canvasCtx.moveTo(x, height);
      canvasCtx.lineTo(x, y + radius);
      canvasCtx.quadraticCurveTo(x, y, x + radius, y);
      canvasCtx.lineTo(x + barWidth - radius, y);
      canvasCtx.quadraticCurveTo(x + barWidth, y, x + barWidth, y + radius);
      canvasCtx.lineTo(x + barWidth, height);
      canvasCtx.fill();
    }
  }
  requestAnimationFrame(drawVisualizer);

  // 调试/自动化测试用的只读钩子
  window.__waveDebug = {
    state, engine, position, duration,
    get nodes() { return nodes; },
    get ctx() { return audioContext; },
  };

  /* ======================= 初始化 ======================= */
  $('#langToggle').addEventListener('click', () => applyLanguage(state.settings.lang === 'zh' ? 'en' : 'zh'));
  async function init() {
    // 尽早建立 Web Audio 处理链：若在音频加载之后才接入，WebKit 会重建管线，首次播放卡顿约 2 秒
    initAudioGraph();
    updatePlayButton();
    setSliderFill(seekBar);
    if (!bridge.available) {
      updateStemsPanel();
      toast('Please start the app with wave_music.py', 5000);
      return;
    }
    try {
      const data = await bridge.call('app.init');
      state.tracks = data.tracks;
      state.settings = { ...DEFAULT_SETTINGS, ...data.settings };
      state.ai = data.ai;
      state.warm = data.warm || {};
      if (data.jobs?.running) state.jobs[data.jobs.running] = { status: 'running', progress: 0 };
      (data.jobs?.queued || []).forEach((id) => { state.jobs[id] = { status: 'queued', progress: 0 }; });
      state.playlists = data.playlists || [];
      if (data.jobs?.bgm?.running) Object.assign(bgm, { job: data.jobs.bgm.running, status: 'running' });
    } catch (error) { fail(error); }

    const s = state.settings;
    applyLanguage(s.lang === 'zh' ? 'zh' : 'en');
    setVolume(s.volume, false);
    lastVolume = s.volume || 0.75;
    setSpeed(s.speed, false);
    applyShuffle(s.shuffle);
    applyRepeat(s.repeatOne);
    applyEffect(s.effect, false);
    updateCounts();
    renderPlaylistNav();
    renderTracks();
    const last = trackById(s.lastTrackId);
    if (last && !last.missing) loadTrack(last.id, false);
    updateStemsPanel();
    bgm.seconds = Number(state.settings.bgmSeconds) === 4 ? 4 : 8;
    setComposeMode(state.settings.composeMode === 'cloud' ? 'cloud' : 'local');
    updateComposePanel();
    schedulePreview();
  }
  init();
})();
