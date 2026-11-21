"""随机访问（跳到后段 / 向前倒拖 / 随机索引）时的画布状态缓存。

症状
----
顺序播放完全正确；一旦跳到后段再向前拖，透明小窗（舷窗）里会留下
上一帧的颜色。顺序播放时解码器只需维护"当前画布"增量更新，跳帧才
迫使回答：为了显示第 j 帧，画布应当先回到什么状态？

记录：跳帧前保存的是哪个阶段的画布？
------------------------------------
必须保存**处置后**的画布 S_k（= 第 k+1 帧的合成前画布），而不是
合成后、处置前的显示画布 D_k。D_k 与 S_k 只在第 k 帧的编码矩形内
不同，差别恰好是 dispose=background 清空 / dispose=previous 恢复的
那一块；顺序播放时差别不可见（下一帧渲染前才补做处置），跳帧时若
把 D_k 当成后续帧的基准，等于偷偷跳过了第 k 帧的处置，透明区域里
就留下了第 k 帧的颜色。

矩形边界
--------
局部回退区域必须取**帧自身的编码矩形**在合成前的内容（等价于
S_{k-1} 在该矩形内的部分）。不能取可见变化包围盒：over 混合未改变
的像素、dispose=background 清掉的旧内容都在可见 bbox 之外，却在
处置影响的矩形之内。

两种正确做法比较
----------------
A. 关键画布重演（KeyCanvasPlayer）：每 K 帧快照一份完整 S_k，
   跳帧 = 载入最近快照 + 向前重演 ≤K 帧。内存 O(N/K · W·H)，
   倒拖也要正向重演；适合全帧画面为主的动画。
B. 局部回退区域（RollbackPlayer，验片窗口采用）：每帧只存自身
   矩形合成前的内容，倒拖一帧 = 恢复一个矩形，O(1)；
   内存 O(Σ 矩形面积)，对局部帧动画远小于 N·W·H。
两者都必须以上述"处置后 / 合成前"为缓存阶段，否则同样出错。

相同显示 ≠ 相同内部状态
-----------------------
视觉结果相同的两帧若处置元数据不同（如 none vs background），其
处置后画布 S 不同。DisplayHashPlayer 演示了以显示内容为键复用
内部状态的错误：反复跨过这两帧后，下一帧被画在错误的基准上。
"""
from . import model
from .model import NONE, BACKGROUND, PREVIOUS, SOURCE, OVER


def region(canvas, width, x, y, w, h):
    out = bytearray(w * h * 4)
    for row in range(h):
        s = ((y + row) * width + x) * 4
        out[row * w * 4:(row + 1) * w * 4] = canvas[s:s + w * 4]
    return bytes(out)


def paste(canvas, width, x, y, w, h, data):
    out = bytearray(canvas)
    for row in range(h):
        s = ((y + row) * width + x) * 4
        out[s:s + w * 4] = data[row * w * 4:(row + 1) * w * 4]
    return bytes(out)


def composite(canvas, width, f):
    """只混合（blend），不做处置；返回显示画布 D。"""
    x, y, w, h = f["x"], f["y"], f["w"], f["h"]
    img = f["img"]
    disp = bytearray(canvas)
    if f["blend"] == SOURCE:
        for row in range(h):
            i = ((y + row) * width + x) * 4
            s = row * w * 4
            disp[i:i + w * 4] = img[s:s + w * 4]
    else:
        for row in range(h):
            for col in range(w):
                i = ((y + row) * width + (x + col)) * 4
                s = (row * w + col) * 4
                disp[i:i + 4] = model._over_px(disp[i:i + 4], img[s:s + 4])
    return bytes(disp)


def apply_disposal(canvas, width, f, pre):
    """对显示画布补做帧 f 的处置，得到处置后画布 S。

    pre: 帧 f 矩形在合成前的内容（dispose=previous 时用于恢复）。
    """
    if f["dispose"] == NONE:
        return canvas
    x, y, w, h = f["x"], f["y"], f["w"], f["h"]
    if f["dispose"] == BACKGROUND:
        return paste(canvas, width, x, y, w, h, b"\x00" * (w * h * 4))
    return paste(canvas, width, x, y, w, h, pre)  # PREVIOUS


def reference(frames, width, height):
    """完整逐帧参考：严格顺序合成，返回 [(显示画布 D_k, 处置后画布 S_k)]。"""
    canvas = bytes(width * height * 4)
    out = []
    for f in frames:
        pre = region(canvas, width, f["x"], f["y"], f["w"], f["h"])
        disp = composite(canvas, width, f)
        canvas = apply_disposal(disp, width, f, pre)
        out.append((disp, canvas))
    return out


