#!/usr/bin/env python3
"""おしだし（oshidashi）の問題生成器。Python3 標準ライブラリのみ。

ランダムな盤 → 状態（盤の全タイル・手持ち・駒・直前の押し込み）で幅優先探索して
「駒からゴールまで通路がつながる」までの最短手数を出し、条件を満たす盤だけを
tools/levels.json に書き、../index.html の LEVELS-BEGIN〜END に埋め込む。

記法（index.html の window.Oshidashi と同じ。spec.md §記法）
  - 腕のビット N=1 E=2 S=4 W=8。時計回り90°は1ビット左巡回
  - タイルは 直線(5,10) / かど(3,6,12,9) / 三叉(7,14,13,11) の3種
  - マス番号 i = r*n + c（左上0、右へ c、下へ r）
  - 押せる列＝奇数番目の行・列（0始まりで 1,3,5…）。偶数行かつ偶数列のマスは動かない
  - 押し込み口の番号: 押せる行ごとに [左から, 右から]、続いて押せる列ごとに [上から, 下から]
      5×5: 0=行1左 1=行1右 2=行3左 3=行3右 4=列1上 5=列1下 6=列3上 7=列3下
  - 1手＝押し込み1回。直前に押し込んだ口の反対側の口（＝いま押し出された1枚が出た口）は次の1手で使えない
  - 回せる段では押す前に手持ちを回せる（手数に数えない）。探索では「向きを決めて押す」を1手として展開し、
    同じ形になる向き（直線の180°）は同一視する

使い方
  python3 tools/gen_levels.py            # 40問を作って levels.json と index.html を更新
  python3 tools/gen_levels.py --survey   # 段ごとに最短手数の分布だけを見る（書き出さない）
"""
import argparse
import json
import os
import random
import re
import sys
import time
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
HTML = os.path.join(HERE, '..', 'index.html')
OUT = os.path.join(HERE, 'levels.json')

STRAIGHT = (5, 10)
CORNER = (3, 6, 12, 9)
TEE = (7, 14, 13, 11)


def rot(m, t=1):
    """時計回りに t 回（90°ずつ）"""
    t %= 4
    for _ in range(t):
        m = ((m << 1) | (m >> 3)) & 15
    return m


def variants(m):
    """向きの重複を同一視した異なる向き（直線2・かど4・三叉4）"""
    out = []
    x = m
    for _ in range(4):
        if x not in out:
            out.append(x)
        x = rot(x)
    return out


def canon(m):
    return min(variants(m))


