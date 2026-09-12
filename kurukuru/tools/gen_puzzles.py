#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""くるくる 問題生成器（Python3 標準ライブラリのみ）

    python3 gen_puzzles.py                        # 生成して JSON を標準出力へ
    python3 gen_puzzles.py --out puzzles.json     # JSON に書き出す
    python3 gen_puzzles.py --embed ../index.html  # PUZZLES-BEGIN/END の間だけ差し替え
    python3 gen_puzzles.py --seed 123 --budget 600
    python3 gen_puzzles.py --survey               # 盤サイズごとの実測（閾値決め用・生成はしない）

手順（docs/spec.md）
  1. 全マスを覆う木をランダムに作る（辺をシャッフルした Kruskal）。木の辺がそのまま
     マスの腕になる。盤の外へ出る腕は作らない
  2. ソルバーで解を2つまで数え、ちょうど1つのものだけ採用
  3. 正解から各マスをランダムに回して出題の向きを作る。最初から正解のマスが
     半分以上の盤は捨てる

腕のビット  N=1 E=2 S=4 W=8（16進1桁）。時計回りの90度回転は1ビット左巡回。

一意性（憲法）
  向きの重複を同一視する。十字は4通りとも同じ形・同じ接続なので1通りとして扱い、
  直線は2通り、端・かど・三叉は4通りが全部違う。この「異なる向き」だけを候補にして
  数えるので、数えているのは実質「異なる接続のしかた」そのものになる。

枝刈り（行優先でマスを決めていく）
  ・縁のマスは外向きの腕を持てない
  ・左・上の既に決めたマスと、向かい合う辺の腕の有無が一致しなければならない
  ・輪ができたら打ち切る（腕の総数は木と同じなので、輪があると必ずどこかが切れる）
  ・まだ決めていない領域へ腕が1本も向いていない塊ができたら打ち切る（もう広がれない）

難度
  上の探索が解を2つ数え切るまでに踏んだノード数（nodes）で4段階に分ける。
  閾値は --survey の実測で決めて docs/spec.md に書き戻す。
