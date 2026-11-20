"""Reference scene: a boat sails behind a wall with a transparent porthole.

Timeline (N=30 frames @ 60fps):
  t=0..3   static base (beacon off, boat hidden)
  t=4..6   corner beacon on
  t=7      beacon off
  t=8      full-white flash (must restore previous canvas afterwards)
  t=9      only the corner beacon changes vs t=7
  t=11..19 boat crosses the porthole (visible only through the transparent hole)
  t=14,17  beacon blinks while the boat is mid-hole (two distant diff regions)
  t=24..29 back to base; canvas at t=29 equals t=0 so the loop joins seamlessly.
"""
from fractions import Fraction

W, H = 160, 120
CX, CY = 80, 60
R_IN, R_OUT = 27, 34
N = 30
FPS = 60
DELAY = Fraction(1, FPS)
LOOP_S = N * DELAY

TRANSP = (0, 0, 0, 0)
WALL = (38, 46, 62, 255)
RING = (202, 168, 74, 255)
BEACON_OFF = (120, 52, 52, 255)
BEACON_ON = (255, 74, 54, 255)
HULL = (158, 64, 42, 255)
SAIL = (238, 236, 222, 255)
MAST = (96, 74, 54, 255)
FLASH_C = (255, 255, 255, 255)

PALETTE = [TRANSP, WALL, RING, BEACON_OFF, BEACON_ON, HULL, SAIL, MAST, FLASH_C]

BEACON_RECT = (138, 8, 12, 10)
BOAT_W, BOAT_H = 26, 14
BOAT_Y = 66
FLASH_T = 8


def boat_xc(t):
    return 80 + (t - 15) * 9


def beacon_on(t):
    return (4 <= t <= 6) or (9 <= t <= 13) or (17 <= t <= 23)


def boat_sprite():
    img = [[TRANSP] * BOAT_W for _ in range(BOAT_H)]
    for y in range(9, 13):
        inset = (y - 9) * 2
        for x in range(2 + inset, 24 - inset):
            img[y][x] = HULL
    for x in range(3, 23):
        img[8][x] = HULL
    for y in range(1, 9):
        img[y][13] = MAST
    for y in range(2, 9):
        for x in range(14, 14 + (9 - y)):
            img[y][x] = SAIL
    for y in range(4, 9):
        for x in range(13 - (9 - y) // 2, 13):
            img[y][x] = SAIL
    return img


SPRITE = boat_sprite()


def _put_px(buf, x, y, c):
    if 0 <= x < W and 0 <= y < H:
        i = (y * W + x) * 4
        buf[i:i + 4] = bytes(c)


def frame(t):
    """Full RGBA canvas (bytes) for source frame t."""
    if t == FLASH_T:
        return bytes(FLASH_C) * (W * H)
    buf = bytearray(W * H * 4)
    # boat layer (behind the wall)
    bx = boat_xc(t) - BOAT_W // 2
    for sy, row in enumerate(SPRITE):
        for sx, c in enumerate(row):
            if c[3]:
                _put_px(buf, bx + sx, BOAT_Y + sy, c)
    # wall with transparent porthole + brass ring
    for y in range(H):
        for x in range(W):
            d2 = (x - CX) ** 2 + (y - CY) ** 2
            if d2 <= R_IN * R_IN:
                continue  # transparent hole
            c = RING if d2 <= R_OUT * R_OUT else WALL
            _put_px(buf, x, y, c)
    # corner beacon
    bx0, by0, bw, bh = BEACON_RECT
    c = BEACON_ON if beacon_on(t) else BEACON_OFF
    for y in range(by0, by0 + bh):
        for x in range(bx0, bx0 + bw):
            _put_px(buf, x, y, c)
    return bytes(buf)


def boat_visible(t):
    """True if any boat pixel shows through the hole at frame t."""
    bx = boat_xc(t) - BOAT_W // 2
    for sy, row in enumerate(SPRITE):
        for sx, c in enumerate(row):
            if c[3]:
                x, y = bx + sx, BOAT_Y + sy
                if (x - CX) ** 2 + (y - CY) ** 2 <= R_IN * R_IN:
                    return True
    return False


def build():
    canvases = [frame(t) for t in range(N)]
    delays = [DELAY] * N
    # hole sample points the boat never covers (boat occupies y 66..79)
    hole_points = [(CX, CY - 22), (CX - 16, CY - 14), (CX + 16, CY - 14), (CX, CY + 22)]
    # post-flash frames where the hull centre is inside the hole
    boat_checks = []
    for t in range(FLASH_T + 1, N):
        if boat_visible(t):
            x, y = boat_xc(t), BOAT_Y + 11
            if (x - CX) ** 2 + (y - CY) ** 2 <= (R_IN - 3) ** 2:
                boat_checks.append((t, x, y))
    meta = dict(W=W, H=H, N=N, FPS=FPS, FLASH_T=FLASH_T,
                hole_points=hole_points, boat_checks=boat_checks,
                beacon_rect=BEACON_RECT,
                boat_visible=[t for t in range(N) if boat_visible(t)],
                loop_ms=float(LOOP_S * 1000))
    return canvases, delays, meta
