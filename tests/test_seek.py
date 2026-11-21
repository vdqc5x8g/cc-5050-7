"""跳帧缓存修复的验证：最小片段、三种访问顺序、相同显示≠相同状态。"""
import random
import tempfile
import unittest
from pathlib import Path

from animtrans import apng, gif, main, miniclip, scene, seek

OUT = Path(__file__).resolve().parent.parent / "out"


def px(buf, w, x, y):
    i = (y * w + x) * 4
    return bytes(buf[i:i + 4])


class MiniclipTest(unittest.TestCase):
    """三个相互局部覆盖的矩形，连续含 previous/background 两种处置。"""

    def setUp(self):
        self.frames = miniclip.build()
        self.ref = seek.reference(self.frames, miniclip.W, miniclip.H)

    def orders(self):
        n = len(self.frames)
        return {
            "顺播": list(range(n)),
            "倒拖": list(range(n - 1, -1, -1)),
            "随机索引": random.Random(7).sample(range(n), n),
        }

    def test_rollback_three_orders(self):
        for name, order in self.orders().items():
            p = seek.RollbackPlayer(self.frames, miniclip.W, miniclip.H)
            for j in order:
                self.assertEqual(p.render(j), self.ref[j][0], f"{name} 帧 {j}")

    def test_keycanvas_three_orders(self):
        for name, order in self.orders().items():
            p = seek.KeyCanvasPlayer(self.frames, miniclip.W, miniclip.H, every=2)
            for j in order:
                self.assertEqual(p.render(j), self.ref[j][0], f"{name} 帧 {j}")

    def test_display_cache_leaves_stale_color(self):
        order = [0, 1, 2, 3, 2, 3]  # 跳到后段(3)再向前拖(2)，然后继续播放
        buggy = seek.DisplayCachePlayer(self.frames, miniclip.W, miniclip.H)
        got = [buggy.render(j) for j in order]
        # 倒拖到 2 时显示本身仍正确（缓存的是显示画布）——症状潜伏到下一步
        self.assertEqual(got[4], self.ref[2][0])
        # 继续播放的帧 3：透明小窗 C\B 里留下帧 2 的蓝色
        self.assertNotEqual(got[5], self.ref[3][0])
        self.assertEqual(px(got[5], miniclip.W, *miniclip.STALE_PT), bytes(miniclip.BLUE))
        self.assertEqual(px(self.ref[3][0], miniclip.W, *miniclip.STALE_PT), b"\x00" * 4)
        # 修复后的播放器（缓存处置后/合成前状态）同序访问完全一致
        fixed = seek.RollbackPlayer(self.frames, miniclip.W, miniclip.H)
        for j in order:
            self.assertEqual(fixed.render(j), self.ref[j][0])

    def test_miniclip_matches_independent_decoder(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "clip.png"
            apng.write_apng(path, miniclip.W, miniclip.H, self.frames)
            decoded = apng.composite(apng.read_apng(path.read_bytes()), loops=1)
        for j, (canvas, _) in enumerate(decoded):
            self.assertEqual(canvas, self.ref[j][0], f"独立解码器 帧 {j}")


class SameDisplayTest(unittest.TestCase):
    """视觉结果相同但处置元数据不同的连续两帧。"""

    def setUp(self):
        self.frames = miniclip.build_same_display()
        self.ref = seek.reference(self.frames, miniclip.W, miniclip.H)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "clip.png"
            apng.write_apng(path, miniclip.W, miniclip.H, self.frames)
            self.decoded = [c for c, _ in apng.composite(apng.read_apng(path.read_bytes()), loops=1)]

    def test_same_display_different_state(self):
        # 前提：两帧显示相同，处置后画布（内部状态）不同
        self.assertEqual(self.ref[0][0], self.ref[1][0])
        self.assertNotEqual(self.ref[0][1], self.ref[1][1])

    def test_single_baseline_crossing(self):
        # 缓存限制为只留一份基准画布，反复跨过这两帧
        order = [0, 1, 2, 1, 0, 1, 2, 1, 2, 0, 1, 2]
        p = seek.KeyCanvasPlayer(self.frames, miniclip.W, miniclip.H, every=1, capacity=1)
        for j in order:
            self.assertEqual(p.render(j), self.decoded[j], f"帧 {j} 与独立解码器不一致")
        # 局部回退区域做法同样一致
        p2 = seek.RollbackPlayer(self.frames, miniclip.W, miniclip.H)
        for j in order:
            self.assertEqual(p2.render(j), self.decoded[j], f"帧 {j} 与独立解码器不一致")

    def test_display_hash_cache_is_wrong(self):
        # 把相同显示图当成相同内部状态：下一帧被画在错误的基准上
        buggy = seek.DisplayHashPlayer(self.frames, miniclip.W, miniclip.H)
        got = [buggy.render(j) for j in (0, 1, 2)]
        self.assertEqual(got[0], self.decoded[0])
        self.assertEqual(got[1], self.decoded[1])  # 显示碰巧仍对
        self.assertNotEqual(got[2], self.decoded[2])


class RealPlanSeekTest(unittest.TestCase):
    """真实场景的四种导出计划：三种顺序访问同一帧，与参考画布逐像素比对。"""

    @classmethod
    def setUpClass(cls):
        cls.canvases, cls.delays, _ = scene.build()
        cls.plans = {}
        for cfg in ("exact", "size"):
            for fmt in ("apng", "gif"):
                cls.plans[(cfg, fmt)] = main.build_plan(cls.canvases, cls.delays, cfg, fmt)

    def test_three_orders_pixel_exact(self):
        for (cfg, fmt), frames in self.plans.items():
            n = len(frames)
            orders = {
                "顺播": list(range(n)),
                "倒拖": list(range(n - 1, -1, -1)),
                "随机索引": random.Random(99).sample(range(n), n),
            }
            for name, order in orders.items():
                p = seek.RollbackPlayer(frames, scene.W, scene.H)
                for j in order:
                    f = frames[j]
                    if f["transient"]:
                        continue
                    self.assertEqual(p.render(j), self.canvases[f["src"]],
                                     f"{cfg}/{fmt} {name} 帧 {j}")

    def test_plans_keep_local_rects(self):
        for (cfg, fmt), frames in self.plans.items():
            partial = [f for f in frames if f["w"] < scene.W or f["h"] < scene.H]
            self.assertTrue(partial, f"{cfg}/{fmt} 失去了局部更新矩形")


class ExportedFileTest(unittest.TestCase):
    """写出的动画文件仍保有局部更新矩形。"""

    def test_exported_files_keep_local_rects(self):
        for name in ("loop_exact.png", "loop_size.png"):
            meta = apng.read_apng((OUT / name).read_bytes())
            partial = [f for f in meta["frames"]
                       if f["w"] < meta["width"] or f["h"] < meta["height"]]
            self.assertTrue(partial, f"{name} 失去了局部更新矩形")
        for name in ("loop_exact.gif", "loop_size.gif"):
            meta = gif.read_gif((OUT / name).read_bytes())
            partial = [f for f in meta["frames"]
                       if f["w"] < meta["width"] or f["h"] < meta["height"]]
            self.assertTrue(partial, f"{name} 失去了局部更新矩形")


if __name__ == "__main__":
    unittest.main()
