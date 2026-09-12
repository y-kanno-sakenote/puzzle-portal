#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""担当: 🧪 qa係

くるくる 40問の独立検証（実装者コード=index.html/gen_puzzles.py の中身は見ずに書いた別実装）。

探索順を実装者の gen_puzzles.py（行優先）と変え、ここでは列優先で解を数える。
一意性の定義（向きの重複を同一視）は spec.md の記述に基づき自分で組んだ。

    python3 qa_check.py [puzzles.json]
"""
import itertools
import json
import random
import sys

HEXCH = "0123456789abcdef"
N_BIT, E_BIT, S_BIT, W_BIT = 1, 2, 4, 8


def from_hex(s):
    return [HEXCH.index(ch) for ch in s]


def rot(m, t=1):
    t %= 4
    for _ in range(t):
        m = ((m << 1) | (m >> 3)) & 15
    return m


_VARCACHE = {}


def variants(m):
    if m in _VARCACHE:
        return _VARCACHE[m]
    out, x = [], m
    for _ in range(4):
        if x not in out:
            out.append(x)
        x = rot(x)
    _VARCACHE[m] = out
    return out


def count_and_get(n, shape, limit=2):
    """列優先で解を limit 個まで数える。(個数, 見つかった解の一覧, ノード数)"""
    N = n * n
    allowed = [None] * N
    for i in range(N):
        r, c = divmod(i, n)
        vs = []
        for m in variants(shape[i]):
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
            return 0, [], 0
        allowed[i] = vs

    order = [r * n + c for c in range(n) for r in range(n)]  # 列優先（実装者は行優先）

    parent, sz, opn, cur, log = list(range(N)), [1] * N, [0] * N, [0] * N, []
    state = {"nodes": 0, "cnt": 0, "sols": []}

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

    def step(pos):
        if state["cnt"] >= limit:
            return
        if pos == N:
            if sz[find(order[0])] == N:
                state["cnt"] += 1
                state["sols"].append(list(cur))
            return
        i = order[pos]
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
                opn[rb] -= 1
                if ra == rb:
                    ok = False
                    break
                if sz[ra] < sz[rb]:
                    ra, rb = rb, ra
                log.append((1, rb, parent[rb]))
                parent[rb] = ra
                log.append((2, ra, sz[ra]))
                sz[ra] += sz[rb]
                log.append((0, ra, opn[ra]))
                opn[ra] += opn[rb]
            if ok and pos + 1 < N and opn[find(i)] == 0:
                ok = False
            if ok:
                step(pos + 1)
            rollback(mark)

    step(0)
    return state["cnt"], state["sols"], state["nodes"]


def brute_force(n, shape, limit=5):
    """小盤面(n<=3)専用の総当たり。列優先実装の自己検証にのみ使う"""
    N = n * n
    doms = [variants(shape[i]) for i in range(N)]
    cnt = 0
    for combo in itertools.product(*doms):
        ok = True
        for i in range(N):
            r, c = divmod(i, n)
            m = combo[i]
            if (m & N_BIT) and (r == 0 or not (combo[i - n] & S_BIT)):
                ok = False; break
            if (m & S_BIT) and (r == n - 1 or not (combo[i + n] & N_BIT)):
                ok = False; break
            if (m & W_BIT) and (c == 0 or not (combo[i - 1] & E_BIT)):
                ok = False; break
            if (m & E_BIT) and (c == n - 1 or not (combo[i + 1] & W_BIT)):
                ok = False; break
        if not ok:
            continue
        seen, stack = {0}, [0]
        while stack:
            i = stack.pop()
            m = combo[i]
            for bit, j in ((N_BIT, i - n), (S_BIT, i + n), (W_BIT, i - 1), (E_BIT, i + 1)):
                if (m & bit) and j not in seen:
                    seen.add(j); stack.append(j)
        if len(seen) == N:
            cnt += 1
            if cnt >= limit:
                return cnt
    return cnt


def self_check(trials=300, seed=1):
    """列優先ソルバー自体を n=2,3 の総当たりと突き合わせる（ソルバーの正しさの裏取り）"""
    rnd = random.Random(seed)
    mismatches = 0
    for _ in range(trials):
        n = rnd.choice([2, 3])
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
                x = parent[x]
            return x

        shape, used = [0] * N, 0
        for a, b, ba, bb in edges:
            ra, rb = find(a), find(b)
            if ra == rb:
                continue
            parent[ra] = rb
            shape[a] |= ba
            shape[b] |= bb
            used += 1
            if used == N - 1:
                break
        bf = brute_force(n, shape, limit=5)
        cnt, _, _ = count_and_get(n, shape, limit=5)
        if bf != cnt:
            mismatches += 1
    return trials, mismatches


def connected_all(n, cells):
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
    seen, stack = {0}, [0]
    while stack:
        i = stack.pop()
        m = cells[i]
        for bit, j in ((N_BIT, i - n), (S_BIT, i + n), (W_BIT, i - 1), (E_BIT, i + 1)):
            if (m & bit) and j not in seen:
                seen.add(j); stack.append(j)
    return len(seen) == N


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "puzzles.json"
    puzzles = json.load(open(path, encoding="utf-8"))

    trials, mismatches = self_check()
    print("[自己検証] n=2,3 総当たり vs 列優先ソルバー: %d試行 mismatch=%d" % (trials, mismatches))

    bad = []
    seen_cells = set()
    node_by_tier = {}
    for k, p in enumerate(puzzles):
        n, N = p["n"], p["n"] * p["n"]
        cells, sol = from_hex(p["cells"]), from_hex(p["solution"])
        if len(cells) != N or len(sol) != N:
            bad.append((k, "長さ不一致")); continue
        if any(m == 0 for m in sol):
            bad.append((k, "solutionに腕0のマス"))
        if not connected_all(n, sol):
            bad.append((k, "solutionが単一の木になっていない"))
        if connected_all(n, cells):
            bad.append((k, "cellsが最初から解けている"))
        if any(cells[i] not in variants(sol[i]) for i in range(N)):
            bad.append((k, "cellsがsolutionの回転になっていない"))
        if p["cells"] in seen_cells:
            bad.append((k, "cells文字列の重複"))
        seen_cells.add(p["cells"])

        cnt, sols, nodes = count_and_get(n, cells, limit=2)
        if cnt != 1:
            bad.append((k, "独立ソルバーの解が%d個" % cnt))
        elif sols[0] != sol:
            bad.append((k, "独立ソルバーの解がsolutionと不一致"))
        node_by_tier.setdefault(p["tier"], []).append(nodes)

        same = sum(1 for i in range(N) if cells[i] == sol[i])
        if same * 2 >= N:
            bad.append((k, "最初から正解のマスが半分以上(%d/%d)" % (same, N)))

    print("[40問] bad=%d件" % len(bad))
    for k, why in bad:
        print("  NG idx=%d: %s" % (k, why))

    print("[ノード数(列優先・自前)] ", {t: (min(v), max(v)) for t, v in node_by_tier.items()})


if __name__ == "__main__":
    main()