"""

import argparse
import json
import random
import re
import sys
import time

N_BIT, E_BIT, S_BIT, W_BIT = 1, 2, 4, 8
HEX = "0123456789abcdef"


def rot(m, t=1):
    """時計回りに t 回（90度ずつ）。N->E->S->W->N は1ビット左巡回"""
    t %= 4
    for _ in range(t):
        m = ((m << 1) | (m >> 3)) & 15
    return m


_VAR = {}


def variants(m):
    """向きの重複を同一視した「異なる向き」の一覧（十字なら1個、直線なら2個）"""
    if m in _VAR:
        return _VAR[m]
    out = []
    x = m
    for _ in range(4):
        if x not in out:
            out.append(x)
        x = rot(x)
    _VAR[m] = out
    return out


def to_hex(cells):
    return "".join(HEX[m] for m in cells)


def from_hex(s):
    return [HEX.index(ch) for ch in s]


# ---------------------------------------------------------------- 木を作る
def random_tree(rnd, n):
    """全マスを覆う木をランダムに作る。戻り値は各マスの腕（マスク）の一覧"""
    N = n * n
    edges = []
    for i in range(N):
        r, c = divmod(i, n)
        if c + 1 < n:
            edges.append((i, i + 1, E_BIT, W_BIT))
        if r + 1 < n:
            edges.append((i, i + n, S_BIT, N_BIT))
    rnd.shuffle(edges)
    parent = list(range(N))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    cells = [0] * N
    used = 0
    for a, b, ba, bb in edges:
        ra, rb = find(a), find(b)
        if ra == rb:
            continue
        parent[ra] = rb
        cells[a] |= ba
        cells[b] |= bb
        used += 1
        if used == N - 1:
            break
    return cells


# ---------------------------------------------------------------- ソルバー
def count_solutions(n, cells, limit=2):
    """解を limit 個まで数える。戻り値 (個数, ノード数, 最初の解)

    cells は各マスの腕のマスク（向きは問わない。回しても腕の本数と形は変わらない）"""
    N = n * n
    allowed = []
    for i in range(N):
        r, c = divmod(i, n)
        vs = []
        for m in variants(cells[i]):
            if r == 0 and (m & N_BIT):
                continue
            if r == n - 1 and (m & S_BIT):
                continue
            if c == 0 and (m & W_BIT):
                continue
            if c == n - 1 and (m & E_BIT):
                continue
            vs.append(m)
        if not vs:
            return 0, 0, None
        allowed.append(vs)

    parent = list(range(N))
    sz = [1] * N
    opn = [0] * N          # その塊から「まだ決めていない領域」へ向いている腕の本数
    cur = [0] * N
    log = []
    state = {"nodes": 0, "cnt": 0, "first": None}

    def find(x):
        while parent[x] != x:
            x = parent[x]
        return x

    def rollback(mark):
        while len(log) > mark:
            kind, x, v = log.pop()
            if kind == 0:
                opn[x] = v
            elif kind == 1:
                parent[x] = v
            else:
                sz[x] = v

    def dfs(i):
        if state["cnt"] >= limit:
            return
        if i == N:
            if sz[find(0)] == N:
                state["cnt"] += 1
                if state["first"] is None:
                    state["first"] = list(cur)
            return
        r, c = divmod(i, n)
        up = i - n if r > 0 else -1
        lf = i - 1 if c > 0 else -1
        need_n = (cur[up] & S_BIT) != 0 if up >= 0 else False
        need_w = (cur[lf] & E_BIT) != 0 if lf >= 0 else False
        for m in allowed[i]:
            if up >= 0 and ((m & N_BIT) != 0) != need_n:
                continue
            if lf >= 0 and ((m & W_BIT) != 0) != need_w:
                continue
            if state["cnt"] >= limit:
                return
            state["nodes"] += 1
            cur[i] = m
            mark = len(log)
            o = 0
            if c + 1 < n and (m & E_BIT):
                o += 1
            if r + 1 < n and (m & S_BIT):
                o += 1
            log.append((0, i, opn[i]))
            opn[i] = o
            ok = True
            for nb, bit in ((up, N_BIT), (lf, W_BIT)):
                if nb < 0 or not (m & bit):
                    continue
                ra, rb = find(i), find(nb)
                log.append((0, rb, opn[rb]))
                opn[rb] -= 1                 # 相手の外向きの腕を1本使い切る
                if ra == rb:
                    ok = False               # 輪ができた
                    break
                if sz[ra] < sz[rb]:
                    ra, rb = rb, ra
                log.append((1, rb, parent[rb]))
                parent[rb] = ra
                log.append((2, ra, sz[ra]))
                sz[ra] += sz[rb]
                log.append((0, ra, opn[ra]))
                opn[ra] += opn[rb]
            if ok and i + 1 < N and opn[find(i)] == 0:
                ok = False                   # もう広がれない塊ができた
            if ok:
                dfs(i + 1)
            rollback(mark)

    dfs(0)
    return state["cnt"], state["nodes"], state["first"]


# ---------------------------------------------------------------- 出題の向き
def scramble(rnd, sol, n, tries=12):
    """正解から各マスをランダムに回す。最初から正解のマスが半分以上なら作り直す"""
    N = n * n
    for _ in range(tries):
        cells = [rnd.choice(variants(sol[i])) for i in range(N)]
        same = sum(1 for i in range(N) if cells[i] == sol[i])
        if same * 2 < N:
            return cells, same
    return None, 0


def make_one(rnd, n, maxnodes):
    sol = random_tree(rnd, n)
    cnt, nodes, _ = count_solutions(n, sol, 2)
    if cnt != 1 or nodes > maxnodes:
        return None
    cells, same = scramble(rnd, sol, n)
    if cells is None:
        return None
    return {"n": n, "cells": to_hex(cells), "solution": to_hex(sol),
            "nodes": nodes, "same": same}


# ---------------------------------------------------------------- 段階
PER_TIER = 10

# 盤サイズと採用するノード数の幅（--survey の実測で決める）
TIERS = [
    ("入門", 5, 0, 200),
    ("初級", 6, 0, 1200),
    ("中級", 8, 0, 40000),
    ("上級", 10, 0, 10 ** 9),
]


def generate(seed, budget, per_tier=PER_TIER, verbose=True):
    rnd = random.Random(seed)
    t0 = time.time()
    out, seen = [], set()
    for name, n, lo, hi in TIERS:
        got, tries = [], 0
        while len(got) < per_tier:
            tries += 1
            if time.time() - t0 > budget:
                raise SystemExit("時間切れ: %s n=%d の %d 本目まで（--budget を伸ばす）"
                                 % (name, n, len(got)))
            p = make_one(rnd, n, hi)
            if p is None or p["nodes"] < lo or p["cells"] in seen:
                continue
            seen.add(p["cells"])
            p["tier"] = name
            got.append(p)
        got.sort(key=lambda q: q["nodes"])
        out.extend(got)
        if verbose:
            print("  %s n=%d %d本 / 試行%d / %.1f秒"
                  % (name, n, per_tier, tries, time.time() - t0), file=sys.stderr)
    if verbose:
        print("生成 %.1f 秒" % (time.time() - t0), file=sys.stderr)
    return out


def survey(seed, per_config, budget, sizes):
    """盤サイズごとに nodes と一意率を実測する（閾値決め用）"""
    rnd = random.Random(seed)
    for n in sizes:
        t0 = time.time()
        rec, tries = [], 0
        while len(rec) < per_config and time.time() - t0 < budget:
            tries += 1
            sol = random_tree(rnd, n)
            cnt, nodes, _ = count_solutions(n, sol, 2)
            if cnt == 1:
                rec.append(nodes)
        if not rec:
            print("n=%d  一意0本（試行%d・%.0f秒）" % (n, tries, time.time() - t0))
            continue
        rec.sort()

        def q(f):
            return rec[min(len(rec) - 1, int(len(rec) * f))]
        print("n=%d 一意%d/試行%d(%.0f%%) %.1f秒  "
              "nodes 最小%d 1/4 %d 中央%d 3/4 %d 上位1割%d 最大%d"
              % (n, len(rec), tries, 100.0 * len(rec) / tries, time.time() - t0,
                 rec[0], q(.25), q(.5), q(.75), q(.9), rec[-1]))


# ---------------------------------------------------------------- 検証・出力
def connected_all(n, cells):
    """腕が過不足なくつながり、全体が一つの網になっているか"""
    N = n * n
    for i in range(N):
        r, c = divmod(i, n)
        m = cells[i]
        if (m & N_BIT) and (r == 0 or not (cells[i - n] & S_BIT)):
            return False
        if (m & S_BIT) and (r == n - 1 or not (cells[i + n] & N_BIT)):
            return False
        if (m & W_BIT) and (c == 0 or not (cells[i - 1] & E_BIT)):
            return False
        if (m & E_BIT) and (c == n - 1 or not (cells[i + 1] & W_BIT)):
            return False
    seen = {0}
    stack = [0]
    while stack:
        i = stack.pop()
        m = cells[i]
        for bit, j in ((N_BIT, i - n), (S_BIT, i + n), (W_BIT, i - 1), (E_BIT, i + 1)):
            if (m & bit) and j not in seen:
                seen.add(j)
                stack.append(j)
    return len(seen) == N


def verify(puzzles):
    """埋め込む前に自分で点検する"""
    bad = []
    for k, p in enumerate(puzzles):
        n, N = p["n"], p["n"] * p["n"]
        if len(p["cells"]) != N or len(p["solution"]) != N:
            bad.append((k, "長さが合わない"))
            continue
        cells, sol = from_hex(p["cells"]), from_hex(p["solution"])
        if any(m == 0 for m in sol):
            bad.append((k, "腕の無いマスがある"))
            continue
        if any(cells[i] not in variants(sol[i]) for i in range(N)):
            bad.append((k, "出題の向きが正解を回したものになっていない"))
            continue
        if not connected_all(n, sol):
            bad.append((k, "正解が一つの網になっていない"))
            continue
        if connected_all(n, cells):
            bad.append((k, "出題が最初から解けている"))
            continue
        same = sum(1 for i in range(N) if cells[i] == sol[i])
        if same * 2 >= N:
            bad.append((k, "最初から正解のマスが多すぎる(%d/%d)" % (same, N)))
            continue
        cnt, _, _ = count_solutions(n, cells, 2)
        if cnt != 1:
            bad.append((k, "解が%d個" % cnt))
    return bad


def embed(path, puzzles):
    lines = ["var PUZZLES = ["]
    for k, p in enumerate(puzzles):
        lines.append('  {"n":%d,"cells":"%s","solution":"%s","tier":"%s","nodes":%d}%s'
                     % (p["n"], p["cells"], p["solution"], p["tier"], p["nodes"],
                        "," if k < len(puzzles) - 1 else ""))
    lines.append("];")
    body = "\n".join(lines)
    src = open(path, encoding="utf-8").read()
    pat = re.compile(r"(/\* PUZZLES-BEGIN[^\n]*\*/\n).*?(\n/\* PUZZLES-END \*/)", re.S)
    if not pat.search(src):
        raise SystemExit("PUZZLES-BEGIN / PUZZLES-END が見つからない: " + path)
    src = pat.sub(lambda m: m.group(1) + body + m.group(2), src)
    open(path, "w", encoding="utf-8").write(src)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20260913)
    ap.add_argument("--budget", type=float, default=600.0, help="打ち切りまでの秒数")
    ap.add_argument("--per-tier", type=int, default=PER_TIER)
    ap.add_argument("--out", default=None)
    ap.add_argument("--embed", default=None, help="index.html の PUZZLES-BEGIN/END を差し替える")
    ap.add_argument("--survey", action="store_true", help="閾値決めの実測だけ行う")
    ap.add_argument("--survey-n", type=int, default=60, help="--survey で盤サイズごとに集める本数")
    ap.add_argument("--survey-sizes", default="5,6,7,8,9,10")
    a = ap.parse_args()

    if a.survey:
        survey(a.seed, a.survey_n, a.budget,
               tuple(int(x) for x in a.survey_sizes.split(",")))
        return

    puzzles = generate(a.seed, a.budget, a.per_tier)
    bad = verify(puzzles)
    if bad:
        for k, why in bad:
            print("NG %d: %s" % (k, why), file=sys.stderr)
        raise SystemExit("検証に落ちたので書き出さない")
    slim = [{"n": p["n"], "cells": p["cells"], "solution": p["solution"],
             "tier": p["tier"], "nodes": p["nodes"]} for p in puzzles]
    text = json.dumps(slim, ensure_ascii=False, indent=1)
    if a.out:
        open(a.out, "w", encoding="utf-8").write(text + "\n")
    if a.embed:
        embed(a.embed, slim)
    if not a.out and not a.embed:
        print(text)
    for name, n, _, _ in TIERS:
        g = [p for p in puzzles if p["tier"] == name]
        if not g:
            continue
        print("%s %d本  n=%d  nodes %d〜%d"
              % (name, len(g), n, min(p["nodes"] for p in g), max(p["nodes"] for p in g)),
              file=sys.stderr)


if __name__ == "__main__":
    main()