class RollbackPlayer:
    """局部回退区域：每帧缓存自身编码矩形合成前的内容，任意顺序访问。

    不变式：self.canvas == S_{self.idx}（第 idx 帧处置后的画布）。
    撤销第 k 帧只需恢复其矩形：S_k 与 S_{k-1} 只在该矩形内不同
    （合成与处置都不超出该矩形）。
    """

    def __init__(self, frames, width, height):
        self.frames = frames
        self.w, self.h = width, height
        self.canvas = bytes(width * height * 4)
        self.idx = -1
        self.undo = [None] * len(frames)
        self.disp = None

    def _forward_one(self, k):
        f = self.frames[k]
        self.undo[k] = region(self.canvas, self.w, f["x"], f["y"], f["w"], f["h"])
        disp = composite(self.canvas, self.w, f)
        self.canvas = apply_disposal(disp, self.w, f, self.undo[k])
        self.disp = disp
        self.idx = k

    def _backward_one(self, k):
        f = self.frames[k]
        self.canvas = paste(self.canvas, self.w, f["x"], f["y"], f["w"], f["h"],
                            self.undo[k])
        self.idx = k - 1
        self.disp = None

    def render(self, j):
        if j == self.idx and self.disp is not None:
            return self.disp
        if j > self.idx:
            for k in range(self.idx + 1, j + 1):
                self._forward_one(k)
        else:
            while self.idx >= j:
                self._backward_one(self.idx)
            self._forward_one(j)
        return self.disp

    def state(self):
        """当前内部状态 S_{self.idx}（处置后画布），供测试断言。"""
        return self.canvas


class KeyCanvasPlayer:
    """关键画布重演：每 every 帧快照一份完整的处置后画布 S_k。

    capacity: 最多保留几份基准画布（初始空白画布恒占一份）；
    capacity=1 即"只能留一份基准画布"，任何回退都从空白重演。
    """

    def __init__(self, frames, width, height, every=8, capacity=None):
        self.frames = frames
        self.w, self.h = width, height
        self.every = every
        self.capacity = capacity
        self.canvas = bytes(width * height * 4)
        self.idx = -1
        self.disp = None
        self.snaps = {-1: self.canvas}

    def _remember(self, k):
        self.snaps[k] = self.canvas
        if self.capacity is not None:
            while len(self.snaps) > self.capacity:
                oldest = min(k2 for k2 in self.snaps if k2 != -1)
                del self.snaps[oldest]

    def _forward_one(self, k):
        f = self.frames[k]
        pre = region(self.canvas, self.w, f["x"], f["y"], f["w"], f["h"])
        disp = composite(self.canvas, self.w, f)
        self.canvas = apply_disposal(disp, self.w, f, pre)
        self.disp = disp
        self.idx = k
        if (k + 1) % self.every == 0:
            self._remember(k)

    def render(self, j):
        if j == self.idx and self.disp is not None:
            return self.disp
        if j < self.idx:
            s = max(k for k in self.snaps if k < j)
            self.canvas, self.idx, self.disp = self.snaps[s], s, None
        while self.idx < j:
            self._forward_one(self.idx + 1)
        return self.disp


class DisplayCachePlayer:
    """错误示范（复现报告的症状）：跳帧缓存保存的是显示画布 D_k
    （合成后、处置前），倒拖恢复后直接以其为基准继续向前合成。
    顺序播放时每帧都补做处置，状态正确，所以症状只在跳帧后出现。"""

    def __init__(self, frames, width, height):
        self.frames = frames
        self.w, self.h = width, height
        self.blank = bytes(width * height * 4)
        self.canvas = self.blank
        self.idx = -1
        self.cache = {}

    def render(self, j):
        if j < self.idx and j in self.cache:
            self.canvas = self.cache[j]  # 错误：D_j 被当成后续合成的基准
            self.idx = j
            return self.canvas
        if j < self.idx:
            self.canvas, self.idx = self.blank, -1
        while self.idx < j:
            k = self.idx + 1
            f = self.frames[k]
            pre = region(self.canvas, self.w, f["x"], f["y"], f["w"], f["h"])
            disp = composite(self.canvas, self.w, f)
            self.cache[k] = disp
            self.canvas = apply_disposal(disp, self.w, f, pre)
            self.idx = k
        return self.cache[j]


class DisplayHashPlayer:
    """错误示范：以显示画布内容为键缓存内部状态——把相同显示图当成
    相同内部状态。只留一份基准画布（空白），回退即从空白重演；
    但前进时若某帧显示与历史帧相同，就直接复用当时缓存的处置后
    画布，跳过本帧自己的处置元数据。"""

    def __init__(self, frames, width, height):
        self.frames = frames
        self.w, self.h = width, height
        self.blank = bytes(width * height * 4)
        self.canvas = self.blank
        self.idx = -1
        self.state_by_display = {}

    def render(self, j):
        if j <= self.idx:
            self.canvas, self.idx = self.blank, -1
        while self.idx < j:
            k = self.idx + 1
            f = self.frames[k]
            pre = region(self.canvas, self.w, f["x"], f["y"], f["w"], f["h"])
            disp = composite(self.canvas, self.w, f)
            key = bytes(disp)
            if key in self.state_by_display:
                self.canvas = self.state_by_display[key]  # 错误：相同显示 ≠ 相同状态
            else:
                self.canvas = apply_disposal(disp, self.w, f, pre)
                self.state_by_display[key] = self.canvas
            self.idx = k
            self.disp = disp
        return self.disp
