#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""星おき 問題生成器（Python3 標準ライブラリのみ）

    python3 gen_puzzles.py                        # 生成して JSON を標準出力へ
    python3 gen_puzzles.py --out puzzles.json     # JSON に書き出す
    python3 gen_puzzles.py --embed ../index.html  # PUZZLES-BEGIN/END の間だけ差し替え
    python3 gen_puzzles.py --seed 123 --budget 600
    python3 gen_puzzles.py --survey               # 段階の閾値を決めるための実測（生成はしない）

手順（docs/spec.md）
  1. 非隣接の順列（各行・各列に★1つ、斜めを含めて隣り合わない）をランダムに作る
  2. 各★を種にして領域をランダムに育て、全マスを N 個の連結領域に分ける
  3. ソルバーで解を2つまで数え、ちょうど1つのものだけ採用

難度
  論理ソルバー（1) 行・列・領域の候補が1つなら確定 2) ある領域の候補が1行か1列に
  収まればその行・列の領域外を消す 3) 確定★の8近傍と同じ行・列・領域を消す）で
  解き切れるか、解き切れないときは伝播つき探索の分岐数（nodes）で4段階に分ける。
  nodes=0 は論理だけで解けたということ。閾値は --survey の実測で決める。
"""

import argparse
import json
import random
import re
import sys
import time

IDCHARS = "abcdefghijklmnopqrstuvwxyz"

# ---------------------------------------------------------------- 盤の表
_TAB = {}


def tables(n):
    """4近傍・8近傍・行のマス・列のマスを一度だけ作って使い回す"""
    if n in _TAB:
        return _TAB[n]
    nb4, nb8 = [], []
    rowcells = [[] for _ in range(n)]
    colcells = [[] for _ in range(n)]
    for i in range(n * n):
        r, c = divmod(i, n)
        rowcells[r].append(i)
        colcells[c].append(i)
        a, b = [], []
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                rr, cc = r + dr, c + dc
                if 0 <= rr < n and 0 <= cc < n:
                    j = rr * n + cc
                    b.append(j)
                    if dr == 0 or dc == 0:
                        a.append(j)
        nb4.append(tuple(a))
        nb8.append(tuple(b))
    _TAB[n] = (nb4, nb8, rowcells, colcells)
    return _TAB[n]


def region_cells(n, reg):
    out = [[] for _ in range(n)]
    for i in range(n * n):
        out[reg[i]].append(i)
    return out


# ---------------------------------------------------------------- ソルバー
# 盤の状態 st: 0=未定 1=置けない 2=★

def place(n, reg, st, i, rowcells, colcells, regcells, nb8):
    """i に★を置き、同じ行・列・領域と8近傍を消す。矛盾したら False"""
    if st[i] == 1:
        return False
    st[i] = 2
    for j in rowcells[i // n]:
        if j != i:
            if st[j] == 2:
                return False
            st[j] = 1
    for j in colcells[i % n]:
        if j != i:
            if st[j] == 2:
                return False
            st[j] = 1
    for j in regcells[reg[i]]:
        if j != i:
            if st[j] == 2:
                return False
            st[j] = 1
    for j in nb8[i]:
        if st[j] == 2:
            return False
        st[j] = 1
    return True


def propagate(n, reg, st, rowcells, colcells, regcells, nb8):
    """論理だけで進めるところまで進める。戻り値 (矛盾なしか, 直線ルールを使ったか)"""
    used_line = False
    units = rowcells + colcells + regcells
    changed = True
    while changed:
        changed = False
        # 1) 候補が1つしかない行・列・領域は確定
        for unit in units:
            star = False
            cands = []
            for c in unit:
                if st[c] == 2:
                    star = True
                    break
                if st[c] == 0:
                    cands.append(c)
            if star:
                continue
            if not cands:
                return False, used_line
            if len(cands) == 1:
                if not place(n, reg, st, cands[0], rowcells, colcells, regcells, nb8):
                    return False, used_line
                changed = True
        if changed:
            continue
        # 2) ある領域の候補が1行（1列）に収まれば、その行（列）の領域外を消す
        for k in range(n):
            unit = regcells[k]
            star = False
            cands = []
            for c in unit:
                if st[c] == 2:
                    star = True
                    break
                if st[c] == 0:
                    cands.append(c)
            if star or not cands:
                continue
            rows = set(c // n for c in cands)
            if len(rows) == 1:
                for c in rowcells[rows.pop()]:
                    if reg[c] != k and st[c] == 0:
                        st[c] = 1
                        changed = True
                        used_line = True
            cols = set(c % n for c in cands)
            if len(cols) == 1:
                for c in colcells[cols.pop()]:
                    if reg[c] != k and st[c] == 0:
                        st[c] = 1
                        changed = True
                        used_line = True
    return True, used_line


def count_fast(n, reg, limit=2):
    """解の数を limit まで数える（行ごとにビットで進む素朴な総当り。ふるい分け用）"""
    full = (1 << n) - 1
    rowreg = [[1 << reg[r * n + c] for c in range(n)] for r in range(n)]
    stat = [0]

    def dfs(r, usedc, usedreg, prevmask):
        if r == n:
            stat[0] += 1
            return
        m = full & ~usedc & ~prevmask
        while m:
            b = m & -m
            m ^= b
            rb = rowreg[r][b.bit_length() - 1]
            if usedreg & rb:
                continue
            dfs(r + 1, usedc | b, usedreg | rb, ((b << 1) | b | (b >> 1)) & full)
            if stat[0] >= limit:
                return

    dfs(0, 0, 0, 0)
    return stat[0]


def analyze(n, reg, limit=2):
    """解の数（limit まで）・分岐数・論理だけで解けたか・直線ルールが要ったか"""
    nb4, nb8, rowcells, colcells = tables(n)
    regcells = region_cells(n, reg)
    st = [0] * (n * n)
    ok, used_line = propagate(n, reg, st, rowcells, colcells, regcells, nb8)
    if not ok:
        return 0, 0, False, False
    logic_solved = (st.count(2) == n)
    stat = {"sol": 0, "nodes": 0}

    def rec(state):
        if stat["sol"] >= limit:
            return
        if state.count(2) == n:
            stat["sol"] += 1
            return
        # 候補のいちばん少ない行・列・領域で分岐する
        best = None
        for unit in rowcells + colcells + regcells:
            star = False
            cands = []
            for c in unit:
                if state[c] == 2:
                    star = True
                    break
                if state[c] == 0:
                    cands.append(c)
            if star:
                continue
            if best is None or len(cands) < len(best):
                best = cands
                if len(best) <= 2:
                    break
        if not best:
            return
        for c in best:
            stat["nodes"] += 1
            s2 = state[:]
            if not place(n, reg, s2, c, rowcells, colcells, regcells, nb8):
                continue
            ok2, _ = propagate(n, reg, s2, rowcells, colcells, regcells, nb8)
            if not ok2:
                continue
            rec(s2)
            if stat["sol"] >= limit:
                return

    if logic_solved:
        stat["sol"] = 1
        # 一意性は伝播だけで確定している（矛盾なく n 個そろった）
        return 1, 0, True, used_line
    rec(st)
    return stat["sol"], stat["nodes"], False, used_line


# ---------------------------------------------------------------- 生成
def random_solution(rnd, n):
    """各行・各列に1つ、斜めを含めて隣り合わない★の配置をランダムに作る"""
    res = []
    used = set()

    def bt(r, prev):
        if r == n:
            return True
        order = [c for c in range(n)
                 if c not in used and (prev is None or abs(c - prev) >= 2)]
        rnd.shuffle(order)
        for c in order:
            used.add(c)
            res.append(c)
            if bt(r + 1, c):
                return True
            used.discard(c)
            res.pop()
        return False

    return res if bt(0, None) else None


def grow_regions(rnd, n, stars, slack):
    """各★を種に、隣り合う未割当マスを1つずつ足して N 個の連結領域に分ける"""
    nb4, _, _, _ = tables(n)
    reg = [-1] * (n * n)
    for k, i in enumerate(stars):
        reg[i] = k
    sizes = [1] * n
    remaining = n * n - n
    while remaining:
        cand = []
        for i in range(n * n):
            if reg[i] != -1:
                continue
            ks = set(reg[j] for j in nb4[i] if reg[j] != -1)
            for k in ks:
                cand.append((sizes[k], i, k))
        if not cand:
            return None
        m = min(c[0] for c in cand)
        pool = [c for c in cand if c[0] <= m + slack]
        _, i, k = rnd.choice(pool)
        reg[i] = k
        sizes[k] += 1
        remaining -= 1
    return reg


def still_connected(n, reg, rid, x):
    """領域 rid から x を抜いても、残りがつながっているか"""
    nb4 = tables(n)[0]
    rest = set(i for i in range(n * n) if reg[i] == rid and i != x)
    if not rest:
        return False
    start = next(iter(rest))
    seen = {start}
    stack = [start]
    while stack:
        i = stack.pop()
        for j in nb4[i]:
            if j in rest and j not in seen:
                seen.add(j)
                stack.append(j)
    return len(seen) == len(rest)


def refine(rnd, n, reg, starset, minsize, maxsize, cap=200, rounds=4000, patience=500):
    """境界のマスを隣の領域へ1つずつ移し、解の数が減る（増えない）方だけ残す。
    ★のマスは動かさないので、どの領域も★をちょうど1つ持ったまま。
    領域が minsize〜maxsize マスに収まる移動だけ試す（1つの領域が盤を覆ってしまうのを防ぐ）。"""
    nb4 = tables(n)[0]
    best = count_fast(n, reg, cap)
    stall = 0
    sizes = [0] * n
    for i in range(n * n):
        sizes[reg[i]] += 1
    while best > 1 and rounds > 0 and stall < patience:
        rounds -= 1
        x = rnd.randrange(n * n)
        if x in starset:
            continue
        old = reg[x]
        if sizes[old] <= minsize:
            continue
        opts = [reg[j] for j in nb4[x] if reg[j] != old and sizes[reg[j]] < maxsize]
        if not opts:
            continue
        t = rnd.choice(opts)
        if not still_connected(n, reg, old, x):
            continue
        reg[x] = t
        c = count_fast(n, reg, cap)
        if c <= best:
            stall = 0 if c < best else stall + 1
            best = c
            sizes[old] -= 1
            sizes[t] += 1
        else:
            reg[x] = old
            stall += 1
    return best


def make_one(rnd, n, minsize=2, maxsize=None):
    sol = random_solution(rnd, n)
    if sol is None:
        return None
    stars = [r * n + sol[r] for r in range(n)]
    reg = grow_regions(rnd, n, stars, rnd.choice([0, 0, 1, 1, 2]))
    if reg is None:
        return None
    if maxsize is None:
        maxsize = 2 * n
    if refine(rnd, n, reg, set(stars), minsize, maxsize) != 1:
        return None
    cnt, nodes, logic, line = analyze(n, reg)
    if cnt != 1:
        return None
    solstr = "".join("1" if i in set(stars) else "0" for i in range(n * n))
    return {
        "n": n,
        "regions": "".join(IDCHARS[k] for k in reg),
        "solution": solstr,
        "nodes": nodes,
        "logic": logic,
        "line": line,
    }


# ---------------------------------------------------------------- 段階
# 閾値（--survey の実測で決めた。docs/spec.md に書き戻すこと）
#   nodes = 伝播つき探索の分岐数。0 なら論理ソルバーだけで解き切れる
MINSIZE = {5: 2, 6: 2, 7: 3, 8: 3, 9: 3}          # 領域の最小マス数
MAXSIZE = {5: 10, 6: 12, 7: 14, 8: 16, 9: 18}     # 領域の最大マス数（盤の 1/4 前後）
TIERS = [
    # (段階名, 使う盤サイズ, 1本の条件)
    ("入門", [5, 6], lambda p: p["nodes"] == 0),
    ("初級", [7], lambda p: p["nodes"] == 0),
    ("中級", [8], lambda p: 1 <= p["nodes"] <= 12),
    ("上級", [9], lambda p: p["nodes"] >= 20),
]
PER_TIER = 10


def generate(seed, budget, per_tier=PER_TIER, verbose=True):
    rnd = random.Random(seed)
    t0 = time.time()
    out = []
    seen = set()
    for name, sizes, ok in TIERS:
        # 盤サイズが複数なら均等に割り振る
        quota = [per_tier // len(sizes)] * len(sizes)
        for k in range(per_tier - sum(quota)):
            quota[k] += 1
        for n, need in zip(sizes, quota):
            got, tries = [], 0
            while len(got) < need:
                tries += 1
                if time.time() - t0 > budget:
                    raise SystemExit("時間切れ: %s n=%d の %d 本目まで（--budget を伸ばす）"
                                     % (name, n, len(got)))
                p = make_one(rnd, n, MINSIZE[n], MAXSIZE[n])
                if p is None or not ok(p) or p["regions"] in seen:
                    continue
                # 修復で縮んだ領域が最小マス数を割っていたら不採用（qa係の指摘）
                if min(p["regions"].count(ch) for ch in set(p["regions"])) < MINSIZE[n]:
                    continue
                seen.add(p["regions"])
                p["tier"] = name
                got.append(p)
            got.sort(key=lambda q: q["nodes"])
            out.extend(got)
            if verbose:
                print("  %s n=%d %d本 / 試行%d / %.1f秒"
                      % (name, n, need, tries, time.time() - t0), file=sys.stderr)
    if verbose:
        print("生成 %.1f 秒" % (time.time() - t0), file=sys.stderr)
    return out


def survey(seed, per_config, budget):
    """盤サイズごとに nodes と論理可否の分布を実測する（閾値決め用）"""
    rnd = random.Random(seed)
    t0 = time.time()
    for n in (5, 6, 7, 8, 9):
        rec = []
        while len(rec) < per_config and time.time() - t0 < budget:
            p = make_one(rnd, n, MINSIZE[n], MAXSIZE[n])
            if p:
                rec.append(p)
        if not rec:
            continue
        logic = sum(1 for p in rec if p["logic"])
        noline = sum(1 for p in rec if p["logic"] and not p["line"])
        nodes = sorted(p["nodes"] for p in rec)
        hard = [x for x in nodes if x > 0]
        def q(a, f):
            return a[min(len(a) - 1, int(len(a) * f))] if a else 0
        print("n=%d  本数%d  論理のみ%d(%.0f%%) うち直線不要%d  "
              "nodes 中央%d 上位1割%d 最大%d  分岐あり%d本(中央%d)"
              % (n, len(rec), logic, 100.0 * logic / len(rec), noline,
                 q(nodes, .5), q(nodes, .9), nodes[-1], len(hard), q(hard, .5)))
    print("実測 %.1f 秒" % (time.time() - t0))


# ---------------------------------------------------------------- 検証・出力
def verify(puzzles):
    """埋め込む前に自分で点検する（領域の連結・領域数・★1つ・一意解）"""
    bad = []
    for k, p in enumerate(puzzles):
        n = p["n"]
        reg = [IDCHARS.index(ch) for ch in p["regions"]]
        if len(reg) != n * n:
            bad.append((k, "領域文字数"))
            continue
        if len(set(reg)) != n:
            bad.append((k, "領域数が N でない"))
            continue
        nb4, _, _, _ = tables(n)
        cells = region_cells(n, reg)
        for k2 in range(n):
            seen = {cells[k2][0]}
            stack = [cells[k2][0]]
            while stack:
                i = stack.pop()
                for j in nb4[i]:
                    if reg[j] == k2 and j not in seen:
                        seen.add(j)
                        stack.append(j)
            if len(seen) != len(cells[k2]):
                bad.append((k, "領域%dが連結でない" % k2))
        stars = [i for i in range(n * n) if p["solution"][i] == "1"]
        if len(stars) != n:
            bad.append((k, "★の数"))
            continue
        if len(set(i // n for i in stars)) != n or len(set(i % n for i in stars)) != n:
            bad.append((k, "行列に1つでない"))
        if len(set(reg[i] for i in stars)) != n:
            bad.append((k, "領域に1つでない"))
        for a in stars:
            for b in stars:
                if a < b and abs(a // n - b // n) <= 1 and abs(a % n - b % n) <= 1:
                    bad.append((k, "★が隣接"))
        cnt, _, _, _ = analyze(n, reg)
        if cnt != 1:
            bad.append((k, "解が%d個" % cnt))
    return bad


def embed(path, puzzles):
    lines = ["var PUZZLES = ["]
    for k, p in enumerate(puzzles):
        lines.append('  {"n":%d,"regions":"%s","solution":"%s","tier":"%s","nodes":%d}%s'
                     % (p["n"], p["regions"], p["solution"], p["tier"], p["nodes"],
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
    ap.add_argument("--seed", type=int, default=20260908)
    ap.add_argument("--budget", type=float, default=600.0, help="打ち切りまでの秒数")
    ap.add_argument("--per-tier", type=int, default=PER_TIER)
    ap.add_argument("--out", default=None)
    ap.add_argument("--embed", default=None, help="index.html の PUZZLES-BEGIN/END を差し替える")
    ap.add_argument("--survey", action="store_true", help="閾値決めの実測だけ行う")
    ap.add_argument("--survey-n", type=int, default=60, help="--survey で盤サイズごとに集める本数")
    a = ap.parse_args()

    if a.survey:
        survey(a.seed, a.survey_n, a.budget)
        return

    puzzles = generate(a.seed, a.budget, a.per_tier)
    bad = verify(puzzles)
    if bad:
        for k, why in bad:
            print("NG %d: %s" % (k, why), file=sys.stderr)
        raise SystemExit("検証に落ちたので書き出さない")
    slim = [{"n": p["n"], "regions": p["regions"], "solution": p["solution"],
             "tier": p["tier"], "nodes": p["nodes"]} for p in puzzles]
    text = json.dumps(slim, ensure_ascii=False, indent=1)
    if a.out:
        open(a.out, "w", encoding="utf-8").write(text + "\n")
    if a.embed:
        embed(a.embed, slim)
    if not a.out and not a.embed:
        print(text)
    for name, _, _ in TIERS:
        g = [p for p in puzzles if p["tier"] == name]
        print("%s %d本  n=%s  nodes %d〜%d" %
              (name, len(g), sorted(set(p["n"] for p in g)),
               min(p["nodes"] for p in g), max(p["nodes"] for p in g)), file=sys.stderr)


if __name__ == "__main__":
    main()
