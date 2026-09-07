#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""担当: qa係
数独40本の独立検証。実装者(gen_puzzles.py)のコードは使わない。
バックトラック一意性・論理難度判定・盤面妥当性を自前で実装して照合する。
"""
import json
import re
import sys

CELLS = 81
ROW = [i // 9 for i in range(CELLS)]
COL = [i % 9 for i in range(CELLS)]
BOX = [(i // 27) * 3 + (i % 9) // 3 for i in range(CELLS)]
ROWCELLS = [[i for i in range(CELLS) if ROW[i] == u] for u in range(9)]
COLCELLS = [[i for i in range(CELLS) if COL[i] == u] for u in range(9)]
BOXCELLS = [[i for i in range(CELLS) if BOX[i] == u] for u in range(9)]
UNITS = ROWCELLS + COLCELLS + BOXCELLS
PEERS = []
for i in range(CELLS):
    s = set(ROWCELLS[ROW[i]]) | set(COLCELLS[COL[i]]) | set(BOXCELLS[BOX[i]])
    s.discard(i)
    PEERS.append(sorted(s))

FLOOR = {"入門": 36, "初級": 28, "中級": 24, "上級": 17}
TIER_ORDER = ["入門", "初級", "中級", "上級"]


def parse(s):
    return [0 if c in "0." else int(c) for c in s]


# ---------------------------------------------------------------- 一意性（自前・単純な再帰）

def count_solutions(puzzle, limit=2):
    """愚直なバックトラック（最初に見つかった空マスから固定順で試す）。
    実装者版とは選ぶマスの順番をあえて変えて、アルゴリズム差でバグを拾う。"""
    grid = list(puzzle)
    count = 0

    def valid(g, i, d):
        for j in PEERS[i]:
            if g[j] == d:
                return False
        return True

    def rec():
        nonlocal count
        try:
            i = grid.index(0)
        except ValueError:
            count += 1
            return
        for d in range(1, 10):
            if valid(grid, i, d):
                grid[i] = d
                rec()
                grid[i] = 0
                if count >= limit:
                    return
        return

    # 先にヒント矛盾チェック
    for unit in UNITS:
        seen = set()
        for i in unit:
            if grid[i]:
                if grid[i] in seen:
                    return 0
                seen.add(grid[i])
    rec()
    return count


def is_complete_grid(g):
    for i in range(CELLS):
        if not (1 <= g[i] <= 9):
            return False
    for unit in UNITS:
        if sorted(g[i] for i in unit) != list(range(1, 10)):
            return False
    return True


# ---------------------------------------------------------------- 難度（自前実装・1件ずつ適用）
# 実装者版は「1回の走査で見つけた分をまとめて適用」。
# こちらは見つけ次第すぐ1件だけ適用し、都度盤面を再走査する（差があれば技法差として報告）。

TECH_NAMES = {1: "裸のシングル", 2: "隠れシングル", 3: "ロックド候補", 4: "裸のペア", 5: "隠れペア"}
UNSOLVED = "それ以上"


def candidates_of(grid):
    rows = [0] * 9
    cols = [0] * 9
    boxes = [0] * 9
    for i, v in enumerate(grid):
        if v:
            b = 1 << (v - 1)
            rows[ROW[i]] |= b
            cols[COL[i]] |= b
            boxes[BOX[i]] |= b
    cand = [0] * CELLS
    for i in range(CELLS):
        if not grid[i]:
            cand[i] = 0x1FF & ~(rows[ROW[i]] | cols[COL[i]] | boxes[BOX[i]])
    return cand


def place(grid, cand, i, d):
    grid[i] = d
    cand[i] = 0
    b = ~(1 << (d - 1))
    for j in PEERS[i]:
        cand[j] &= b


def find_naked_single(grid, cand):
    for i in range(CELLS):
        if not grid[i] and bin(cand[i]).count("1") == 1:
            return (i, cand[i].bit_length())
    return None


def find_hidden_single(grid, cand):
    for unit in UNITS:
        for d in range(1, 10):
            b = 1 << (d - 1)
            spots = [i for i in unit if not grid[i] and (cand[i] & b)]
            if len(spots) == 1:
                return (spots[0], d)
    return None


def find_locked_elim(grid, cand):
    """1件だけエリミネーションを返す（pointing/claiming）"""
    for bx in range(9):
        for d in range(1, 10):
            b = 1 << (d - 1)
            spots = [i for i in BOXCELLS[bx] if not grid[i] and (cand[i] & b)]
            if len(spots) < 2:
                continue
            rows_ = set(ROW[i] for i in spots)
            if len(rows_) == 1:
                r = rows_.pop()
                for i in ROWCELLS[r]:
                    if BOX[i] != bx and not grid[i] and (cand[i] & b):
                        return (i, b)
            cols_ = set(COL[i] for i in spots)
            if len(cols_) == 1:
                c = cols_.pop()
                for i in COLCELLS[c]:
                    if BOX[i] != bx and not grid[i] and (cand[i] & b):
                        return (i, b)
    for lines in (ROWCELLS, COLCELLS):
        for unit in lines:
            for d in range(1, 10):
                b = 1 << (d - 1)
                spots = [i for i in unit if not grid[i] and (cand[i] & b)]
                if len(spots) < 2:
                    continue
                boxes_ = set(BOX[i] for i in spots)
                if len(boxes_) == 1:
                    bx = boxes_.pop()
                    lineset = set(unit)
                    for i in BOXCELLS[bx]:
                        if i not in lineset and not grid[i] and (cand[i] & b):
                            return (i, b)
    return None


def find_naked_pair_elim(grid, cand):
    for unit in UNITS:
        empt = [i for i in unit if not grid[i]]
        for a in range(len(empt)):
            i = empt[a]
            if bin(cand[i]).count("1") != 2:
                continue
            for bidx in range(a + 1, len(empt)):
                j = empt[bidx]
                if cand[j] != cand[i]:
                    continue
                for k in empt:
                    if k != i and k != j and (cand[k] & cand[i]):
                        return (k, cand[k] & cand[i])
    return None


def find_hidden_pair_elim(grid, cand):
    for unit in UNITS:
        for d1 in range(1, 10):
            b1 = 1 << (d1 - 1)
            s1 = [i for i in unit if not grid[i] and (cand[i] & b1)]
            if len(s1) != 2:
                continue
            for d2 in range(d1 + 1, 10):
                b2 = 1 << (d2 - 1)
                s2 = [i for i in unit if not grid[i] and (cand[i] & b2)]
                if s2 != s1:
                    continue
                keep = b1 | b2
                for i in s1:
                    if cand[i] & ~keep:
                        return (i, cand[i] & ~keep)
    return None


def rate_qa(puzzle):
    """1件ずつ適用する独立実装。技法の優先順は spec と同じ
    (裸シングル→隠れシングル→ロックド候補→裸ペア→隠れペア)。"""
    grid = list(puzzle)
    cand = candidates_of(grid)
    hardest = 0
    while not all(grid):
        mv = find_naked_single(grid, cand)
        if mv:
            place(grid, cand, mv[0], mv[1])
            hardest = max(hardest, 1)
            continue
        mv = find_hidden_single(grid, cand)
        if mv:
            place(grid, cand, mv[0], mv[1])
            hardest = max(hardest, 2)
            continue
        el = find_locked_elim(grid, cand)
        if el:
            cand[el[0]] &= ~el[1]
            hardest = max(hardest, 3)
            continue
        el = find_naked_pair_elim(grid, cand)
        if el:
            cand[el[0]] &= ~el[1]
            hardest = max(hardest, 4)
            continue
        el = find_hidden_pair_elim(grid, cand)
        if el:
            cand[el[0]] &= ~el[1]
            hardest = max(hardest, 5)
            continue
        break
    if not all(grid):
        return UNSOLVED
    return TECH_NAMES[hardest] if hardest else TECH_NAMES[1]


def tier_of(name):
    if name == TECH_NAMES[1]:
        return "入門"
    if name == TECH_NAMES[2]:
        return "初級"
    if name == UNSOLVED:
        return "上級"
    return "中級"


# ---------------------------------------------------------------- 実行

def main():
    base = "/Users/ymacmini/Documents/claudecode@macmini/dev/puzzle-portal/sudoku"
    puzzles = json.load(open(base + "/tools/puzzles.json", encoding="utf-8"))

    results = {
        "count": len(puzzles),
        "uniqueness_fail": [],
        "solution_mismatch": [],
        "hint_mismatch": [],
        "solution_not_complete": [],
        "tier_mismatch": [],
        "length_bad": [],
        "givens_mismatch": [],
        "floor_violation": [],
        "order_violation": [],
    }

    prev_tier_group = {}
    for k, p in enumerate(puzzles):
        puz = p["puzzle"]
        sol = p["solution"]
        tier = p["tier"]
        givens = p["givens"]

        if len(puz) != 81 or len(sol) != 81:
            results["length_bad"].append((k, puz))
            continue

        pg = parse(puz)
        sg = parse(sol)

        # 一意性
        c = count_solutions(pg, 2)
        if c != 1:
            results["uniqueness_fail"].append((k, puz, c))

        # solution が完成盤か
        if not is_complete_grid(sg):
            results["solution_not_complete"].append((k, puz))

        # ヒント一致
        for i in range(81):
            if pg[i] != 0 and pg[i] != sg[i]:
                results["hint_mismatch"].append((k, puz))
                break

        # count_solutions で得た解と solution 文字列の一致（一意なら再構築して比較）
        if c == 1:
            grid2 = list(pg)

            def solve_unique(g):
                try:
                    i = g.index(0)
                except ValueError:
                    return True
                for d in range(1, 10):
                    ok = True
                    for j in PEERS[i]:
                        if g[j] == d:
                            ok = False
                            break
                    if ok:
                        g[i] = d
                        if solve_unique(g):
                            return True
                        g[i] = 0
                return False

            solve_unique(grid2)
            if grid2 != sg:
                results["solution_mismatch"].append((k, puz))

        # givens の数
        if puz.count("0") != 81 - givens:
            results["givens_mismatch"].append((k, puz))

        # 難度
        got = rate_qa(pg)
        got_tier = tier_of(got)
        if got_tier != tier:
            results["tier_mismatch"].append((k, puz, tier, p.get("hardest"), got_tier, got))

        # 段階ごとのヒント数下限
        if givens < FLOOR.get(tier, 0):
            results["floor_violation"].append((k, puz, tier, givens))

        # 段階内の降順チェック
        if tier in prev_tier_group and prev_tier_group[tier] < givens:
            results["order_violation"].append((k, puz, tier, givens, prev_tier_group[tier]))
        prev_tier_group[tier] = givens

    ok = True
    print("=== qa_check.py 結果 ===")
    for key, val in results.items():
        if key == "count":
            print("count:", val)
            continue
        status = "PASS" if not val else "FAIL(%d)" % len(val)
        if val:
            ok = False
        print("%-20s %s" % (key, status))
        if val:
            for row in val[:10]:
                print("   ", row)

    print()
    print("総合:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
