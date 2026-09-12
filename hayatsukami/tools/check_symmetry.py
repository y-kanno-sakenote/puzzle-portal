#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""はやつかみ 品の 180 度対称検査（Python3 標準ライブラリのみ）

    python3 check_symmetry.py                 # index.html の PATH を検査
    python3 check_symmetry.py --res 512       # 解像度を変える
    python3 check_symmetry.py --ascii         # 形をアスキーで見る

なぜ要るか
  二人が向かい合って遊ぶので、盤の中央の品は**上の人には上下逆に見える**。
  品が 180 度回して自分自身に重なる形でないと、見つける速さに差が出て不公平になる。
  そこで各形の SVG パスを実際に塗りつぶし、180 度回した像と重ねて一致率を数値で確かめる。

やり方
  1. index.html の PATH = { ... } から各形の d（と fill-rule）を読む
  2. d を折れ線に潰して N×N のマス目に塗る（塗りは even-odd。画素の中心で判定する）
  3. 180 度回転は (x, y) -> (100-x, 100-y)。画素の中心 (i+0.5)/N は (N-1-i)+0.5 の中心へ
     ちょうど移るので、真に対称な形なら**丸め誤差抜きで 100%** 一致する
  4. 一致率（同じ塗り/全画素）と IoU（重なり/合併）を出す

判断基準
  IoU >= 0.9990 を合格とする。解像度 512 の一辺 512 画素に対し 0.1% は
  輪郭のギザギザ1画素ぶんにも満たない差で、目では差が分からない水準。
  今の5つは作図からして対称なので実測は 1.000000（完全一致）になるはず。
