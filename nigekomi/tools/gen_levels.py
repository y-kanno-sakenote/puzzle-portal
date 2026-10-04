#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""にげこみ レベル生成器（Python3 標準ライブラリのみ）

点と線の地図の上で、鬼に捕まらずに家へ逃げ込む「鬼の動きが読める詰将棋」。
ランダムに地図と配置を作り、状態（あなたの点・鬼の点…）で BFS して最短手数を求め、
良い問題の条件を満たすものだけを段ごとに選んで出力する。規則は docs/spec.md が正。

規則（生成器と index.html の window.Nigekomi で同じもの）
  - あなたは隣の点へ必ず1歩動く（待てない）。家に着いたら勝ち（鬼の番は来ない。家に鬼がいても勝ち＝家の判定が先）
  - 家以外で鬼のいる点へ動いたら負け。そのあと鬼が動き、あなたのいる点に来たら負け
  - 鬼は「あなたまでの道のり（線の本数）が一番縮まる隣の点」へ1歩。家にも入れる
  - （2歩動く鬼は試したが入れない：勝てる地図 366 のうち素直な道で負けるのが 1 だけ＝回り道が効かない。
     play() は歩数を受け取れるまま残し、--stats で再測定できる）
  - 鬼どうしは互いを無視して動き、同じ点に重なってよい（だから動く順は結果に関係しない）
  - 同点（候補が2つ以上）のときは、鬼から見て真上（時計の12時）から時計回りに見て最初の点。
    ただし採用する地図は「遊び手が到達しうる全局面で、鬼の候補が常に1つ」に限る（--tie unique・既定）。
    この場合12時の規則は一度も使われない（念のための決めごと）

良い問題の条件
  - 勝てる（BFS で最短手数が出る）
  - 家への最短の道（鬼を無視した道のり）を、どれを選んでもそのまま進むと捕まる
  - 最初の鬼はあなたから道のり2以上
  - 既採用の地図と似すぎない（線の集合の Jaccard <= 0.5。左右反転も同じものとみなす）
  - いらない線が0本：消しても problem_ok が保たれ、かつ最短の筋の上の罠の手の数（trap_info）が減らない線が無い。
    生成した地図からいらない線を消し切って作る（prune。2026-10-02 オーナー実機「いらない道多すぎない？」→ qa 差し戻しで改訂）
  - 同型の重複0（canon）・読みどころの下限（READING_MIN）・初級以上は最初の一手が2通り以上
  - 地図の形（SHAPES・shape_map・shape_kept）と解き方の型（TYPES・solution_types）を持ち、段ごとに混ぜる（pick_tier）
  - 🔑（2026-10-02）：鍵の点に入ると拾い、持つまで家はただの点。局面は (あなた, 鍵, 鬼...)。初級〜上級は鍵あり。
    鍵ありの問題は罠のうち qa の branch 以外が半分以上（trap_kinds）。素直な道＝鍵への最短→家への最短
    鍵ありの問題は鍵を外すと最短手数が縮む（鍵が効いている）
  - 輪と分かれ道（2026-10-02）：削った後の輪（線−点+1）と分かれ道（次数3以上の点）の下限（RING_MIN・FORK_MIN）。
    生成の形は GEN_SHAPES、同点の出る地図は fix_ties で同点0にしてから使う
  - 使われる輪（ring_use）の下限・飾りの輪0・点の広がり（USED_RING_MIN・SPREAD_MIN）。同じ問題の判定に骨組み（core_of）も使う
  - 🏃の輪（あなたの歩みと罠の手の線だけで閉じる輪）1以上（YOU_RING_MIN・全段）
  - 鬼2体（上級）は (a) どちらの鬼を外しても最短手数が縮む（2体とも効いている）
    (b) 最短解のすべての筋で2体が重ならない（2026-10-02 qa 差し戻しで追加）

段の並べ方（難しさの目安＝勝率）
  random_rate():「すぐ捕まる手だけ避けて、あとはでたらめに選ぶ人」が40手以内に家へ着く確率（厳密計算）。
  段ごとに勝率の帯を重ねずに決める（TIERS）。段の中は勝率の高い順。

出力: JSON 配列 [{"nodes":[[c,r],...],"edges":[[i,j],...],"you":i,"home":i,"key":i または null,
                 "onis":[[i,歩数],...],"min":n,"rate":勝率の目安,"tier":"入門",
                 "shape":"輪","types":["誘い出し",...]}, ...]   types の先頭が主な型
  onis の2番目の数＝その鬼が1回の番に動く歩数（採用分はすべて1）。
  c=列(0..3), r=行(0..5)。点の番号は nodes の並び順。

使い方:
  python3 tools/gen_levels.py --seed 20261002 > tools/levels.json     # 12並列で約22分
  python3 tools/gen_levels.py --keep tools/levels.json --embed index.html > /dev/null   # 埋め込みだけ
  python3 tools/gen_levels.py --keep tools/levels.json --replace 24 > new.json          # 1問だけ差し替え（他は動かさない）
  # 2026-10-02 の🏃の輪の差し替えは --replace 6 --replace 9 --replace 18 --replace 20（段ごとにまとめて替える）
  python3 tools/gen_levels.py --stats 3000      # 採用率の測定だけ（出力しない）
