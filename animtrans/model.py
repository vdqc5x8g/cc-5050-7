"""Canvas compositor model shared by the encoder's cost search.

Implements the three disposal rules (keep / clear-to-background /
restore-previous) and the two blend rules (source / over) exactly as the
decoder-side file parsers in apng.py and gif.py re-implement them
independently for cross-verification.
"""
from .scene import W, H

NONE, BACKGROUND, PREVIOUS = "none", "background", "previous"
SOURCE, OVER = "source", "over"


def px(buf, x, y):
    i = (y * W + x) * 4
    return buf[i:i + 4]


def region(canvas, x, y, w, h):
    out = bytearray(w * h * 4)
    for row in range(h):
        s = ((y + row) * W + x) * 4
        out[row * w * 4:(row + 1) * w * 4] = canvas[s:s + w * 4]
    return bytes(out)


def _over_px(dst, src):
    sa = src[3]
    if sa == 255:
        return src
    if sa == 0:
        return dst
    da = dst[3]
    oa = sa + da * (255 - sa) // 255
    if oa == 0:
        return b"\x00\x00\x00\x00"
    out = bytearray(4)
    for c in range(3):
        out[c] = (src[c] * sa * 255 + dst[c] * da * (255 - sa)) // (oa * 255)
    out[3] = oa
    return bytes(out)


def apply_frame(canvas, img, x, y, w, h, blend, dispose, prev=None):
    """Return (displayed, canvas_after_disposal).

    prev: canvas saved before this frame (needed only for PREVIOUS).
    """
    disp = bytearray(canvas)
    if blend == SOURCE:
        for row in range(h):
            i = ((y + row) * W + x) * 4
            s = row * w * 4
            disp[i:i + w * 4] = img[s:s + w * 4]
    else:
        for row in range(h):
            for col in range(w):
                i = ((y + row) * W + (x + col)) * 4
                s = (row * w + col) * 4
                disp[i:i + 4] = _over_px(disp[i:i + 4], img[s:s + 4])
    disp = bytes(disp)
    if dispose == NONE:
        return disp, disp
    if dispose == BACKGROUND:
        after = bytearray(disp)
        for row in range(h):
            s = ((y + row) * W + x) * 4
            after[s:s + w * 4] = b"\x00" * (w * 4)
        return disp, bytes(after)
    # PREVIOUS: restore the rect region from the pre-frame canvas
    after = bytearray(disp)
    base = prev if prev is not None else canvas
    for row in range(h):
        s = ((y + row) * W + x) * 4
        after[s:s + w * 4] = base[s:s + w * 4]
    return disp, bytes(after)


def diff_bbox(a, b):
    """Smallest rect covering pixels where canvases differ, or None."""
    x0, y0, x1, y1 = W, H, -1, -1
    for y in range(H):
        row = y * W * 4
        ar, br = a[row:row + W * 4], b[row:row + W * 4]
        if ar == br:
            continue
        if y < y0:
            y0 = y
        y1 = y
        for x in range(W):
            if ar[x * 4:x * 4 + 4] != br[x * 4:x * 4 + 4]:
                if x < x0:
                    x0 = x
                if x > x1:
                    x1 = x
    if x1 < 0:
        return None
    return (x0, y0, x1 - x0 + 1, y1 - y0 + 1)


def diff_components(a, b, max_comp=8):
    """8-connected components of the diff mask; [] when equal."""
    mask = bytearray(W * H)
    n = 0
    for i in range(W * H):
        if a[i * 4:i * 4 + 4] != b[i * 4:i * 4 + 4]:
            mask[i] = 1
            n += 1
    if n == 0:
        return []
    comps = []
    seen = bytearray(W * H)
    for start in range(W * H):
        if not mask[start] or seen[start]:
            continue
        stack = [start]
        seen[start] = 1
        pts = []
        while stack:
            i = stack.pop()
            pts.append(i)
            x, y = i % W, i // W
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < W and 0 <= ny < H:
                        j = ny * W + nx
                        if mask[j] and not seen[j]:
                            seen[j] = 1
                            stack.append(j)
        comps.append(pts)
        if len(comps) > max_comp:
            return comps
    return comps


def bbox_of(points):
    xs = [p % W for p in points]
    ys = [p // W for p in points]
    return (min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1)


def area(rect):
    return rect[2] * rect[3]


def over_valid(canvas, target, rect):
    """True if painting `target` over `canvas` in rect reproduces target."""
    x, y, w, h = rect
    for row in range(h):
        for col in range(w):
            i = ((y + row) * W + (x + col)) * 4
            t = target[i:i + 4]
            if t[3] == 255:
                continue
            if canvas[i:i + 4] == t:
                continue
            return False
    return True


def gif_over_valid(canvas, target, rect):
    """GIF binary-over can repaint opaque colors but never transparency."""
    x, y, w, h = rect
    for row in range(h):
        for col in range(w):
            i = ((y + row) * W + (x + col)) * 4
            t = target[i:i + 4]
            if t[3] == 0 and canvas[i:i + 4] != t:
                return False
    return True
