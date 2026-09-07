#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""箱入り娘 レベル生成器（Python3 標準ライブラリのみ）

4列×5行の箱に「娘 2×2」「縦長 1×2」「横長 2×1」「小僧 1×1」を詰め、BFS で最短手数
（1手＝1駒を一直線に1マス以上。角を曲がるのは2手）を求め、条件を満たすものだけを
難度4段階に振り分けて出力する。

  解ける／最短5手以上／盤面文字列の重複なし／既採用盤との駒配置 Jaccard <= 0.5
  段階は実測の最短手数からのみ決める（手で貼らない）。各10本・計40本。

  古典配置（横刀立馬など、伝承の並び）は名前つきで必ず候補に入れる。
  並びが不確かな配置は入れない（docs/decision_log.md 参照）。

出力: JSON 配列 [{"board": "20文字", "min": n, "tier": "入門", "name": "横刀立馬"}, ...]
盤面記法: 20文字（row-major）。o=空 / A=娘（2×2）/ B〜=他の駒（同じ文字の範囲が長方形）

使い方:
  python3 tools/gen_levels.py --seed 20260907 > tools/levels.json
  python3 tools/gen_levels.py --seed 20260907 --embed index.html
"""

import argparse
import json
import random
import sys
import time
from collections import deque

W = 4            # 盤の幅
H = 5            # 盤の高さ
N = W * H
GOAL = (1, 3)    # 娘の左上がここに来たらクリア（下辺中央の出口に接する）
LETTERS = "BCDEFGHIJKLMNOPQRSTUVWXYZ"

# 駒の種類（出力順もこの順）: 娘 / 縦長 / 横長 / 小僧
GIRL = (2, 2)
VERT = (1, 2)
HORZ = (2, 1)
SMALL = (1, 1)

TIERS = [
    ["入門", 5, 15],
    ["初級", 16, 35],
    ["中級", 36, 70],
    ["上級", 71, 10 ** 9],
]
PER_TIER = 10
MIN_MOVES = 5
MAX_J = 0.5      # 既採用盤との駒配置 Jaccard の上限


# ------------------------------------------------------------ 古典配置
# 図は上から5行・各4文字。A=娘 / V=縦長 / H=横長 / S=小僧 / o=空
# 出典が割れる配置・並びが不確かな配置は入れない（推測で足さない）
CLASSICS = [
    # 横刀立馬（立馬横刀）: 最も有名な初期配置
    #   張飛 曹操 曹操 趙雲 / 張飛 曹操 曹操 趙雲 / 馬超 関羽 関羽 黄忠
    #   馬超 兵   兵   黄忠 / 兵   空   空   兵
    ("横刀立馬", [
        "VAAV",
        "VAAV",
        "VHHV",
        "VSSV",
        "SooS",
    ]),
]


# ------------------------------------------------------------ 盤面の表現
# 駒 = (x, y, w, h)。状態 = 各駒の (x, y) のタプル（駒の順序は固定）

def cells_of(x, y, w, h):
    return [(y + j) * W + (x + i) for j in range(h) for i in range(w)]


def occupancy(pieces, state):
    g = [-1] * N
    for i, (w, h) in enumerate(pieces):
        x, y = state[i]
        for c in cells_of(x, y, w, h):
            g[c] = i
    return g


def groups_of(pieces):
    """同じ大きさの駒は区別しない（入れ替え可能）。種類ごとの連続した添字範囲を返す。
    build_pieces / from_diagram / parse_board が種類ごとにまとめて並べる前提。"""
    out, i = [], 0
    while i < len(pieces):
        j = i
        while j < len(pieces) and pieces[j] == pieces[i]:
            j += 1
        out.append((i, j))
        i = j
    return out


def canon(pieces, state):
    """種類ごとに座標を並べた正規形（同種の駒を区別しない）"""
    st = list(state)
    for a, b in groups_of(pieces):
        st[a:b] = sorted(st[a:b])
    return tuple(st)


def slides(pieces, state, g, i):
    """駒 i を一直線に滑らせて到達できる位置を列挙（1手ぶん）"""
    w, h = pieces[i]
    x0, y0 = state[i]
    out = []
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        x, y = x0, y0
        while True:
            nx, ny = x + dx, y + dy
            if nx < 0 or ny < 0 or nx + w > W or ny + h > H:
                break
            # 進行方向の先頭の辺だけ調べる
            if dx:
                edge = [((ny + j) * W + (nx + (w - 1 if dx > 0 else 0))) for j in range(h)]
            else:
                edge = [((ny + (h - 1 if dy > 0 else 0)) * W + (nx + j)) for j in range(w)]
            if any(g[c] != -1 and g[c] != i for c in edge):
                break
            x, y = nx, ny
            out.append((x, y))
    return out


def solve(pieces, start, node_limit=2_000_000):
    """最短手数を返す。解けなければ -1。1手＝1駒を一直線に1マス以上"""
    if start[0] == GOAL:
        return 0
    n = len(pieces)
    grp = groups_of(pieces)
    gof = [0] * n                      # 添字 -> その駒が属する種類グループ
    for k, (a, b) in enumerate(grp):
        for i in range(a, b):
            gof[i] = k
    start = canon(pieces, start)
    seen = {start}
    q = deque([(start, 0)])
    nodes = 0
    while q:
        state, d = q.popleft()
        nodes += 1
        if nodes > node_limit:
            return -1
        g = occupancy(pieces, state)
        nd = d + 1
        for i in range(n):
            a, b = grp[gof[i]]
            for pos in slides(pieces, state, g, i):
                if i == 0 and pos == GOAL:
                    return nd
                ns = list(state)
                ns[i] = pos
                ns[a:b] = sorted(ns[a:b])
                ns = tuple(ns)
                if ns not in seen:
                    seen.add(ns)
                    q.append((ns, nd))
    return -1


# ------------------------------------------------------------ 文字列変換
def to_board(pieces, state):
    """左上から row-major に A,B,C… を振って20文字にする"""
    order = sorted(range(len(pieces)), key=lambda i: (state[i][1] * W + state[i][0]))
    order.remove(0)
    order = [0] + order
    grid = ["o"] * N
    for k, i in enumerate(order):
        ch = "A" if i == 0 else LETTERS[k - 1]
        w, h = pieces[i]
        x, y = state[i]
        for c in cells_of(x, y, w, h):
            grid[c] = ch
    return "".join(grid)


def from_diagram(rows):
    """5行×4文字の図 -> (pieces, state)。A=娘 V=縦長 H=横長 S=小僧 o=空"""
    grid = "".join(rows)
    assert len(grid) == N, grid
    used = [False] * N
    pieces, state = [], []
    girl = None
    for c in range(N):
        if used[c] or grid[c] == "o":
            continue
        x, y = c % W, c // W
        ch = grid[c]
        if ch == "A":
            sz = GIRL
        elif ch == "V":
            sz = VERT
        elif ch == "H":
            sz = HORZ
        else:
            sz = SMALL
        w, h = sz
        cs = cells_of(x, y, w, h)
        for cc in cs:
            assert not used[cc] and grid[cc] == ch, rows
            used[cc] = True
        if ch == "A":
            assert girl is None
            girl = (sz, (x, y))
        else:
            pieces.append(sz)
            state.append((x, y))
    assert girl is not None
    assert all(used[c] or grid[c] == "o" for c in range(N))
    order = sorted(range(len(pieces)), key=lambda i: (-pieces[i][0] * pieces[i][1],
                                                      pieces[i], state[i]))
    return ([girl[0]] + [pieces[i] for i in order],
            tuple([girl[1]] + [state[i] for i in order]))


def parse_board(board):
    """20文字の盤面記法 -> (pieces, state)。娘（A）を先頭に置く"""
    seen = {}
    for c, ch in enumerate(board):
        if ch == "o":
            continue
        seen.setdefault(ch, []).append(c)
    pieces, state, girl = [], [], None
    for ch, cs in sorted(seen.items(), key=lambda kv: kv[1][0]):
        xs = [c % W for c in cs]
        ys = [c // W for c in cs]
        x, y = min(xs), min(ys)
        w, h = max(xs) - x + 1, max(ys) - y + 1
        assert w * h == len(cs), board
        if ch == "A":
            girl = ((w, h), (x, y))
        else:
            pieces.append((w, h))
            state.append((x, y))
    order = sorted(range(len(pieces)), key=lambda i: (-pieces[i][0] * pieces[i][1],
                                                      pieces[i], state[i]))
    return ([girl[0]] + [pieces[i] for i in order],
            tuple([girl[1]] + [state[i] for i in order]))


# ------------------------------------------------------------ 駒組と配置
def piece_sets():
    """駒の組み合わせ（娘は必ず1つ）。古典の 縦4・横1・小僧4・空2 を基本に少し崩す"""
    out = []
    for nv in range(2, 6):
        for nh in range(0, 3):
            for ns in range(0, 7):
                empty = N - 4 - 2 * nv - 2 * nh - ns
                if empty < 2 or empty > 4:
                    continue
                out.append((nv, nh, ns))
    return out


CLASSIC_SET = (4, 1, 4)


def build_pieces(nv, nh, ns):
    return [GIRL] + [VERT] * nv + [HORZ] * nh + [SMALL] * ns


def random_fill(rng, pieces, tries=400):
    """左上から未使用マスを埋めていく（そのマスがどの駒の左上か／空きかを試す）"""
    remain = {}
    for sz in pieces[1:]:
        remain[sz] = remain.get(sz, 0) + 1
    empty = N - sum(w * h for w, h in pieces)
    grid = [None] * N
    placed = [None] * len(pieces)   # index -> (x,y)
    # 娘は index 0 固定。残りは種類ごとに順番に割り当てる
    slots = {}
    idx = 1
    for sz in pieces[1:]:
        slots.setdefault(sz, []).append(idx)
        idx += 1
    slot_ptr = {sz: 0 for sz in slots}
    girl_done = [False]
    steps = [0]

    def rec():
        steps[0] += 1
        if steps[0] > tries * 40:
            return False
        c = next((i for i in range(N) if grid[i] is None), None)
        if c is None:
            return girl_done[0] and empty_left[0] == 0 and all(v == 0 for v in remain.values())
        x, y = c % W, c // W
        opts = []
        if not girl_done[0] and x + 2 <= W and y + 2 <= H:
            opts.append(GIRL)
        for sz, cnt in remain.items():
            if cnt > 0 and x + sz[0] <= W and y + sz[1] <= H:
                opts.append(sz)
        opts.append(None)   # 空きにする
        rng.shuffle(opts)
        for sz in opts:
            if sz is None:
                if empty_left[0] <= 0:
                    continue
                empty_left[0] -= 1
                grid[c] = "o"
                if rec():
                    return True
                grid[c] = None
                empty_left[0] += 1
                continue
            cs = cells_of(x, y, sz[0], sz[1])
            if any(grid[i] is not None for i in cs):
                continue
            if sz == GIRL and not girl_done[0]:
                i = 0
                girl_done[0] = True
            else:
                if remain.get(sz, 0) <= 0:
                    continue
                i = slots[sz][slot_ptr[sz]]
                slot_ptr[sz] += 1
                remain[sz] -= 1
            for cc in cs:
                grid[cc] = i
            placed[i] = (x, y)
            if rec():
                return True
            for cc in cs:
                grid[cc] = None
            placed[i] = None
            if i == 0:
                girl_done[0] = False
            else:
                slot_ptr[sz] -= 1
                remain[sz] += 1
        return False

    empty_left = [empty]
    if not rec():
        return None
    return tuple(placed)


# ------------------------------------------------------------ 選抜
def tier_of(m):
    for name, lo, hi in TIERS:
        if lo <= m <= hi:
            return name
    return None


def shape_set(pieces, state):
    return frozenset((state[i][0], state[i][1], pieces[i][0], pieces[i][1])
                     for i in range(len(pieces)))


def jaccard(a, b):
    u = len(a | b)
    return (len(a & b) / u) if u else 0.0


def far_enough(shape, chosen):
    return all(jaccard(shape, c["shape"]) <= MAX_J for c in chosen)


def select_tier(rng, cands, k, chosen):
    """段階の中で最短手数を端から端まで散らして k 本選ぶ（Jaccard <= 0.5）"""
    by_min = {}
    for c in cands:
        by_min.setdefault(c["min"], []).append(c)
    for v in by_min.values():
        rng.shuffle(v)
    out = []

    def take(bucket):
        for idx, c in enumerate(bucket):
            if far_enough(c["shape"], chosen + out):
                return bucket.pop(idx)
        del bucket[:]        # 条件は厳しくなる一方なので、この手数は打ち切り
        return None

    # 古典配置は必ず入れる
    for key in sorted(by_min):
        for idx in range(len(by_min[key]) - 1, -1, -1):
            c = by_min[key][idx]
            if c.get("name") and far_enough(c["shape"], chosen + out):
                out.append(by_min[key].pop(idx))

    while len(out) < k:
        keys = [key for key in sorted(by_min) if by_min[key]]
        if not keys:
            break
        need = k - len(out)
        # 残りの手数を端から端まで等間隔にねらう
        targets = []
        for j in range(need):
            targets.append(keys[round(j * (len(keys) - 1) / max(1, need - 1))])
        got = 0
        for t in targets:
            if len(out) >= k:
                break
            if not by_min.get(t):
                continue
            c = take(by_min[t])
            if c:
                out.append(c)
                got += 1
        if got == 0:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20260907)
    ap.add_argument("--rounds", type=int, default=4000, help="ランダム配置の試行回数")
    ap.add_argument("--select-attempts", type=int, default=30)
    ap.add_argument("--pool-cap", type=int, default=400)
    ap.add_argument("--embed", metavar="HTML",
                    help="この HTML の LEVELS-BEGIN / LEVELS-END の間へ直接埋め込む")
    ap.add_argument("--tiers", help='段階の閾値を上書き（例 "5-20,21-45,46-80,81-"）')
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if args.tiers:
        parts = args.tiers.split(",")
        assert len(parts) == 4
        for i, p in enumerate(parts):
            lo, _, hi = p.partition("-")
            TIERS[i][1] = int(lo)
            TIERS[i][2] = int(hi) if hi else 10 ** 9

    t0 = time.time()
    rng = random.Random(args.seed)
    log = (lambda *a: None) if args.quiet else (lambda *a: print(*a, file=sys.stderr))

    seen_boards = set()
    pool = {}       # tier -> [cand]
    all_mins = []

    def add(pieces, state, name=None):
        board = to_board(pieces, state)
        if board in seen_boards:
            return None
        seen_boards.add(board)
        if state[0] == GOAL:
            return None
        m = solve(pieces, state)
        if m < MIN_MOVES:
            return None
        all_mins.append(m)
        c = {"board": board, "min": m, "shape": shape_set(pieces, state)}
        if name:
            c["name"] = name
        return c

    log("[1/3] 古典配置 ...")
    classics = []
    for name, rows in CLASSICS:
        pieces, state = from_diagram(rows)
        c = add(pieces, state, name)
        if c is None:
            log("   %s: 除外（重複または解けない）" % name)
            continue
        classics.append(c)
        log("   %s  最短 %d手  %s" % (name, c["min"], c["board"]))

    log("[2/3] ランダム配置 ...")
    sets = piece_sets()
    weights = [4 if s == CLASSIC_SET else 1 for s in sets]
    for r in range(args.rounds):
        nv, nh, ns = rng.choices(sets, weights=weights)[0]
        pieces = build_pieces(nv, nh, ns)
        state = random_fill(rng, pieces)
        if state is None:
            continue
        c = add(pieces, state)
        if c is None:
            continue
        t = tier_of(c["min"])
        if t:
            pool.setdefault(t, []).append(c)
        if not args.quiet and r % 500 == 499:
            log("   %4d/%d  候補 %s  経過 %.0fs"
                % (r + 1, args.rounds,
                   {n: len(pool.get(n, [])) for n, _, _ in TIERS}, time.time() - t0))

    # 手数の分布（閾値を決め直す材料）
    if all_mins:
        s = sorted(all_mins)
        q = lambda p: s[min(len(s) - 1, int(len(s) * p))]
        log("実測の最短手数: n=%d 最小%d 中央%d 最大%d / 四分位 %d %d %d"
            % (len(s), s[0], q(.5), s[-1], q(.25), q(.5), q(.75)))

    log("[3/3] 選抜（Jaccard <= %.2f）..." % MAX_J)
    for c in classics:
        t = tier_of(c["min"])
        if t:
            pool.setdefault(t, []).insert(0, c)

    order = ["上級", "中級", "初級", "入門"]
    pools = {}
    for name in order:
        cands = pool.get(name, [])
        named = [c for c in cands if c.get("name")]
        rest = [c for c in cands if not c.get("name")]
        if len(rest) > args.pool_cap:
            rest = rng.sample(rest, args.pool_cap)
        pools[name] = named + rest

    best = None
    for _ in range(args.select_attempts):
        chosen, per = [], {}
        for name in order:
            got = select_tier(rng, pools[name], PER_TIER, chosen)
            per[name] = got
            chosen += got
        nnamed = sum(1 for c in chosen if c.get("name"))
        spread = sum(len({c["min"] for c in per[n]}) for n in order)
        score = (len(chosen), nnamed, spread)
        if best is None or score > best[0]:
            best = (score, chosen, per)
    chosen, per = best[1], best[2]

    chosen.sort(key=lambda c: (c["min"], c["board"]))
    out = []
    for c in chosen:
        o = {"board": c["board"], "min": c["min"], "tier": tier_of(c["min"])}
        if c.get("name"):
            o["name"] = c["name"]
        out.append(o)

    for name, _, _ in TIERS:
        v = [o["min"] for o in out if o["tier"] == name]
        log("分布 %s: %d本 %s" % (name, len(v), ("%d..%d" % (min(v), max(v))) if v else "-"))
    shapes = [c["shape"] for c in chosen]
    mj = max((jaccard(shapes[i], shapes[j])
              for i in range(len(shapes)) for j in range(i + 1, len(shapes))), default=0.0)
    log("相互Jaccard最大 %.2f / 所要 %.0fs" % (mj, time.time() - t0))

    def enc(o):
        s = '  {"board":"%s","min":%d,"tier":"%s"' % (o["board"], o["min"], o["tier"])
        if o.get("name"):
            s += ',"name":"%s"' % o["name"]
        return s + "}"

    body = "var LEVELS = [\n" + ",\n".join(enc(o) for o in out) + "\n];\n"

    if args.embed:
        with open(args.embed, encoding="utf-8") as f:
            html = f.read()
        b = html.index("/* LEVELS-BEGIN")
        b = html.index("\n", b) + 1
        e = html.index("/* LEVELS-END")
        html = html[:b] + body + html[e:]
        with open(args.embed, "w", encoding="utf-8") as f:
            f.write(html)
        log("埋め込み完了:", args.embed)

    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
