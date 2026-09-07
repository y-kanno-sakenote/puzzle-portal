#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""すべりロボ レベル生成器（Python3 標準ライブラリのみ）

12×12 の盤にランダムに壁（外周からの突起・盤内のL字の角）を置き、中央2×2を塊にし、
4体のロボットと的を置いて、BFS で最短手数を求める。条件を満たすものだけを
難度4段階に振り分けて出力する。

  1手＝1体を1方向に「壁か他の体に当たるまで」滑らせる（0マスは手にならない）
  解ける／最短3手以上／盤面重複なし／既採用盤との盤内の壁の一致率 <= 0.7

出力: JSON 配列（最短手数の昇順）
  {"w":12,"walls":"144文字(16進1桁 N=1,E=2,S=4,W=8 の和)",
   "robots":[[x,y,"R"],[x,y,"B"],[x,y,"Y"],[x,y,"G"]],
   "target":[x,y,"R"],"min":5,"tier":"初級","needsOthers":true}

使い方:
  python3 tools/gen_levels.py --seed 20260907 > tools/levels.json
  python3 tools/gen_levels.py --seed 20260907 --budget 300 --embed index.html
"""

import argparse
import json
import random
import sys
import time

W = 12
N = W * W
BLOCK = set()                      # 中央2×2の塊（入れない）
for _bx in (W // 2 - 1, W // 2):
    for _by in (W // 2 - 1, W // 2):
        BLOCK.add(_by * W + _bx)

DIRS = ['N', 'E', 'S', 'W']        # 0,1,2,3
BIT = {'N': 1, 'E': 2, 'S': 4, 'W': 8}
DXY = {'N': (0, -1), 'E': (1, 0), 'S': (0, 1), 'W': (-1, 0)}
OPP = {'N': 'S', 'E': 'W', 'S': 'N', 'W': 'E'}
COLORS = ['R', 'B', 'Y', 'G']

DEPTH_CAP = 12          # 宣言が1〜12なので、13手以上かかる盤は作らない
MIN_MOVES = 3
PER_TIER = 10
MAX_SIM = 0.7           # 既採用盤との「盤内の壁」の一致率の上限
TIERS = [["入門", 3, 4], ["初級", 5, 6], ["中級", 7, 8], ["上級", 9, 10 ** 9]]


# ------------------------------------------------------------ 壁
def put(m, x, y, d):
    """(x,y) の d 側に壁を置く（隣のマスの反対側にも同じ壁を置く）"""
    m[y * W + x] |= BIT[d]
    dx, dy = DXY[d]
    nx, ny = x + dx, y + dy
    if 0 <= nx < W and 0 <= ny < W:
        m[ny * W + nx] |= BIT[OPP[d]]


def base_walls():
    """外周と中央の塊だけの盤（どの盤にも共通なので、似ている判定から外す）"""
    m = [0] * N
    for x in range(W):
        put(m, x, 0, 'N')
        put(m, x, W - 1, 'S')
    for y in range(W):
        put(m, 0, y, 'W')
        put(m, W - 1, y, 'E')
    for c in BLOCK:
        for d in DIRS:
            put(m, c % W, c // W, d)
    return m


BASE = base_walls()


def gen_walls(rng):
    """外周からの突起と、盤内のL字の角を置く。(壁マスク, L字の角のマスの一覧) を返す"""
    m = list(BASE)

    # (a) 外周から1〜2マス伸びる突起を各辺に2本前後
    for edge in range(4):
        for _ in range(rng.choice([1, 2, 2, 2, 3])):
            L = rng.choice([1, 1, 2])
            for _try in range(20):
                p = rng.randrange(2, W - 1)
                cells = []
                ok = True
                for r in range(L):
                    if edge == 0:      # 上辺: 縦の壁（p-1 と p の間）
                        x, y, d = p, r, 'W'
                    elif edge == 1:    # 下辺
                        x, y, d = p, W - 1 - r, 'W'
                    elif edge == 2:    # 左辺: 横の壁（p-1 と p の間）
                        x, y, d = r, p, 'N'
                    else:              # 右辺
                        x, y, d = W - 1 - r, p, 'N'
                    i = y * W + x
                    dx, dy = DXY[d]
                    j = (y + dy) * W + (x + dx)
                    if i in BLOCK or j in BLOCK or (m[i] & BIT[d]):
                        ok = False
                        break
                    cells.append((x, y, d))
                if not ok:
                    continue
                for x, y, d in cells:
                    put(m, x, y, d)
                break

    # (b) 盤内に L字（隣接する2辺）の角を 12〜16個
    want = rng.randint(12, 16)
    corners = []
    tries = 0
    while len(corners) < want and tries < 3000:
        tries += 1
        x = rng.randrange(1, W - 1)
        y = rng.randrange(1, W - 1)
        i = y * W + x
        if i in BLOCK or m[i] != 0:
            continue                                   # 既に壁があるマスは使わない
        if any(max(abs(x - cx), abs(y - cy)) < 2 for cx, cy in corners):
            continue                                   # 角どうしは1マス以上あける
        pair = rng.choice([('N', 'E'), ('E', 'S'), ('S', 'W'), ('W', 'N')])
        ok = True
        for d in pair:
            dx, dy = DXY[d]
            j = (y + dy) * W + (x + dx)
            if j in BLOCK or bin(m[j]).count('1') >= 2:
                ok = False                             # 隣のマスを3方向ふさがない
                break
        if not ok:
            continue
        for d in pair:
            put(m, x, y, d)
        corners.append((x, y))
    return m, corners


def walls_str(m):
    return ''.join('%x' % v for v in m)


def wall_sig(m):
    """外周・塊に由来しない「盤内の壁」だけの辞書（似ている判定に使う）"""
    return {i: (m[i] & ~BASE[i]) for i in range(N) if (m[i] & ~BASE[i])}


def similarity(a, b):
    """盤内の壁がどれだけ同じか。両方とも壁のないマスは数えない（0〜1）"""
    u = set(a) | set(b)
    if not u:
        return 1.0
    same = sum(1 for i in u if a.get(i, 0) == b.get(i, 0))
    return same / len(u)


# ------------------------------------------------------------ 滑り
def build_rays(m):
    """rays[d][cell] = その向きに壁まで進んだときに通るマスの並び"""
    rays = [[()] * N for _ in range(4)]
    for i in range(N):
        x0, y0 = i % W, i // W
        for di, d in enumerate(DIRS):
            dx, dy = DXY[d]
            x, y = x0, y0
            path = []
            while not (m[y * W + x] & BIT[d]):
                x += dx
                y += dy
                path.append(y * W + x)
            rays[di][i] = tuple(path)
    return rays


def slide(rays, occ, pos, d):
    """壁か他の体に当たるまで滑った先。1マスも動けなければ None"""
    last = pos
    for c in rays[d][pos]:
        if c in occ:
            break
        last = c
    return None if last == pos else last


# ------------------------------------------------------------ 探索
def solve_solo(rays, t, others, goal):
    """的の色の体だけを動かして解けるか（他の体は壁として固定）。解けなければ -1"""
    if t == goal:
        return 0
    occ = set(others)
    seen = {t}
    frontier = [t]
    depth = 0
    while frontier and depth < DEPTH_CAP:
        depth += 1
        nxt = []
        for p in frontier:
            for d in range(4):
                q = slide(rays, occ, p, d)
                if q is None:
                    continue
                if q == goal:
                    return depth
                if q not in seen:
                    seen.add(q)
                    nxt.append(q)
        frontier = nxt
    return -1


def solve(rays, t, others, goal, node_cap):
    """最短手数。状態＝4体の位置（的の色の体は区別、他3体は順不同）
       戻り値: (手数, 状態) 状態は 'ok' / 'cap'（打ち切り）/ 'no'（DEPTH_CAP 内に解なし）"""
    if t == goal:
        return 0, 'ok'
    start = (t,) + tuple(sorted(others))
    seen = {start}
    frontier = [start]
    depth = 0
    nodes = 0
    add = seen.add
    while frontier and depth < DEPTH_CAP:
        depth += 1
        nxt = []
        push = nxt.append
        for st in frontier:
            nodes += 1
            if nodes > node_cap:
                return -1, 'cap'
            occ = set(st)
            p0 = st[0]
            for d in range(4):
                q = slide(rays, occ, p0, d)
                if q is None:
                    continue
                if q == goal:
                    return depth, 'ok'
                ns = (q, st[1], st[2], st[3])
                if ns not in seen:
                    add(ns)
                    push(ns)
            for k in (1, 2, 3):
                pk = st[k]
                for d in range(4):
                    q = slide(rays, occ, pk, d)
                    if q is None:
                        continue
                    o = [st[1], st[2], st[3]]
                    o[k - 1] = q
                    o.sort()
                    ns = (p0, o[0], o[1], o[2])
                    if ns not in seen:
                        add(ns)
                        push(ns)
        frontier = nxt
    return -1, 'no'


# ------------------------------------------------------------ 候補づくり
def tier_of(m):
    for name, lo, hi in TIERS:
        if lo <= m <= hi:
            return name
    return None


def make_candidate(rng, m, rays, corners, layout_id, sig):
    """壁は固定のまま、的とロボット4体をランダムに置いた1件（未解答）"""
    gx, gy = rng.choice(corners)
    goal = gy * W + gx
    free = [i for i in range(N) if i not in BLOCK and i != goal]
    spots = rng.sample(free, 4)
    tcolor = rng.randrange(4)
    return {
        'layout': layout_id, 'sig': sig, 'walls': m,
        'goal': goal, 'tcolor': tcolor, 'spots': spots, 'rays': rays,
    }


def encode(c):
    robots = [[c['spots'][k] % W, c['spots'][k] // W, COLORS[k]] for k in range(4)]
    return {
        'w': W,
        'walls': walls_str(c['walls']),
        'robots': robots,
        'target': [c['goal'] % W, c['goal'] // W, COLORS[c['tcolor']]],
        'min': c['min'],
        'tier': tier_of(c['min']),
        'needsOthers': bool(c['needsOthers']),
    }


def enc_line(o):
    return ('  {"w":%d,"walls":"%s","robots":%s,"target":%s,"min":%d,"tier":"%s","needsOthers":%s}'
            % (o['w'], o['walls'],
               json.dumps(o['robots'], ensure_ascii=False, separators=(',', ':')),
               json.dumps(o['target'], ensure_ascii=False, separators=(',', ':')),
               o['min'], o['tier'], 'true' if o['needsOthers'] else 'false'))


# ------------------------------------------------------------ 選抜
def pick_ok(c, chosen):
    for o in chosen:
        if o['layout'] == c['layout']:
            return False
        if similarity(c['sig'], o['sig']) > MAX_SIM:
            return False
    return True


def select_tier(rng, cands, k, chosen, prefer_needs):
    """prefer_needs=True なら「他の体を動かさないと最短にならない盤」を先に、
       False なら「的の色の体だけで解ける盤」を先に取る（見立ての妙味は上の段階へ）"""
    by_min = {}
    for c in cands:
        by_min.setdefault(c['min'], []).append(c)
    for v in by_min.values():
        if prefer_needs:
            v.sort(key=lambda c: (0 if c['needsOthers'] else 1, rng.random()))
        else:
            v.sort(key=lambda c: (1 if c['needsOthers'] else 0, rng.random()))
    keys = sorted(by_min)
    out = []
    while len(out) < k:
        progress = False
        for key in keys:                       # 手数を端から端まで順番に取る
            if len(out) >= k:
                break
            b = by_min[key]
            while b:
                c = b.pop(0)
                if pick_ok(c, chosen + out):
                    out.append(c)
                    progress = True
                    break
        if not progress:
            break
    return out


# ------------------------------------------------------------ 本体
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20260907)
    ap.add_argument("--budget", type=float, default=300.0, help="生成に使う秒数の上限")
    ap.add_argument("--layouts", type=int, default=100000, help="壁配置の試行回数の上限")
    ap.add_argument("--per-layout", type=int, default=6, help="1つの壁配置で試す駒の置き方")
    ap.add_argument("--node-cap", type=int, default=60000, help="1回目の探索の打ち切り")
    ap.add_argument("--hard-node-cap", type=int, default=2500000, help="難しい盤の再探索の打ち切り")
    ap.add_argument("--embed", metavar="HTML",
                    help="この HTML の LEVELS-BEGIN / LEVELS-END の間へ直接埋め込む")
    ap.add_argument("--tiers", help='段階の閾値を上書き（例 "3-4,5-6,7-8,9-"）')
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

    pool = {}          # tier -> [cand]
    hard = []          # 打ち切りになった盤（あとでじっくり解く）
    all_mins = []
    seen_boards = set()
    layouts = 0

    def register(c, mn, status, solo):
        if status != 'ok' or mn < MIN_MOVES:
            return False
        c['min'] = mn
        c['needsOthers'] = (solo != mn)
        all_mins.append(mn)
        t = tier_of(mn)
        if t:
            pool.setdefault(t, []).append(c)
        return True

    log("[1/3] 盤を作って解く（%.0f秒まで）..." % (args.budget * 0.7))
    while layouts < args.layouts and time.time() - t0 < args.budget * 0.7:
        layouts += 1
        m, corners = gen_walls(rng)
        if len(corners) < 10:
            continue
        rays = build_rays(m)
        sig = wall_sig(m)
        ws = walls_str(m)
        for _ in range(args.per_layout):
            c = make_candidate(rng, m, rays, corners, layouts, sig)
            key = (ws, c['goal'], c['tcolor'], tuple(c['spots']))
            if key in seen_boards:
                continue
            seen_boards.add(key)
            t = c['spots'][c['tcolor']]
            others = [c['spots'][k] for k in range(4) if k != c['tcolor']]
            solo = solve_solo(rays, t, others, c['goal'])
            mn, status = solve(rays, t, others, c['goal'], args.node_cap)
            if status == 'cap':
                c['solo'] = solo
                c.pop('rays', None)
                hard.append(c)
                continue
            register(c, mn, status, solo)
        if not args.quiet and layouts % 200 == 0:
            log("   壁配置 %d  候補 %s  難 %d  経過 %.0fs"
                % (layouts, {n: len(pool.get(n, [])) for n, _, _ in TIERS},
                   len(hard), time.time() - t0))

    log("[2/3] 難しい盤をじっくり解く（%d件）..." % len(hard))
    rng.shuffle(hard)
    deep = 0
    for c in hard:
        if time.time() - t0 > args.budget:
            break
        need = [n for n, lo, hi in TIERS if len(pool.get(n, [])) < PER_TIER * 3 and lo >= 7]
        if not need:
            break
        rays = build_rays(c['walls'])
        t = c['spots'][c['tcolor']]
        others = [c['spots'][k] for k in range(4) if k != c['tcolor']]
        mn, status = solve(rays, t, others, c['goal'], args.hard_node_cap)
        deep += 1
        register(c, mn, status, c['solo'])
    log("   再探索 %d件 / 経過 %.0fs" % (deep, time.time() - t0))

    if all_mins:
        s = sorted(all_mins)
        hist = {}
        for v in s:
            hist[v] = hist.get(v, 0) + 1
        log("実測の最短手数: n=%d  %s" % (len(s), hist))

    log("[3/3] 選抜（盤内の壁の一致率 <= %.2f）..." % MAX_SIM)
    chosen = []
    order = ["上級", "中級", "初級", "入門"]
    for name in order:
        lo = [t for t in TIERS if t[0] == name][0][1]
        got = select_tier(rng, list(pool.get(name, [])), PER_TIER, chosen, lo >= 7)
        chosen += got
        log("   %s: %d本（他の体を動かす必要 %d本）"
            % (name, len(got), sum(1 for c in got if c['needsOthers'])))

    chosen.sort(key=lambda c: (c['min'], c['layout']))
    out = [encode(c) for c in chosen]

    sigs = [c['sig'] for c in chosen]
    ms = max((similarity(sigs[i], sigs[j])
              for i in range(len(sigs)) for j in range(i + 1, len(sigs))), default=0.0)
    log("相互の一致率 最大 %.2f / 壁配置 %d / 所要 %.0fs" % (ms, layouts, time.time() - t0))

    body = "var LEVELS = [\n" + ",\n".join(enc_line(o) for o in out) + "\n];\n"

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