"""

import argparse
import collections
import json
import math
import random
import sys
from collections import deque

COLS, ROWS = 4, 6
PER_TIER = 10
MAX_J = 0.5

# 段: (名前, 鬼の構成, 最短手数の下限, 上限)  鬼の構成は歩数のタプル
# 段: (名前, 鬼の構成, 最短手数の下限, 上限, 勝率の目安の下限, 上限)  鬼の構成は歩数のタプル
#   勝率の目安＝random_rate()。帯を重ねないので、上の段ほど必ず勝率が低い（段どうしの逆転が無い）
# 段: (名前, 使う候補 [(鬼の構成, 鍵あり)...], 最短の下限, 上限, 勝率の下限, 上限)  2026-10-02 鍵を導入
TIERS = [
    ("入門", [((1,), False)], 4, 6, 0.35, 0.75),          # 鍵なし（規則に慣れる）
    ("初級", [((1,), True)], 6, 14, 0.10, 0.35),
    ("中級", [((1,), True)], 8, 99, 0.03, 0.10),
    ("上級", [((1, 1), True), ((1,), True)], 9, 16, 0.001, 0.03),   # 鬼2体が基本（5問以上）、残りは鬼1体の難しいもの
    # 上級の下限 0.001・17手以上を外す：40手以内の勝率が 0 に張り付き、目安として働かないため
]
TWO_ONI_MIN = 5        # 上級のうち鬼2体の問題の下限
NONBRANCH_MIN = 0.5    # 鍵ありの問題は、罠のうち枝（qa_solver の branch）以外が半分以上
KEY_TIP_MAX = 5        # 鍵が行き止まりの先っぽ（次数1）にある問題は1段に5問まで
# 削った後の地図の下限（2026-10-02 オーナー「ただの円とかの一本道しかない」）
#   輪＝独立な輪の数（線−点+1）、分かれ道＝線が3本以上出ている点の数
RING_MIN = {"入門": 2, "初級": 2, "中級": 2, "上級": 2}
#   叩き台は中級・上級 3 だったが、輪3以上は格子と回の形にしか出ず「形3種類以上」を満たせないので 2 に下げ、
#   選抜で輪の多いものを優先する（pick_tier の並べ替えの先頭）
FORK_MIN = {"入門": 2, "初級": 3, "中級": 3, "上級": 3}


# 使われる輪の下限・飾りの輪・点の広がり（2026-10-02 qa 参考値と揃える）
USED_RING_MIN = {"入門": 1, "初級": 2, "中級": 2, "上級": 2}
YOU_RING_MIN = 1      # 🏃の輪（あなたの歩みと罠の手の線だけで閉じる輪）の下限・全段（2026-10-02）
SPREAD_MIN = (3, 4)   # 使っている格子の列数・行数の下限（4列中3列以上・6行中4行以上）


def _cyclomatic(edges):
    """線−点+成分数（点は edges に現れるものだけ数える）"""
    vs = {x for e in edges for x in e}
    par = {v: v for v in vs}
    def f(x):
        while par[x] != x:
            par[x] = par[par[x]]; x = par[x]
        return x
    for a, b in edges:
        par[f(a)] = f(b)
    return len(edges) - len(vs) + len({f(v) for v in vs})


def ring_use(g, you, home, onis, steps, with_you=False):
    """最短の筋であなた・鬼が通る線と、罠の手の線を合わせた「使われる線」。
    戻り値 (使われる線だけで閉じる輪の数, 使われない線だけでできた飾りの輪の数[, 🏃の輪の数])
    🏃の輪＝あなたの歩み（最短の筋）と罠の手の線だけで閉じる輪の数（鬼の歩みは入れない。2026-10-02 本体判断）"""
    start = g.start(you, onis)
    dist = {start: 0}; order = [start]; out = {}; wins = {}
    q = deque([start])
    while q:
        s = q.popleft(); out[s] = []; wins[s] = []
        for to in g.adj[s[0]]:
            r, ns, _ = g.play(s, to, home, steps)
            if r == 'win':
                wins[s].append(to)
            elif r is None:
                out[s].append((to, ns))
                if ns not in dist:
                    dist[ns] = dist[s] + 1; order.append(ns); q.append(ns)
    rev = {}
    for s_, lst in out.items():
        for _, ns in lst:
            rev.setdefault(ns, []).append(s_)
    dtw = {s_: 1 for s_ in order if wins[s_]}
    q = deque(dtw)
    while q:
        s_ = q.popleft()
        for pp in rev.get(s_, []):
            if pp not in dtw:
                dtw[pp] = dtw[s_] + 1; q.append(pp)
    best = dtw.get(start)
    U = set()
    Y = set()      # あなたの歩み（最短の筋）と罠の手の線だけ
    if best is not None:
        for s_ in order:
            if s_ not in dtw or dist[s_] + dtw[s_] != best:
                continue
            d = dtw[s_]
            for to, ns in out[s_]:
                if dtw.get(ns) == d - 1:
                    U.add(frozenset((s_[0], to)))
                    Y.add(frozenset((s_[0], to)))
                    for o, o2 in zip(s_[2:], ns[2:]):
                        if o != o2:
                            U.add(frozenset((o, o2)))
                if ns not in dtw:
                    U.add(frozenset((s_[0], to)))      # 罠の手
                    Y.add(frozenset((s_[0], to)))
            if d == 1:
                for to in wins[s_]:
                    U.add(frozenset((s_[0], to)))
                    Y.add(frozenset((s_[0], to)))
    E = [tuple(sorted((a, b))) for a in range(g.k) for b in g.adj[a] if a < b]
    used = [e for e in E if frozenset(e) in U]
    unused = [e for e in E if frozenset(e) not in U]
    mine = [e for e in E if frozenset(e) in Y]
    if with_you:
        return _cyclomatic(used), (_cyclomatic(unused) if unused else 0), _cyclomatic(mine)
    return _cyclomatic(used), (_cyclomatic(unused) if unused else 0)


def core_of(nodes, edges, you, home, onis, key):
    """役割の無い行き止まりの枝（駒・家・鍵のどれでもない次数1の点）を刈り続けた骨組み"""
    sp = {you, home} | set(onis) | ({key} if key is not None else set())
    E = [tuple(e) for e in edges]
    while True:
        deg = collections.Counter()
        for a, b in E:
            deg[a] += 1; deg[b] += 1
        leaf = {v for v, d in deg.items() if d == 1 and v not in sp}
        if not leaf:
            break
        E = [e for e in E if not (set(e) & leaf)]
    vs = sorted({x for e in E for x in e} | sp)
    ix = {v: k for k, v in enumerate(vs)}
    return ([nodes[v] for v in vs], [(ix[a], ix[b]) for a, b in E], ix[you], ix[home],
            [ix[o] for o in onis], (ix[key] if key is not None else None))


def ensure_metrics(c):
    """候補に、使われる輪・飾りの輪・骨組みの正準形・点の広がりを足す（あとから計算してよい値）"""
    if "_used" in c:
        return c
    nodes = c["_nodes"]; edges = c["_edges"]
    o = [x for x, _ in c["onis"]]; st = [n for _, n in c["onis"]]
    g = Game(nodes, edges, c["key"])
    c["_used"], c["_deco"], c["_yring"] = ring_use(g, c["you"], c["home"], o, st, with_you=True)
    cn, ce, cy, ch, co, ck = core_of(nodes, edges, c["you"], c["home"], o, c["key"])
    c["_core"] = canon(cn, ce, cy, ch, co, ck)
    c["_spread"] = (len({p[0] for p in nodes}), len({p[1] for p in nodes}))
    c["_rate_raw"] = random_rate(g, c["you"], c["home"], o, st)   # 帯の境で丸めの影響を受けないよう、丸める前の値で判定
    return c


def rings_forks(l):
    deg = collections.Counter()
    for a, b in l["edges"]:
        deg[a] += 1; deg[b] += 1
    return len(l["edges"]) - len(l["nodes"]) + 1, sum(1 for v in deg.values() if v >= 3)


def routes(l):
    """道を選ぶ余地の目安：始めの点から目標（鍵があれば鍵、無ければ家）まで、線を共有しない道が何本とれるか（最大流）"""
    n = len(l["nodes"])
    s, t = l["you"], (l["key"] if l.get("key") is not None else l["home"])
    cap = collections.defaultdict(int)
    adj = [set() for _ in range(n)]
    for a, b in l["edges"]:
        cap[(a, b)] += 1; cap[(b, a)] += 1
        adj[a].add(b); adj[b].add(a)
    flow = 0
    while True:
        par = {s: None}
        q = deque([s])
        while q and t not in par:
            v = q.popleft()
            for w in adj[v]:
                if w not in par and cap[(v, w)] > 0:
                    par[w] = v; q.append(w)
        if t not in par:
            return flow
        v = t
        while par[v] is not None:
            u = par[v]; cap[(u, v)] -= 1; cap[(v, u)] += 1; v = u
        flow += 1
# 勝率 0.75 超は「すぐ捕まる手を避けるだけでほぼ勝てる」ので、どの段にも採らない（線を減らすと増える）
# 読みどころ（trap_info の reading）の下限。初級以上は最初の一手が2通り以上（入門だけ1通りを許す）
READING_MIN = {"入門": 1, "初級": 2, "中級": 3, "上級": 4}
CHUNK = 20000   # 並列生成の1かたまりの試行数（かたまりごとに seed を決めるので並列数で結果が変わらない）
STATS_KINDS = [(1,), (1, 1), (2,)]   # --stats で測る鬼の構成（2 は2歩の鬼）


# ---------------------------------------------------------------- 幾何
def orient(a, b, c):
    v = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return (v > 0) - (v < 0)


def on_seg(a, b, p):
    return (min(a[0], b[0]) <= p[0] <= max(a[0], b[0])
            and min(a[1], b[1]) <= p[1] <= max(a[1], b[1]))


def seg_hits_point(a, b, p):
    """p が線分 ab の内側（端点以外）にある"""
    return p != a and p != b and orient(a, b, p) == 0 and on_seg(a, b, p)


def segs_cross(a, b, c, d):
    """線分 ab と cd が端点の共有以外で触れる"""
    shared = {a, b} & {c, d}
    if shared:
        if len(shared) == 2:
            return True
        s = shared.pop()
        o1 = b if a == s else a
        o2 = d if c == s else c
        # 共有端点から同じ向きに重なる場合だけ交差
        if orient(s, o1, o2) == 0:
            v1 = (o1[0] - s[0], o1[1] - s[1])
            v2 = (o2[0] - s[0], o2[1] - s[1])
            return v1[0] * v2[0] + v1[1] * v2[1] > 0
        return False
    o1, o2 = orient(a, b, c), orient(a, b, d)
    o3, o4 = orient(c, d, a), orient(c, d, b)
    if o1 != o2 and o3 != o4:
        return True
    if o1 == 0 and on_seg(a, b, c): return True
    if o2 == 0 and on_seg(a, b, d): return True
    if o3 == 0 and on_seg(c, d, a): return True
    if o4 == 0 and on_seg(c, d, b): return True
    return False


# ---------------------------------------------------------------- 地図
def random_map(rng, k, extra):
    """k 個の点と、交差しない短い線。木（k-1本）＋ extra 本の輪を目安に間引く"""
    pts = [(c, r) for r in range(ROWS) for c in range(COLS)]
    nodes = rng.sample(pts, k)
    nodes.sort(key=lambda p: (p[1], p[0]))
    cand = []
    for i in range(k):
        for j in range(i + 1, k):
            a, b = nodes[i], nodes[j]
            dx, dy = abs(a[0] - b[0]), abs(a[1] - b[1])
            if max(dx, dy) > 2:
                continue
            if any(seg_hits_point(a, b, p) for p in nodes):
                continue
            ln = math.hypot(dx, dy)
            cand.append((ln + rng.random() * 0.9, i, j))
    cand.sort()
    edges = []
    for _, i, j in cand:
        a, b = nodes[i], nodes[j]
        if any(segs_cross(a, b, nodes[x], nodes[y]) for x, y in edges):
            continue
        edges.append((i, j))
    # 連結を保ちながら間引く
    target = (k - 1) + extra
    rng.shuffle(edges)
    edges = list(edges)
    idx = 0
    while len(edges) > target and idx < len(edges):
        trial = edges[:idx] + edges[idx + 1:]
        if connected(k, trial):
            edges = trial
        else:
            idx += 1
    if not connected(k, edges):
        return None
    edges = sorted(tuple(sorted(e)) for e in edges)
    return nodes, edges


# ---------------------------------------------------------------- 地図の形（2026-10-02 オーナー「どれも同じに見える」）
SHAPES = ["格子", "輪", "はしご", "星", "八の字", "木と輪", "回", "田"]
GRID_EXTRA = (5, 10)  # 格子の輪の本数の目安（2026-10-02 輪を増やす版で (2, 6) から (5, 10) に）
# 生成に使う形（2026-10-02 オーナー「ただの円とかの一本道」：輪1つにしかならない「輪」「木と輪」を外し、回・田を足した）
GEN_SHAPES = ["格子", "はしご", "星", "八の字", "回", "田"]
# 入門（鍵なし）で使われる輪のある問題は 4〜6手では少ないので、出やすい形だけ試行を増やす（2026-10-02）
ROUNDS0_MORE = {"格子": 1200000, "回": 1200000, "田": 1200000}


def _on_grid(p):
    return 0 <= p[0] < COLS and 0 <= p[1] < ROWS


def _edge_ok(a, b, pts, edges):
    """a-b を足してよいか：縦横2マス以内・他の点の上を通らない・既存の線と交差しない"""
    if a == b or max(abs(a[0] - b[0]), abs(a[1] - b[1])) > 2:
        return False
    if any(seg_hits_point(a, b, p) for p in pts):
        return False
    return not any(segs_cross(a, b, c, d) for c, d in edges)


def _point_free(p, pts, edges):
    return p not in pts and not any(seg_hits_point(a, b, p) for a, b in edges)


def _rect_ring(rng, x0, y0, x1, y1, keep=()):
    """長方形の周の点（時計回り）。角と keep 以外の点を、間隔2以内を保って間引く"""
    ring = [(x, y0) for x in range(x0, x1)] + [(x1, y) for y in range(y0, y1)] + \
           [(x, y1) for x in range(x1, x0, -1)] + [(x0, y) for y in range(y1, y0, -1)]
    corners = {(x0, y0), (x1, y0), (x1, y1), (x0, y1)} | set(keep)
    out = []
    dropped_prev = False
    for p in ring:
        if p not in corners and not dropped_prev and rng.random() < 0.3:
            dropped_prev = True
            continue
        dropped_prev = False
        out.append(p)
    return out


def _cycle_edges(ring):
    return [(ring[i], ring[(i + 1) % len(ring)]) for i in range(len(ring))]


def _finish(rng, pts, edges, n_branch, n_chord=0):
    """骨組み（点と線・座標）を検査し、行き止まりの枝と弦を足して (nodes, edges) にする"""
    pts = list(dict.fromkeys(pts))
    ok_edges = []
    for a, b in edges:
        if not _edge_ok(a, b, pts, ok_edges):
            return None
        ok_edges.append((a, b))
    edges = ok_edges
    free = [(c, r) for r in range(ROWS) for c in range(COLS)]
    for _ in range(n_branch):
        rng.shuffle(free)
        for p in free:
            if not _point_free(p, pts, edges):
                continue
            anchors = [q for q in pts if _edge_ok(p, q, pts + [p], edges)]
            if anchors:
                q = rng.choice(anchors)
                pts.append(p); edges.append((p, q))
                break
    for _ in range(n_chord):
        pairs = [(a, b) for i, a in enumerate(pts) for b in pts[i + 1:]
                 if (a, b) not in edges and (b, a) not in edges and _edge_ok(a, b, pts, edges)]
        if pairs:
            edges.append(rng.choice(pairs))
    nodes = sorted(pts, key=lambda p: (p[1], p[0]))
    idx = {p: i for i, p in enumerate(nodes)}
    E = sorted(tuple(sorted((idx[a], idx[b]))) for a, b in edges)
    if not connected(len(nodes), E):
        return None
    return nodes, E


def shape_map(rng, shape):
    """形の型ごとに地図を作る。戻り値 (nodes, edges, 骨組みの線（座標の組の集合）, 形の情報) か None"""
    if shape == "格子":
        m = random_map(rng, rng.randint(10, 17), rng.randint(*GRID_EXTRA))
        return None if m is None else (m[0], m[1], set(), {})
    if shape == "回":
        # 外の長方形の周と内の長方形の周を、2〜4本の渡り線でつなぐ（輪がいくつもできる）
        ox0, oy0 = 0, rng.randint(0, 1)
        ox1, oy1 = 3, rng.randint(4, 5)
        outer = _rect_ring(rng, ox0, oy0, ox1, oy1)
        ix0, ix1 = 1, 2
        iy0 = rng.randint(oy0 + 1, oy1 - 2)
        iy1 = rng.randint(iy0 + 1, oy1 - 1)
        inner = [(x, y) for x in (ix0,) for y in range(iy0, iy1 + 1)] + [(ix1, y) for y in range(iy1, iy0 - 1, -1)]
        sk = _cycle_edges(outer) + _cycle_edges(inner)
        spokes = []
        cand = [(a, b) for a in inner for b in outer if max(abs(a[0] - b[0]), abs(a[1] - b[1])) == 1]
        rng.shuffle(cand)
        for a, b in cand:
            if len(spokes) >= rng.randint(2, 4):
                break
            if _edge_ok(a, b, outer + inner, sk + spokes):
                spokes.append((a, b))
        if len(spokes) < 2:
            return None
        m = _finish(rng, outer + inner, sk + spokes, rng.randint(0, 2))
        return None if m is None else (m[0], m[1], {frozenset(e) for e in sk + spokes}, {"min_rings": 2})
    if shape == "田":
        # 窓の並ぶ格子（3列×3〜4行の点を1マスおき or 詰めて並べ、縦横の線の一部を抜く）
        xs = rng.choice([[0, 1, 2], [1, 2, 3], [0, 1, 3], [0, 2, 3]])
        ys = sorted(rng.sample(range(ROWS), rng.choice([3, 4])))
        if any(b - a > 2 for a, b in zip(ys, ys[1:])):
            return None
        pts = [(x, y) for x in xs for y in ys]
        es = [((x, y), (x2, y)) for y in ys for x, x2 in zip(xs, xs[1:])] + \
             [((x, y), (x, y2)) for x in xs for y, y2 in zip(ys, ys[1:])]
        rng.shuffle(es)
        drop = rng.randint(1, max(1, len(es) // 4))
        keep = es[drop:]
        m = _finish(rng, pts, keep, rng.randint(0, 2))
        return None if m is None else (m[0], m[1], {frozenset(e) for e in keep}, {"min_rings": 2})
    if shape == "輪":
        w, h = rng.choice([2, 3]), rng.choice([3, 4, 5])
        x0, y0 = rng.randint(0, COLS - 1 - w), rng.randint(0, ROWS - 1 - h)
        ring = _rect_ring(rng, x0, y0, x0 + w, y0 + h)
        sk = _cycle_edges(ring)
        m = _finish(rng, ring, list(sk), rng.randint(2, 5))
        return None if m is None else (m[0], m[1], {frozenset(e) for e in sk}, {"rings": [sk]})
    if shape == "はしご":
        g = rng.choice([1, 2])
        a = rng.randint(0, COLS - 1 - g)
        h = rng.choice([3, 4, 5])
        y0 = rng.randint(0, ROWS - 1 - h)
        rows = list(range(y0, y0 + h + 1))
        rails = [(a, y) for y in rows] + [(a + g, y) for y in rows]
        sk_rail = [((x, y), (x, y + 1)) for x in (a, a + g) for y in rows[:-1]]
        rungs = rng.sample(rows, rng.randint(3, len(rows)))
        sk_rung = [((a, y), (a + g, y)) for y in rungs]
        m = _finish(rng, rails, sk_rail + sk_rung, rng.randint(1, 4))
        return None if m is None else (m[0], m[1], {frozenset(e) for e in sk_rail + sk_rung},
                                       {"rungs": [frozenset(e) for e in sk_rung]})
    if shape == "星":
        c = rng.choice([(1, 2), (2, 2), (1, 3), (2, 3)])
        dirs = [(0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1)]
        pick = sorted(rng.sample(range(8), rng.randint(4, 6)))
        pts, sk, arms = [c], [], []
        for di in pick:
            d = dirs[di]
            prev, arm = c, []
            for k in range(1, rng.randint(1, 3) + 1):
                p = (c[0] + d[0] * k, c[1] + d[1] * k)
                if not _on_grid(p):
                    break
                pts.append(p); sk.append((prev, p)); arm.append(p); prev = p
            if arm:
                arms.append(arm)
        if len(arms) < 4:
            return None
        # 隣り合う腕どうしを1〜2本の弦でつなぐ（中心を通る輪ができる）
        chords = []
        for _ in range(rng.randint(1, 2)):
            i = rng.randrange(len(arms))
            A, B = arms[i], arms[(i + 1) % len(arms)]
            a, b = rng.choice(A), rng.choice(B)
            if _edge_ok(a, b, pts, sk + chords):
                chords.append((a, b))
        if not chords:
            return None
        m = _finish(rng, pts, sk + chords, rng.randint(0, 3))
        return None if m is None else (m[0], m[1], {frozenset(e) for e in sk}, {"center": c})
    if shape == "八の字":
        xj, yj = rng.choice([1, 2]), rng.randint(1, 4)
        xa, ya = rng.randint(0, xj - 1), rng.randint(max(0, yj - 3), yj - 1)
        xb, yb = rng.randint(xj + 1, min(COLS - 1, xj + 2)), rng.randint(yj + 1, min(ROWS - 1, yj + 3))
        top = _rect_ring(rng, xa, ya, xj, yj)
        bot = _rect_ring(rng, xj, yj, xb, yb)
        if len(top) < 4 or len(bot) < 4:
            return None
        flip = rng.random() < 0.5
        f = (lambda p: (COLS - 1 - p[0], p[1])) if flip else (lambda p: p)
        top = [f(p) for p in top]; bot = [f(p) for p in bot]
        sk1, sk2 = _cycle_edges(top), _cycle_edges(bot)
        m = _finish(rng, top + bot, sk1 + sk2, rng.randint(1, 4))
        return None if m is None else (m[0], m[1], {frozenset(e) for e in sk1 + sk2}, {"rings": [sk1, sk2]})
    if shape == "木と輪":
        k = rng.randint(9, 15)
        allp = [(c, r) for r in range(ROWS) for c in range(COLS)]
        pts = [rng.choice(allp)]
        edges = []
        tries = 0
        while len(pts) < k and tries < 200:
            tries += 1
            p = rng.choice(allp)
            if not _point_free(p, pts, edges):
                continue
            anchors = [q for q in pts if _edge_ok(p, q, pts + [p], edges)]
            if anchors:
                pts.append(p); edges.append((p, rng.choice(anchors)))
        # 長さ4以上の輪を1つだけ作る弦
        nodes0 = pts
        adj = {p: [] for p in pts}
        for a, b in edges:
            adj[a].append(b); adj[b].append(a)
        def tdist(a, b):
            d = {a: 0}; q = deque([a])
            while q:
                v = q.popleft()
                for w in adj[v]:
                    if w not in d:
                        d[w] = d[v] + 1; q.append(w)
            return d[b]
        pairs = [(a, b) for i, a in enumerate(pts) for b in pts[i + 1:]
                 if b not in adj[a] and _edge_ok(a, b, pts, edges) and tdist(a, b) >= 3]
        if not pairs:
            return None
        edges.append(rng.choice(pairs))
        m = _finish(rng, nodes0, edges, 0)
        return None if m is None else (m[0], m[1], set(), {"one_ring": True})
    raise ValueError(shape)


def cycle_rank(nodes, edges):
    return len(edges) - len(nodes) + 1


def shape_kept(shape, nodes, edges, sk, info):
    """削った後も形の特徴が残っているか"""
    es = {frozenset((tuple(nodes[i]), tuple(nodes[j]))) for i, j in edges}
    if shape == "格子":
        return True
    if shape in ("輪", "八の字"):
        return all(all(frozenset(e) in es for e in ring) for ring in info["rings"])
    if shape == "はしご":
        return sum(1 for r in info["rungs"] if r in es) >= 2 and cycle_rank(nodes, edges) >= 1 and \
            sum(1 for e in sk if e in es) >= len(sk) - 2
    if shape == "星":
        c = info["center"]
        deg = sum(1 for e in es if c in e)
        return deg >= 3 and cycle_rank(nodes, edges) >= 1
    if shape == "木と輪":
        return cycle_rank(nodes, edges) == 1
    if shape in ("回", "田"):
        return cycle_rank(nodes, edges) >= info["min_rings"]
    return False


def connected(k, edges):
    adj = [[] for _ in range(k)]
    for i, j in edges:
        adj[i].append(j); adj[j].append(i)
    seen = {0}; st = [0]
    while st:
        v = st.pop()
        for w in adj[v]:
            if w not in seen:
                seen.add(w); st.append(w)
    return len(seen) == k


class Game:
    """局面は (あなたの点, 鍵を持っているか 0/1, 鬼の点...)。鍵の無い問題は最初から 1（家に入れば勝ち）"""
    def __init__(self, nodes, edges, key=None):
        self.nodes = nodes
        self.key = key
        self.k = len(nodes)
        self.adj = [[] for _ in range(self.k)]
        for i, j in edges:
            self.adj[i].append(j); self.adj[j].append(i)
        self.D = [self.bfs(s) for s in range(self.k)]
        # 12時から時計回りの角度（画面座標: x 右・y 下）
        self.ang = {}
        for v in range(self.k):
            for w in self.adj[v]:
                dx = nodes[w][0] - nodes[v][0]
                dy = nodes[w][1] - nodes[v][1]
                self.ang[(v, w)] = math.atan2(dx, -dy) % (2 * math.pi)

    def bfs(self, s):
        d = [-1] * self.k
        d[s] = 0
        q = deque([s])
        while q:
            v = q.popleft()
            for w in self.adj[v]:
                if d[w] < 0:
                    d[w] = d[v] + 1; q.append(w)
        return d

    def start(self, you, onis):
        return (you, 1 if self.key is None else 0) + tuple(onis)

    def oni_cands(self, o, y):
        dy = self.D[y]
        return [w for w in self.adj[o] if dy[w] == dy[o] - 1]

    def oni_step(self, o, y):
        c = self.oni_cands(o, y)
        if len(c) == 1:
            return c[0], False
        return min(c, key=lambda w: self.ang[(o, w)]), True

    def play(self, st, to, home, steps, home_first=True):
        """st=(you, 鍵, onis...)。戻り値 ('win'|'lose'|None, 新しい st, 同点が出たか)
        鍵を持たずに家へ入っても勝ちにならない（ただの点）。鍵の点に入るとその手で拾う。
        home_first=False は「🏠に鬼がいたら負け」の逆順（採用条件の確認にだけ使う）"""
        onis = st[2:]
        k = st[1]
        if to == home and k and (home_first or to not in onis):
            return 'win', st, False
        if to in onis:
            return 'lose', st, False
        if to == self.key:
            k = 1
        tie = False
        new = []
        caught = False
        for o, n in zip(onis, steps):
            for _ in range(n):
                o, t = self.oni_step(o, to)
                tie = tie or t
                if o == to:
                    caught = True
                    break
            new.append(o)
        ns = (to, k) + tuple(new)
        return ('lose' if caught else None), ns, tie


def analyze(g, you, home, onis, steps, home_first=True, start=None):
    """BFS。戻り値 dict(min, ties, nstates)。勝てなければ min=-1。start で途中の局面から始められる"""
    start = start or g.start(you, onis)
    dist = {start: 0}
    q = deque([start])
    best = -1
    ties = 0
    while q:
        s = q.popleft()
        for to in g.adj[s[0]]:
            r, ns, tie = g.play(s, to, home, steps, home_first)
            if tie:
                ties += 1
            if r == 'win':
                if best < 0:
                    best = dist[s] + 1
                continue
            if r == 'lose':
                continue
            if ns not in dist:
                dist[ns] = dist[s] + 1
                q.append(ns)
    return {"min": best, "ties": ties, "nstates": len(dist)}


def naive_loses(g, you, home, onis, steps):
    """素直な道（鬼を無視）をどれを選んでもそのまま進むと捕まるか。鍵の無い問題は家への最短の道、
    鍵のある問題は「鍵への最短の道→家への最短の道」（鍵を持つまでは鍵へ、持ったら家へ道のりが縮む隣だけ）"""
    def rec(s):
        v = s[0]
        dh = g.D[home] if s[1] else g.D[g.key]
        for to in g.adj[v]:
            if dh[to] != dh[v] - 1:
                continue
            r, ns, _ = g.play(s, to, home, steps)
            if r == 'win':
                return False
            if r is None and not rec(ns):
                return False
        return True
    return rec(g.start(you, onis))


def edge_set(nodes, edges, mirror=False):
    out = set()
    for i, j in edges:
        a, b = nodes[i], nodes[j]
        if mirror:
            a = (COLS - 1 - a[0], a[1]); b = (COLS - 1 - b[0], b[1])
        out.add(tuple(sorted((a, b))))
    return out


def jaccard(a, b):
    u = len(a | b)
    return len(a & b) / u if u else 0.0


def similar(lv, chosen):
    """既採用と似すぎ：線の集合の Jaccard > MAX_J（左右反転込み）か、役割つきグラフとして同型か、
    役割の無い行き止まりの枝を刈った骨組みが役割つきで同型（2026-10-02 qa：枝1本の付け替えだけの問題を除く）"""
    if any(c.get("_canon") is not None and c["_canon"] == lv.get("_canon") for c in chosen):
        return True
    if lv.get("_core") is not None and any(c.get("_core") == lv["_core"] for c in chosen):
        return True
    e = lv["_eset"]
    m = lv.get("_mset") or edge_set(lv["_nodes"], lv["_edges"], mirror=True)
    for c in chosen:
        ce = c["_eset"]
        if jaccard(e, ce) > MAX_J or jaccard(m, ce) > MAX_J:
            return True
    return False


# ---------------------------------------------------------------- 難しさの目安・上級の条件
HORIZON = 40   # でたらめに選ぶ人の手数の上限（これを超えたら負け扱い）


def random_rate(g, you, home, onis, steps, horizon=HORIZON):
    """「すぐ捕まる手だけ避けて、あとはでたらめに選ぶ人」が horizon 手以内に家へ着く確率。
    各局面で、動いた直後に負けにならない手（鬼のいる点へ入る・鬼の番で追いつかれる、を除く）から
    等確率で1つ選ぶ。家へ入る手も候補の1つ（見えていても特別扱いしない）。安全な手が無ければ負け。"""
    start = g.start(you, onis)
    trans = {}
    q = [start]
    while q:
        s = q.pop()
        if s in trans:
            continue
        outs = []
        for to in g.adj[s[0]]:
            r, ns, _ = g.play(s, to, home, steps)
            if r == 'win':
                outs.append(None)
            elif r is None:
                outs.append(ns)
                if ns not in trans:
                    q.append(ns)
        trans[s] = outs
    P = {s: 0.0 for s in trans}
    for _ in range(horizon):
        P = {s: (sum(1.0 if n is None else P[n] for n in outs) / len(outs) if outs else 0.0)
             for s, outs in trans.items()}
    return P[start]


def optimal_states(g, you, home, onis, steps):
    """最短解のどれかの筋に乗る局面の集合（始めの局面を含む）"""
    start = g.start(you, onis)
    dist = {start: 0}
    order = [start]
    q = deque([start])
    best = -1
    while q:
        s = q.popleft()
        for to in g.adj[s[0]]:
            r, ns, _ = g.play(s, to, home, steps)
            if r == 'win' and best < 0:
                best = dist[s] + 1
            if r is None and ns not in dist:
                dist[ns] = dist[s] + 1
                order.append(ns)
                q.append(ns)
    if best < 0:
        return set(), -1
    good = set()
    for s in reversed(order):
        d = dist[s]
        if d >= best:
            continue
        for to in g.adj[s[0]]:
            r, ns, _ = g.play(s, to, home, steps)
            if (r == 'win' and d + 1 == best) or (r is None and ns in good and dist[ns] == d + 1):
                good.add(s)
                break
    return good, best


def two_oni_ok(g, you, home, onis, steps, m):
    """上級の条件 (a) どちらの鬼を外しても最短手数が変わる (b) 最短解の筋で2体が重ならない"""
    for i in range(len(onis)):
        rest = [o for j, o in enumerate(onis) if j != i]
        rs = [n for j, n in enumerate(steps) if j != i]
        if analyze(g, you, home, rest, rs)["min"] == m:
            return False
    good, best = optimal_states(g, you, home, onis, steps)
    if best != m:
        return False
    return all(len(set(s[2:])) == len(s) - 2 for s in good)


# ---------------------------------------------------------------- 生成
# ---------------------------------------------------------------- 線を意味のあるものだけに減らす
def problem_ok(nodes, edges, you, home, onis, key, steps, want_min, want_traps=None):
    """「問題が変わらない」の判定（2026-10-02）。(1) 最短手数 want_min で解ける (2) 新しい地図での
    家への最短の道はすべて素直に進むと負け (3) 到達しうる全局面で鬼の行き先が1つ (4) 鬼2体なら (a)(b)。
    地図が連結であることも要る。戻り値 (ok, Game, analyze の結果)"""
    if not connected(len(nodes), edges):
        return False, None, None
    g = Game(nodes, edges, key)
    a = analyze(g, you, home, onis, steps)
    if a["min"] != want_min or a["ties"]:
        return False, g, a
    if not naive_loses(g, you, home, onis, steps):
        return False, g, a
    if len(steps) > 1 and not two_oni_ok(g, you, home, onis, list(steps), want_min):
        return False, g, a
    # 判定の順を逆（🏠に鬼がいたら負け）にしても最短が同じ（spec の注記を保つ）
    if analyze(g, you, home, onis, steps, home_first=False)["min"] != want_min:
        return False, g, a
    if want_traps is not None and trap_info(g, you, home, onis, steps)["traps"] < want_traps:
        return False, g, a
    return True, g, a


def trap_info(g, you, home, onis, steps):
    """最短の筋の上の「罠の手」（すぐ捕まらないのに、その先もう勝てない局面へ落ちる手）。
    traps   = 最短解のどれかの筋に乗る局面すべての罠の手の合計（線を消すときに減らしてはいけない数）
    reading = 読みどころ＝最短の筋の上で、罠の手が1つ以上ある手番の数。筋が複数あれば一番少ない筋の値
    first_trap = 最初の局面に罠の手があるか"""
    start = g.start(you, onis)
    dist = {start: 0}
    order = [start]
    out = {}
    wins = {}
    q = deque([start])
    while q:
        s = q.popleft()
        out[s] = []
        wins[s] = False
        for to in g.adj[s[0]]:
            r, ns, _ = g.play(s, to, home, steps)
            if r == 'win':
                wins[s] = True
            elif r is None:
                out[s].append(ns)
                if ns not in dist:
                    dist[ns] = dist[s] + 1
                    order.append(ns)
                    q.append(ns)
    # 勝ちまでの残り手数（逆向き）
    rev = {}
    for s, ns_list in out.items():
        for ns in ns_list:
            rev.setdefault(ns, []).append(s)
    dtw = {s: 1 for s in order if wins[s]}
    q = deque(dtw)
    while q:
        s = q.popleft()
        for p in rev.get(s, []):
            if p not in dtw:
                dtw[p] = dtw[s] + 1
                q.append(p)
    if start not in dtw:
        return {"traps": 0, "reading": 0, "first_trap": False}
    best = dtw[start]
    opt = [s for s in order if s in dtw and dist[s] + dtw[s] == best]
    nt = {s: sum(1 for ns in out[s] if ns not in dtw) for s in opt}
    R = {}
    for s in sorted(opt, key=lambda x: dtw[x]):
        h = 1 if nt[s] else 0
        if dtw[s] == 1:
            R[s] = h
        else:
            R[s] = h + min(R[ns] for ns in out[s]
                           if ns in R and dtw.get(ns) == dtw[s] - 1 and dist.get(ns) == dist[s] + 1)
    return {"traps": sum(nt.values()), "reading": R[start], "first_trap": nt[start] > 0}


TIE_FIX = True    # 同点の出る地図も、線を消して同点0にしてから使う（2026-10-02 輪の多い地図は同点が出やすいため）


def fix_ties(rng, nodes, edges, you, home, onis, key, steps, max_steps=12):
    """同点（鬼の候補が2つ以上）が出る回数が減る線を1本ずつ消し、0になったら返す。勝てなくなる・
    連結でなくなる消し方はしない。0にできなければ None"""
    cur = (nodes, edges, you, home, onis, key)
    g = Game(nodes, edges, key)
    t = analyze(g, you, home, onis, steps)["ties"]
    for _ in range(max_steps):
        if t == 0:
            return cur
        order = list(range(len(cur[1])))
        rng.shuffle(order)
        best = None
        for ei in order:
            r = remove_edge(*cur, ei)
            if r is None or not connected(len(r[0]), r[1]):
                continue
            g2 = Game(r[0], r[1], r[5])
            a2 = analyze(g2, r[2], r[3], r[4], steps)
            if a2["min"] < 0:
                continue
            if best is None or a2["ties"] < best[0]:
                best = (a2["ties"], r)
                if a2["ties"] == 0:
                    break
        if best is None or best[0] >= t:
            return None
        t, cur = best
    return cur if t == 0 else None


def remove_edge(nodes, edges, you, home, onis, key, ei):
    """ei 番目の線を消す。孤立した点は点ごと消して番号を詰める。駒・家・鍵の点が孤立するなら None"""
    rest = [e for i, e in enumerate(edges) if i != ei]
    deg = [0] * len(nodes)
    for i, j in rest:
        deg[i] += 1; deg[j] += 1
    if any(deg[v] == 0 for v in [you, home] + list(onis) + ([key] if key is not None else [])):
        return None
    keep = [v for v in range(len(nodes)) if deg[v] > 0]
    idx = {v: n for n, v in enumerate(keep)}
    return ([nodes[v] for v in keep], sorted((idx[i], idx[j]) for i, j in rest),
            idx[you], idx[home], [idx[o] for o in onis], (idx[key] if key is not None else None))


def removable(nodes, edges, you, home, onis, key, steps, want_min, keep_traps=True):
    """いらない線の番号の一覧。keep_traps=False は旧定義（罠の数を見ない・2026-10-02 前半）"""
    out = []
    t0 = trap_info(Game(nodes, edges, key), you, home, onis, steps)["traps"] if keep_traps else None
    for ei in range(len(edges)):
        r = remove_edge(nodes, edges, you, home, onis, key, ei)
        if r is not None and problem_ok(*r, steps, want_min, t0)[0]:
            out.append(ei)
    return out


def cur_traps(cur, steps):
    return trap_info(Game(cur[0], cur[1], cur[5]), cur[2], cur[3], cur[4], steps)["traps"]


PRUNE_TRIES = 4
PRUNE_PREFER = "few"   # "few"=残る線が一番少ない順、"rings"=独立な輪が一番多い順（2026-10-02）


def prune(rng, nodes, edges, you, home, onis, key, steps, want_min, tries=None):
    """いらない線（消しても problem_ok が保たれ、かつ最短の筋の上の罠の手の数が減らない線）を
    1本ずつ消し、消せなくなるまで続ける（2026-10-02 qa 差し戻し：罠を作る線は残す）。消す順を
    ランダムに tries 通り試し、残る線が一番少ない（同じなら点が少ない）ものを返す"""
    best = None
    for _ in range(tries or PRUNE_TRIES):
        cur = (nodes, edges, you, home, onis, key)
        while True:
            order = list(range(len(cur[1])))
            rng.shuffle(order)
            t0 = cur_traps(cur, steps)
            for ei in order:
                r = remove_edge(*cur, ei)
                if r is not None and problem_ok(*r, steps, want_min, t0)[0]:
                    cur = r
                    break
            else:
                break
        if PRUNE_PREFER == "rings":
            sc = lambda c: (-(len(c[1]) - len(c[0])), len(c[0]))   # 輪の数（線−点）が多い、同じなら点が少ない
        else:
            sc = lambda c: (len(c[1]), len(c[0]))
        if best is None or sc(cur) < sc(best):
            best = cur
    return best


def unused(g, you, home, onis, steps):
    """最短解のどの筋でも、あなたも鬼も一度も通らない線と点の数"""
    good, best = optimal_states(g, you, home, onis, steps)
    start = g.start(you, onis)
    dist = {start: 0}
    q = deque([start])
    while q:
        s = q.popleft()
        for to in g.adj[s[0]]:
            r, ns, _ = g.play(s, to, home, steps)
            if r is None and ns not in dist:
                dist[ns] = dist[s] + 1; q.append(ns)
    used_e, used_v = set(), {home}
    for s in good:
        d = dist[s]
        used_v.update(s)
        for to in g.adj[s[0]]:
            r, ns, _ = g.play(s, to, home, steps)
            if (r == 'win' and d + 1 == best) or (r is None and ns in good and dist[ns] == d + 1):
                used_e.add(frozenset((s[0], to))); used_v.add(to)
                if r is None:
                    for o, n in zip(s[2:], steps):
                        # 鬼の通った線（1歩ずつたどり直す）
                        for _ in range(n):
                            o2, _t = g.oni_step(o, to)
                            used_e.add(frozenset((o, o2))); used_v.add(o2)
                            o = o2
                            if o == to:
                                break
    ne = sum(len(a) for a in g.adj) // 2
    return ne - len(used_e), g.k - len(used_v)


# ---------------------------------------------------------------- 解き方の型（2026-10-02）
TYPES = ["誘い出し", "輪でまく", "枝でやり過ごす"]   # ① ② ③。主な型はこの順で先に当てはまるもの


def edge_kinds(g, home):
    """有向の線 (u,v) の種類（qa_solver の罠の型の分類と同じ定義）：橋でなければ 'ring'。
    橋なら v 側に家があれば 'home'、v 側が木（行き止まりの枝）なら 'branch'、それ以外 'back'"""
    kind = {}
    for u in range(g.k):
        for v in g.adj[u]:
            seen = {v}; st = [v]
            while st:
                x = st.pop()
                for y in g.adj[x]:
                    if {x, y} == {u, v} or y in seen:
                        continue
                    seen.add(y); st.append(y)
            if u in seen:
                kind[(u, v)] = 'ring'
            elif home in seen:
                kind[(u, v)] = 'home'
            else:
                ne = sum(len(g.adj[x]) for x in seen) // 2
                kind[(u, v)] = 'branch' if ne == len(seen) - 1 else 'back'
    return kind


def solution_types(g, you, home, onis, steps, limit=20000):
    """最短解のすべての筋に共通する型の集合と、家から遠ざかる手数（筋ごとの最大の、筋どうしの最小）。
    ① 誘い出し：家までの道のりが始めより2以上増える（鬼を引きつける）うえに、一度通った点をもう一度通って
       戻ってくる（引きつけた鬼の脇を抜けて家へ向かう）
    ② 輪でまく：筋の中に、互いに異なる k(>=4) 個の点を続けて通り、最初と最後の点が線でつながる区間がある
       （長さ k の輪を k-1 本以上ぐるりと回る）
    ③ 枝でやり過ごす：筋の上の罠の手に、行き止まりの枝へ入る手（edge_kinds が 'branch'）がある
    罠の手＝すぐ捕まらないのに、その先もう勝てない局面へ落ちる手。筋が多すぎれば None
    （叩き台では①②にも「その場面の罠の手」を求めたが、鬼はすぐ後ろを追ってくるので家の方へ引き返す手・
      逆回りの手はほぼ「すぐ捕まる手」になり罠にならない。①の罠つきは候補約2000中0〜3件だった）"""
    start = g.start(you, onis)
    dist = {start: 0}; order = [start]; out = {}; wins = {}
    q = deque([start])
    while q:
        s = q.popleft(); out[s] = []; wins[s] = []
        for to in g.adj[s[0]]:
            r, ns, _ = g.play(s, to, home, steps)
            if r == 'win':
                wins[s].append(to)
            elif r is None:
                out[s].append((to, ns))
                if ns not in dist:
                    dist[ns] = dist[s] + 1; order.append(ns); q.append(ns)
    rev = {}
    for s, lst in out.items():
        for _, ns in lst:
            rev.setdefault(ns, []).append(s)
    dtw = {s: 1 for s in order if wins[s]}
    q = deque(dtw)
    while q:
        s = q.popleft()
        for pp in rev.get(s, []):
            if pp not in dtw:
                dtw[pp] = dtw[s] + 1; q.append(pp)
    lines = []
    def rec(s, path):
        if len(lines) > limit:
            return
        d = dtw[s]
        if d == 1:
            for to in wins[s]:
                lines.append(path + [(s, to)])
            return
        for to, ns in out[s]:
            if dtw.get(ns) == d - 1:
                rec(ns, path + [(s, to)])
    rec(start, [])
    if len(lines) > limit:
        return None
    kind = edge_kinds(g, home)
    Dh = g.D[home]
    common = None
    away_min = None
    for line in lines:
        traps = [(s, to) for s, _ in line for to, ns in out[s] if ns not in dtw]
        pos = [s[0] for s, _ in line] + [home]
        # 目標までの道のり：鍵を持つまでは鍵、持ったら家。区間（鍵の前・後）ごとに始めより何手遠ざかったか
        flags = [s[1] for s, _ in line] + [1]
        tgt = [g.D[home][p] if f else g.D[g.key][p] for p, f in zip(pos, flags)]
        away, base, seen_phase, revisit = 0, tgt[0], set(), False
        for i, (p, f) in enumerate(zip(pos, flags)):
            if i > 0 and f != flags[i - 1]:
                base, seen_phase = tgt[i], set()
            away = max(away, tgt[i] - base)
            if p in seen_phase:
                revisit = True
            seen_phase.add(p)
        t = set()
        # ①
        if away >= 2 and revisit:
            t.add(TYPES[0])
        # ②
        done = False
        for i in range(len(pos)):
            for j in range(i + 3, len(pos)):
                seg = pos[i:j + 1]
                if len(set(seg)) != len(seg):
                    break
                if seg[0] in g.adj[seg[-1]]:
                    done = True
                    break
            if done:
                break
        if done:
            t.add(TYPES[1])
        # ③
        if any(kind[(s[0], to)] == 'branch' for s, to in traps):
            t.add(TYPES[2])
        common = t if common is None else common & t
        away_min = away if away_min is None else min(away_min, away)
    return {"types": sorted(common, key=TYPES.index), "away": away_min, "nlines": len(lines)}


def trap_kinds(g, you, home, onis, steps):
    """最短の筋に乗る局面すべての罠の手を種類別に数える。
    qa: qa_solver と同じ線の種類（edge_kinds：ring/home/back/branch。鍵は見ない）
    key: 鍵を考えた呼び名（2026-10-02 鍵の導入で追加）
      鍵へ急ぐ＝鍵を持たずに鍵への道のりが縮む罠／家へ急ぐ＝鍵を持って家への道のりが縮む罠／
      輪の向き＝橋でない線で上のどちらでもない罠／枝＝行き止まりの枝（鍵も家も無い木）へ入る罠／その他"""
    start = g.start(you, onis)
    dist = {start: 0}; order = [start]; out = {}; wins = {}
    q = deque([start])
    while q:
        s = q.popleft(); out[s] = []; wins[s] = False
        for to in g.adj[s[0]]:
            r, ns, _ = g.play(s, to, home, steps)
            if r == 'win':
                wins[s] = True
            elif r is None:
                out[s].append((to, ns))
                if ns not in dist:
                    dist[ns] = dist[s] + 1; order.append(ns); q.append(ns)
    rev = {}
    for s, lst in out.items():
        for _, ns in lst:
            rev.setdefault(ns, []).append(s)
    dtw = {s: 1 for s in order if wins[s]}
    q = deque(dtw)
    while q:
        s = q.popleft()
        for pp in rev.get(s, []):
            if pp not in dtw:
                dtw[pp] = dtw[s] + 1; q.append(pp)
    qa, kk = collections.Counter(), collections.Counter()
    if start not in dtw:
        return {"qa": {}, "key": {}}
    best = dtw[start]
    kind = edge_kinds(g, home)
    kind_k = edge_kinds(g, g.key) if g.key is not None else None
    for s in order:
        if s not in dtw or dist[s] + dtw[s] != best:
            continue
        for to, ns in out[s]:
            if ns in dtw:
                continue
            u = s[0]
            qa[kind[(u, to)]] += 1
            tgt = g.D[home] if s[1] else g.D[g.key]
            if tgt[to] < tgt[u]:
                kk["家へ急ぐ" if s[1] else "鍵へ急ぐ"] += 1
            elif kind[(u, to)] == 'ring':
                kk["輪の向き"] += 1
            elif kind[(u, to)] == 'branch' and (kind_k is None or kind_k[(u, to)] == 'branch'):
                kk["枝"] += 1
            else:
                kk["その他"] += 1
    return {"qa": dict(qa), "key": dict(kk)}


def make_record(nodes, edges, you, home, onis, steps, g, a):
    rate = random_rate(g, you, home, onis, list(steps))
    ti = trap_info(g, you, home, onis, steps)
    # 最初の一手のうち、まだ勝てる手の数（少ないほど読みが要る）
    wfirst = 0
    for to in g.adj[you]:
        r, ns, _ = g.play(g.start(you, onis), to, home, steps)
        if r == 'win' or (r is None and analyze(g, None, home, None, steps, start=ns)["min"] >= 0):
            wfirst += 1
    return {"nodes": [list(p) for p in nodes], "edges": [list(e) for e in edges],
            "you": you, "home": home, "onis": [[o, n] for o, n in zip(onis, steps)],
            "min": a["min"], "_nodes": nodes, "_edges": edges,
            "_eset": edge_set(nodes, edges), "_mset": edge_set(nodes, edges, mirror=True), "_states": a["nstates"],
            "_detour": a["min"] - (g.D[you][home] if g.key is None else g.D[you][g.key] + g.D[g.key][home]),
            "_wfirst": wfirst, "rate": round(rate, 4),
            "_reading": ti["reading"], "_traps": ti["traps"], "_first": len(g.adj[you]),
            "_canon": canon(nodes, edges, you, home, onis, g.key), "key": g.key,
            "_tk": trap_kinds(g, you, home, onis, steps)}


def canon(nodes, edges, you, home, onis, key=None):
    """駒・家の役割つきグラフの正準形（同型なら同じ値）。点の色を道のりの分布で細分してから、
    同じ色の中の並べ方を全部試して辞書順最小の隣接行列を採る（点は最大17・色が細かいので軽い）"""
    n = len(nodes)
    adj = [set() for _ in range(n)]
    for i, j in edges:
        adj[i].add(j); adj[j].add(i)
    role = ['.'] * n
    role[you] = 'Y'; role[home] = 'H'
    if key is not None:
        role[key] += 'K'
    for o in onis:
        role[o] += 'O'
    color = [(role[v], len(adj[v])) for v in range(n)]
    for _ in range(n):   # 色の細分（WL）
        new = [(color[v], tuple(sorted(color[w] for w in adj[v]))) for v in range(n)]
        keys = sorted(set(new))
        new = [keys.index(c) for c in new]
        if len(set(new)) == len(set(color)):
            color = new
            break
        color = new
    keys = sorted(set(color))
    groups = [[v for v in range(n) if color[v] == c] for c in keys]
    best = [None]
    import itertools as _it
    def rec(gi, order):
        if gi == len(groups):
            pos = {v: k for k, v in enumerate(order)}
            code = (tuple(role[v] for v in order),
                    tuple(sorted(tuple(sorted((pos[i], pos[j]))) for i, j in edges)))
            if best[0] is None or code < best[0]:
                best[0] = code
            return
        for perm in _it.permutations(groups[gi]):
            rec(gi + 1, order + list(perm))
    total = 1
    for gr in groups:
        total *= math.factorial(len(gr))
    if total > 50000:          # 対称性が高すぎる地図は正準形を諦め、別物として扱わない（採らない）
        return None
    rec(0, [])
    return best[0]


def try_one(rng, steps, tie_mode, stat, shape="格子", do_prune=True, need_type=True, use_key=False):
    m = shape_map(rng, shape)
    if m is None:
        stat["bad_map"] += 1
        return None
    nodes, edges, sk, info = m
    k = len(nodes)
    need = 2 + len(steps) + (1 if use_key else 0)
    if k < need:
        return None
    # 形のある地図は、駒と家（と鍵）を骨組みの点に置きやすくする（削った後も形が残りやすい）
    skel = sorted({i for i, p in enumerate(nodes) for e in sk if tuple(p) in e})
    pool = skel if (len(skel) >= need and rng.random() < 0.7) else list(range(k))
    ids = rng.sample(pool, need)
    you, home, onis = ids[0], ids[1], ids[2:2 + len(steps)]
    key = ids[-1] if use_key else None
    g = Game(nodes, edges, key)
    stat["tried"] += 1
    if key is None and g.D[you][home] < 2:
        return None
    if key is not None and (g.D[key][home] < 2 or g.D[you][key] < 2):   # 鍵は家と同じ点・隣は不可
        return None
    if any(g.D[o][you] < 2 for o in onis):
        return None
    a = analyze(g, you, home, onis, steps)
    if a["min"] < 0:
        return None
    stat["winnable"] += 1
    if not naive_loses(g, you, home, onis, steps):
        return None
    stat["naive_lose"] += 1
    if a["ties"] and tie_mode == "unique" and TIE_FIX:
        # 同点が出る線を消して同点0の地図にしてから、いつもの条件をかけ直す（2026-10-02 輪を増やす版）
        r = fix_ties(rng, nodes, edges, you, home, onis, key, steps)
        if r is None:
            stat["tie_bad"] += 1
            return None
        stat["tie_fixed"] += 1
        nodes, edges, you, home, onis, key = r
        g = Game(nodes, edges, key)
        a = analyze(g, you, home, onis, steps)
        if a["min"] < 0 or not naive_loses(g, you, home, onis, steps):
            return None
        if key is not None and (g.D[key][home] < 2 or g.D[you][key] < 2):
            return None
        if any(g.D[o][you] < 2 for o in onis):
            return None
    if a["ties"]:
        stat["tie_bad"] += 1
        if tie_mode == "unique":
            return None
    if len(steps) > 1:
        if not two_oni_ok(g, you, home, onis, list(steps), a["min"]):
            return None
        stat["two_ok"] += 1
    if do_prune and tie_mode == "unique":
        ok, g, a = problem_ok(nodes, edges, you, home, onis, key, steps, a["min"])
        if not ok:          # 判定の順を逆にすると最短が変わる地図
            return None
        nodes, edges, you, home, onis, key = prune(rng, nodes, edges, you, home, onis, key, steps, a["min"])
        ok, g, a = problem_ok(nodes, edges, you, home, onis, key, steps, a["min"])
        assert ok
        if not shape_kept(shape, nodes, edges, sk, info):
            stat["shape_lost"] += 1
            return None
    if key is not None:
        # 鍵が効いている：鍵を外すと最短手数が縮む（2026-10-02 qa 指摘：鍵が解の通り道の上にあるだけの問題を除く）
        if analyze(Game(nodes, edges, None), you, home, onis, steps)["min"] >= a["min"]:
            stat["key_idle"] += 1
            return None
    st = solution_types(g, you, home, onis, steps)
    if st is None or (need_type and not st["types"]):
        stat["no_type"] += 1
        return None
    stat["ok"] += 1
    rec = make_record(nodes, edges, you, home, onis, steps, g, a)
    rec["shape"] = shape
    rec["types"] = st["types"]
    rec["_away"] = st["away"]
    rec["_keydeg"] = len(g.adj[key]) if key is not None else None
    return rec


def new_stat():
    return {"tried": 0, "bad_map": 0, "winnable": 0, "naive_lose": 0, "tie_bad": 0, "two_ok": 0, "shape_lost": 0, "no_type": 0, "key_idle": 0, "tie_fixed": 0, "ok": 0}


def run_chunk(job):
    """並列生成の1かたまり（multiprocessing から呼ぶので最上位に置く）"""
    steps, use_key, shape, seed, n, tie_mode = job
    rng = random.Random(seed)
    st = new_stat()
    out = []
    for _ in range(n):
        lv = try_one(rng, steps, tie_mode, st, shape, use_key=use_key)
        if lv is not None:
            out.append(lv)
    return steps, use_key, shape, st, out


def collect(seed, tie_mode, rounds, log, workers=None):
    """(鬼の構成, 鍵の有無, 形) ごとに rounds 回試し、候補を集める。rounds は {(構成, 鍵, 形): 回数}。
    戻り値の候補は {(構成, 鍵): [...]}"""
    import multiprocessing
    order = sorted(rounds, key=lambda k: (len(k[0]), k[1], SHAPES.index(k[2])))
    jobs = []
    for ki, (steps, use_key, shape) in enumerate(order):
        total = rounds[(steps, use_key, shape)]
        for c in range((total + CHUNK - 1) // CHUNK):
            jobs.append((steps, use_key, shape, seed * 10000 + ki * 1000 + c,
                         min(CHUNK, total - c * CHUNK), tie_mode))
    with multiprocessing.Pool(workers) as pool:
        results = pool.map(run_chunk, jobs, chunksize=1)
    cands = {}
    stats = {}
    for steps, use_key, shape, st, out in results:
        cands.setdefault((steps, use_key), []).extend(out)
        acc = stats.setdefault((steps, use_key, shape), new_stat())
        for k in st:
            acc[k] += st[k]
    for kk in order:
        st = stats[kk]
        log("鬼%d体 %s %s: 試行 %d / 勝てる %d / 素直に負ける %d / 同点あり %d / 形が崩れた %d / 型なし %d / 採用候補 %d" % (
            len(kk[0]), "鍵あり" if kk[1] else "鍵なし", kk[2], st["tried"], st["winnable"], st["naive_lose"],
            st["tie_bad"], st["shape_lost"], st["no_type"], st["ok"]))
    return cands, stats


MAX_SAME_SHAPE = 4   # 1段の中で同じ形は4問まで


def arrange(picked):
    """勝率の高い順に並べ、同じ勝率の中で並べ替えて、隣どうしが同じ形にならない並びを返す（無ければ None）"""
    rest = sorted(picked, key=lambda l: -l["rate"])
    out = []
    while rest:
        top = rest[0]["rate"]
        block = [l for l in rest if l["rate"] == top]
        cnt = collections.Counter(l["shape"] for l in block)
        cand = [l for l in block if not out or l["shape"] != out[-1]["shape"]]
        if not cand:
            return None
        nxt = max(cand, key=lambda l: (cnt[l["shape"]], -l["min"]))
        out.append(nxt)
        rest.remove(nxt)
    return out


def pick_tier(rng, name, pool, chosen, attempts=1500):
    """1段10問を選ぶ。条件：主な型①②③をそれぞれ2問以上（候補が足りない型は取れるだけ）・形3種類以上・
    同じ形は4問まで・勝率順に並べて隣が同じ形にならない・既採用と似すぎない。手数の偏りも抑える"""
    if name == "上級":
        key = lambda l: (-min(rings_forks(l)[0], 4), l["rate"], l["_wfirst"])
    else:
        key = lambda l: (-min(rings_forks(l)[0], 4), l["_wfirst"], -l["_detour"], -l["_states"])
    base = sorted(pool, key=key)
    best = None
    for at in range(attempts):
        # 2回目からは品質順に揺らぎを足す（揺らぎは回を追うごとに大きく）
        w = len(base) * min(1.0, at / 300.0)
        order = base if at == 0 else [l for _, l in sorted(((k + rng.random() * w, l) for k, l in enumerate(base)),
                                                           key=lambda t: t[0])]
        picked, shp, mins = [], collections.Counter(), collections.Counter()
        def can(c):
            return (shp[c["shape"]] < MAX_SAME_SHAPE and mins[c["min"]] < (5 if name == "入門" else 4)
                    and sum(1 for p in picked if p["_keydeg"] == 1) + (c["_keydeg"] == 1) <= KEY_TIP_MAX
                    and not similar(c, chosen + picked))
        def take(c):
            picked.append(c); shp[c["shape"]] += 1; mins[c["min"]] += 1
        if name == "上級":   # 鬼2体を先に TWO_ONI_MIN 問
            for c in order:
                if sum(1 for p in picked if len(p["onis"]) == 2) >= TWO_ONI_MIN:
                    break
                if len(c["onis"]) == 2 and can(c):
                    take(c)
        for t in TYPES:
            got = 0
            for c in order:
                if got >= 2:
                    break
                if c["types"][0] == t and c not in picked and can(c) and len(picked) < PER_TIER:
                    take(c); got += 1
        # 形の種類を先に3つ以上に
        for c in order:
            if len(picked) >= PER_TIER or len(shp) >= 3:
                break
            if c["shape"] not in shp and c not in picked and can(c):
                take(c)
        for c in sorted(order, key=lambda l: shp[l["shape"]]):
            if len(picked) >= PER_TIER:
                break
            if c not in picked and can(c):
                take(c)
        if len(picked) < PER_TIER or len(shp) < 3:
            continue
        if name == "上級" and sum(1 for p in picked if len(p["onis"]) == 2) < TWO_ONI_MIN:
            continue
        seq = arrange(picked)
        if seq is None:
            continue
        tc = collections.Counter(l["types"][0] for l in seq)
        score = (sum(min(tc[t], 2) for t in TYPES), len(shp))
        if best is None or score > best[0]:
            best = (score, seq)
        if score[0] == 6:
            break
    return None if best is None else best[1]


def nonbranch(c):
    q = c["_tk"]["qa"]
    t = sum(q.values())
    return (t - q.get("branch", 0)) / t if t else 0.0


def select(rng, cands, log):
    chosen = []
    out = []
    for name, kinds, mlo, mhi, rlo, rhi in TIERS:
        pool = tier_pool(cands, name)
        seq = pick_tier(rng, name, pool, chosen)
        if seq is None:
            log("!! %s が選べない（候補 %d）" % (name, len(pool)))
            continue
        log("%s: 候補 %d / 最短 %s / 勝率 %s" % (name, len(pool), [p["min"] for p in seq], [p["rate"] for p in seq]))
        log("    形 %s" % [p["shape"] for p in seq])
        log("    型 %s" % ["/".join(p["types"]) for p in seq])
        log("    鬼 %s 鍵の次数 %s" % ([len(p["onis"]) for p in seq], [p["_keydeg"] for p in seq]))
        chosen += seq
        for p in seq:
            p["tier"] = name
            out.append(p)
    return out


def tier_pool(cands, name):
    """select と同じ条件で、その段の候補を返す"""
    for nm, kinds, mlo, mhi, rlo, rhi in TIERS:
        if nm != name:
            continue
        return [c for kd in kinds for c in cands.get(kd, [])
                if mlo <= c["min"] <= mhi and rlo <= c["rate"] < rhi
                and c["_reading"] >= READING_MIN[name] and c["_canon"] is not None
                and (name == "入門" or c["_first"] >= 2)
                and (c["key"] is None or nonbranch(c) >= NONBRANCH_MIN)
                and rings_forks(c)[0] >= RING_MIN[name] and rings_forks(c)[1] >= FORK_MIN[name]
                and ensure_metrics(c)["_used"] >= USED_RING_MIN[name] and c["_deco"] == 0
                and c["_yring"] >= YOU_RING_MIN
                and c["_spread"][0] >= SPREAD_MIN[0] and c["_spread"][1] >= SPREAD_MIN[1]
                and rlo <= c["_rate_raw"] < rhi]
    raise ValueError(name)


def replace_some(cands, levels, idxs, log):
    """levels の idxs（同じ段）だけを差し替える。他の段の問題は動かさない。
    差し替える各問題と同じ主な型の候補から、既存の問題と似すぎず、段の並び（勝率順・隣が同じ形にならない）と
    形・鍵の配分を保てる組を選ぶ。同じ段の残りの問題の位置が動かない組を優先する"""
    import itertools
    name = levels[idxs[0]]["tier"]
    assert all(levels[i]["tier"] == name for i in idxs)
    def full(l):   # 埋め込み済みの問題を similar / arrange で扱える形にする
        nodes = [tuple(p) for p in l["nodes"]]
        edges = [tuple(e) for e in l["edges"]]
        g = Game(nodes, edges, l.get("key"))
        o = [x for x, _ in l["onis"]]
        return dict(l, _nodes=nodes, _edges=edges, _eset=edge_set(nodes, edges),
                    _mset=edge_set(nodes, edges, mirror=True),
                    _canon=canon(nodes, edges, l["you"], l["home"], o, l.get("key")),
                    _core=canon(*core_of(nodes, edges, l["you"], l["home"], o, l.get("key"))),
                    _keydeg=(len(g.adj[l["key"]]) if l.get("key") is not None else None))
    others_f = [full(l) for i, l in enumerate(levels) if i not in idxs]
    tier_idx = [i for i, l in enumerate(levels) if l["tier"] == name]
    rest = [full(levels[i]) for i in tier_idx if i not in idxs]
    pool = [c for c in tier_pool(cands, name) if not similar(c, others_f)]
    pool.sort(key=lambda l: (l["_wfirst"], -l["_detour"], -l["_states"]))
    def search(same_type):
        lists = [[c for c in pool if (not same_type) or c["types"][0] == levels[i]["types"][0]] for i in idxs]
        best = None
        for combo in itertools.product(*lists):
            if len(set(map(id, combo))) < len(combo):
                continue
            if any(similar(x, list(combo[:k])) for k, x in enumerate(combo)):
                continue
            group = rest + list(combo)
            shp = collections.Counter(l["shape"] for l in group)
            if len(shp) < 3 or max(shp.values()) > MAX_SAME_SHAPE:
                continue
            if sum(1 for l in group if l["_keydeg"] == 1) > KEY_TIP_MAX:
                continue
            # 元の位置のまま入るか
            seq_same = list(rest)
            pos = [tier_idx.index(i) for i in idxs]
            for p_, x in sorted(zip(pos, combo), key=lambda t: t[0]):
                seq_same.insert(p_, x)
            rates = [l["rate"] for l in seq_same]
            if rates == sorted(rates, reverse=True) and all(
                    seq_same[k]["shape"] != seq_same[k + 1]["shape"] for k in range(len(seq_same) - 1)):
                best = (combo, seq_same, True)
                break
            if best is None:
                seq = arrange(group)
                if seq is not None:
                    best = (combo, seq, False)

        return best
    best = search(True)
    if best is None:
        # 同じ主な型の候補が無ければ、型を問わずに選ぶ（型の配分が変わる。ログに出す）
        best = search(False)
        if best is not None:
            log("  （同じ主な型の候補が無いので、型を問わずに選んだ）")
    if best is None:
        raise SystemExit("差し替えられる候補が無い")
    combo, seq, kept = best
    new = list(levels)
    ids = set(map(id, combo))
    for i, l in zip(tier_idx, seq):
        if id(l) in ids:
            l["tier"] = name
            new[i] = public(l)
        else:
            new[i] = {k: l[k] for k in levels[0].keys()}
    log("%s の %s を差し替え（%s）: %s" % (name, idxs, "残りの位置はそのまま" if kept else "段の中の並びが動いた",
        [(c["min"], c["rate"], c["shape"], c["types"][0]) for c in combo]))
    return new


def public(lv):
    return {k: lv[k] for k in ("nodes", "edges", "you", "home", "key", "onis", "min", "rate", "tier", "shape", "types")}


def embed(path, levels):
    body = "var LEVELS = [\n" + ",\n".join(
        "  " + json.dumps(l, ensure_ascii=False, separators=(",", ":")) for l in levels) + "\n];\n"
    with open(path, encoding="utf-8") as f:
        html = f.read()
    b = html.index("/* LEVELS-BEGIN")
    b = html.index("\n", b) + 1
    e = html.index("/* LEVELS-END")
    html = html[:b] + body + html[e:]
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20261002)
    ap.add_argument("--rounds0", type=int, default=200000, help="鍵なし鬼1体（入門）の、形1種類あたりの試行回数（ROUNDS0_MORE の形は多め）")
    ap.add_argument("--rounds1", type=int, default=150000, help="鍵あり鬼1体の、形1種類あたりの試行回数")
    ap.add_argument("--rounds2", type=int, default=300000, help="鍵あり鬼2体の、形1種類あたりの試行回数（条件が厳しいので多め）")
    ap.add_argument("--workers", type=int, default=None, help="並列数（既定=CPU数。結果は変わらない）")
    ap.add_argument("--tie", choices=["unique", "clock"], default="unique",
                    help="unique=到達しうる全局面で鬼の候補が1つの地図だけ採る / clock=12時から時計回りで決める")
    ap.add_argument("--stats", type=int, metavar="N", help="採用率の測定だけ（出力しない）")
    ap.add_argument("--keep", metavar="JSON", help="生成し直さずこの JSON を使う")
    ap.add_argument("--embed", metavar="HTML", help="LEVELS-BEGIN / LEVELS-END の間へ埋め込む")
    ap.add_argument("--replace", type=int, action="append", metavar="IDX",
                    help="--keep の問題のうちこの添字（同じ段）だけ、同じ seed で候補を集め直して差し替える（何度でも指定可）")
    args = ap.parse_args()
    log = lambda *a: print(*a, file=sys.stderr)
    rng = random.Random(args.seed)

    if args.stats:
        collect(args.seed, "clock", {(k, False, "格子"): args.stats for k in STATS_KINDS}, log, args.workers)
        return

    rounds = {}
    for sh in GEN_SHAPES:
        rounds[((1,), False, sh)] = ROUNDS0_MORE.get(sh, args.rounds0)
        rounds[((1,), True, sh)] = args.rounds1
        rounds[((1, 1), True, sh)] = args.rounds2
    if args.keep:
        with open(args.keep, encoding="utf-8") as f:
            levels = json.load(f)
        if args.replace:
            cands, _ = collect(args.seed, args.tie, rounds, log, workers=args.workers)
            by_tier = {}
            for idx in args.replace:
                by_tier.setdefault(levels[idx]["tier"], []).append(idx)
            for t_, idxs in by_tier.items():
                levels = replace_some(cands, levels, sorted(idxs), log)
    else:
        cands, _ = collect(args.seed, args.tie, rounds, log, workers=args.workers)
        levels = [public(l) for l in select(rng, cands, log)]
    if args.embed:
        embed(args.embed, levels)
        log("埋め込み完了:", args.embed)
    sys.stdout.write("[\n" + ",\n".join(
        " " + json.dumps(l, ensure_ascii=False, separators=(",", ":")) for l in levels) + "\n]\n")


if __name__ == "__main__":
    main()