"""

import argparse
import math
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, "index.html")

NUM = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")
CMD = re.compile(r"[MmLlHhVvCcQqAaZz]")


# ---------------------------------------------------------------- パスを折れ線へ

def _arc(x0, y0, rx, ry, phi, large, sweep, x1, y1, seg=180):
    """SVG の円弧（終点指定）を中心指定に直して折れ線にする（W3C 実装ノートの通り）"""
    if rx == 0 or ry == 0 or (x0 == x1 and y0 == y1):
        return [(x1, y1)]
    rx, ry = abs(rx), abs(ry)
    cp, sp = math.cos(phi), math.sin(phi)
    dx2, dy2 = (x0 - x1) / 2.0, (y0 - y1) / 2.0
    x1p, y1p = cp * dx2 + sp * dy2, -sp * dx2 + cp * dy2
    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1:                               # 半径が足りないときは spec 通り拡大する
        s = math.sqrt(lam)
        rx, ry = rx * s, ry * s
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    co = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large == sweep:
        co = -co
    cxp, cyp = co * rx * y1p / ry, -co * ry * x1p / rx
    cx = cp * cxp - sp * cyp + (x0 + x1) / 2.0
    cy = sp * cxp + cp * cyp + (y0 + y1) / 2.0

    def ang(ux, uy, vx, vy):
        d = math.sqrt((ux * ux + uy * uy) * (vx * vx + vy * vy))
        if d == 0:
            return 0.0
        c = max(-1.0, min(1.0, (ux * vx + uy * vy) / d))
        a = math.acos(c)
        return -a if ux * vy - uy * vx < 0 else a

    th0 = ang(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dth = ang((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and dth > 0:
        dth -= 2 * math.pi
    elif sweep and dth < 0:
        dth += 2 * math.pi

    pts = []
    n = max(8, int(seg * abs(dth) / (2 * math.pi)) + 1)
    for k in range(1, n + 1):
        t = th0 + dth * k / n
        ex, ey = rx * math.cos(t), ry * math.sin(t)
        pts.append((cp * ex - sp * ey + cx, sp * ex + cp * ey + cy))
    return pts


def _bez(p0, p1, p2, p3, n=48):
    out = []
    for k in range(1, n + 1):
        t = k / n
        u = 1 - t
        out.append((u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0],
                    u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1]))
    return out


def flatten(d):
    """d 属性を閉じた折れ線（サブパスの並び）に潰す。M/L/H/V/C/Q/A/Z（大小文字）に対応"""
    toks, i = [], 0
    while i < len(d):
        ch = d[i]
        if CMD.match(ch):
            toks.append(ch)
            i += 1
            continue
        m = NUM.match(d, i)
        if m and m.group():
            toks.append(float(m.group()))
            i = m.end()
        else:
            i += 1

    subs, cur = [], []
    x = y = sx = sy = 0.0
    cmd = None
    k = 0

    def take(n):
        nonlocal k
        vals = toks[k:k + n]
        if len(vals) != n or any(isinstance(v, str) for v in vals):
            raise ValueError("引数が足りないパス: %r" % (d[:40],))
        k += n
        return vals

    while k < len(toks):
        if isinstance(toks[k], str):
            cmd = toks[k]
            k += 1
            if cmd in "Zz":
                if len(cur) > 2:
                    subs.append(cur)
                cur = []
                x, y = sx, sy
                continue
        if cmd is None:
            raise ValueError("コマンドの無いパス")
        rel = cmd.islower()
        c = cmd.upper()
        if c == "M":
            ax, ay = take(2)
            x, y = (x + ax, y + ay) if rel else (ax, ay)
            if len(cur) > 2:
                subs.append(cur)
            cur = [(x, y)]
            sx, sy = x, y
            cmd = "l" if rel else "L"          # 続く数値は暗黙の L
        elif c == "L":
            ax, ay = take(2)
            x, y = (x + ax, y + ay) if rel else (ax, ay)
            cur.append((x, y))
        elif c == "H":
            (ax,) = take(1)
            x = x + ax if rel else ax
            cur.append((x, y))
        elif c == "V":
            (ay,) = take(1)
            y = y + ay if rel else ay
            cur.append((x, y))
        elif c == "C":
            a = take(6)
            p1 = (x + a[0], y + a[1]) if rel else (a[0], a[1])
            p2 = (x + a[2], y + a[3]) if rel else (a[2], a[3])
            p3 = (x + a[4], y + a[5]) if rel else (a[4], a[5])
            cur.extend(_bez((x, y), p1, p2, p3))
            x, y = p3
        elif c == "Q":
            a = take(4)
            q = (x + a[0], y + a[1]) if rel else (a[0], a[1])
            p3 = (x + a[2], y + a[3]) if rel else (a[2], a[3])
            p1 = (x + 2.0 / 3 * (q[0] - x), y + 2.0 / 3 * (q[1] - y))
            p2 = (p3[0] + 2.0 / 3 * (q[0] - p3[0]), p3[1] + 2.0 / 3 * (q[1] - p3[1]))
            cur.extend(_bez((x, y), p1, p2, p3))
            x, y = p3
        elif c == "A":
            a = take(7)
            nx, ny = (x + a[5], y + a[6]) if rel else (a[5], a[6])
            cur.extend(_arc(x, y, a[0], a[1], math.radians(a[2]), int(a[3]), int(a[4]), nx, ny))
            x, y = nx, ny
        else:
            raise ValueError("未対応のコマンド: %s" % cmd)
    if len(cur) > 2:
        subs.append(cur)
    return subs


# ---------------------------------------------------------------- 塗る・比べる

def raster(subs, n, box=100.0, rule="nonzero"):
    """塗る。1画素 = 中心1点で判定。fill-rule は SVG と同じ evenodd / nonzero"""
    img = bytearray(n * n)
    edges = []
    for sp in subs:
        pts = sp + [sp[0]]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if y0 != y1:
                edges.append((x0, y0, x1, y1, 1 if y1 > y0 else -1))
    for row in range(n):
        yc = (row + 0.5) * box / n
        hits = []
        for x0, y0, x1, y1, w in edges:
            if (y0 <= yc < y1) or (y1 <= yc < y0):
                hits.append((x0 + (yc - y0) * (x1 - x0) / (y1 - y0), w))
        if not hits:
            continue
        hits.sort()
        spans = []
        if rule == "evenodd":
            xs = [h[0] for h in hits]
            spans = list(zip(xs[0::2], xs[1::2]))
        else:
            wind = 0
            start = None
            for xv, w in hits:
                prev = wind
                wind += w
                if prev == 0 and wind != 0:
                    start = xv
                elif prev != 0 and wind == 0 and start is not None:
                    spans.append((start, xv))
                    start = None
        base = row * n
        for a, b in spans:
            ia = max(0, int(math.ceil(a * n / box - 0.5)))
            ib = min(n - 1, int(math.floor(b * n / box - 0.5)))
            for col in range(ia, ib + 1):
                img[base + col] = 1
    return img


def rot180(img, n):
    out = bytearray(n * n)
    for i in range(n * n):
        out[n * n - 1 - i] = img[i]
    return out


def score(img, n):
    r = rot180(img, n)
    same = inter = union = 0
    for a, b in zip(img, r):
        if a == b:
            same += 1
        if a and b:
            inter += 1
        if a or b:
            union += 1
    total = n * n
    return {
        "一致率": same / total,
        "IoU": (inter / union) if union else 1.0,
        "面積": sum(img) / total,
        "ずれ画素": total - same,
    }


def ascii_art(img, n, w=34):
    step = n / w
    lines = []
    for r in range(w // 2):
        line = ""
        for c in range(w):
            yy, xx = int((r + 0.5) * step * 2), int((c + 0.5) * step)
            yy = min(n - 1, yy)
            line += "#" if img[yy * n + xx] else "."
        lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------- index.html から拾う

def read_paths(path=INDEX):
    src = open(path, encoding="utf-8").read()
    m = re.search(r"var PATH = \{(.*?)\n  \};", src, re.S)
    if not m:
        raise SystemExit("index.html の PATH が見つからない")
    out = []
    for line in m.group(1).splitlines():
        mm = re.search(r'"([^"]+)"\s*:\s*\{\s*d:\s*"([^"]+)"(?:\s*,\s*rule:\s*"([^"]+)")?', line)
        if mm:
            out.append((mm.group(1), mm.group(2), mm.group(3) or "nonzero"))
    if not out:
        raise SystemExit("PATH の中身が読めない")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--res", type=int, default=512, help="検査の解像度（1辺の画素数）")
    ap.add_argument("--ascii", action="store_true", help="形をアスキーで表示する")
    ap.add_argument("--min-iou", type=float, default=0.9990, help="合格とする IoU")
    a = ap.parse_args()

    n = a.res
    ok = True
    print("180 度対称の検査（解像度 %dx%d・合格 IoU >= %.4f）" % (n, n, a.min_iou))
    imgs = []
    for name, d, rule in read_paths():
        img = raster(flatten(d), n, rule=rule)
        imgs.append((name, img))
        s = score(img, n)
        good = s["IoU"] >= a.min_iou
        ok &= good
        print("  [%s] %-6s IoU=%.6f  一致率=%.6f  ずれ %d 画素  面積 %.1f%%"
              % ("PASS" if good else "FAIL", name, s["IoU"], s["一致率"], s["ずれ画素"], s["面積"] * 100))
        if a.ascii:
            print(ascii_art(img, n))
            print()

    # ついでに形どうしの重なり（似すぎていないか）も出す。判断は目でするための目安
    print("形どうしの重なり（IoU が高いほど輪郭が似ている。目安）")
    for i in range(len(imgs)):
        for j in range(i + 1, len(imgs)):
            inter = union = 0
            for p, q in zip(imgs[i][1], imgs[j][1]):
                if p and q:
                    inter += 1
                if p or q:
                    union += 1
            print("  %-6s × %-6s  IoU=%.3f" % (imgs[i][0], imgs[j][0], inter / union if union else 0))

    print("=== 対称性: %s ===" % ("PASS" if ok else "FAIL"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
