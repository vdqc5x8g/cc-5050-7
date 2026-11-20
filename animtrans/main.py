"""Pipeline: scene -> greedy source file -> input decode -> joint-optimized
APNG/GIF exports (two configs) -> independent verification -> review window."""
import base64
import json
from pathlib import Path

from . import scene, model, optimize, apng, gif, verify, report

OUT = Path("out")


def data_url(f):
    return ("data:image/png;base64,"
            + base64.b64encode(apng.png_encode(f["w"], f["h"], f["img"])).decode())


def visible_chain(frames):
    canvas = bytes(scene.W * scene.H * 4)
    prev = None
    out = []
    for f in frames:
        disp, canvas = model.apply_frame(canvas, f["img"], f["x"], f["y"],
                                         f["w"], f["h"], f["blend"], f["dispose"])
        base = prev if prev is not None else bytes(scene.W * scene.H * 4)
        out.append(model.diff_bbox(base, disp))
        prev = disp
    return out


def manifest(frames, fmt):
    vis = visible_chain(frames)
    mf = []
    for f, v in zip(frames, vis):
        delay_ms = float(f["delay"] * 1000) if fmt == "apng" else f["delay_cs"] * 10.0
        mf.append(dict(x=f["x"], y=f["y"], w=f["w"], h=f["h"], delay_ms=delay_ms,
                       dispose=f["dispose"], blend=f["blend"], src=f["src"],
                       transient=f["transient"], img=data_url(f),
                       visible=list(v) if v else None))
    return dict(w=scene.W, h=scene.H, loop_ms=sum(m["delay_ms"] for m in mf), frames=mf)


def build_plan(canvases, delays, cfg, fmt):
    if cfg == "size":
        cs, ds, srcs = optimize.merge_runs(canvases, delays)
    else:
        cs, ds, srcs = canvases, delays, list(range(len(canvases)))
    frames = optimize.dp_plan(cs, ds, fmt, size_mode=(cfg == "size"), src_map=srcs)
    if fmt == "gif":
        optimize.assign_gif_delays(frames)
    return frames


def decode_file(path, fmt, loops):
    data = path.read_bytes()
    if fmt == "apng":
        return apng.composite(apng.read_apng(data), loops=loops)
    return gif.composite(gif.read_gif(data), loops=loops)


def stats_entry(cfg, fmt, frames, nbytes, vres):
    transients = sum(1 for f in frames if f["transient"])
    if fmt == "apng":
        gran = ("1/60 s 有理数精确 (num/den)" if cfg == "exact"
                else "1 ms (den=1000)，供拆分瞬态帧")
    else:
        gran = ("1 cs = 10 ms，Bresenham 抖动分配" if cfg == "exact"
                else "1 cs = 10 ms；拆分瞬态帧 = 10 ms")
    cum = vres["stats"]["max_cum_delay_err_ms"]
    cumerr = f"≤ {cum:.2f} ms"
    if transients:
        d = 1 if fmt == "apng" else 10
        cumerr += f"；另引入 {transients} 个 ≤{d} ms 瞬态"
    return dict(frames=len(frames), pixels=optimize.pixels_written(frames),
                bytes=nbytes, transients=transients, gran=gran, cumerr=cumerr)


def rect_s(f):
    return f"({f['x']},{f['y']},{f['w']}×{f['h']})={f['w'] * f['h']}px"


def example_html(greedy, plans):
    ea = plans["exact"]["apng"]
    g = {f["src"]: f for f in greedy}
    e = {f["src"]: f for f in ea}
    gsum = sum(g[t]["w"] * g[t]["h"] for t in (7, 8, 9))
    esum = sum(e[t]["w"] * e[t]["h"] for t in (7, 8, 9))
    x14 = e[14]
    s14 = [f for f in plans["size"]["apng"] if f["src"] == 14]
    a14 = x14["w"] * x14["h"]
    s14sum = sum(f["w"] * f["h"] for f in s14)
    boat_prev = [f["src"] for f in plans["exact"]["gif"]
                 if f["dispose"] == "previous" and 11 <= f["src"] <= 19]
    return f"""
<div><b>例 1 — 闪光前后（源帧 7→8→9）：</b>贪心策略每帧都裁到当前画布下的最小矩形，
但处置不计后果（一律 dispose=none）。</div>
<div>　贪心：f7=<code>{rect_s(g[7])}</code>，f8 闪光=<code>{rect_s(g[8])}</code>，
f9 面对全白画布只能整帧重绘 <code>{rect_s(g[9])}</code>，三帧合计 <code>{gsum}</code> px。</div>
<div>　联合优化：f7=<code>{e[7]['w']}×{e[7]['h']}</code> 矩形同样最小，但 dispose=<code>previous</code>；
f8 闪光矩形同为 <code>{e[8]['w']}×{e[8]['h']}</code>（无法再小），dispose=<code>previous</code>。
两级处置的结果参与后续帧成本：闪光后画布先回到 f7 之前、再回到信标已点亮的画布，
f9 只需 <code>{rect_s(e[9])}</code>，三帧合计 <code>{esum}</code> px。</div>
<div>　→ 当前帧同样裁到最小，三帧合计却多写 <code>{gsum - esum}</code> px
（{100.0 * (gsum - esum) / gsum:.1f}% 浪费）——省像素靠的是处置方式参与下一帧成本，而不是更小的矩形。</div>
<div><b>例 2 — 一帧两处远隔变化（源帧 14：舷窗中的船 + 角落信标）：</b>
精确保时配置禁拆分，单矩形 <code>{rect_s(x14)}</code>；
体积优先配置拆为两帧 <code>{' + '.join(rect_s(f) for f in s14)}</code> = {s14sum} px
（另计 1 帧开销折算 {optimize.SPLIT_OVERHEAD_PX} px），
省 {a14 - s14sum} px（{100.0 * (a14 - s14sum) / a14:.1f}%），代价是 1 个瞬态帧（APNG 1 ms / GIF 10 ms）。</div>
<div><b>GIF 的处置链：</b>GIF 局部帧无法把像素改回透明（无 source 混合、弃用有歧义的
disposal=2），精确保时 GIF 中源帧 {boat_prev[0]}..{boat_prev[-1]} 的船身帧全部以
dispose=previous 链接回船未入窗的画布，船驶出后舷窗自动恢复透明孔，后续帧近乎零成本。</div>
"""


