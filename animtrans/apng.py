"""APNG writer + an independent APNG reader/compositor (second decode path)."""
import struct
import zlib
from fractions import Fraction

SIG = b"\x89PNG\r\n\x1a\n"
DISPOSE_OP = {"none": 0, "background": 1, "previous": 2}
BLEND_OP = {"source": 0, "over": 1}
DISPOSE_NAME = {v: k for k, v in DISPOSE_OP.items()}
BLEND_NAME = {v: k for k, v in BLEND_OP.items()}


def _chunk(typ, data):
    return (struct.pack(">I", len(data)) + typ + data
            + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF))


def png_encode(w, h, rgba):
    raw = b"".join(b"\x00" + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return SIG + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b"")


def _delay_numden(delay):
    num, den = delay.numerator, delay.denominator
    assert 0 <= num <= 65535 and 1 <= den <= 65535, f"delay {delay} not representable"
    return num, den


def write_apng(path, w, h, frames, num_plays=0):
    out = [SIG, _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)),
           _chunk(b"acTL", struct.pack(">II", len(frames), num_plays))]
    seq = 0
    for i, f in enumerate(frames):
        num, den = _delay_numden(f["delay"])
        out.append(_chunk(b"fcTL", struct.pack(">IIIIIHHBB", seq, f["w"], f["h"],
                                               f["x"], f["y"], num, den,
                                               DISPOSE_OP[f["dispose"]],
                                               BLEND_OP[f["blend"]])))
        seq += 1
        raw = b"".join(b"\x00" + f["img"][r * f["w"] * 4:(r + 1) * f["w"] * 4]
                       for r in range(f["h"]))
        z = zlib.compress(raw, 9)
        if i == 0:
            out.append(_chunk(b"IDAT", z))
        else:
            out.append(_chunk(b"fdAT", struct.pack(">I", seq) + z))
            seq += 1
    out.append(_chunk(b"IEND", b""))
    path.write_bytes(b"".join(out))
    return sum(len(c) for c in out)


def unfilter(raw, w, h, bpp=4):
    stride = w * bpp
    out = bytearray(h * stride)
    prev = bytearray(stride)
    pos = 0
    for y in range(h):
        filt = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + stride])
        pos += stride
        if filt == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 255
        elif filt == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif filt == 3:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + (a + prev[i]) // 2) & 255
        elif filt == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 255
        elif filt != 0:
            raise ValueError(f"unknown png filter {filt}")
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return bytes(out)


def read_apng(data):
    assert data[:8] == SIG, "not a png"
    pos = 8
    ihdr = None
    frames = []
    idat = bytearray()
    num_plays = None
    while pos < len(data):
        ln, typ = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if typ == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif typ == b"acTL":
            _, num_plays = struct.unpack(">II", body)
        elif typ == b"fcTL":
            (seq, fw, fh, fx, fy, dnum, dden, dop, bop) = struct.unpack(">IIIIIHHBB", body)
            frames.append(dict(x=fx, y=fy, w=fw, h=fh,
                               delay=Fraction(dnum, dden or 100),
                               dispose=DISPOSE_NAME[dop], blend=BLEND_NAME[bop],
                               data=bytearray()))
        elif typ == b"IDAT":
            idat += body
        elif typ == b"fdAT":
            frames[-1]["data"] += body[4:]  # skip sequence number
        elif typ == b"IEND":
            break
    w, h = ihdr[0], ihdr[1]
    if not frames:  # plain PNG: single full-canvas frame
        frames.append(dict(x=0, y=0, w=w, h=h, delay=Fraction(0),
                           dispose="none", blend="source", data=idat))
    else:
        frames[0]["data"] = idat
    for f in frames:
        f["img"] = unfilter(zlib.decompress(bytes(f["data"])), f["w"], f["h"])
        del f["data"]
    return dict(width=w, height=h, frames=frames, num_plays=num_plays)


def _over(dst, src):
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


def composite(meta, loops=1):
    """Decode-side compositor; returns [(displayed_canvas, frame)] per output frame."""
    w, h = meta["width"], meta["height"]
    canvas = bytearray(w * h * 4)
    out = []
    for _ in range(loops):
        for f in meta["frames"]:
            x, y, fw, fh = f["x"], f["y"], f["w"], f["h"]
            saved = None
            if f["dispose"] == "previous":
                saved = bytearray()
                for row in range(fh):
                    s = ((y + row) * w + x) * 4
                    saved += canvas[s:s + fw * 4]
            img = f["img"]
            if f["blend"] == "source":
                for row in range(fh):
                    i = ((y + row) * w + x) * 4
                    s = row * fw * 4
                    canvas[i:i + fw * 4] = img[s:s + fw * 4]
            else:
                for row in range(fh):
                    for col in range(fw):
                        i = ((y + row) * w + (x + col)) * 4
                        s = (row * fw + col) * 4
                        canvas[i:i + 4] = _over(canvas[i:i + 4], img[s:s + 4])
            out.append((bytes(canvas), f))
            if f["dispose"] == "background":
                for row in range(fh):
                    s = ((y + row) * w + x) * 4
                    canvas[s:s + fw * 4] = b"\x00" * (fw * 4)
            elif f["dispose"] == "previous":
                for row in range(fh):
                    s = ((y + row) * w + x) * 4
                    canvas[s:s + fw * 4] = saved[row * fw * 4:(row + 1) * fw * 4]
    return out
