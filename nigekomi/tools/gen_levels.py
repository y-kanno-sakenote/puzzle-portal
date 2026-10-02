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
  - 鬼2体（上級）は (a) どちらの鬼を外しても最短手数が縮む（2体とも効いている）
    (b) 最短解のすべての筋で2体が重ならない（2026-10-02 qa 差し戻しで追加）

段の並べ方（難しさの目安＝勝率）
  random_rate():「すぐ捕まる手だけ避けて、あとはでたらめに選ぶ人」が40手以内に家へ着く確率（厳密計算）。
  段ごとに勝率の帯を重ねずに決める（TIERS）。段の中は勝率の高い順。

出力: JSON 配列 [{"nodes":[[c,r],...],"edges":[[i,j],...],"you":i,"home":i,
                 "onis":[[i,歩数],...],"min":n,"rate":勝率の目安,"tier":"入門"}, ...]
  onis の2番目の数＝その鬼が1回の番に動く歩数（採用分はすべて1）。
  c=列(0..3), r=行(0..5)。点の番号は nodes の並び順。

使い方:
  python3 tools/gen_levels.py --seed 20261002 > tools/levels.json     # 12並列で約2分
  python3 tools/gen_levels.py --keep tools/levels.json --embed index.html > /dev/null   # 埋め込みだけ
  python3 tools/gen_levels.py --stats 3000      # 採用率の測定だけ（出力しない）
