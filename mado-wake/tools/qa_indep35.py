#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""担当: qa係
窓わけ index=35 専用・第2の独立ソルバー。

qa_check.py（マス単位の領域成長バックトラック・フロンティア方式）とは
考え方もデータ構造も別にする：この盤のルールは size + color + rect で、
rect がある＝領域は必ず長方形になる。そこで「長方形タイル敷き詰め問題
（exact cover）」として解く。

- 候補は「盤に置きうる全長方形」を先に列挙し、size/color 制約で静的に
  ふるいにかける（qa_check.py はマスをフロンティアから1つずつ足す成長法）
- 探索は Algorithm X 風に「残りマスの中で候補数が最も少ないマス」を毎回
  選んで分岐する（qa_check.py はマス番号昇順で候補を試すだけ）
- 状態はビットマスク1個（64マス=64bit int）で表現し、メモ化用の
  visited セットも持つ（同じ被覆状態に複数経路で到達したら打ち切る）
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
COLORS = "RBY"
IDCHARS = "abcdefghijklmnopqrstuvwxyz"
TIME_LIMIT_SEC = 600


def canon(part):
    seen = {}
    out = []
    for p in part:
        if p not in seen:
            seen[p] = len(seen)
        out.append(seen[p])
    return out


def same_partition(a, b):
    if a is None or b is None or len(a) != len(b):
        return False
    return canon(a) == canon(b)


def build_candidates(n, cells, rules):
    """size/color を満たす全長方形（面積2以上）を静的に列挙し、ビットマスク化"""
    dig = [int(c) if c.isdigit() else 0 for c in cells]
    col = [c if c in COLORS else "" for c in cells]
    r_size = "size" in rules
    r_color = "color" in rules

    masks = []
    for r0 in range(n):
        for r1 in range(r0, n):
            for c0 in range(n):
                for c1 in range(c0, n):
                    h = r1 - r0 + 1
                    w = c1 - c0 + 1
                    area = h * w
                    if area < 2:
                        continue
                    idxs = [rr * n + cc for rr in range(r0, r1 + 1) for cc in range(c0, c1 + 1)]
                    if r_size:
                        digs = [dig[i] for i in idxs if dig[i]]
                        if len(digs) > 1:
                            continue
                        if len(digs) == 1 and digs[0] != area:
                            continue
                    if r_color:
                        cols = {col[i] for i in idxs if col[i]}
                        if len(cols) > 1:
                            continue
                    mask = 0
                    for i in idxs:
                        mask |= (1 << i)
                    masks.append((mask, idxs))
    return masks


def solve(n, cells, rules, limit=2, time_limit=TIME_LIMIT_SEC):
    N = n * n
    full = (1 << N) - 1
    all_masks_info = build_candidates(n, cells, rules)
    all_masks = [m for m, _ in all_masks_info]

    # 各マスをカバーしうる候補一覧（静的・状態に依存しない）
    by_cell = [[] for _ in range(N)]
    for m in all_masks:
        i = 0
        mm = m
        while mm:
            if mm & 1:
                by_cell[i].append(m)
            mm >>= 1
            i += 1

    state = {"count": 0, "nodes": 0, "solution_owner": None, "timeout": False}
    memo_fail = set()  # 到達済みで解につながらなかった uncovered_mask（メモ化）
    t_start = time.time()

    owner = [-1] * N  # 復元用（見つけた1つの解を保存する）

    def rec(uncovered, region_id):
        if state["timeout"]:
            return
        if time.time() - t_start > time_limit:
            state["timeout"] = True
            return
        state["nodes"] += 1
        if uncovered == 0:
            state["count"] += 1
            if state["solution_owner"] is None:
                state["solution_owner"] = list(owner)
            return
        if uncovered in memo_fail:
            return
        # MRV: 残りマスのうち「(候補 かつ uncovered の部分集合)」が最も少ないマスを選ぶ
        best_cell = -1
        best_opts = None
        best_n = None
        rem = uncovered
        while rem:
            low = rem & (-rem)
            i = low.bit_length() - 1
            opts = [m for m in by_cell[i] if (m & uncovered) == m]
            if best_n is None or len(opts) < best_n:
                best_n = len(opts)
                best_cell = i
                best_opts = opts
                if best_n == 0:
                    break
            rem &= rem - 1
        if best_n == 0:
            memo_fail.add(uncovered)
            return
        found_here = False
        for m in best_opts:
            idxs = None
            mm = m
            j = 0
            picked = []
            while mm:
                if mm & 1:
                    picked.append(j)
                mm >>= 1
                j += 1
            for i in picked:
                owner[i] = region_id
            rec(uncovered & ~m, region_id + 1)
            for i in picked:
                owner[i] = -1
            found_here = True
            if state["count"] >= limit or state["timeout"]:
                return
        if not found_here or state["count"] == 0:
            memo_fail.add(uncovered)

    rec(full, 0)
    return state["count"], state["nodes"], state["timeout"], state["solution_owner"]


def main():
    with open(os.path.join(HERE, "puzzles.json"), encoding="utf-8") as f:
        puzzles = json.load(f)
    p = puzzles[35]
    n, cells, rules, sol_str = p["n"], p["cells"], p["rules"], p["solution"]
    print("index=35 盤: n=%d rules=%s tier=%s" % (n, "+".join(rules), p["tier"]))
    print("cells =", cells)

    t0 = time.time()
    cnt, nodes, timed_out, found = solve(n, cells, rules, limit=2, time_limit=TIME_LIMIT_SEC)
    elapsed = time.time() - t0

    print("経過時間 = %.1f 秒, ノード数 = %d, timeout=%s" % (elapsed, nodes, timed_out))
    print("解の数（上限2で打ち切り） =", cnt)

    if timed_out:
        print("=> 10分以内に決着せず。独立には確認できなかった。")
        return

    sol = [IDCHARS.index(ch) for ch in sol_str]
    if cnt == 1 and found is not None:
        match = same_partition(found, sol)
        print("solution と一致:", match)
    else:
        print("(解数が1でないため solution との照合は行わない)")


if __name__ == "__main__":
    main()
