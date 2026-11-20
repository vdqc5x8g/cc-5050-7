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
<h2>另一解码路径逐帧核对（独立解析文件字节流）</h2>
<table id="verify"></table>
<h2>导出的实际动画（浏览器原生解码播放）</h2>
<div id="native"></div>
<script>
const DATA = @@DATA@@;

class Player {
  constructor(cv, ov, hud) {
    this.ctx = cv.getContext('2d');
    this.octx = ov.getContext('2d');
    this.hud = hud;
    this.idx = -1;
    this.prev = null;
    this.saved = null;
  }
  setManifest(mani, images) {
    this.mani = mani; this.images = images;
    this.idx = -1; this.prev = null; this.saved = null;
    this.ctx.clearRect(0, 0, mani.w, mani.h);
  }
  render(j, overlay) {
    const m = this.mani, f = m.frames[j], ctx = this.ctx;
    if (this.prev) {
      const p = this.prev;
      if (p.dispose === 'background') ctx.clearRect(p.x, p.y, p.w, p.h);
      else if (p.dispose === 'previous' && this.saved) ctx.putImageData(this.saved, p.x, p.y);
    }
    if (f.dispose === 'previous') this.saved = ctx.getImageData(f.x, f.y, f.w, f.h);
    const img = this.images[j];
    if (f.blend === 'source') ctx.clearRect(f.x, f.y, f.w, f.h);
    ctx.drawImage(img, f.x, f.y);
    this.prev = f;
    if (overlay) {
      const o = this.octx;
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
    if (idx !== this.idx) {
      let j = this.idx;
      while (j !== idx) { j = (j + 1) % m.frames.length; this.render(j, j === idx); }
      this.idx = idx;
    }
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
  infoA.textContent = `${p.apng.frames.length} 帧`;
  infoG.textContent = `${p.gif.frames.length} 帧`;
}

btnExact.onclick = () => { btnExact.classList.add('on'); btnSize.classList.remove('on'); applyConfig('exact'); };
btnSize.onclick = () => { btnSize.classList.add('on'); btnExact.classList.remove('on'); applyConfig('size'); };
btnPause.onclick = () => { running = !running; btnPause.textContent = running ? '暂停' : '继续'; };
showOv.onchange = () => { DATA.showOv = showOv.checked; players.forEach(pl => { pl.idx = -1; pl.start = null; }); };

(function loop(now) {
  if (running) players.forEach(pl => pl.tick(now || 0));
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