"""

import argparse
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
TIERS = [
    ("入門", (1,), 4, 6, 0.25, 0.70),
    ("初級", (1,), 6, 9, 0.10, 0.25),
    ("中級", (1,), 9, 99, 0.035, 0.10),
    ("上級", (1, 1), 8, 99, 0.0, 0.035),   # 鬼2体（2体とも効いていて、最短解の筋で重ならない）
]
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
    def __init__(self, nodes, edges):
        self.nodes = nodes
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

    def oni_cands(self, o, y):
        dy = self.D[y]
        return [w for w in self.adj[o] if dy[w] == dy[o] - 1]

    def oni_step(self, o, y):
        c = self.oni_cands(o, y)
        if len(c) == 1:
            return c[0], False
        return min(c, key=lambda w: self.ang[(o, w)]), True

    def play(self, st, to, home, steps):
        """st=(you, onis...)。戻り値 ('win'|'lose'|None, 新しい st, 同点が出たか)"""
        onis = st[1:]
        if to == home:
            return 'win', st, False
        if to in onis:
            return 'lose', st, False
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
        ns = (to,) + tuple(new)
        return ('lose' if caught else None), ns, tie


def analyze(g, you, home, onis, steps):
    """BFS。戻り値 dict(min, ties, nstates, wins_first)。勝てなければ min=-1"""
    start = (you,) + tuple(onis)
    dist = {start: 0}
    q = deque([start])
    best = -1
    ties = 0
    while q:
        s = q.popleft()
        for to in g.adj[s[0]]:
            r, ns, tie = g.play(s, to, home, steps)
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
    """家への最短の道（鬼を無視）をどれを選んでもそのまま進むと捕まるか"""
    dh = g.D[home]
    def rec(s):
        v = s[0]
        for to in g.adj[v]:
            if dh[to] != dh[v] - 1:
                continue
            r, ns, _ = g.play(s, to, home, steps)
            if r == 'win':
                return False
            if r is None and not rec(ns):
                return False
        return True
    return rec((you,) + tuple(onis))


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
    e = edge_set(lv["_nodes"], lv["_edges"])
    m = edge_set(lv["_nodes"], lv["_edges"], mirror=True)
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
    start = (you,) + tuple(onis)
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
    start = (you,) + tuple(onis)
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
    return all(len(set(s[1:])) == len(s) - 1 for s in good)


# ---------------------------------------------------------------- 生成
def try_one(rng, steps, tie_mode, stat):
    k = rng.randint(10, 17)
    extra = rng.randint(2, 6)
    m = random_map(rng, k, extra)
    if m is None:
        stat["bad_map"] += 1
        return None
    nodes, edges = m
    g = Game(nodes, edges)
    ids = rng.sample(range(k), 2 + len(steps))
    you, home, onis = ids[0], ids[1], ids[2:]
    stat["tried"] += 1
    if g.D[you][home] < 2:
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
    if a["ties"]:
        stat["tie_bad"] += 1
        if tie_mode == "unique":
            return None
    if len(steps) > 1:
        if not two_oni_ok(g, you, home, onis, list(steps), a["min"]):
            return None
        stat["two_ok"] += 1
    stat["ok"] += 1
    rate = random_rate(g, you, home, onis, list(steps))
    # 最初の一手のうち、まだ勝てる手の数（少ないほど読みが要る）
    wfirst = 0
    for to in g.adj[you]:
        r, ns, _ = g.play((you,) + tuple(onis), to, home, steps)
        if r == 'win' or (r is None and analyze(g, ns[0], home, ns[1:], steps)["min"] >= 0):
            wfirst += 1
    return {"nodes": [list(p) for p in nodes], "edges": [list(e) for e in edges],
            "you": you, "home": home, "onis": [[o, n] for o, n in zip(onis, steps)],
            "min": a["min"], "_nodes": nodes, "_edges": edges,
            "_eset": edge_set(nodes, edges), "_states": a["nstates"],
            "_detour": a["min"] - g.D[you][home], "_wfirst": wfirst, "rate": round(rate, 4)}


def new_stat():
    return {"tried": 0, "bad_map": 0, "winnable": 0, "naive_lose": 0, "tie_bad": 0, "two_ok": 0, "ok": 0}


def run_chunk(job):
    """並列生成の1かたまり（multiprocessing から呼ぶので最上位に置く）"""
    steps, seed, n, tie_mode = job
    rng = random.Random(seed)
    st = new_stat()
    out = []
    for _ in range(n):
        lv = try_one(rng, steps, tie_mode, st)
        if lv is not None:
            out.append(lv)
    return steps, st, out


def collect(seed, tie_mode, rounds, log, kinds=None, workers=None):
    """鬼の構成ごとに rounds 回試し、候補を集める。rounds は {構成: 回数}"""
    import multiprocessing
    kinds = kinds or [(1,), (1, 1)]
    jobs = []
    for ki, steps in enumerate(kinds):
        total = rounds[steps]
        for c in range((total + CHUNK - 1) // CHUNK):
            jobs.append((steps, seed * 1000 + ki * 100 + c, min(CHUNK, total - c * CHUNK), tie_mode))
    with multiprocessing.Pool(workers) as pool:
        results = pool.map(run_chunk, jobs)
    cands = {steps: [] for steps in kinds}
    stats = {steps: new_stat() for steps in kinds}
    for steps, st, out in results:
        cands[steps] += out
        for k in st:
            stats[steps][k] += st[k]
    for steps in kinds:
        st = stats[steps]
        log("鬼 %s: 試行 %d / 勝てる %d / 素直に負ける %d / 同点あり %d / 2体とも効いて重ならない %d / 採用候補 %d" % (
            steps, st["tried"], st["winnable"], st["naive_lose"], st["tie_bad"], st["two_ok"], st["ok"]))
    return cands, stats


def select(rng, cands, log):
    chosen = []
    out = []
    for name, steps, mlo, mhi, rlo, rhi in TIERS:
        pool = [c for c in cands.get(steps, [])
                if mlo <= c["min"] <= mhi and rlo <= c["rate"] < rhi]
        rng.shuffle(pool)
        picked = []
        if len(steps) > 1:
            # 上級は勝率の低い順
            pool.sort(key=lambda l: (l["rate"], l["_wfirst"]))
            for c in pool:
                if len(picked) >= PER_TIER:
                    break
                if not similar(c, chosen + picked):
                    picked.append(c)
        else:
            # 最初の一手で勝ちにつながる手が少ない・回り道が大きい・状態が多いものを優先し、最短手数を散らす
            pool.sort(key=lambda l: (l["_wfirst"], -l["_detour"], -l["_states"]))
            used_min = {}
            for c in pool:
                if len(picked) >= PER_TIER:
                    break
                if used_min.get(c["min"], 0) >= 4:
                    continue
                if similar(c, chosen + picked):
                    continue
                picked.append(c)
                used_min[c["min"]] = used_min.get(c["min"], 0) + 1
        if len(picked) < PER_TIER:
            log("!! %s が %d 本しか集まらない（候補 %d）" % (name, len(picked), len(pool)))
        # 段の中は勝率の目安の高い順（やさしい順）
        picked.sort(key=lambda l: (-l["rate"], l["min"]))
        log("%s: %d本（候補 %d） 最短 %s 勝率 %s" % (name, len(picked), len(pool),
            [p["min"] for p in picked], [p["rate"] for p in picked]))
        chosen += picked
        for p in picked:
            p["tier"] = name
            out.append(p)
    return out


def public(lv):
    return {k: lv[k] for k in ("nodes", "edges", "you", "home", "onis", "min", "rate", "tier")}


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
    ap.add_argument("--rounds1", type=int, default=60000, help="鬼1体の試行回数")
    ap.add_argument("--rounds2", type=int, default=1200000, help="鬼2体の試行回数（条件が厳しいので多め）")
    ap.add_argument("--workers", type=int, default=None, help="並列数（既定=CPU数。結果は変わらない）")
    ap.add_argument("--tie", choices=["unique", "clock"], default="unique",
                    help="unique=到達しうる全局面で鬼の候補が1つの地図だけ採る / clock=12時から時計回りで決める")
    ap.add_argument("--stats", type=int, metavar="N", help="採用率の測定だけ（出力しない）")
    ap.add_argument("--keep", metavar="JSON", help="生成し直さずこの JSON を使う")
    ap.add_argument("--embed", metavar="HTML", help="LEVELS-BEGIN / LEVELS-END の間へ埋め込む")
    args = ap.parse_args()
    log = lambda *a: print(*a, file=sys.stderr)
    rng = random.Random(args.seed)

    if args.stats:
        collect(args.seed, "clock", {k: args.stats for k in STATS_KINDS}, log, STATS_KINDS, args.workers)
        return

    if args.keep:
        with open(args.keep, encoding="utf-8") as f:
            levels = json.load(f)
    else:
        cands, _ = collect(args.seed, args.tie, {(1,): args.rounds1, (1, 1): args.rounds2}, log,
                           workers=args.workers)
        levels = [public(l) for l in select(rng, cands, log)]
    if args.embed:
        embed(args.embed, levels)
        log("埋め込み完了:", args.embed)
    sys.stdout.write("[\n" + ",\n".join(
        " " + json.dumps(l, ensure_ascii=False, separators=(",", ":")) for l in levels) + "\n]\n")


if __name__ == "__main__":
    main()
