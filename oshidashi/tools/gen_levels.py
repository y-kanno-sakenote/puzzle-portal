#!/usr/bin/env python3
"""おしだし（oshidashi）の問題生成器。Python3 標準ライブラリのみ。

規則（spec.md）: 盤の端から手持ちのタイルを押し込んで列を1マスずらす（1手＝押し込み1回）。
盤の宝①②③はタイルに乗っていて列と一緒に動き、押し出されたら手持ちのタイルに乗る。
押し込みの後、駒から「次の宝」まで道がつながっていれば駒はそこまで進んで拾う（続けて次も）。
最後の宝を拾えばクリア。

記法（index.html の window.Oshidashi と同じ）
  - 腕のビット N=1 E=2 S=4 W=8。時計回り90°は1ビット左巡回
  - タイルは 直線(5,10) / かど(3,6,12,9) / 三叉(7,14,13,11)
  - マス番号 i = r*n + c。押せる列＝奇数番目の行・列。偶数行かつ偶数列のマスは動かない
  - 押し込み口 op: 押せる行ごとに [左から, 右から]、続いて押せる列ごとに [上から, 下から]。反対の口は op^1
  - 直前に押し込んだ口の反対の口は、次の1手で使えない
  - 局面 = (腕ごとのビット盤4枚, 手持ち（回せる段は形だけ）, 残りの宝の位置（手持ちに乗っていれば -1）, 駒, 使えない口)

探索
  - 最短: 幅優先（同じ局面はまとめる）を S 手まで持ち、その先は深さ優先で1手ずつ深める。
    最後の1〜2手は「その列を押して次の宝とつながりうるか」の必要条件で枝を刈る（leaf_lines）
  - 解の数・初手・押し出しの有無: 最短手数の全解を数える（analyze）
  - 素直な順: 毎回「次の宝に一番早く届く押し込み」だけを選び続ける全分岐（greedy_reaches）

使い方
  python3 tools/gen_levels.py            # 40問を作って levels.json と index.html を更新
  python3 tools/gen_levels.py --survey 96   # 段ごとの通過・落ちた理由を見る（書き出さない）
  python3 tools/gen_levels.py --embed-only  # levels.json を index.html に埋め込むだけ
  python3 tools/gen_levels.py --check       # levels.json を今の規則で測り直す（最短・解の数・拾う手・素直な順・回転）
  python3 tools/gen_levels.py --cache <file>  # 試行結果を貯めて、条件だけ変えた再実行を速くする
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
HEX = '0123456789abcdef'

STRAIGHT = (5, 10)
CORNER = (3, 6, 12, 9)
TEE = (7, 14, 13, 11)


def rot(m, t=1):
    for _ in range(t % 4):
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


CANON = [min(variants(m)) for m in range(16)]
VARS = [tuple(variants(m)) for m in range(16)]


class Geo:
    """盤の大きさごとの定数"""

    def __init__(self, n):
        self.n = n
        self.N = n * n
        self.ops = []
        for r in range(1, n, 2):
            self.ops += [('L', r), ('R', r)]
        for c in range(1, n, 2):
            self.ops += [('T', c), ('B', c)]
        self.nops = len(self.ops)
        self.full = (1 << self.N) - 1
        self.rowfull = (1 << n) - 1
        self.colmask = [sum(1 << (r * n + c) for r in range(n)) for c in range(n)]
        self.notlast = self.full & ~self.colmask[n - 1]
        self.notfirst = self.full & ~self.colmask[0]
        self.fixed = [i for i in range(self.N) if (i // n) % 2 == 0 and (i % n) % 2 == 0]
        self.movable = [i for i in range(self.N) if i not in self.fixed]
        self.posmap, self.entry, self.exit, self.linemask = [], [], [], []
        for side, k in self.ops:
            cells = [k * n + c for c in range(n)] if side in 'LR' else [r * n + k for r in range(n)]
            if side in 'RB':
                cells = cells[::-1]          # 入口側から並べる
            pm = list(range(self.N))
            for j, i in enumerate(cells):
                pm[i] = cells[j + 1] if j + 1 < n else -1     # -1 = 押し出される
            self.posmap.append(tuple(pm))
            self.entry.append(cells[0])
            self.exit.append(cells[-1])
            self.linemask.append(sum(1 << i for i in cells))


GEO = {}


def geo(n):
    if n not in GEO:
        GEO[n] = Geo(n)
    return GEO[n]


def to_bb(cells):
    b = [0, 0, 0, 0]
    for i, m in enumerate(cells):
        for a in range(4):
            if m >> a & 1:
                b[a] |= 1 << i
    return tuple(b)


def push_bb(g, bb, op, h):
    """押し込み口 op に向き h の手持ちを押し込む → (新しいビット盤, 押し出された1枚)"""
    n = g.n
    side, k = g.ops[op]
    ej = 0
    nb = []
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
            nb.append((B & ~(rf << base)) | (new << base))
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
            nb.append((B & ~cm) | new)
    return (nb[0], nb[1], nb[2], nb[3]), ej


def flood(g, bb, start, allowed):
    """start（ビット集合）から、allowed のマスだけを通って両側に腕がある辺で届くマス"""
    n = g.n
    Nb, Eb, Sb, Wb = bb
    ee = Eb & (Wb >> 1) & g.notlast & allowed & (allowed >> 1)
    se = Sb & (Nb >> n) & allowed & (allowed >> n)
    r = start
    while True:
        nr = r | ((r & ee) << 1) | ((r >> 1) & ee) | ((r & se) << n) | ((r >> n) & se)
        if nr == r:
            return r
        r = nr


def reach(g, bb, p):
    return flood(g, bb, 1 << p, g.full)


def collect(g, bb, piece, tpos):
    """押し込みの後：駒から次の宝まで道がつながっていれば拾ってそこへ進む（続けて次も）"""
    if tpos and tpos[0] >= 0:
        R = reach(g, bb, piece)
        while tpos and tpos[0] >= 0 and (R >> tpos[0]) & 1:
            piece = tpos[0]
            tpos = tpos[1:]
    return piece, tpos


def step(g, st, op, h, rotatable):
    """1手打った局面と、宝を押し出したか"""
    bb, hand, tpos, piece, ban = st
    cbb, ej = push_bb(g, bb, op, h)
    pm = g.posmap[op]
    ent = g.entry[op]
    np_ = pm[piece]
    if np_ < 0:
        np_ = ent
    out = False
    nt = []
    for p in tpos:
        if p < 0:
            nt.append(ent)
        else:
            q = pm[p]
            if q < 0:
                out = True
            nt.append(q)
    np_, nt = collect(g, cbb, np_, tuple(nt))
    return (cbb, CANON[ej] if rotatable else ej, nt, np_, op ^ 1), out


def touches(g, comp, bb, ml):
    """comp のどこかから ml のマスへ腕が向いているか"""
    n = g.n
    Nb, Eb, Sb, Wb = bb
    return bool((((comp & Eb & g.notlast) << 1) | ((comp & Wb & g.notfirst) >> 1)
                 | ((comp & Sb) << n) | ((comp & Nb) >> n)) & ml)


def can_link(g, st, ml):
    """ml のマスだけが変わる押し込みで、駒と次の宝がつながりうるか（必要条件・ゆるい側に倒す）"""
    bb, hand, tpos, piece, ban = st
    t = tpos[0]
    allowed = g.full & ~ml
    if not (ml >> piece) & 1:
        cp = flood(g, bb, 1 << piece, allowed)
        if t >= 0 and (cp >> t) & 1:
            return True
        if not touches(g, cp, bb, ml):
            return False
    if t >= 0 and not (ml >> t) & 1:
        ct = flood(g, bb, 1 << t, allowed)
        if not touches(g, ct, bb, ml):
            return False
    return True


def leaf_ops(g, st, rem):
    """残り rem 手（1か2）でクリアしうる押し込み口だけを返す"""
    ops = [op for op in range(g.nops) if op != st[4]]
    if rem == 1:
        ok = {}
        out = []
        for op in ops:
            ml = g.linemask[op]
            if ml not in ok:
                ok[ml] = can_link(g, st, ml)
            if ok[ml]:
                out.append(op)
        return out
    if rem == 2:
        masks = sorted(set(g.linemask))
        ok = {}
        out = []
        for op in ops:
            m1 = g.linemask[op]
            good = False
            for m2 in masks:
                u = m1 | m2
                if u not in ok:
                    ok[u] = can_link(g, st, u)
                if ok[u]:
                    good = True
                    break
            if good:
                out.append(op)
        return out
    return ops


def hands(st, rotatable):
    return VARS[st[1]] if rotatable else (st[1],)


class Heavy(Exception):
    pass


def solve(g, start, rotatable, maxd, S, max_states=1500000, budget=None):
    """最短手数と解の1例。幅優先で S 手まで（同じ局面はまとめる）、その先は深さ優先で1手ずつ深める。
    maxd 手以内に無ければ (None, None)。budget（1手を打つ回数の上限）を超えたら Heavy（最短を不確かにしないため棄却）"""
    if not start[2]:
        return 0, []
    calls = [0]
    parent = {start: None}
    frontier = [start]

    def path_to(st):
        out = []
        while parent[st] is not None:
            st, mv = parent[st]
            out.append(mv)
        return out[::-1]

    for d in range(1, min(S, maxd) + 1):
        nxt = []
        for st in frontier:
            ops = leaf_ops(g, st, 1) if d == maxd else [op for op in range(g.nops) if op != st[4]]
            for op in ops:
                for h in hands(st, rotatable):
                    ch, _ = step(g, st, op, h, rotatable)
                    if not ch[2]:
                        return d, path_to(st) + [(op, h)]
                    if d < maxd and ch not in parent:
                        parent[ch] = (st, (op, h))
                        nxt.append(ch)
            if len(parent) > max_states:
                raise Heavy()
        frontier = nxt
    if maxd <= S:
        return None, None

    def dfs(st, rem):
        ops = leaf_ops(g, st, rem)
        if budget is not None:
            calls[0] += len(ops)
            if calls[0] > budget:
                raise Heavy()
        for op in ops:
            for h in hands(st, rotatable):
                ch, _ = step(g, st, op, h, rotatable)
                if not ch[2]:
                    return [(op, h)]
                if rem > 1:
                    r = dfs(ch, rem - 1)
                    if r is not None:
                        return [(op, h)] + r
        return None

    for D in range(S + 1, maxd + 1):
        for st in frontier:
            r = dfs(st, D - S)
            if r is not None:
                return D, path_to(st) + r
    return None, None


def analyze(g, start, rotatable, m, S):
    """最短 m 手の全解を数える → (解の数, 最短につながる初手の数, 押し出して入れ直す解の数, 拾う手の数の最小)
    「拾う手の数」= 解の中で宝を1個以上拾った押し込みの数（同じ手で続けて拾えば1と数える）。
    途中でつながる列は数えない（m が最短なので起こらない）"""
    assert m >= 2
    Sl = min(S, m - 1)
    # 局面 -> [押し出しなしの数, 押し出しありの数, 初手のビット集合, ここまでの拾う手の数のビット集合]
    layer = {start: [1, 0, 0, 1]}
    for d in range(1, Sl + 1):
        nxt = {}
        for st, (c0, c1, fm, pm) in layer.items():
            r0 = len(st[2])
            for op in range(g.nops):
                if op == st[4]:
                    continue
                for h in hands(st, rotatable):
                    ch, out = step(g, st, op, h, rotatable)
                    v = nxt.get(ch)
                    if v is None:
                        v = nxt[ch] = [0, 0, 0, 0]
                    if out:
                        v[1] += c0 + c1
                    else:
                        v[0] += c0
                        v[1] += c1
                    v[2] |= (1 << (op * 16 + h)) if d == 1 else fm
                    v[3] |= (pm << 1) if len(ch[2]) < r0 else pm
        layer = nxt

    def dfs(st, rem):
        """(押し出しなしで着く解の数, 押し出しありで着く解の数, 残りで拾う手の数のビット集合)"""
        n0 = n1 = 0
        em = 0
        r0 = len(st[2])
        for op in leaf_ops(g, st, rem):
            for h in hands(st, rotatable):
                ch, out = step(g, st, op, h, rotatable)
                if rem == 1:
                    if not ch[2]:
                        if out:
                            n1 += 1
                        else:
                            n0 += 1
                        em |= 2          # 最後の手で拾う（1手）
                else:
                    a, b, sm = dfs(ch, rem - 1)
                    if not (a or b):
                        continue
                    if out:
                        n1 += a + b
                    else:
                        n0 += a
                        n1 += b
                    em |= (sm << 1) if len(ch[2]) < r0 else sm
        return n0, n1, em

    tot0 = tot1 = 0
    fmask = 0
    allp = 0
    rem = m - Sl
    for st, (c0, c1, fm, pm) in layer.items():
        a, b, sm = dfs(st, rem)
        if not (a or b):
            continue
        fmask |= fm
        tot0 += c0 * a
        tot1 += c1 * (a + b) + c0 * b
        i = 0
        while pm >> i:
            if (pm >> i) & 1:
                allp |= sm << i
            i += 1
    minpick = (allp & -allp).bit_length() - 1
    return tot0 + tot1, bin(fmask).count('1'), tot1, minpick


def greedy_reaches(g, st, rotatable, budget):
    """素直な順：毎回「次の宝に一番早く届く押し込み」だけを選び続けて（同点は全部）budget 手以内に全部拾えるか"""
    if not st[2]:
        return True
    if budget <= 0:
        return False
    r0 = len(st[2])
    seen = {st}
    layer = [st]
    ends = set()
    used = 0
    for d in range(1, budget + 1):
        nxt = []
        for s in layer:
            for op in range(g.nops):
                if op == s[4]:
                    continue
                for h in hands(s, rotatable):
                    ch, _ = step(g, s, op, h, rotatable)
                    if len(ch[2]) < r0:
                        ends.add(ch)
                    elif not ends and ch not in seen:
                        seen.add(ch)
                        nxt.append(ch)
        if ends:
            used = d
            break
        layer = nxt
        if len(seen) > 600000:
            return True     # 広すぎて数え切れない盤は素直とみなして捨てる（安全側）
    if not ends:
        return False
    for e in ends:
        if greedy_reaches(g, e, rotatable, budget - used):
            return True
    return False


def segments(g, start, path, rotatable):
    """解の手順で、各宝を何手目に拾ったか → 区間ごとの手数"""
    st = start
    k = len(start[2])
    got = []
    for i, (op, h) in enumerate(path):
        before = len(st[2])
        st, _ = step(g, st, op, h, rotatable)
        for _ in range(before - len(st[2])):
            got.append(i + 1)
    seg = []
    prev = 0
    for x in got:
        seg.append(x - prev)
        prev = x
    assert len(seg) == k
    return seg


# ---- 段 ----
# k = 宝の数 / min..max = 採る最短手数 / S = 幅優先で持つ深さ（SA は全解を数えるとき）/ gather = 10本の何倍を集めてから選ぶか
# budget = 深さ優先で調べる押し込み口の数の上限（超える盤は重すぎるので捨てる）
TIERS = [
    {'tier': '入門', 'n': 5, 'rot': 0, 'k': 2, 'min': 4, 'max': 5, 'S': 6, 'gather': 2},
    {'tier': '初級', 'n': 5, 'rot': 1, 'k': 2, 'min': 4, 'max': 5, 'S': 3, 'gather': 2},
    {'tier': '中級', 'n': 5, 'rot': 1, 'k': 3, 'min': 5, 'max': 5, 'S': 3, 'gather': 2},
    {'tier': '上級', 'n': 5, 'rot': 1, 'k': 3, 'min': 6, 'max': 6, 'S': 3, 'SA': 4, 'gather': 1, 'budget': 2000000, 'max_tries': 600000,
     'firsts': 10},   # 6手の解は順番の入れ替えが効くので初手が増える（5では作れない）
]
PER_TIER = 10
CAP3 = 0            # 宝3個の段で「3回に分けて拾う盤を半分以上」を目指して集め足す試行の上限（2026-10-15 0に：上級でその盤は約5.7万回に1本で、半分は現実的でない。中級は集め足さなくても5/10ある）
MAX_FIRSTS = 5      # 最短につながる初手（押し込み口×向き）がこれより多い盤は易しすぎるので捨てる
NSOL_RATIO = 5      # 最短の解の数が、段で採った10本の中央値のこの倍を超える盤は外す
WEIGHTS = (STRAIGHT, 3), (CORNER, 4), (TEE, 3)   # 直線:かど:三叉 の出やすさ


def rand_tile(rng):
    pool = []
    for tiles, w in WEIGHTS:
        pool += [tiles] * w
    return rng.choice(rng.choice(pool))


def try_one(args):
    """1本作って測る。条件を満たせば (理由'ok', 問題の dict)、満たさなければ (理由, None)"""
    ti, seed = args
    t = TIERS[ti]
    rng = random.Random(seed)
    n, k, rotatable = t['n'], t['k'], t['rot']
    g = geo(n)
    cells = [rand_tile(rng) for _ in range(g.N)]
    hand = rand_tile(rng)
    piece = rng.choice(g.movable)
    tre = rng.sample([i for i in range(g.N) if i != piece], k)
    start = (to_bb(cells), CANON[hand] if rotatable else hand, tuple(tre), piece, -1)
    if collect(g, start[0], piece, start[2])[1] != start[2]:
        return ('start', None)          # 最初から①とつながっている
    try:
        d, path = solve(g, start, rotatable, t['max'], t['S'], budget=t.get('budget'))
    except Heavy:
        return ('heavy', None)
    if d is None:
        return ('deep', None)
    if d < t['min']:
        return ('min%d' % d, None)
    needrot = 0
    if rotatable:
        s0 = (start[0], hand, start[2], piece, -1)
        dn, _ = solve(g, s0, 0, d, 6)
        if dn is not None:
            return ('norot', None)      # 回さなくても最短で解ける
        needrot = 1
    if greedy_reaches(g, start, rotatable, d):
        return ('greedy', None)         # 素直な順で最短に届く
    nsol, firsts, nej, minpick = analyze(g, start, rotatable, d, t.get('SA', t['S']))
    if minpick < 2:
        return ('onepick', None)        # 最後の1手で残りの宝をまとめて拾う最短解がある
    if firsts > t.get('firsts', MAX_FIRSTS):
        return ('firsts', None)
    return ('ok', {
        'n': n, 'cells': ''.join(HEX[m] for m in cells), 'hand': HEX[hand],
        'piece': piece, 'tre': tre, 'rot': rotatable, 'min': d,
        'seg': segments(g, start, path, rotatable),
        'sol': [[op, h] for op, h in path],
        'firsts': firsts, 'nsol': nsol, 'ej': nej, 'minpick': minpick, 'needrot': needrot, 'tier': t['tier'],
    })


def overlap(a, b):
    if a['n'] != b['n']:
        return 0.0
    same = sum(1 for x, y in zip(a['cells'], b['cells']) if x == y)
    return same / len(a['cells'])


def median(xs):
    xs = sorted(xs)
    k = len(xs)
    return (xs[(k - 1) // 2] + xs[k // 2]) / 2.0


def pick(cands, t, strict3=True):
    """候補から10本を採る。最短手数の大きい順、同じなら初手の少ない順（同点は seed 順）。
    宝3個の段は「どの最短解でも3回に分けて拾う」盤を半分以上含める。
    最短の解の数が採った10本の中央値の NSOL_RATIO 倍を超える盤は外して採り直す。
    並びは易しい順（最短手数の昇順、同じなら初手・解の多い順）"""
    order = sorted(cands, key=lambda x: (-x['min'], x['firsts']))
    banned = set()
    want3 = PER_TIER // 2 if t['k'] >= 3 else 0     # 宝3個の段は、どの最短解でも3回に分けて拾う盤を半分以上
    while True:
        pool_ = [c for c in order if id(c) not in banned]
        three = [c for c in pool_ if c['minpick'] >= 3][:want3]
        if strict3 and len(three) < want3:
            return None                 # 3回に分けて拾う盤が半分に足りない → もう少し集める
        sel = three + [c for c in pool_ if c not in three][:PER_TIER - len(three)]
        if len(sel) < PER_TIER:
            return None                 # 候補が足りない（呼び出し側がもう1回り集める）
        med = median([c['nsol'] for c in sel])
        over = [c for c in sel if c['nsol'] > NSOL_RATIO * med]
        if not over:
            break
        for c in over:
            banned.add(id(c))
    sel.sort(key=lambda x: (x['min'], -x['firsts'], -x['nsol']))
    return sel


def seeds(seed, ti, k0, cnt):
    return [(ti, seed * 1000003 + ti * 7919 + k0 + j) for j in range(cnt)]


def survey(pool, count, seed, only):
    for ti, t in enumerate(TIERS):
        if only is not None and ti != only:
            continue
        t0 = time.time()
        res = pool.map(try_one, seeds(seed, ti, 0, count), chunksize=1)
        hist = {}
        for why, lv in res:
            hist[why] = hist.get(why, 0) + 1
        oks = [lv for why, lv in res if lv]
        extra = ''
        if oks:
            extra = ' 押し出しを含む最短解がある %d/%d' % (sum(1 for x in oks if x['ej']), len(oks))
        print('%s %dx%d rot=%d 宝%d  %s%s  %.1fs' % (t['tier'], t['n'], t['n'], t['rot'], t['k'],
              json.dumps(hist, ensure_ascii=False, sort_keys=True), extra, time.time() - t0))
        sys.stdout.flush()


def run_batch(pool, args, cache):
    """try_one を並列で回す。cache（seed→結果）にあれば使い回す（同じ seed なら結果は同じ）"""
    def stale(r):
        return r[1] is not None and 'minpick' not in r[1]     # 拾う手の数を測る前の結果
    key = lambda a: '%d:%d' % a                     # 段:seed（seed は段をまたいで重なりうる）
    todo = [a for a in args if key(a) not in cache or stale(cache[key(a)])]
    for a, r in zip(todo, pool.map(try_one, todo, chunksize=1)):
        cache[key(a)] = r
    return [cache[key(a)] for a in args]


def save_cache(path, cache):
    """試行結果を書き出す（途中で落ちても再開できるように、一時ファイルに書いてから置き換える）"""
    if not path:
        return
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False)
    os.replace(tmp, path)


def generate(pool, seed, sim_max, cache, only=None, keep=(), cache_path=None):
    """only = 作り直す段の番号の集合（None なら全部）。作り直さない段は keep（今の levels.json）から引き継ぐ"""
    levels = []
    report = []
    for ti, t in enumerate(TIERS):
        if only is not None and ti not in only:
            old = [lv for lv in keep if lv['tier'] == t['tier']]
            levels += old
            report.append('%s: 作り直さず引き継ぎ %d本' % (t['tier'], len(old)))
            print(report[-1])
            continue
        t0 = time.time()
        got = []
        tried = 0
        k = 0
        batch = 240
        want = PER_TIER * t['gather']
        sel = None
        while sel is None:
            while len(got) < want:
                for why, lv in run_batch(pool, seeds(seed, ti, k, batch), cache):
                    tried += 1
                    if lv is None or len(got) >= want:
                        continue
                    if any(overlap(lv, o) > sim_max for o in got + levels):
                        continue
                    got.append(lv)
                k += batch
                print('  %s 進み具合: 試行%d 条件を満たした%d本（3回に分けて拾う%d本）%.0fs' % (
                    t['tier'], tried, len(got), sum(1 for x in got if x['minpick'] >= 3), time.time() - t0))
                sys.stdout.flush()
                if (k // batch) % 5 == 0:
                    save_cache(cache_path, cache)
                if tried > t.get('max_tries', 100000):
                    raise SystemExit('%s: %d 本試して %d 本しか作れない' % (t['tier'], tried, len(got)))
            # 3回に分けて拾う盤は「できれば半分以上」：CAP3 試行までは集め足し、それでも足りなければあるだけ
            sel = pick(got, t, strict3=tried < CAP3)
            want += PER_TIER // 2           # 外れ値を外して足りなければ、もう少し集める
        passed = len(got)
        levels += sel
        report.append('%s: 条件を満たした%d本/%d試行（%.1f%%）から%d本 最短%d〜%d 押し出しを含む最短解あり%d本 %.0fs' % (
            t['tier'], passed, tried, 100.0 * passed / tried, len(sel),
            sel[0]['min'], sel[-1]['min'], sum(1 for x in sel if x['ej']), time.time() - t0))
        print(report[-1])
        sys.stdout.flush()
    return levels, report


def check_one(lv):
    """levels.json の1問を今の規則で測り直す → 食い違いの一覧（空なら合格）"""
    t = [x for x in TIERS if x['tier'] == lv['tier']][0]
    rotatable = lv['rot']
    g = geo(lv['n'])
    cells = [HEX.index(ch) for ch in lv['cells']]
    hand = HEX.index(lv['hand'])
    start = (to_bb(cells), CANON[hand] if rotatable else hand, tuple(lv['tre']), lv['piece'], -1)
    bad = []
    if collect(g, start[0], lv['piece'], start[2])[1] != start[2]:
        bad.append('最初から①とつながる')
    d, _ = solve(g, start, rotatable, lv['min'], t['S'])
    if d != lv['min']:
        bad.append('最短 %s' % d)
    if len(lv['sol']) != lv['min'] or segments(g, start, [tuple(x) for x in lv['sol']], rotatable) != lv['seg']:
        bad.append('解の手順・区間')
    nsol, firsts, nej, minpick = analyze(g, start, rotatable, lv['min'], t.get('SA', t['S']))
    if [nsol, firsts, nej, minpick] != [lv['nsol'], lv['firsts'], lv['ej'], lv.get('minpick')]:
        bad.append('解の数など %s' % [nsol, firsts, nej, minpick])
    if minpick < 2:
        bad.append('最後の1手でまとめて拾う解がある')
    if firsts > t.get('firsts', MAX_FIRSTS):
        bad.append('初手が多い')
    if greedy_reaches(g, start, rotatable, lv['min']):
        bad.append('素直な順で最短に届く')
    if rotatable and solve(g, (start[0], hand, start[2], lv['piece'], -1), 0, lv['min'], 6)[0] is not None:
        bad.append('回さずに最短で解ける')
    return bad


def check(pool, levels):
    res = pool.map(check_one, levels, chunksize=1)
    ng = 0
    for i, (lv, bad) in enumerate(zip(levels, res)):
        if bad:
            ng += 1
            print('#%d %s %s' % (i + 1, lv['tier'], ' / '.join(bad)))
    for t in TIERS:
        xs = [lv for lv in levels if lv['tier'] == t['tier']]
        if xs:
            med = median([x['nsol'] for x in xs])
            over = [x for x in xs if x['nsol'] > NSOL_RATIO * med]
            if over:
                ng += 1
                print('%s: 解の数が中央値の%d倍を超える問題 %d' % (t['tier'], NSOL_RATIO, len(over)))
    print('検査 %d 問：%s' % (len(levels), '全部合格' if not ng else '不合格 %d' % ng))
    return ng


def embed(levels):
    with open(HTML, encoding='utf-8') as f:
        src = f.read()
    body = ',\n'.join('  ' + json.dumps(lv, ensure_ascii=False, separators=(',', ':')) for lv in levels)
    new, cnt = re.subn(r'(/\* LEVELS-BEGIN[^\n]*\n)var LEVELS = \[.*?\];\n(/\* LEVELS-END \*/)',
                       lambda m: m.group(1) + 'var LEVELS = [\n' + body + '\n];\n' + m.group(2),
                       src, count=1, flags=re.S)
    if cnt != 1:
        raise SystemExit('index.html に LEVELS-BEGIN〜END が無い')
    with open(HTML, 'w', encoding='utf-8') as f:
        f.write(new)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seed', type=int, default=20261015)
    ap.add_argument('--survey', type=int, default=0, help='段ごとに N 本測るだけ')
    ap.add_argument('--tier', type=int, default=None, help='--survey で測る段（0始まり）')
    ap.add_argument('--sim', type=float, default=0.5, help='同じ大きさの盤で同じタイルの割合の上限')
    ap.add_argument('--no-embed', action='store_true')
    ap.add_argument('--embed-only', action='store_true')
    ap.add_argument('--check', action='store_true', help='levels.json を今の規則で測り直す（書き換えない）')
    ap.add_argument('--cache', default=None, help='試した結果を貯めて再実行で使い回す JSON（任意）')
    ap.add_argument('--only', default=None, help='作り直す段（名前か0始まりの番号・カンマ区切り）。ほかの段は今の levels.json から引き継ぐ')
    a = ap.parse_args()
    if a.embed_only:
        with open(OUT, encoding='utf-8') as f:
            embed(json.load(f)['levels'])
        return
    if a.check:
        with open(OUT, encoding='utf-8') as f:
            levels = json.load(f)['levels']
        with Pool() as pool:
            sys.exit(1 if check(pool, levels) else 0)
    with Pool() as pool:
        if a.survey:
            survey(pool, a.survey, a.seed, a.tier)
            return
        cache = {}
        if a.cache and os.path.exists(a.cache):
            with open(a.cache, encoding='utf-8') as f:
                cache = json.load(f)
        t0 = time.time()
        try:
            only = None
            keep = []
            if a.only is not None:
                names = [t['tier'] for t in TIERS]
                only = set(names.index(x) if x in names else int(x) for x in a.only.split(','))
                with open(OUT, encoding='utf-8') as f:
                    keep = json.load(f)['levels']
            levels, report = generate(pool, a.seed, a.sim, cache, only, keep, a.cache)
        finally:
            save_cache(a.cache, cache)
    total = time.time() - t0
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({'seed': a.seed, 'seconds': round(total, 1), 'report': report, 'levels': levels},
                  f, ensure_ascii=False, indent=1)
    if not a.no_embed:
        embed(levels)
    print('計 %d 問 %.1f 秒' % (len(levels), total))


if __name__ == '__main__':
    main()
