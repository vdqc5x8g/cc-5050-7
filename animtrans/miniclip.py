"""最小复现片段。

build(): 三个相互局部覆盖的矩形 A/B/C（两两相交、互不包含），
连续包含 dispose=previous（恢复此前画布）与 dispose=background
（清背景）两种处置，用于复现"跳到后段再向前拖，透明小窗残留
上一帧颜色"。

build_same_display(): 连续两帧视觉结果相同但处置元数据不同
（none vs background），用于暴露"把相同显示图当成相同内部状态"。
"""
from fractions import Fraction

from .model import NONE, BACKGROUND, PREVIOUS, SOURCE

W, H = 12, 12

RED = (200, 30, 30, 255)
GREEN = (30, 180, 60, 255)
BLUE = (40, 80, 220, 255)
YELLOW = (230, 210, 40, 255)

RECT_A = (1, 1, 6, 6)  # x1..6  y1..6
RECT_B = (4, 4, 6, 6)  # x4..9  y4..9
RECT_C = (2, 6, 6, 4)  # x2..7  y6..9
# A∩B = (4..6, 4..6)，A∩C = (2..6, 6)，B∩C = (4..7, 6..9)：两两局部覆盖

# B 内、A/C 之外的透明点：f1(previous) 处置后必须恢复透明
HOLE_PT = (8, 5)
# C\B 区域：f2(background) 清背景后必须透明；症状帧会在这里残留蓝色
STALE_PT = (2, 7)

DELAY = Fraction(1, 10)


def _frame(rect, color, dispose):
    x, y, w, h = rect
    return dict(x=x, y=y, w=w, h=h, img=bytes(color) * (w * h),
                blend=SOURCE, dispose=dispose, delay=DELAY, src=-1,
                transient=False)


def build():
    """f0 红A(none) → f1 绿B(previous) → f2 蓝C(background) → f3 黄B(none)。"""
    frames = [_frame(RECT_A, RED, NONE),
              _frame(RECT_B, GREEN, PREVIOUS),
              _frame(RECT_C, BLUE, BACKGROUND),
              _frame(RECT_B, YELLOW, NONE)]
    return frames


def build_same_display():
    """g0 与 g1 显示完全相同（R 内红色），处置元数据不同：
    g0=none（处置后 R 仍红），g1=background（处置后 R 透明）。
    g2 在远处画绿块：正确的下一帧里 R 区域必须透明。"""
    r = (2, 2, 4, 4)
    frames = [_frame(r, RED, NONE),
              _frame(r, RED, BACKGROUND),
              _frame((8, 8, 2, 2), GREEN, NONE)]
    return frames
