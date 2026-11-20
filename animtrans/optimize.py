"""Frame planning: greedy baseline + joint DP optimizer.

The DP state is the decoder canvas *after disposal*; candidate rectangles'
disposal results therefore feed directly into the next frame's diff and cost.
Cost unit = encoded pixels (rect area).
"""
from fractions import Fraction
from .scene import W, H
from . import model
from .model import NONE, BACKGROUND, PREVIOUS, SOURCE, OVER

BEAM = 64
SPLIT_OVERHEAD_PX = 64  # extra chunk/framing cost of one more output frame

FMT_DISPOSE = {
    "apng": [NONE, BACKGROUND, PREVIOUS],
    "gif": [NONE, PREVIOUS],  # GIF disposal-2 (background) is decoder-ambiguous; avoid
}
SPLIT_DELTA = {"apng": Fraction(1, 1000), "gif": Fraction(1, 100)}


def _rect_img_apng(target, rect):
    x, y, w, h = rect
    return model.region(target, x, y, w, h)


def _rect_img_gif(canvas, target, rect):
    x, y, w, h = rect
    out = bytearray(model.region(target, x, y, w, h))
    for row in range(h):
        for col in range(w):
            i = ((y + row) * W + (x + col)) * 4
            if canvas[i:i + 4] == target[i:i + 4]:
                out[(row * w + col) * 4:(row * w + col) * 4 + 4] = b"\x00" * 4
    return bytes(out)


def _mkframe(rect, img, blend, dispose, delay, src, transient=False):
    return dict(x=rect[0], y=rect[1], w=rect[2], h=rect[3], img=img,
                blend=blend, dispose=dispose, delay=delay, src=src,
                transient=transient)


def _noop(canvas, delay, src, fmt):
    img = _rect_img_apng(canvas, (0, 0, 1, 1)) if fmt == "apng" else b"\x00" * 4
    return _mkframe((0, 0, 1, 1), img, SOURCE if fmt == "apng" else OVER,
                    NONE, delay, src)


def _img(fmt, canvas, target, rect):
    return (_rect_img_apng(target, rect) if fmt == "apng"
            else _rect_img_gif(canvas, target, rect))


def _blends(fmt, canvas, target, rect):
    if fmt == "apng":
        out = [SOURCE]
        if model.over_valid(canvas, target, rect):
            out.append(OVER)
        return out
    return [OVER] if model.gif_over_valid(canvas, target, rect) else []


def greedy_plan(canvases, delays, fmt="apng"):
    """Baseline: minimal rect per frame, dispose NONE, no lookahead."""
    canvas = bytes(W * H * 4)
    frames = []
    for t, (target, delay) in enumerate(zip(canvases, delays)):
        r = model.diff_bbox(canvas, target)
        if r is None:
            frames.append(_noop(canvas, delay, t, fmt))
            continue
        img = _rect_img_apng(target, r)
        disp, canvas = model.apply_frame(canvas, img, *r, SOURCE, NONE)
        assert disp == target
        frames.append(_mkframe(r, img, SOURCE, NONE, delay, t))
    return frames


def merge_runs(canvases, delays):
    """Coalesce runs of identical canvases (size-first config only)."""
    cs, ds, srcs = [], [], []
    t = 0
    while t < len(canvases):
        d, src = delays[t], t
        while t + 1 < len(canvases) and canvases[t + 1] == canvases[t]:
            t += 1
            d += delays[t]
        cs.append(canvases[t])
        ds.append(d)
        srcs.append(src)
        t += 1
    return cs, ds, srcs


def _actions(canvas, target, delay, src, fmt, size_mode):
    r = model.diff_bbox(canvas, target)
    if r is None:
        yield [_noop(canvas, delay, src, fmt)], 1
        return
    for blend in _blends(fmt, canvas, target, r):
        img = _img(fmt, canvas, target, r)
        for dispose in FMT_DISPOSE[fmt]:
            yield [_mkframe(r, img, blend, dispose, delay, src)], model.area(r)
    if not size_mode:
        return
    comps = model.diff_components(canvas, target)
    if not (2 <= len(comps) <= 8):
        return
    best = None
    k = len(comps)
    for mask in range(1, 1 << (k - 1)):
        g1 = [p for i, c in enumerate(comps) if mask >> i & 1 for p in c]
        g2 = [p for i, c in enumerate(comps) if not mask >> i & 1 for p in c]
        r1, r2 = model.bbox_of(g1), model.bbox_of(g2)
        cost = model.area(r1) + model.area(r2)
        if best is None or cost < best[0]:
            best = (cost, r1, r2)
    if best is None or best[0] + SPLIT_OVERHEAD_PX >= model.area(r):
        return
    _, r1, r2 = best
    delta = SPLIT_DELTA[fmt]
    if delay - delta <= 0:
        return
    b1 = SOURCE if fmt == "apng" else OVER
    if fmt == "gif" and not model.gif_over_valid(canvas, target, r1):
        return
    img1 = _img(fmt, canvas, target, r1)
    f1 = _mkframe(r1, img1, b1, NONE, delta, src, transient=True)
    mid, _ = model.apply_frame(canvas, img1, *r1, b1, NONE)
    for blend in _blends(fmt, mid, target, r2):
        img2 = _img(fmt, mid, target, r2)
        for dispose in FMT_DISPOSE[fmt]:
            f2 = _mkframe(r2, img2, blend, dispose, delay - delta, src)
            yield [f1, f2], best[0]


def dp_plan(canvases, delays, fmt, size_mode, src_map=None):
    src_map = src_map or list(range(len(canvases)))
    init = bytes(W * H * 4)
    states = {init: (0, [])}  # canvas after disposal -> (cost, frames)
    for target, delay, src in zip(canvases, delays, src_map):
        nxt = {}
        for canvas, (cost, path) in states.items():
            for frames, acost in _actions(canvas, target, delay, src, fmt, size_mode):
                cur = canvas
                for f in frames:
                    disp, cur = model.apply_frame(cur, f["img"], f["x"], f["y"],
                                                  f["w"], f["h"], f["blend"],
                                                  f["dispose"])
                if disp != target:  # last sub-frame must show the exact target
                    continue
                nc = cost + acost
                if cur not in nxt or nc < nxt[cur][0]:
                    nxt[cur] = (nc, path + frames)
        if len(nxt) > BEAM:
            nxt = dict(sorted(nxt.items(), key=lambda kv: kv[1][0])[:BEAM])
        states = nxt
        assert states, f"no valid plan for source frame {src} ({fmt})"
    return min(states.values(), key=lambda s: s[0])[1]


def assign_gif_delays(frames):
    """Integer centiseconds via cumulative rounding (Bresenham).

    Every frame keeps >= 1cs (browser-safe) and the loop total is preserved.
    """
    cum = Fraction(0)
    prev = 0
    raw = []
    for f in frames:
        cum += f["delay"]
        cur = int(cum * 100 + Fraction(1, 2))
        raw.append(cur - prev)
        prev = cur
    for i, v in enumerate(raw):
        if v < 1:
            j = max((k for k in range(len(raw)) if k != i), key=lambda k: raw[k])
            raw[j] -= 1 - v
            raw[i] = 1
    for f, cs in zip(frames, raw):
        f["delay_cs"] = cs
    return frames


def pixels_written(frames):
    return sum(f["w"] * f["h"] for f in frames)
