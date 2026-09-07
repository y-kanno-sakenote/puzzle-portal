#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""窓わけ 問題生成器（Python3 標準ライブラリのみ）

    python3 gen_puzzles.py                        # 生成して JSON を標準出力へ
    python3 gen_puzzles.py --out puzzles.json     # JSON に書き出す
    python3 gen_puzzles.py --embed ../index.html  # HTML の PUZZLES-BEGIN/END の間を差し替え
    python3 gen_puzzles.py --seed 123 --budget 600
    python3 gen_puzzles.py --survey               # 段階の閾値を決めるための実測（生成はしない）

手順（docs/spec.md）
  1. ランダムな分割（つながった2マス以上の領域）を作る
  2. ルールを1〜3個選ぶ
  3. 解からルールが要求する記号を置く
  4. 制約ソルバーで解を2つまで数え、ちょうど1つのものだけ採用
  5. 記号を1つずつ抜いて、一意性が保てる限界まで減らす

制約ソルバー
  未割当のいちばん小さいマスを起点に新しい領域を開き、隣接する未割当マスを
  1つずつ加える（連結部分集合の重複なし列挙）。2マス以上でルールを満たしたら
  領域を閉じて次の領域へ。閉じるたびに残りの連結成分を調べて枝を切る。
"""

import argparse
import json
import random
import re
import sys
import time

RULE_TEXT = {
    "star":   "どの領域も★をちょうど1つ含む",
    "size":   "数字のマスは、その領域のマス数（数字は領域に1つまで）",
    "nosame": "マス数が同じ領域は辺で接しない",
    "color":  "一つの領域に違う色の●は入らない",
    "rect":   "どの領域も長方形",
}
RULE_ORDER = ["star", "size", "nosame", "color", "rect"]
COLORS = "RBY"
IDCHARS = "abcdefghijklmnopqrstuvwxyz"

# 段階の設定: (名前, 盤の大きさ, ルール数の候補, ノード数の範囲)
# ノード数の閾値は実測で決めた（docs/spec.md に書き戻し済み）。
# ルール1本だけでは一意解がほぼ出ない（5x5 で 2/3000、6x6 で 0/3000）ので最低2本。
TIERS = [
    ("入門", 5, (2,),    (1, 700)),
    ("初級", 6, (2, 3), (700, 5000)),
    ("中級", 7, (2, 3), (5000, 60000)),
    ("上級", 8, (2, 3), (60000, 400000)),
]
TIER_NAMES = [t[0] for t in TIERS]

_NB = {}


def nb(n):
    """マスごとの上下左右の隣接マス"""
    if n in _NB:
        return _NB[n]
    out = []
    for i in range(n * n):
        r, c = divmod(i, n)
        l = []
        if r > 0:
            l.append(i - n)
        if c > 0:
            l.append(i - 1)
        if c < n - 1:
            l.append(i + 1)
        if r < n - 1:
            l.append(i + n)
        out.append(tuple(l))
    _NB[n] = out
    return out


class NodeLimit(Exception):
    """探索が上限を超えた（この問題は諦める）"""


# ---------------------------------------------------------------- ルール判定

def check_rules(n, cells, rules, part):
    """part（マスごとの領域番号）がルールを満たすか。違反したルール名の配列を返す。
    構造（全マス割当・連結・2マス以上）が壊れていれば "region" を入れる。"""
    N = n * n
    NBR = nb(n)
    bad = []
    if len(part) != N or any(p is None or p < 0 for p in part):
        return ["region"]
    groups = {}
    for i, p in enumerate(part):
        groups.setdefault(p, []).append(i)
    structural = False
    for g in groups.values():
        if len(g) < 2:
            structural = True
            break
        seen = {g[0]}
        stack = [g[0]]
        gs = set(g)
        while stack:
            v = stack.pop()
            for w in NBR[v]:
                if w in gs and w not in seen:
                    seen.add(w)
                    stack.append(w)
        if len(seen) != len(g):
            structural = True
            break
    if structural:
        bad.append("region")

    for rule in rules:
        ng = False
        if rule == "star":
            for g in groups.values():
                if sum(1 for v in g if cells[v] == "*") != 1:
                    ng = True
                    break
        elif rule == "size":
            for g in groups.values():
                ds = [int(cells[v]) for v in g if cells[v].isdigit()]
                if len(ds) > 1 or (ds and ds[0] != len(g)):
                    ng = True
                    break
        elif rule == "color":
            for g in groups.values():
                cs = set(cells[v] for v in g if cells[v] in COLORS)
                if len(cs) > 1:
                    ng = True
                    break
        elif rule == "rect":
            for g in groups.values():
                rs = [v // n for v in g]
                cs2 = [v % n for v in g]
                if (max(rs) - min(rs) + 1) * (max(cs2) - min(cs2) + 1) != len(g):
                    ng = True
                    break
        elif rule == "nosame":
            for i in range(N):
                for w in NBR[i]:
                    if part[w] != part[i] and len(groups[part[w]]) == len(groups[part[i]]):
                        ng = True
                        break
                if ng:
                    break
        if ng:
            bad.append(rule)
    return bad


# ---------------------------------------------------------------- ソルバー

def count_solutions(n, cells, rules, limit=2, max_nodes=400000, want=None):
    """解を limit 個まで数える。(個数, 探索ノード数) を返す。
    上限を超えたら NodeLimit を投げる。"""
    N = n * n
    NBR = nb(n)
    r_star = "star" in rules
    r_size = "size" in rules
    r_nosame = "nosame" in rules
    r_color = "color" in rules
    r_rect = "rect" in rules

    star = [c == "*" for c in cells]
    digit = [int(c) if c.isdigit() else 0 for c in cells]
    col = [c if c in COLORS else "" for c in cells]

    owner = [-1] * N
    closed = []
    cnt = 0
    nodes = 0
    found = []

    def remaining_ok():
        seen = [False] * N
        for i in range(N):
            if owner[i] != -1 or seen[i]:
                continue
            stack = [i]
            seen[i] = True
            comp = [i]
            while stack:
                v = stack.pop()
                for w in NBR[v]:
                    if owner[w] == -1 and not seen[w]:
                        seen[w] = True
                        stack.append(w)
                        comp.append(w)
            sz = len(comp)
            if sz < 2:
                return False
            if r_star:
                s = 0
                for v in comp:
                    if star[v]:
                        s += 1
                if s == 0 or 2 * s > sz:
                    return False
            if r_size:
                tot = 0
                for v in comp:
                    if digit[v]:
                        if digit[v] > sz:
                            return False
                        tot += digit[v]
                if tot > sz:
                    return False
        return True

    def grow(reg, cands, forb, rid, nst, dig, ccol):
        nonlocal cnt, nodes
        nodes += 1
        if nodes > max_nodes:
            raise NodeLimit()
        if len(reg) >= 2:
            ok = True
            if r_star and nst != 1:
                ok = False
            if ok and r_size and dig and dig != len(reg):
                ok = False
            if ok and r_rect:
                rs = [v // n for v in reg]
                cs = [v % n for v in reg]
                if (max(rs) - min(rs) + 1) * (max(cs) - min(cs) + 1) != len(reg):
                    ok = False
            if ok and r_nosame:
                sz = len(reg)
                adj = set()
                for v in reg:
                    for w in NBR[v]:
                        o = owner[w]
                        if o != -1 and o != rid:
                            adj.add(o)
                for o in adj:
                    if len(closed[o]) == sz:
                        ok = False
                        break
            if ok:
                closed.append(list(reg))
                if remaining_ok():
                    solve()
                closed.pop()
                if cnt >= limit:
                    return
        base = cands
        for i in range(len(base)):
            v = base[i]
            nst2 = nst + (1 if star[v] else 0)
            if r_star and nst2 > 1:
                continue
            dig2 = dig
            if digit[v]:
                if r_size:
                    if dig:
                        continue
                    dig2 = digit[v]
                    if len(reg) + 1 > dig2:
                        continue
            if r_size and dig2 and len(reg) + 1 > dig2:
                continue
            ccol2 = ccol
            if r_color and col[v]:
                if ccol and ccol != col[v]:
                    continue
                ccol2 = col[v]
            newforb = forb | set(base[:i])
            if r_rect:
                rs = [x // n for x in reg] + [v // n]
                cs = [x % n for x in reg] + [v % n]
                r0, r1, c0, c1 = min(rs), max(rs), min(cs), max(cs)
                bad = False
                for rr in range(r0, r1 + 1):
                    for cc in range(c0, c1 + 1):
                        o = owner[rr * n + cc]
                        if o != -1 and o != rid:
                            bad = True
                            break
                    if bad:
                        break
                if bad:
                    continue
            owner[v] = rid
            reg.append(v)
            seen = set(base)
            seen.update(newforb)
            newc = base[i + 1:] + []
            for w in NBR[v]:
                if owner[w] == -1 and w not in seen:
                    seen.add(w)
                    newc.append(w)
            grow(reg, newc, newforb, rid, nst2, dig2, ccol2)
            reg.pop()
            owner[v] = -1
            if cnt >= limit:
                return

    def solve():
        nonlocal cnt
        s = -1
        for i in range(N):
            if owner[i] == -1:
                s = i
                break
        if s < 0:
            cnt += 1
            if want is not None and len(found) < 4:
                found.append(canon([o for o in owner]))
            return
        rid = len(closed)
        owner[s] = rid
        cands = [w for w in NBR[s] if owner[w] == -1]
        grow([s], cands, set(), rid, 1 if star[s] else 0, digit[s], col[s])
        owner[s] = -1

    solve()
    return cnt, nodes


def canon(part):
    """領域番号の付け方を出現順にそろえる"""
    m = {}
    out = []
    for p in part:
        if p not in m:
            m[p] = len(m)
        out.append(m[p])
    return out


# ---------------------------------------------------------------- 分割を作る

def random_partition(rnd, n, minsz, maxsz, avoid_same_size=False):
    """つながった2マス以上の領域へのランダムな分割。失敗したら None"""
    N = n * n
    NBR = nb(n)
    owner = [-1] * N
    regs = []
    while True:
        free = [i for i in range(N) if owner[i] == -1]
        if not free:
            break
        s = free[0]
        rid = len(regs)
        used = set()
        if avoid_same_size:
            for w in NBR[s]:
                if owner[w] != -1:
                    used.add(len(regs[owner[w]]))
        choices = [k for k in range(minsz, maxsz + 1) if k not in used] or list(range(minsz, maxsz + 1))
        target = rnd.choice(choices)
        reg = [s]
        owner[s] = rid
        frontier = [w for w in NBR[s] if owner[w] == -1]
        while len(reg) < target and frontier:
            v = frontier.pop(rnd.randrange(len(frontier)))
            if owner[v] != -1:
                continue
            owner[v] = rid
            reg.append(v)
            for w in NBR[v]:
                if owner[w] == -1 and w not in frontier:
                    frontier.append(w)
        regs.append(reg)
    # 1マスの領域は隣の領域に混ぜる
    for rid in range(len(regs)):
        if len(regs[rid]) >= 2:
            continue
        v = regs[rid][0]
        opts = [owner[w] for w in NBR[v] if owner[w] != -1 and owner[w] != rid]
        if not opts:
            return None
        tgt = rnd.choice(opts)
        regs[tgt].append(v)
        owner[v] = tgt
        regs[rid] = []
    regs = [r for r in regs if r]
    if not regs or len(regs) > 26:
        return None
    part = [0] * N
    for k, r in enumerate(regs):
        for v in r:
            part[v] = k
    return canon(part)


def random_rect_partition(rnd, n, maxsz):
    """長方形だけの分割（rect ルール用）。失敗したら None"""
    N = n * n
    owner = [-1] * N
    k = 0
    while True:
        s = -1
        for i in range(N):
            if owner[i] == -1:
                s = i
                break
        if s < 0:
            break
        r0, c0 = divmod(s, n)
        opts = []
        for h in range(1, n - r0 + 1):
            for w in range(1, n - c0 + 1):
                if h * w < 2 or h * w > maxsz:
                    continue
                ok = True
                for rr in range(r0, r0 + h):
                    for cc in range(c0, c0 + w):
                        if owner[rr * n + cc] != -1:
                            ok = False
                            break
                    if not ok:
                        break
                if ok:
                    opts.append((h, w))
        if not opts:
            return None
        h, w = rnd.choice(opts)
        for rr in range(r0, r0 + h):
            for cc in range(c0, c0 + w):
                owner[rr * n + cc] = k
        k += 1
    if k > 26:
        return None
    return canon(owner)


# ---------------------------------------------------------------- 記号を置く

def place_symbols(rnd, n, part, rules):
    """解からルールが要求する記号を置く。cells 文字列を返す"""
    N = n * n
    NBR = nb(n)
    cells = ["."] * N
    groups = {}
    for i, p in enumerate(part):
        groups.setdefault(p, []).append(i)
    free = {g: list(cs) for g, cs in groups.items()}
    for g in free:
        rnd.shuffle(free[g])

    if "star" in rules:
        for g in sorted(groups):
            v = free[g].pop()
            cells[v] = "*"

    if "size" in rules:
        for g in sorted(groups):
            sz = len(groups[g])
            if sz < 2 or sz > 9 or not free[g]:
                continue
            v = free[g].pop()
            cells[v] = str(sz)

    if "color" in rules:
        # 隣り合う領域どうしは違う色になるよう貪欲に塗る（3色なので失敗することはある）
        adj = {g: set() for g in groups}
        for i in range(N):
            for w in NBR[i]:
                if part[w] != part[i]:
                    adj[part[i]].add(part[w])
        colof = {}
        for g in sorted(groups):
            used = set(colof[o] for o in adj[g] if o in colof)
            avail = [c for c in COLORS if c not in used] or list(COLORS)
            colof[g] = rnd.choice(avail)
        for g in sorted(groups):
            take = max(1, len(groups[g]) // 2)
            for _ in range(min(take, len(free[g]))):
                v = free[g].pop()
                cells[v] = colof[g]
    return "".join(cells)


def minimize(rnd, n, cells, rules, part, max_nodes):
    """記号を1つずつ抜き、一意性が保てる限り減らす"""
    cur = list(cells)
    idx = [i for i in range(n * n) if cur[i] != "."]
    rnd.shuffle(idx)
    for i in idx:
        keep = cur[i]
        cur[i] = "."
        s = "".join(cur)
        if check_rules(n, s, rules, part):
            cur[i] = keep
            continue
        try:
            c, _ = count_solutions(n, s, rules, 2, max_nodes)
        except NodeLimit:
            cur[i] = keep
            continue
        if c != 1:
            cur[i] = keep
    return "".join(cur)


# ---------------------------------------------------------------- 1本作る

def make_one(rnd, n, nrules, max_nodes):
    """1本ぶんの候補を作る。できなければ None"""
    base = rnd.choice(["star", "size"])
    extras = ["nosame", "color", "rect"]
    rnd.shuffle(extras)
    rules = [base]
    pool = [r for r in ["star", "size"] if r != base] + extras
    rnd.shuffle(pool)
    for r in pool:
        if len(rules) >= nrules:
            break
        rules.append(r)
    rules = [r for r in RULE_ORDER if r in rules]

    maxsz = 5 if n <= 6 else 6
    if "rect" in rules:
        part = random_rect_partition(rnd, n, maxsz)
    else:
        part = random_partition(rnd, n, 2 if n <= 5 else 3, maxsz,
                                avoid_same_size=("nosame" in rules))
    if part is None:
        return None
    cells0 = place_symbols(rnd, n, part, rules)
    if check_rules(n, cells0, rules, part):
        return None
    try:
        c, _ = count_solutions(n, cells0, rules, 2, max_nodes)
    except NodeLimit:
        return None
    if c != 1:
        return None
    cells = minimize(rnd, n, cells0, rules, part, max_nodes)
    try:
        c, nodes = count_solutions(n, cells, rules, 2, max_nodes)
    except NodeLimit:
        return None
    if c != 1:
        return None
    sol = "".join(IDCHARS[p] for p in part)
    return {"n": n, "cells": cells, "rules": rules, "solution": sol,
            "tier": "", "nodes": nodes}


# ---------------------------------------------------------------- 生成ループ

def generate(seed, budget, per_tier, verbose=True):
    rnd = random.Random(seed)
    out = {t: [] for t in TIER_NAMES}
    seen = {t: set() for t in TIER_NAMES}
    stats = {t: [] for t in TIER_NAMES}
    t0 = time.time()
    attempts = 0
    order = list(TIERS)
    while time.time() - t0 < budget:
        remaining = [t for t in order if len(out[t[0]]) < per_tier]
        if not remaining:
            break
        # 残りが多い段階を優先
        remaining.sort(key=lambda t: len(out[t[0]]))
        name, n, nrs, (lo, hi) = remaining[0]
        nr = rnd.choice(nrs)
        attempts += 1
        p = make_one(rnd, n, nr, hi if hi > 0 else 400000)
        if p is None:
            continue
        stats[name].append(p["nodes"])
        if not (lo <= p["nodes"] <= hi):
            continue
        if p["cells"] in seen[name]:
            continue
        seen[name].add(p["cells"])
        p["tier"] = name
        out[name].append(p)
        if verbose:
            print("  %s %d/%d  n=%d rules=%s nodes=%d" %
                  (name, len(out[name]), per_tier, n, "+".join(p["rules"]), p["nodes"]),
                  file=sys.stderr)
    puzzles = []
    for t in TIER_NAMES:
        ps = sorted(out[t], key=lambda p: p["nodes"])
        puzzles.extend(ps)
    info = {"seconds": time.time() - t0, "attempts": attempts,
            "filled": {t: len(out[t]) for t in TIER_NAMES}, "stats": stats}
    return puzzles, info


def survey(seed, per_config, max_nodes):
    """段階の閾値を決めるための実測"""
    rnd = random.Random(seed)
    for name, n, nrs, _ in TIERS:
        for nr in nrs:
            got = []
            tries = 0
            t0 = time.time()
            while len(got) < per_config and tries < per_config * 60 and time.time() - t0 < 120:
                tries += 1
                p = make_one(rnd, n, nr, max_nodes)
                if p:
                    got.append(p["nodes"])
            got.sort()
            if got:
                print("n=%d ルール%d本 (%s): %d本/%d試行 %.0f秒 nodes 最小%d 中央%d 最大%d  %s"
                      % (n, nr, name, len(got), tries, time.time() - t0,
                         got[0], got[len(got) // 2], got[-1], got), file=sys.stderr)
            else:
                print("n=%d ルール%d本 (%s): 0本/%d試行 %.0f秒"
                      % (n, nr, name, tries, time.time() - t0), file=sys.stderr)


# ---------------------------------------------------------------- 検証・出力

def verify(puzzles):
    bad = []
    for k, p in enumerate(puzzles):
        n = p["n"]
        part = [IDCHARS.index(ch) for ch in p["solution"]]
        if len(p["solution"]) != n * n or len(p["cells"]) != n * n:
            bad.append((k, "長さが合わない"))
            continue
        v = check_rules(n, p["cells"], p["rules"], part)
        if v:
            bad.append((k, "解がルール違反: %r" % (v,)))
            continue
        try:
            c, nodes = count_solutions(n, p["cells"], p["rules"], 2, 2000000)
        except NodeLimit:
            bad.append((k, "ノード上限"))
            continue
        if c != 1:
            bad.append((k, "解が %d 個" % c))
        if nodes != p["nodes"]:
            bad.append((k, "nodes が合わない"))
    return bad


def embed(path, puzzles):
    lines = ["var PUZZLES = ["]
    for k, p in enumerate(puzzles):
        lines.append('  {"n":%d,"cells":"%s","rules":[%s],"solution":"%s","tier":"%s","nodes":%d}%s'
                     % (p["n"], p["cells"], ",".join('"%s"' % r for r in p["rules"]),
                        p["solution"], p["tier"], p["nodes"],
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
    ap.add_argument("--seed", type=int, default=20260907)
    ap.add_argument("--budget", type=float, default=600.0, help="生成に使う秒数")
    ap.add_argument("--per-tier", type=int, default=10)
    ap.add_argument("--out", default=None, help="JSON の書き出し先")
    ap.add_argument("--embed", default=None, help="index.html の PUZZLES-BEGIN/END を差し替える")
    ap.add_argument("--survey", action="store_true", help="閾値決めの実測だけ")
    ap.add_argument("--survey-n", type=int, default=12)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if args.survey:
        survey(args.seed, args.survey_n, 400000)
        return

    puzzles, info = generate(args.seed, args.budget, args.per_tier, verbose=not args.quiet)
    print("", file=sys.stderr)
    print("生成 %.1f 秒 / 試行 %d 回" % (info["seconds"], info["attempts"]), file=sys.stderr)
    print("できた本数: " + " ".join("%s %d" % (t, info["filled"][t]) for t in TIER_NAMES),
          file=sys.stderr)
    for t in TIER_NAMES:
        ps = [p for p in puzzles if p["tier"] == t]
        if ps:
            ns = [p["nodes"] for p in ps]
            rc = sorted(set(len(p["rules"]) for p in ps))
            print("  %s n=%d ルール%s本 nodes %d〜%d"
                  % (t, ps[0]["n"], "/".join(str(x) for x in rc), min(ns), max(ns)),
                  file=sys.stderr)
    bad = verify(puzzles)
    if bad:
        print("検証で落ちた: %r" % (bad,), file=sys.stderr)
        raise SystemExit(1)
    print("検証: 一意性・ルール整合・ノード数、すべて通った", file=sys.stderr)

    js = json.dumps(puzzles, ensure_ascii=False, indent=1)
    if args.out:
        open(args.out, "w", encoding="utf-8").write(js + "\n")
        print("書き出し: " + args.out, file=sys.stderr)
    if args.embed:
        embed(args.embed, puzzles)
        print("埋め込み: " + args.embed, file=sys.stderr)
    if not args.out and not args.embed:
        print(js)


if __name__ == "__main__":
    main()