def main():
    OUT.mkdir(exist_ok=True)
    canvases, delays, meta = scene.build()
    assert canvases[-1] == canvases[0], "loop seam: last canvas must equal first"

    # 1) baseline greedy encoder -> the transcoder's input file
    greedy = optimize.greedy_plan(canvases, delays)
    src_path = OUT / "src_input.png"
    apng.write_apng(src_path, scene.W, scene.H, greedy)

    # 2) input side: recover full canvases via blend/clear/restore rules
    decoded_src = decode_file(src_path, "apng", 1)
    input_ok = all(c == canvases[t] for t, (c, _) in enumerate(decoded_src))
    input_rows = [dict(check="输入端按混合/清背景/恢复旧画面求出完整图",
                       ok=input_ok,
                       detail=f"{sum(1 for t, (c, _) in enumerate(decoded_src) if c == canvases[t])}"
                              f"/{scene.N} 帧与参考画布逐像素一致")]
    verify_results = [dict(label="src_input.png（转码输入）", ok=input_ok, rows=input_rows,
                           stats=dict(max_cum_delay_err_ms=0.0))]

    # 3) target encoder: joint choice of full vs partial frames, two configs
    plans, files_info = {}, []
    for cfg in ("exact", "size"):
        plans[cfg] = {}
        for fmt in ("apng", "gif"):
            frames = build_plan(canvases, delays, cfg, fmt)
            path = OUT / f"loop_{cfg}.{ 'png' if fmt == 'apng' else 'gif'}"
            if fmt == "apng":
                nbytes = apng.write_apng(path, scene.W, scene.H, frames)
            else:
                nbytes = gif.write_gif(path, scene.W, scene.H, frames, scene.PALETTE)
            plans[cfg][fmt] = frames
            files_info.append((cfg, fmt, frames, path, nbytes))

    # 4) verification through the independent decode paths
    stats = {"exact": {}, "size": {}}
    for cfg, fmt, frames, path, nbytes in files_info:
        d1 = decode_file(path, fmt, 1)
        d2 = decode_file(path, fmt, 2)
        vres = verify.verify(d1, d2, frames, canvases, meta, path.name)
        verify_results.append(vres)
        stats[cfg][fmt] = stats_entry(cfg, fmt, frames, nbytes, vres)

    # 5) review window
    data = dict(
        meta=meta,
        plans={cfg: {fmt: manifest(plans[cfg][fmt], fmt) for fmt in ("apng", "gif")}
               for cfg in ("exact", "size")},
        stats=stats,
        example_html=example_html(greedy, plans),
        verify=verify_results,
        files=[dict(name=p.name, bytes=n) for _, _, _, p, n in files_info]
        + [dict(name=src_path.name, bytes=src_path.stat().st_size)],
    )
    (OUT / "viewer.html").write_text(report.build_html(data), encoding="utf-8")
    slim = dict(stats=stats, verify=verify_results)
    (OUT / "report.json").write_text(json.dumps(slim, ensure_ascii=False, indent=1),
                                     encoding="utf-8")

    # console summary
    print("== 导出 ==")
    for f in data["files"]:
        print(f"  {f['name']:<18} {f['bytes']:>7} B")
    print("== 配置取舍 ==")
    for cfg in ("exact", "size"):
        for fmt in ("apng", "gif"):
            s = stats[cfg][fmt]
            print(f"  {cfg:>5}/{fmt:<4} 帧数 {s['frames']:>2}  像素 {s['pixels']:>6}  "
                  f"{s['bytes']:>6} B  瞬态 {s['transients']}  累计误差 {s['cumerr']}")
    print("== 验片 ==")
    all_ok = True
    for v in verify_results:
        all_ok &= v["ok"]
        print(f"  [{'OK' if v['ok'] else 'FAIL'}] {v['label']}")
        for r in v["rows"]:
            print(f"       {'✓' if r['ok'] else '✗'} {r['check']}: {r['detail']}")
    print(f"\n验片窗口: {(OUT / 'viewer.html').resolve()}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
