#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""みちつなぎ 問題生成器（Python3 標準ライブラリのみ）

    python3 gen_puzzles.py                        # 生成して JSON を標準出力へ
    python3 gen_puzzles.py --out puzzles.json     # JSON に書き出す
    python3 gen_puzzles.py --embed ../index.html  # PUZZLES-BEGIN/END の間だけ差し替え
    python3 gen_puzzles.py --seed 123 --budget 600
    python3 gen_puzzles.py --survey               # 段階の閾値を決める実測（生成はしない）

手順（docs/spec.md）
  1. 盤の全マスを一筆でなぞる道（ハミルトン路）を backbite 法でランダムに作る
  2. 長さ2以上になるように K 本へ切り分ける。各断片が「対の道」、両端が数字になる
  3. ソルバー（バックトラック＋枝刈り）で解を2つまで数え、ちょうど1つのものだけ採用

枝刈り
  ・空きマスは最終的に必ず道の途中になる＝つながる先が2つ要る。
    まだ伸ばせる先（空きマス・未完の対の先端・未完の対の相手の数字）が
    2つ未満の空きマスができたら、その先に解は無い
  ・「空きマス＋未完の端点」の連結成分を見て、未完の対の両端が別成分に
    分かれたら、あるいはどの未完の端点にも触れない空きの島ができたら、その先に解は無い

難度
  上の枝刈りつき探索が解を2つ数え切るまでに踏んだノード数（nodes）で4段階に分ける。
  閾値は --survey の実測で決めて docs/spec.md に書き戻す。
