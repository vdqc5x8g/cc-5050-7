"""GIF89a writer (LZW) + an independent reader/compositor (second decode path)."""
import struct
from fractions import Fraction

DISPOSAL = {"none": 1, "previous": 3}  # disposal-2 (background) intentionally unused
DISPOSAL_NAME = {1: "none", 2: "background", 3: "previous"}


class _BitWriter:
    def __init__(self):
        self.acc = 0
        self.nbits = 0
        self.out = bytearray()

    def write(self, code, size):
        self.acc |= code << self.nbits
        self.nbits += size
        while self.nbits >= 8:
            self.out.append(self.acc & 255)
            self.acc >>= 8
            self.nbits -= 8

    def finish(self):
        if self.nbits:
            self.out.append(self.acc & 255)
        return bytes(self.out)


def lzw_encode(data, mcs):
    clear = 1 << mcs
    eoi = clear + 1
    w = _BitWriter()

    def fresh():
        return {(i,): i for i in range(clear)}, eoi + 1, mcs + 1

    table, nxt, size = fresh()
    w.write(clear, size)
    prefix = ()
    for k in data:
        pk = prefix + (k,)
        if pk in table:
            prefix = pk
            continue
        w.write(table[prefix], size)
        table[pk] = nxt
        nxt += 1
        if nxt == 4096:
            w.write(clear, size)
            table, nxt, size = fresh()
        elif nxt == (1 << size) + 1 and size < 12:
            size += 1
        prefix = (k,)
    if prefix:
        w.write(table[prefix], size)
    w.write(eoi, size)
    return w.finish()


def lzw_decode(data, mcs, expected):
    clear = 1 << mcs
    eoi = clear + 1
    table, nd, size = None, None, None

    def fresh():
        return [bytes([i]) for i in range(clear)] + [b"", b""], eoi + 1, mcs + 1

    table, nd, size = fresh()
    bitpos = 0
    out = bytearray()
    old = None
    while bitpos + size <= len(data) * 8:
        code = 0
        for i in range(size):
            code |= ((data[bitpos >> 3] >> (bitpos & 7)) & 1) << i
            bitpos += 1
        if code == clear:
            table, nd, size = fresh()
            old = None
            continue
        if code == eoi:
            break
        if old is None:
            if code >= nd:
                raise ValueError("bad first code")
            out += table[code]
            old = code
            continue
        if code < nd:
            entry = table[code]
        elif code == nd:
            entry = table[old] + table[old][:1]
        else:
            raise ValueError("bad lzw code")
        out += entry
        table.append(table[old] + entry[:1])
        nd += 1
        if nd == (1 << size) and size < 12:
            size += 1
        old = code
    if len(out) != expected:
        raise ValueError(f"lzw decoded {len(out)} bytes, expected {expected}")
    return bytes(out)


def write_gif(path, w, h, frames, palette):
    """palette: RGBA list, index 0 = transparent. Frames need delay_cs."""
    assert len(palette) <= 16
    pal = list(palette) + [(0, 0, 0, 0)] * (16 - len(palette))
    cmap = {}
    for i, c in enumerate(palette):
        if c[3]:
            cmap[c[:3]] = i
    out = [b"GIF89a", struct.pack("<HHBBB", w, h, 0xF3, 0, 0)]
    out.append(bytes(v for c in pal[:16] for v in c[:3]))
    out.append(b"\x21\xFF\x0BNETSCAPE2.0\x03\x01\x00\x00\x00")  # loop forever
    for f in frames:
        packed = (DISPOSAL[f["dispose"]] << 2) | 1  # transparent index in use
        out.append(bytes([0x21, 0xF9, 0x04, packed])
                   + struct.pack("<H", f["delay_cs"]) + b"\x00\x00")
        out.append(struct.pack("<BHHHHB", 0x2C, f["x"], f["y"], f["w"], f["h"], 0))
        img = f["img"]
        idx = bytearray(f["w"] * f["h"])
        for p in range(f["w"] * f["h"]):
            s = p * 4
            idx[p] = 0 if img[s + 3] == 0 else cmap[(img[s], img[s + 1], img[s + 2])]
        out.append(bytes([4]))
        data = lzw_encode(bytes(idx), 4)
        for p in range(0, len(data), 255):
            out.append(bytes([min(255, len(data) - p)]) + data[p:p + 255])
        out.append(b"\x00")
    out.append(b"\x3B")
    path.write_bytes(b"".join(out))
    return sum(len(c) for c in out)


