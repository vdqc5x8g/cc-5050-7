"""Builds the self-contained HTML review window (验片窗口)."""
import json

TEMPLATE = """<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>动画转码验片窗口</title>
<style>
  body { background:#14161c; color:#d8dce6; font:13px/1.5 ui-monospace,Menlo,Consolas,monospace; margin:24px; }
  h1 { font-size:18px; } h2 { font-size:14px; color:#9fb4ff; margin:18px 0 6px; }
  .bar { margin:10px 0 16px; display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
  button { background:#232838; color:#d8dce6; border:1px solid #3a4360; padding:4px 14px; cursor:pointer; font:inherit; }
  button.on { background:#3d5afe; border-color:#3d5afe; color:#fff; }
  #stage { display:flex; gap:24px; flex-wrap:wrap; }
  .panel h2 { margin:0 0 6px; }
  .cv { position:relative; width:480px; height:360px; }
  .cv canvas { position:absolute; inset:0; width:480px; height:360px; image-rendering:pixelated;
               background:repeating-conic-gradient(#222 0 25%, #333 0 50%) 0 0/16px 16px; }
  .hud { width:480px; min-height:34px; color:#8fd0ff; white-space:pre-wrap; }
  .legend { margin:8px 0; color:#aab; }
  .sw { display:inline-block; width:10px; height:10px; border:2px solid; vertical-align:-1px; margin:0 4px 0 12px; }
  table { border-collapse:collapse; margin:6px 0; }
  td, th { border:1px solid #333a4d; padding:3px 10px; text-align:left; }
  th { background:#1d2230; }
  .ok { color:#6fe38a; } .bad { color:#ff7070; } .warn { color:#ffd166; }
  #example div { margin:4px 0; }
  code { color:#ffd166; }
  #native img { width:320px; image-rendering:pixelated; border:1px solid #333a4d; margin:4px;
                background:repeating-conic-gradient(#222 0 25%, #333 0 50%) 0 0/16px 16px; }
</style>
</head>
<body>
<h1>动画转码验片窗口 — 局部帧格式（APNG / GIF）联合优化</h1>
<div class="bar">
  <span>编码配置：</span>
  <button id="btnExact" class="on">精确保时</button>
  <button id="btnSize">体积优先</button>
  <label><input type="checkbox" id="showOv" checked> 叠加编码矩形与可见区域</label>
  <button id="btnPause">暂停</button>
</div>
<div class="bar">
  <span>跳帧：</span>
  <input type="range" id="seek" min="0" max="0" value="0" style="width:320px">
  <button id="btnRandom">随机跳一帧</button>
  <span class="legend" style="margin:0">拖动滑条可向前倒拖——播放器按局部回退区域逐帧撤销</span>
</div>
<div id="stage">
  <div class="panel"><h2>APNG <span id="infoA" class="warn"></span></h2>
    <div class="cv"><canvas id="cvA" width="160" height="120"></canvas><canvas id="ovA" width="160" height="120"></canvas></div>
    <div class="hud" id="hudA"></div></div>
  <div class="panel"><h2>GIF <span id="infoG" class="warn"></span></h2>
    <div class="cv"><canvas id="cvG" width="160" height="120"></canvas><canvas id="ovG" width="160" height="120"></canvas></div>
    <div class="hud" id="hudG"></div></div>
</div>
<div class="legend">叠加层：<span class="sw" style="border-color:#ff5252"></span>编码矩形（本帧写出的局部区域）
  <span class="sw" style="border-color:#69f0ae"></span>最终可见区域（显示画布实际变化的包围盒）　棋盘格=透明</div>
<h2>当前配置的取舍：目标延迟粒度 / 累计误差 / 体积</h2>
<table id="stats"></table>
<h2>优化实例：当前帧裁得最小，两帧合计反而写更多像素</h2>
<div id="example"></div>
<h2>跳帧缓存：倒拖残留的原因与修复</h2>
<div id="seekAnalysis">
<div><b>症状：</b>顺序播放正确；跳到后段再向前拖，透明舷窗里留下上一帧的颜色。</div>
<div><b>记录：</b>跳帧前保存的必须是<b>处置后</b>的画布（= 下一帧合成前的画布），而不是合成后、
处置前的显示画布。两者只差本帧编码矩形内 dispose 清空 / 恢复的那一块；顺序播放时差别不可见
（下一帧渲染前才补做处置），跳帧时若拿显示画布当基准，等于跳过本帧处置，透明区便残留颜色。</div>
<div><b>矩形边界：</b>局部回退区域取<b>帧自身的编码矩形</b>在合成前的内容，不取可见变化包围盒——
over 混合未变的像素、清背景波及的旧内容都在可见 bbox 之外，却在处置影响的矩形之内。</div>
<div><b>做法比较：</b>关键画布重演（每 K 帧存一份完整处置后画布，内存 O(N/K·W·H)，倒拖仍要正向
重演 ≤K 帧）vs 局部回退区域（每帧只存自身矩形合成前的内容，倒拖一帧 O(1)，内存 O(Σ矩形面积)）。
本窗口播放器采用后者（Player.undo），Python 侧对照实现见 animtrans/seek.py。</div>
<div><b>陷阱：</b>视觉相同的两帧若处置元数据不同，其处置后画布（内部状态）不同；把相同显示图
当成相同内部状态、跨帧复用，就会画错下一帧（tests/test_seek.py 用最小片段复现）。</div>
</div>
<h2>跳帧自检：三种顺序访问同一帧，与完整逐帧参考逐像素比对</h2>
<table id="seektest"></table>
<h2>另一解码路径逐帧核对（独立解析文件字节流）</h2>
<table id="verify"></table>
<h2>导出的实际动画（浏览器原生解码播放）</h2>
<div id="native"></div>
<script>
const DATA = @@DATA@@;

class Player {
  constructor(cv, ov, hud) {
    this.ctx = cv.getContext('2d');
    this.octx = ov ? ov.getContext('2d') : null;
    this.hud = hud;
    this.idx = -1;
    this.prev = null;   // {f, j}：懒处置——第 j 帧的处置尚未补做
    this.undo = [];     // 每帧编码矩形在合成前的内容（局部回退区域）
  }
  setManifest(mani, images) {
    this.mani = mani; this.images = images;
    this.idx = -1; this.prev = null;
    this.undo = new Array(mani.frames.length);
    this.ctx.clearRect(0, 0, mani.w, mani.h);
  }
  render(j, overlay) {
    const m = this.mani, f = m.frames[j], ctx = this.ctx;
    if (this.prev) {  // 补做上一帧的处置（顺序播放时差别不可见，跳帧时关键）
      const p = this.prev.f, u = this.undo[this.prev.j];
      if (p.dispose === 'background') ctx.clearRect(p.x, p.y, p.w, p.h);
      else if (p.dispose === 'previous' && u) ctx.putImageData(u, p.x, p.y);
    }
    // 局部回退区域 = 本帧编码矩形在合成前的内容（即上一帧处置后的画布）
    this.undo[j] = ctx.getImageData(f.x, f.y, f.w, f.h);
    const img = this.images[j];
    if (f.blend === 'source') ctx.clearRect(f.x, f.y, f.w, f.h);
    ctx.drawImage(img, f.x, f.y);
    this.prev = { f, j }; this.idx = j;
    if (overlay) this.drawOverlay(j);
  }
  drawOverlay(j) {
    const m = this.mani, f = m.frames[j], o = this.octx;
    o.clearRect(0, 0, m.w, m.h);
    if (DATA.showOv) {
      o.strokeStyle = '#ff5252'; o.lineWidth = 1;
      o.strokeRect(f.x + .5, f.y + .5, f.w - 1, f.h - 1);
      if (f.visible) {
        o.strokeStyle = '#69f0ae';
        o.strokeRect(f.visible[0] + .5, f.visible[1] + .5, f.visible[2] - 1, f.visible[3] - 1);
      }
    }
    this.hud.textContent =
      `帧 ${j}/${m.frames.length - 1}  源帧 ${f.src}${f.transient ? ' [瞬态]' : ''}\n` +
      `编码矩形 (${f.x},${f.y},${f.w}×${f.h}) = ${f.w * f.h}px  ` +
      `${f.dispose}/${f.blend}  延迟 ${f.delay_ms.toFixed(1)}ms`;
  }
  seekTo(j, overlay) {
    j = Math.max(0, Math.min(j, this.mani.frames.length - 1));
    if (j < this.idx) {
      // 倒拖：逐帧恢复"合成前"的矩形内容，回到第 j-1 帧处置后的画布。
      // S_k 与 S_{k-1} 只在第 k 帧编码矩形内不同，恢复该矩形即撤销一帧。
      while (this.idx >= j) {
        const f = this.mani.frames[this.idx];
        this.ctx.putImageData(this.undo[this.idx], f.x, f.y);
        this.idx--; this.prev = null;
      }
      this.render(j, overlay !== false);
    } else if (j > this.idx) {
      for (let k = this.idx + 1; k <= j; k++) this.render(k, overlay !== false && k === j);
    } else if (overlay) this.drawOverlay(j);
  }
  tick(now) {
    const m = this.mani;
    if (!m) return;
    if (this.start == null) this.start = now;
    let t = (now - this.start) % m.loop_ms;
    let acc = 0, idx = 0;
    for (let i = 0; i < m.frames.length; i++) {
      if (t < acc + m.frames[i].delay_ms) { idx = i; break; }
      acc += m.frames[i].delay_ms;
    }
    if (idx !== this.idx) this.seekTo(idx, true);
  }
}

const players = [new Player(cvA, ovA, hudA), new Player(cvG, ovG, hudG)];
let running = true;

function loadImages(mani) {
  return Promise.all(mani.frames.map(f => new Promise(res => {
    const im = new Image();
    im.onload = () => res(im);
    im.src = f.img;
  })));
}

function renderStats(cfg) {
  const s = DATA.stats[cfg];
  let h = '<tr><th>格式</th><th>帧数</th><th>写出像素</th><th>文件字节</th><th>瞬态帧</th>' +
          '<th>目标延迟粒度</th><th>累计误差</th></tr>';
  for (const fmt of ['apng', 'gif']) {
    const r = s[fmt];
    h += `<tr><td>${fmt.toUpperCase()}</td><td>${r.frames}</td><td>${r.pixels}</td>` +
         `<td>${r.bytes}</td><td>${r.transients}</td><td>${r.gran}</td><td>${r.cumerr}</td></tr>`;
  }
  stats.innerHTML = h;
}

async function applyConfig(cfg) {
  DATA.showOv = showOv.checked;
  renderStats(cfg);
  const p = DATA.plans[cfg];
  const [ia, ig] = await Promise.all([loadImages(p.apng), loadImages(p.gif)]);
  players[0].setManifest(p.apng, ia);
  players[1].setManifest(p.gif, ig);
  players.forEach(pl => { pl.start = null; });
  seek.max = Math.min(p.apng.frames.length, p.gif.frames.length) - 1;
  infoA.textContent = `${p.apng.frames.length} 帧`;
  infoG.textContent = `${p.gif.frames.length} 帧`;
}

function pause() { if (running) { running = false; btnPause.textContent = '继续'; } }

btnExact.onclick = () => { btnExact.classList.add('on'); btnSize.classList.remove('on'); applyConfig('exact'); };
btnSize.onclick = () => { btnSize.classList.add('on'); btnExact.classList.remove('on'); applyConfig('size'); };
btnPause.onclick = () => { running = !running; btnPause.textContent = running ? '暂停' : '继续'; };
showOv.onchange = () => {
  DATA.showOv = showOv.checked;
  players.forEach(pl => { if (pl.mani) { pl.setManifest(pl.mani, pl.images); pl.start = null; } });
};
seek.oninput = () => { pause(); players.forEach(pl => pl.seekTo(+seek.value, true)); };
btnRandom.onclick = () => {
  const m = players[0].mani;
  if (!m) return;
  pause();
  seek.value = Math.floor(Math.random() * m.frames.length);
  players.forEach(pl => pl.seekTo(+seek.value, true));
};

(function loop(now) {
  if (running) {
    players.forEach(pl => pl.tick(now || 0));
    if (players[0].idx >= 0 && +seek.value !== players[0].idx) seek.value = players[0].idx;
  }
  requestAnimationFrame(loop);
})(0);

// verification table
{
  let h = '<tr><th>文件</th><th>结果</th><th>核对明细</th></tr>';
  for (const v of DATA.verify) {
    const det = v.rows.map(r =>
      `<span class="${r.ok ? 'ok' : 'bad'}">${r.ok ? '✓' : '✗'}</span> ${r.check}：${r.detail}`
    ).join('<br>');
    h += `<tr><td>${v.label}</td><td class="${v.ok ? 'ok' : 'bad'}">${v.ok ? '通过' : '失败'}</td><td>${det}</td></tr>`;
  }
  verify.innerHTML = h;
}
example.innerHTML = DATA.example_html;

// 跳帧自检：三种顺序访问同一帧，与完整逐帧参考逐像素比对
async function seekSelftest() {
  const W = DATA.meta.W, H = DATA.meta.H;
  const refImgs = await Promise.all(DATA.ref.map(u => new Promise(res => {
    const im = new Image(); im.onload = () => res(im); im.src = u;
  })));
  const rc = document.createElement('canvas'); rc.width = W; rc.height = H;
  const rctx = rc.getContext('2d');
  const refs = refImgs.map(im => {
    rctx.clearRect(0, 0, W, H); rctx.drawImage(im, 0, 0);
    return rctx.getImageData(0, 0, W, H).data;
  });
  const lcg = s => { let x = s >>> 0; return () => (x = (x * 1664525 + 1013904223) >>> 0) / 4294967296; };
  const shuffled = (n, seed) => {
    const a = [...Array(n).keys()], rnd = lcg(seed);
    for (let i = n - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
    return a;
  };
  let h = '<tr><th>配置 / 格式</th><th>检查</th><th>结果</th><th>明细</th></tr>';
  for (const cfg of ['exact', 'size']) {
    for (const fmt of ['apng', 'gif']) {
      const mani = DATA.plans[cfg][fmt];
      const images = await loadImages(mani);
      const n = mani.frames.length;
      const orders = [['顺播', [...Array(n).keys()]],
                      ['倒拖', [...Array(n).keys()].reverse()],
                      ['随机索引', shuffled(n, 20261121)]];
      for (const [name, order] of orders) {
        const cv = document.createElement('canvas'); cv.width = W; cv.height = H;
        const pl = new Player(cv, null, null);
        pl.setManifest(mani, images);
        let bad = null, checked = 0;
        for (const j of order) {
          pl.seekTo(j, false);
          const f = mani.frames[j];
          if (f.transient) continue;
          checked++;
          const got = pl.ctx.getImageData(0, 0, W, H).data, want = refs[f.src];
          for (let i = 0; i < got.length; i++) {
            if (got[i] !== want[i]) { bad = `帧 ${j}（源帧 ${f.src}）第 ${i} 字节失配`; break; }
          }
          if (bad) break;
        }
        h += `<tr><td>${cfg} / ${fmt.toUpperCase()}</td><td>${name}</td>` +
             `<td class="${bad ? 'bad' : 'ok'}">${bad ? '失败' : '通过'}</td>` +
             `<td>${bad || `比对 ${checked} 帧，逐像素一致`}</td></tr>`;
      }
      const partial = mani.frames.filter(f => f.w < mani.w || f.h < mani.h).length;
      h += `<tr><td>${cfg} / ${fmt.toUpperCase()}</td><td>局部更新矩形</td>` +
           `<td class="${partial ? 'ok' : 'bad'}">${partial ? '通过' : '失败'}</td>` +
           `<td>写出的动画仍保有局部更新矩形：${partial}/${n} 帧为局部矩形</td></tr>`;
    }
  }
  seektest.innerHTML = h;
}
seekSelftest();
{
  let h = '';
  for (const f of DATA.files)
    h += `<figure style="display:inline-block;margin:0 8px;text-align:center">
      <img src="${f.name}" alt="${f.name}"><figcaption>${f.name}<br>${f.bytes} B</figcaption></figure>`;
  native.innerHTML = h;
}
applyConfig('exact');
</script>
</body>
</html>
"""


def build_html(data):
    return TEMPLATE.replace("@@DATA@@", json.dumps(data, ensure_ascii=False))