class Geo:
    """盤の大きさごとの定数（押し込み口・ビットマスク）"""

    def __init__(self, n):
        self.n = n
        self.N = n * n
        self.lines = [k for k in range(1, n, 2)]
        self.ops = []           # (側, 何番目の行/列)  側: 'L','R','T','B'
        for r in self.lines:
            self.ops.append(('L', r))
            self.ops.append(('R', r))
        for c in self.lines:
            self.ops.append(('T', c))
            self.ops.append(('B', c))
        self.opp = []
        for side, k in self.ops:
            o = {'L': 'R', 'R': 'L', 'T': 'B', 'B': 'T'}[side]
            self.opp.append(self.ops.index((o, k)))
        self.rowfull = (1 << n) - 1
        self.full = (1 << self.N) - 1
        self.colmask = []
        for c in range(n):
            m = 0
            for r in range(n):
                m |= 1 << (r * n + c)
            self.colmask.append(m)
        self.notlast = self.full & ~self.colmask[n - 1]
        self.fixed = [i for i in range(self.N) if (i // n) % 2 == 0 and (i % n) % 2 == 0]
        self.movable = [i for i in range(self.N) if i not in self.fixed]


GEO = {}


def geo(n):
    if n not in GEO:
        GEO[n] = Geo(n)
    return GEO[n]


def to_bb(cells):
    """タイルの並び → 腕ごとのビット盤 (N,E,S,W)"""
    b = [0, 0, 0, 0]
    for i, m in enumerate(cells):
        for a in range(4):
            if m >> a & 1:
                b[a] |= 1 << i
    return tuple(b)


def from_bb(g, bb):
    out = []
    for i in range(g.N):
        m = 0
        for a in range(4):
            if bb[a] >> i & 1:
                m |= 1 << a
        out.append(m)
    return out


def push_bb(g, bb, piece, op, h):
    """押し込み口 op に向き h の手持ちを押し込む → (新しいビット盤, 押し出された1枚, 駒の新位置)"""
    n = g.n
    side, k = g.ops[op]
    nb = [0, 0, 0, 0]
    ej = 0
    if side == 'L' or side == 'R':
        base = k * n
        rf = g.rowfull
        for a in range(4):
            B = bb[a]
            row = (B >> base) & rf
            b = h >> a & 1
            if side == 'L':
                e = (row >> (n - 1)) & 1
                new = ((row << 1) & rf) | b
            else:
                e = row & 1
                new = (row >> 1) | (b << (n - 1))
            ej |= e << a
            nb[a] = (B & ~(rf << base)) | (new << base)
        if piece // n == k:
            c = piece % n
            if side == 'L':
                c = c + 1 if c < n - 1 else 0
            else:
                c = c - 1 if c > 0 else n - 1
            piece = k * n + c
    else:
        cm = g.colmask[k]
        last = (n - 1) * n + k
        for a in range(4):
            B = bb[a]
            col = B & cm
            b = h >> a & 1
            if side == 'T':
                e = (col >> last) & 1
                new = ((col << n) & cm) | (b << k)
            else:
                e = (col >> k) & 1
                new = (col >> n) | (b << last)
            ej |= e << a
            nb[a] = (B & ~cm) | new
        if piece % n == k:
            r = piece // n
            if side == 'T':
                r = r + 1 if r < n - 1 else 0
            else:
                r = r - 1 if r > 0 else n - 1
            piece = r * n + k
    return (nb[0], nb[1], nb[2], nb[3]), ej, piece


def reach(g, bb, piece):
    """駒のマスから、両側に腕がある辺だけを渡って届くマスのビット集合"""
    n = g.n
    Nb, Eb, Sb, Wb = bb
    ee = Eb & (Wb >> 1) & g.notlast       # i と i+1 がつながる
    se = Sb & (Nb >> n)                   # i と i+n がつながる
    r = 1 << piece
    while True:
        nr = r | ((r & ee) << 1) | ((r >> 1) & ee) | ((r & se) << n) | ((r >> n) & se)
        if nr == r:
            return r
        r = nr


def solve(n, cells, hand, piece, goal, rotatable, maxd):
    """最短手数と解の1例 [(op, 押し込んだ向き), ...]。maxd 以内に無ければ (None, None)"""
    return solve_from(geo(n), to_bb(cells), hand, piece, -1, goal, rotatable, maxd)


MAX_STATES = 2500000   # 局面がこれを超える盤は重すぎるので捨てる（最短手数を不確かにしないため打ち切りでなく棄却）


class Heavy(Exception):
    pass


def solve_from(g, bb, hand, piece, ban, goal, rotatable, maxd):
    gbit = 1 << goal
    if reach(g, bb, piece) & gbit:
        return 0, []
    h0 = canon(hand) if rotatable else hand
    start = (bb, h0, piece, ban)
    parent = {start: None}
    frontier = [start]
    nops = len(g.ops)
    VAR = {m: (variants(m) if rotatable else [m]) for m in range(16)}
    for d in range(1, maxd + 1):
        nxt = []
        for st in frontier:
            sbb, sh, sp, sban = st
            for op in range(nops):
                if op == sban:
                    continue
                nban = g.opp[op]
                for h in VAR[sh]:
                    cbb, ej, cp = push_bb(g, sbb, sp, op, h)
                    if reach(g, cbb, cp) & gbit:
                        path = [(op, h)]
                        cur = st
                        while parent[cur] is not None:
                            pst, mv = parent[cur]
                            path.append(mv)
                            cur = pst
                        path.reverse()
                        return d, path
                    if d < maxd:
                        key = (cbb, canon(ej) if rotatable else ej, cp, nban)
                        if key not in parent:
                            parent[key] = (st, (op, h))
                            nxt.append(key)
            if len(parent) > MAX_STATES:
                raise Heavy()
        frontier = nxt
    return None, None


def first_moves(n, cells, hand, piece, goal, rotatable, d):
    """最短 d 手の解につながる初手（押し込み口と向き）の数。少ないほど考えどころが狭い"""
    g = geo(n)
    bb = to_bb(cells)
    cnt = 0
    for op in range(len(g.ops)):
        for h in (variants(hand) if rotatable else [hand]):
            cbb, ej, cp = push_bb(g, bb, piece, op, h)
            dd, _ = solve_from(g, cbb, ej, cp, g.opp[op], goal, rotatable, d - 1)
            if dd is not None and dd == d - 1:
                cnt += 1
    return cnt


def manhattan_to_goal(g, rbits, goal):
    n = g.n
    gr, gc = divmod(goal, n)
    best = 99
    i = 0
    while rbits:
        if rbits & 1:
            r, c = divmod(i, n)
            d = abs(r - gr) + abs(c - gc)
            if d < best:
                best = d
        rbits >>= 1
        i += 1
    return best


def naive_solves(n, cells, hand, piece, goal, rotatable, steps, beam=400):
    """「素直な手」で steps 手以内に届いてしまうか。
    素直な手 = (a) 駒の乗っている列を押す手だけ、または
               (b) 毎手「駒から届く範囲がゴールに一番近づく」手（その手番の全局面で一番の手・同点は全部残す）
    (c) どの局面からも、その局面で一番ゴールに近づく手（同点は全部）を選び続ける全分岐（親ごと）
    のどれかで最短手数に届くなら、その問題は素直すぎるので捨てる"""
    g = geo(n)
    gbit = 1 << goal
    bb0 = to_bb(cells)
    nops = len(g.ops)
    VAR = {m: (variants(m) if rotatable else [m]) for m in range(16)}

    def piece_line(op, p):
        side, k = g.ops[op]
        return (p // n == k) if side in 'LR' else (p % n == k)

    # (a) 駒の列だけ
    front = {(bb0, hand, piece, -1)}
    for _ in range(steps):
        nxt = set()
        for sbb, sh, sp, ban in front:
            for op in range(nops):
                if op == ban or not piece_line(op, sp):
                    continue
                for h in VAR[sh]:
                    cbb, ej, cp = push_bb(g, sbb, sp, op, h)
                    if reach(g, cbb, cp) & gbit:
                        return 'piece-line'
                    nxt.add((cbb, ej, cp, g.opp[op]))
        front = nxt
        if not front:
            break
    # (b) 近づく手を貪る
    front = [(bb0, hand, piece, -1)]
    for _ in range(steps):
        cand = []
        best = 99
        for sbb, sh, sp, ban in front:
            for op in range(nops):
                if op == ban:
                    continue
                for h in VAR[sh]:
                    cbb, ej, cp = push_bb(g, sbb, sp, op, h)
                    rb = reach(g, cbb, cp)
                    if rb & gbit:
                        return 'greedy'
                    sc = manhattan_to_goal(g, rb, goal)
                    if sc < best:
                        best = sc
                        cand = []
                    if sc == best:
                        cand.append((cbb, ej, cp, g.opp[op]))
        seen = set()
        front = []
        for s in cand:
            if s not in seen:
                seen.add(s)
                front.append(s)
            if len(front) >= beam:
                break
    # (c) 親ごとに貪る：どの局面からも、その局面で一番ゴールに近づく手（同点は全部）を選び続ける全分岐
    front = {(bb0, hand, piece, -1)}
    for _ in range(steps):
        nxt = set()
        for sbb, sh, sp, ban in front:
            best = 99
            mine = []
            for op in range(nops):
                if op == ban:
                    continue
                for h in VAR[sh]:
                    cbb, ej, cp = push_bb(g, sbb, sp, op, h)
                    rb = reach(g, cbb, cp)
                    if rb & gbit:
                        return 'greedy-each'
                    sc = manhattan_to_goal(g, rb, goal)
                    if sc < best:
                        best = sc
                        mine = []
                    if sc == best:
                        mine.append((cbb, canon(ej) if rotatable else ej, cp, g.opp[op]))
            nxt.update(mine)
        front = nxt
        if len(front) > 300000:
            return 'greedy-each-heavy'    # 全分岐が数え切れないほど広い盤は素直とみなして捨てる（安全側）
    return None


def count_min_solutions(n, cells, hand, piece, goal, rotatable, m):
    """最短 m 手の解（押し込み口と向きの列）の数。qa の数え方と同じく、途中でつながる列は数えない"""
    g = geo(n)
    gbit = 1 << goal
    VAR = {x: (variants(x) if rotatable else [x]) for x in range(16)}
    layer = {(to_bb(cells), canon(hand) if rotatable else hand, piece, -1): 1}
    for d in range(1, m + 1):
        nxt = {}
        total = 0
        for (sbb, sh, sp, ban), cnt in layer.items():
            for op in range(len(g.ops)):
                if op == ban:
                    continue
                for h in VAR[sh]:
                    cbb, ej, cp = push_bb(g, sbb, sp, op, h)
                    if reach(g, cbb, cp) & gbit:
                        total += cnt
                        continue
                    if d < m:
                        key = (cbb, canon(ej) if rotatable else ej, cp, g.opp[op])
                        nxt[key] = nxt.get(key, 0) + cnt
        if d == m:
            return total
        layer = nxt
    return 0


# ---- 段 ----
# min..max = 採る最短手数の帯 / maxd = 探索の深さの上限（これより深い盤は「解けない」扱いで捨てる）
# gather = 10本の何倍を集めてから、最短手数の大きい順（同じなら最短につながる初手の少ない順）に10本を採るか
TIERS = [
    {'tier': '入門', 'n': 5, 'rot': 0, 'min': 3, 'max': 4, 'maxd': 4, 'gather': 1},
    {'tier': '初級', 'n': 5, 'rot': 1, 'min': 3, 'max': 5, 'maxd': 5, 'gather': 3},
    {'tier': '中級', 'n': 7, 'rot': 1, 'min': 3, 'max': 3, 'maxd': 3, 'gather': 3},
    {'tier': '上級', 'n': 7, 'rot': 1, 'min': 4, 'max': 4, 'maxd': 4, 'gather': 2},
]
PER_TIER = 10
MAX_FIRSTS = 5      # 最短につながる初手（押し込み口×向き）がこれより多い盤は易しすぎるので捨てる
NSOL_RATIO = 5      # 最短の解の数が、段で採った10本の中央値のこの倍を超える盤は捨てる
WEIGHTS = (STRAIGHT, 3), (CORNER, 4), (TEE, 3)   # 直線:かど:三叉 の出やすさ


def rand_tile(rng):
    pool = []
    for tiles, w in WEIGHTS:
        pool += [tiles] * w
    return rng.choice(rng.choice(pool))


def rand_board(rng, n):
    g = geo(n)
    cells = [rand_tile(rng) for _ in range(g.N)]
    hand = rand_tile(rng)
    goal = rng.choice(g.fixed)
    # 駒は動くマスに置き、ゴールからマンハッタン距離 n//2+1 以上離す（5×5で3・7×7で4）
    far = [i for i in g.movable
           if abs(i // n - goal // n) + abs(i % n - goal % n) >= n // 2 + 1]
    piece = rng.choice(far)
    return cells, hand, piece, goal


def try_one(args):
    """1本作って測る（multiprocessing 用）。条件を満たせば問題の dict、満たさなければ理由の文字列"""
    ti, seed = args
    t = TIERS[ti]
    rng = random.Random(seed)
    n = t['n']
    cells, hand, piece, goal = rand_board(rng, n)
    try:
        d, path = solve(n, cells, hand, piece, goal, t['rot'], t['maxd'])
    except Heavy:
        return ('heavy', None)
    if d is None:
        return ('deep', None)
    if d < t['min'] or d > t['max']:
        return ('min%d' % d, None)
    if t['rot']:
        # 回さないと最短手数で解けないか（回せない規則で解くと長くなる、または解けない）
        dn, _ = solve(n, cells, hand, piece, goal, 0, d)
        needrot = dn is None
        if not needrot and t.get('needrot', 1) == 1:
            return ('norot', None)
    else:
        needrot = False
    why = naive_solves(n, cells, hand, piece, goal, t['rot'], d)
    if why:
        return (why, None)
    firsts = first_moves(n, cells, hand, piece, goal, t['rot'], d)
    if firsts > MAX_FIRSTS:
        return ('firsts', None)
    return ('ok', {
        'firsts': firsts,
        'nsol': count_min_solutions(n, cells, hand, piece, goal, t['rot'], d),
        'needrot': int(needrot),
        'n': n, 'cells': ''.join('0123456789abcdef'[m] for m in cells),
        'hand': '0123456789abcdef'[hand], 'piece': piece, 'goal': goal,
        'rot': t['rot'], 'min': d, 'sol': [[op, h] for op, h in path], 'tier': t['tier'],
    })


def median(xs):
    xs = sorted(xs)
    k = len(xs)
    return (xs[(k - 1) // 2] + xs[k // 2]) / 2.0


def pick(cands, t):
    """候補から10本を採る。
    最短手数の大きい順、同じなら最短につながる初手の少ない順（同点は集まった順＝seed 順）に並べ、
    回さないと解けない盤を needrot_min 本以上含め、最短の解の数が採った10本の中央値の NSOL_RATIO 倍を
    超える盤を外して、条件が落ち着くまで繰り返す。並びは易しい順（最短手数の昇順、同じなら初手・解の多い順）"""
    order = sorted(cands, key=lambda x: (-x['min'], x['firsts']))
    banned = set()
    while True:
        pool = [c for c in order if id(c) not in banned]
        need = t.get('needrot_min', 0)
        rot_ok = [c for c in pool if c['needrot']][:need]
        rest = [c for c in pool if c not in rot_ok]
        sel = rot_ok + rest[:PER_TIER - len(rot_ok)]
        if len(sel) < PER_TIER:
            raise SystemExit('%s: 候補が足りない' % t['tier'])
        med = median([c['nsol'] for c in sel])
        over = [c for c in sel if c['nsol'] > NSOL_RATIO * med]
        if not over:
            break
        for c in over:
            banned.add(id(c))
    sel.sort(key=lambda x: (x['min'], -x['firsts'], -x['nsol']))
    return sel


def overlap(a, b):
    if a['n'] != b['n']:
        return 0.0
    same = sum(1 for x, y in zip(a['cells'], b['cells']) if x == y)
    return same / len(a['cells'])


def survey(pool, count, seed):
    for ti, t in enumerate(TIERS):
        t0 = time.time()
        res = pool.map(try_one, [(ti, seed * 1000003 + ti * 7919 + k) for k in range(count)])
        hist = {}
        for why, _ in res:
            hist[why] = hist.get(why, 0) + 1
        print('%s %dx%d rot=%d  %s  %.1fs' % (t['tier'], t['n'], t['n'], t['rot'],
              json.dumps(hist, ensure_ascii=False, sort_keys=True), time.time() - t0))
        sys.stdout.flush()


def generate(pool, seed, sim_max):
    levels = []
    report = []
    for ti, t in enumerate(TIERS):
        t0 = time.time()
        got = []
        tried = 0
        k = 0
        batch = 48
        want = PER_TIER * t['gather']
        while len(got) < want:
            args = [(ti, seed * 1000003 + ti * 7919 + k + j) for j in range(batch)]
            k += batch
            for why, lv in pool.map(try_one, args):
                tried += 1
                if lv is None or len(got) >= want:
                    continue
                if any(overlap(lv, o) > sim_max for o in got + levels):
                    continue
                got.append(lv)
            if tried > 200000:
                raise SystemExit('%s: %d 本試して %d 本しか作れない' % (t['tier'], tried, len(got)))
        passed = len(got)
        got = pick(got, t)
        levels += got
        report.append('%s: 条件を満たした%d本/%d試行（%.1f%%）から%d本 最短%d〜%d %.1fs' % (
            t['tier'], passed, tried, 100.0 * passed / tried, len(got),
            got[0]['min'], got[-1]['min'], time.time() - t0))
        print(report[-1])
        sys.stdout.flush()
    return levels, report


def embed(levels):
    with open(HTML, encoding='utf-8') as f:
        src = f.read()
    body = ',\n'.join('  ' + json.dumps(lv, ensure_ascii=False, separators=(',', ':')) for lv in levels)
    new = re.sub(r'(/\* LEVELS-BEGIN[^\n]*\n)var LEVELS = \[.*?\];\n(/\* LEVELS-END \*/)',
                 lambda m: m.group(1) + 'var LEVELS = [\n' + body + '\n];\n' + m.group(2),
                 src, count=1, flags=re.S)
    if new == src and 'LEVELS-BEGIN' not in src:
        raise SystemExit('index.html に LEVELS-BEGIN が無い')
    with open(HTML, 'w', encoding='utf-8') as f:
        f.write(new)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seed', type=int, default=20261014)
    ap.add_argument('--survey', type=int, default=0, help='段ごとに N 本測るだけ')
    ap.add_argument('--sim', type=float, default=0.5, help='同じ大きさの盤で同じタイルの割合の上限')
    ap.add_argument('--no-embed', action='store_true')
    ap.add_argument('--embed-only', action='store_true', help='levels.json を index.html に埋め込むだけ')
    a = ap.parse_args()
    if a.embed_only:
        with open(OUT, encoding='utf-8') as f:
            embed(json.load(f)['levels'])
        return
    with Pool() as pool:
        if a.survey:
            survey(pool, a.survey, a.seed)
            return
        t0 = time.time()
        levels, report = generate(pool, a.seed, a.sim)
    total = time.time() - t0
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({'seed': a.seed, 'seconds': round(total, 1), 'report': report, 'levels': levels},
                  f, ensure_ascii=False, indent=1)
    if not a.no_embed:
        embed(levels)
    print('計 %d 問 %.1f 秒' % (len(levels), total))


if __name__ == '__main__':
    main()