def read_gif(data):
    assert data[:6] in (b"GIF89a", b"GIF87a"), "not a gif"
    w, h, packed, bg, _aspect = struct.unpack("<HHBBB", data[6:13])
    pos = 13
    gct = None
    if packed & 0x80:
        n = 3 * (1 << ((packed & 7) + 1))
        gct = data[pos:pos + n]
        pos += n
    frames = []
    gce = None
    loop_count = None
    while pos < len(data):
        b = data[pos]
        pos += 1
        if b == 0x3B:
            break
        if b == 0x21:
            label = data[pos]
            pos += 1
            if label == 0xF9:
                blen = data[pos]
                pos += 1
                gp, delay, tidx = struct.unpack("<BHB", data[pos:pos + blen])
                pos += blen + 1  # skip block terminator
                gce = dict(disposal=(gp >> 2) & 7, delay_cs=delay,
                           transparent=tidx if gp & 1 else None)
            else:
                blen = data[pos]
                pos += 1
                app = data[pos:pos + blen]
                pos += blen
                subs = bytearray()
                while True:
                    blen = data[pos]
                    pos += 1
                    if blen == 0:
                        break
                    subs += data[pos:pos + blen]
                    pos += blen
                if app == b"NETSCAPE2.0" and len(subs) >= 3 and subs[0] == 1:
                    loop_count = subs[1] | (subs[2] << 8)
        elif b == 0x2C:
            x, y, fw, fh, ip = struct.unpack("<HHHHB", data[pos:pos + 9])
            pos += 9
            lct = None
            if ip & 0x80:
                n = 3 * (1 << ((ip & 7) + 1))
                lct = data[pos:pos + n]
                pos += n
            assert not (ip & 0x40), "interlaced gif unsupported"
            mcs = data[pos]
            pos += 1
            comp = bytearray()
            while True:
                blen = data[pos]
                pos += 1
                if blen == 0:
                    break
                comp += data[pos:pos + blen]
                pos += blen
            indices = lzw_decode(bytes(comp), mcs, fw * fh)
            frames.append(dict(x=x, y=y, w=fw, h=fh, indices=indices,
                               lct=lct, gce=gce or dict(disposal=0, delay_cs=0,
                                                        transparent=None)))
            gce = None
        else:
            raise ValueError(f"unknown gif block {b:#x}")
    return dict(width=w, height=h, gct=gct, frames=frames, loop_count=loop_count)


def composite(meta, loops=1):
    """Decode-side compositor; returns [(displayed_canvas, info)] per output frame."""
    w, h = meta["width"], meta["height"]
    canvas = bytearray(w * h * 4)
    out = []
    for _ in range(loops):
        for f in meta["frames"]:
            gce = f["gce"]
            disposal = gce["disposal"]
            tidx = gce["transparent"]
            pal = f["lct"] or meta["gct"]
            x, y, fw, fh = f["x"], f["y"], f["w"], f["h"]
            saved = None
            if disposal == 3:
                saved = bytearray()
                for row in range(fh):
                    s = ((y + row) * w + x) * 4
                    saved += canvas[s:s + fw * 4]
            for row in range(fh):
                for col in range(fw):
                    idx = f["indices"][row * fw + col]
                    if tidx is not None and idx == tidx:
                        continue
                    i = ((y + row) * w + (x + col)) * 4
                    canvas[i:i + 4] = pal[idx * 3:idx * 3 + 3] + b"\xff"
            info = dict(dispose=DISPOSAL_NAME.get(disposal, str(disposal)),
                        delay=Fraction(gce["delay_cs"], 100), rect=(x, y, fw, fh))
            out.append((bytes(canvas), info))
            if disposal == 2:  # restore to background (unused by our writer)
                fill = b"\x00" * 4 if tidx is not None else b"\x00" * 3 + b"\xff"
                for row in range(fh):
                    s = ((y + row) * w + x) * 4
                    canvas[s:s + fw * 4] = fill * fw
            elif disposal == 3:
                for row in range(fh):
                    s = ((y + row) * w + x) * 4
                    canvas[s:s + fw * 4] = saved[row * fw * 4:(row + 1) * fw * 4]
    return out
