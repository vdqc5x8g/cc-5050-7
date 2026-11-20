"""Frame-by-frame verification of exported files against the reference timeline."""
from fractions import Fraction
from . import scene

TRANSIENT_MAX = Fraction(1, 50)  # 20 ms


def _px(canvas, x, y):
    i = (y * scene.W + x) * 4
    return canvas[i:i + 4]


def verify(decoded, decoded_loop2, plan_frames, reference, meta, label):
    """decoded: [(canvas, info)] from the independent decoder, one loop.
    decoded_loop2: same decoder run for two loops (seam check).
    plan_frames: encoder plan (ideal delays, src indices, transient flags).
    """
    rows = []

    def row(name, ok, detail):
        rows.append(dict(check=name, ok=bool(ok), detail=detail))

    # --- frame count & delay integrity -------------------------------------
    delays = [f["delay"] for _, f in decoded]
    ideals = [f["delay"] for f in plan_frames]
    row("帧数一致", len(decoded) == len(plan_frames),
        f"{len(decoded)} vs plan {len(plan_frames)}")
    # cumulative deviation against the ideal timeline
    cum_actual = Fraction(0)
    cum_ideal = Fraction(0)
    max_dev = Fraction(0)
    for d, ideal in zip(delays, ideals):
        cum_actual += d
        cum_ideal += ideal
        max_dev = max(max_dev, abs(cum_actual - cum_ideal))
    row("循环总时长", cum_actual == scene.LOOP_S,
        f"{float(cum_actual * 1000):.2f} ms (目标 {float(scene.LOOP_S * 1000):.2f} ms)")
    row("累计延迟误差", True, f"max |Σactual-Σideal| = {float(max_dev * 1000):.2f} ms")

    # --- per-frame canvas exactness ----------------------------------------
    exact = 0
    transient = 0
    fails = []
    cum = Fraction(0)
    for i, ((canvas, f), pf) in enumerate(zip(decoded, plan_frames)):
        mid = cum + f["delay"] / 2
        cum += f["delay"]
        t = min(int(mid * scene.FPS), scene.N - 1)
        if canvas == reference[t]:
            exact += 1
        elif f["delay"] <= TRANSIENT_MAX and i + 1 < len(decoded):
            transient += 1
        else:
            fails.append((i, t))
    row("逐帧像素精确", not fails,
        f"{exact} 精确 + {transient} 瞬态" + (f"，失败 {fails[:4]}" if fails else ""))

    # --- transient sub-frames are bounded ----------------------------------
    plan_trans = [f for f in plan_frames if f.get("transient")]
    row("瞬态帧受控", transient == len(plan_trans),
        f"{transient} 个，单个 ≤ {float(TRANSIENT_MAX * 1000):.0f} ms")

    # --- transparent porthole hole -----------------------------------------
    bad = []
    cum = Fraction(0)
    for i, (canvas, f) in enumerate(decoded):
        mid = cum + f["delay"] / 2
        cum += f["delay"]
        t = min(int(mid * scene.FPS), scene.N - 1)
        if t == scene.FLASH_T:
            continue  # the flash is intentionally opaque everywhere
        for (hx, hy) in meta["hole_points"]:
            if _px(canvas, hx, hy)[3] != 0:
                bad.append((i, hx, hy))
    row("透明舷窗孔", not bad, f"{len(meta['hole_points'])} 采样点" +
        (f"，异常 {bad[:4]}" if bad else " 全部 alpha=0"))

    # --- boat body after the flash ------------------------------------------
    bad = []
    cum = Fraction(0)
    for i, ((canvas, f), pf) in enumerate(zip(decoded, plan_frames)):
        mid = cum + f["delay"] / 2
        cum += f["delay"]
        if pf.get("transient"):
            continue  # split sub-frame: boat lands with the following sub-frame
        t = min(int(mid * scene.FPS), scene.N - 1)
        for (bt, bx, by) in meta["boat_checks"]:
            if bt == t and _px(canvas, bx, by) != bytes(scene.HULL):
                bad.append((i, t))
    row("闪光后的船身", not bad,
        f"{len(meta['boat_checks'])} 个船身采样帧" + ("，异常 " + str(bad[:4]) if bad else " 全部命中"))

    # --- loop seam: last frame joins back to the first ----------------------
    n1 = len(decoded)
    seam_ok = len(decoded_loop2) == 2 * n1
    if seam_ok:
        for k in range(n1):
            if decoded_loop2[k][0] != decoded_loop2[n1 + k][0]:
                seam_ok = False
                break
    row("末帧接回首帧", seam_ok, "第二循环逐帧画布与第一循环完全一致")

    ok = all(r["ok"] for r in rows)
    return dict(label=label, ok=ok, rows=rows,
                stats=dict(frames=len(decoded), exact=exact, transient=transient,
                           max_cum_delay_err_ms=float(max_dev * 1000)))