"""

import argparse
import json
import random
import re
import sys
import time

DIGITS = "123456789abcdefghijklmnopqrstuvwxyz"

# ---------------------------------------------------------------- 盤の表
_TAB = {}


def tables(n):
    """4近傍を、番号の一覧とビットマスクの両方で持つ（一度だけ作って使い回す）"""
    if n in _TAB:
        return _TAB[n]
    nb, nbm = [], []
    for i in range(n * n):
        r, c = divmod(i, n)
        a = []
        if r > 0:
            a.append(i - n)
        if r + 1 < n:
            a.append(i + n)
        if c > 0:
            a.append(i - 1)
        if c + 1 < n:
            a.append(i + 1)
        nb.append(tuple(a))
        m = 0
        for j in a:
            m |= 1 << j
        nbm.append(m)
    _TAB[n] = (nb, nbm)
    return _TAB[n]


# ---------------------------------------------------------------- 一筆の道
def backbite(rnd, n, steps):
    """蛇行の初期路から backbite 法でランダムなハミルトン路へ混ぜる"""
    N = n * n
    nb, _ = tables(n)
    path = []
    for r in range(n):
        cols = range(n) if r % 2 == 0 else range(n - 1, -1, -1)
        for c in cols:
            path.append(r * n + c)
    pos = [0] * N
    for k, cell in enumerate(path):
        pos[cell] = k
    for _ in range(steps):
        if rnd.random() < 0.5:
            v = rnd.choice(nb[path[0]])
            j = pos[v]
            if j <= 1:
                continue
            path[:j] = path[j - 1::-1]
            for k in range(j):
                pos[path[k]] = k
        else:
            v = rnd.choice(nb[path[-1]])
            j = pos[v]
            if j >= N - 2:
                continue
            path[j + 1:] = path[N - 1:j:-1]
            for k in range(j + 1, N):
                pos[path[k]] = k
    return path


# ---------------------------------------------------------------- ソルバー
def flood_parts(region, nbm):
    """region（ビットマスク）を連結成分に分ける"""
    parts = []
    rest = region
    while rest:
        b = rest & -rest
        seen = b
        frontier = b
        while frontier:
            nxt = 0
            f = frontier
            while f:
                x = f & -f
                f ^= x
                nxt |= nbm[x.bit_length() - 1]
            nxt &= region & ~seen
            seen |= nxt
            frontier = nxt
        parts.append(seen)
        rest &= ~seen
    return parts


def count_solutions(n, pairs, limit=2, maxnodes=0):
    """解を limit 個まで数える。(解の数, ノード数, 打ち切ったか) を返す"""
    N = n * n
    _, nbm = tables(n)
    full = (1 << N) - 1
    K = len(pairs)
    A = [p[0] for p in pairs]
    B = [p[1] for p in pairs]
    endbit = [(1 << a) | (1 << b) for a, b in pairs]
    # 未完の対 j>k の端点をまとめたマスク（後ろから積んでおく）
    tailopen = [0] * (K + 1)
    for k in range(K - 1, -1, -1):
        tailopen[k] = tailopen[k + 1] | endbit[k]

    occ0 = 0
    for m in endbit:
        occ0 |= m
    stat = {"occ": occ0, "cnt": 0, "nodes": 0, "cap": False}

    def ok(k, head, dropped):
        """k 番の対を head まで伸ばした今の盤に、まだ望みがあるか。
        dropped は「今しがた伸ばせなくなったマス」。空きマスの手が減るのは
        その近所だけなので、そこだけ数え直す（None なら全部見る）"""
        occ = stat["occ"]
        empty = full & ~occ
        # まだ動ける端点（今の先端・今の相手・これから引く対の両端）
        opens = (1 << head) | (1 << B[k]) | tailopen[k + 1]
        avail = empty | opens
        if dropped is None:
            e = empty
        else:
            e = 0
            for x in dropped:
                e |= nbm_list2[x]
            e &= empty
        while e:
            b = e & -e
            e ^= b
            m = nbm_list2[b.bit_length() - 1] & avail
            if m & (m - 1) == 0:      # つながる先が0か1つ＝その空きマスは埋まらない
                return False
        for part in flood_parts(avail, nbm_list2):
            if not (part & opens):    # どの端点にも触れない空きの島
                return False
            if bool(part & (1 << head)) != bool(part & (1 << B[k])):
                return False
            for j in range(k + 1, K):
                if bool(part & (1 << A[j])) != bool(part & (1 << B[j])):
                    return False
        return True

    def dfs(k, head):
        stat["nodes"] += 1
        if maxnodes and stat["nodes"] > maxnodes:
            stat["cap"] = True
            return
        goal = B[k]
        for v in nbm_list[head]:
            if stat["cnt"] >= limit or stat["cap"]:
                return
            if v == goal:
                if k + 1 == K:
                    if stat["occ"] == full:
                        stat["cnt"] += 1
                elif ok(k + 1, A[k + 1], (head, goal)):
                    dfs(k + 1, A[k + 1])
            elif not (stat["occ"] >> v) & 1:
                stat["occ"] |= 1 << v
                if ok(k, v, (head,)):
                    dfs(k, v)
                stat["occ"] &= ~(1 << v)

    nbm_list, nbm_list2 = tables(n)
    if not ok(0, A[0], None):
        return 0, 1, False
    sys.setrecursionlimit(10000 + N * 4)
    dfs(0, A[0])
    return stat["cnt"], stat["nodes"], stat["cap"]


# ---------------------------------------------------------------- 1問作る
def split_dominoes(rnd, path):
    """一筆の道を長さ2（奇数のときだけ1つ長さ3）の断片に刻む"""
    N = len(path)
    lens = [2] * (N // 2)
    if N % 2:
        lens[rnd.randrange(len(lens))] = 3
    segs, at = [], 0
    for L in lens:
        segs.append(path[at:at + L])
        at += L
    return segs


def as_pairs(segs):
    return [[s[0], s[-1]] for s in segs]


def make_one(rnd, n, kmin, kmax, maxseg, steps, maxnodes):
    """刻んでから、一意解のままでいられる限り隣どうしを併合していく。
    手がかりを削って難しくしていく作り方（数独の生成と同じ考え）"""
    path = backbite(rnd, n, steps)
    segs = split_dominoes(rnd, path)
    cnt, _, cap = count_solutions(n, as_pairs(segs), 2, maxnodes)
    if cnt != 1 or cap:
        return None
    fails, nodes = 0, 0
    limit_fail = 4 * len(segs) + 20
    while len(segs) > kmin and fails < limit_fail:
        i = rnd.randrange(len(segs) - 1)
        if len(segs[i]) + len(segs[i + 1]) > maxseg:
            fails += 1
            continue
        trial = segs[:i] + [segs[i] + segs[i + 1]] + segs[i + 2:]
        cnt, nd, cap = count_solutions(n, as_pairs(trial), 2, maxnodes)
        if cnt == 1 and not cap:
            segs = trial
            nodes = nd
            fails = 0
        else:
            fails += 1
    if not (kmin <= len(segs) <= kmax):
        return None
    rnd.shuffle(segs)
    pairs = as_pairs(segs)
    cnt, nodes, cap = count_solutions(n, pairs, 2, 0)
    if cnt != 1:
        return None
    sol = [""] * (n * n)
    for idx, s in enumerate(segs):
        for cell in s:
            sol[cell] = DIGITS[idx]
    return {"n": n, "pairs": pairs, "solution": "".join(sol), "nodes": nodes}


# ---------------------------------------------------------------- 段階
# (段階名, 盤サイズ, 対の数の範囲, 断片の長さ範囲, 採用条件)
CONFIG = {
    5: dict(k=(3, 6), maxseg=12, steps=600, maxnodes=60000),
    6: dict(k=(4, 7), maxseg=16, steps=900, maxnodes=60000),
    7: dict(k=(4, 8), maxseg=20, steps=1200, maxnodes=80000),
    8: dict(k=(5, 9), maxseg=24, steps=1600, maxnodes=80000),
    9: dict(k=(5, 10), maxseg=28, steps=2000, maxnodes=100000),
    10: dict(k=(6, 11), maxseg=32, steps=2400, maxnodes=100000),
    # 9・10 は 1問あたり数分かかり実用外（実測）。使うのは 5〜8
}

# 閾値は --survey の実測から（docs/spec.md に書き戻し済み）
TIERS = [
    ("入門", 5, lambda p: p["nodes"] <= 120),
    ("初級", 6, lambda p: 80 <= p["nodes"] <= 1200),
    ("中級", 7, lambda p: 300 <= p["nodes"] <= 5000),
    ("上級", 8, lambda p: p["nodes"] >= 3000),
]
PER_TIER = 10


def gen_candidate(rnd, n):
    c = CONFIG[n]
    return make_one(rnd, n, c["k"][0], c["k"][1], c["maxseg"], c["steps"], c["maxnodes"])


def generate(seed, budget, per_tier=PER_TIER, verbose=True):
    rnd = random.Random(seed)
    t0 = time.time()
    out = []
    seen = set()
    for name, n, ok in TIERS:
        got, tries = [], 0
        while len(got) < per_tier:
            tries += 1
            if time.time() - t0 > budget:
                raise SystemExit("時間切れ: %s n=%d の %d 本目まで（--budget を伸ばす）"
                                 % (name, n, len(got)))
            p = gen_candidate(rnd, n)
            if p is None or not ok(p) or p["solution"] in seen:
                continue
            seen.add(p["solution"])
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


def survey(seed, per_config, budget, sizes=(5, 6, 7, 8)):
    """盤サイズごとに nodes と一意率を実測する（閾値決め用）"""
    rnd = random.Random(seed)
    for n in sizes:
        t0 = time.time()
        rec, tries = [], 0
        while len(rec) < per_config and time.time() - t0 < budget:
            tries += 1
            p = gen_candidate(rnd, n)
            if p:
                rec.append(p)
        if not rec:
            print("n=%d  採用0本（試行%d・%.0f秒）" % (n, tries, time.time() - t0))
            continue
        nodes = sorted(p["nodes"] for p in rec)

        def q(f):
            return nodes[min(len(nodes) - 1, int(len(nodes) * f))]
        print("n=%d 採用%d/試行%d(%.0f%%) %.1f秒  対%d〜%d  "
              "nodes 最小%d 1/4 %d 中央%d 3/4 %d 上位1割%d 最大%d"
              % (n, len(rec), tries, 100.0 * len(rec) / tries, time.time() - t0,
                 min(len(p["pairs"]) for p in rec), max(len(p["pairs"]) for p in rec),
                 nodes[0], q(.25), q(.5), q(.75), q(.9), nodes[-1]))


# ---------------------------------------------------------------- 検証・出力
def walkable(n, cells, a, b, nb):
    """cells のマスだけを使って a から b へ、全部通る一筆の道があるか。
    道は自分自身と隣り合ってよい（全マスを埋める以上どうしても起きる）ので、
    次数では判定できない。実際に一筆で歩けるかを確かめる"""
    S = set(cells)
    if a not in S or b not in S or a == b:
        return False
    need = len(S)
    seen = {a}

    def go(cur, cnt):
        if cur == b:
            return cnt == need
        for j in nb[cur]:
            if j in S and j not in seen:
                seen.add(j)
                if go(j, cnt + 1):
                    return True
                seen.discard(j)
        return False

    return go(a, 1)


def verify(puzzles):
    """埋め込む前に自分で点検する（一筆で歩ける・全マス被覆・端点一致・一意解）"""
    bad = []
    for k, p in enumerate(puzzles):
        n, N = p["n"], p["n"] * p["n"]
        sol = p["solution"]
        pairs = p["pairs"]
        if len(sol) != N:
            bad.append((k, "solution の長さ"))
            continue
        if any(ch not in DIGITS[:len(pairs)] for ch in sol):
            bad.append((k, "solution に知らない番号"))
            continue
        if len(set(sol)) != len(pairs):
            bad.append((k, "使われていない対がある"))
            continue
        if len(set(x for pr in pairs for x in pr)) != len(pairs) * 2:
            bad.append((k, "端点が重複"))
            continue
        nb, _ = tables(n)
        for idx, (a, b) in enumerate(pairs):
            cells = [i for i in range(N) if DIGITS.index(sol[i]) == idx]
            if len(cells) < 2:
                bad.append((k, "対%dの道が短い" % idx))
            elif not walkable(n, cells, a, b, nb):
                bad.append((k, "対%dが一筆で歩けない" % idx))
        cnt, _, _ = count_solutions(n, pairs, 2)
        if cnt != 1:
            bad.append((k, "解が%d個" % cnt))
    return bad


def embed(path, puzzles):
    lines = ["var PUZZLES = ["]
    for k, p in enumerate(puzzles):
        pr = ",".join("[%d,%d]" % (a, b) for a, b in p["pairs"])
        lines.append('  {"n":%d,"pairs":[%s],"solution":"%s","tier":"%s","nodes":%d}%s'
                     % (p["n"], pr, p["solution"], p["tier"], p["nodes"],
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
    ap.add_argument("--seed", type=int, default=20260910)
    ap.add_argument("--budget", type=float, default=600.0, help="打ち切りまでの秒数")
    ap.add_argument("--per-tier", type=int, default=PER_TIER)
    ap.add_argument("--out", default=None)
    ap.add_argument("--embed", default=None, help="index.html の PUZZLES-BEGIN/END を差し替える")
    ap.add_argument("--survey", action="store_true", help="閾値決めの実測だけ行う")
    ap.add_argument("--survey-n", type=int, default=40, help="--survey で盤サイズごとに集める本数")
    ap.add_argument("--survey-sizes", default="5,6,7,8")
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
    slim = [{"n": p["n"], "pairs": p["pairs"], "solution": p["solution"],
             "tier": p["tier"], "nodes": p["nodes"]} for p in puzzles]
    text = json.dumps(slim, ensure_ascii=False, indent=1)
    if a.out:
        open(a.out, "w", encoding="utf-8").write(text + "\n")
    if a.embed:
        embed(a.embed, slim)
    if not a.out and not a.embed:
        print(text)
    for name, n, _ in TIERS:
        g = [p for p in puzzles if p["tier"] == name]
        if not g:
            continue
        print("%s %d本  n=%d  対%d〜%d  nodes %d〜%d"
              % (name, len(g), n,
                 min(len(p["pairs"]) for p in g), max(len(p["pairs"]) for p in g),
                 min(p["nodes"] for p in g), max(p["nodes"] for p in g)), file=sys.stderr)


if __name__ == "__main__":
    main()
