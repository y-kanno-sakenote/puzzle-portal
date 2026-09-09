# 担当: qa係
# -*- coding: utf-8 -*-
"""ピクセル 独立検証（実装者の gen_puzzles.py のコードは使わない）
    python3 qa_check.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_from_html():
    src = (ROOT / "index.html").read_text(encoding="utf-8")
    m = re.search(r"var PUZZLES = (\[.*?\]);", src, re.S)
    if not m:
        raise SystemExit("PUZZLES 配列が見つからない")
    raw_json = re.sub(r"/\*.*?\*/", "", m.group(1), flags=re.S)
    return json.loads(raw_json)


def load_from_json():
    return json.loads((ROOT / "tools/puzzles.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 独立ソルバー
def generate_patterns(length, hints):
    if hints == [0]:
        return [[0] * length]
    res = []

    def rec(idx, pos, cur):
        if idx == len(hints):
            res.append(cur + [0] * (length - len(cur)))
            return
        b = hints[idx]
        rem = hints[idx + 1 :]
        min_space = b + (sum(rem) + len(rem))
        for st in range(pos, length - min_space + 1):
            pat = cur + [0] * (st - len(cur)) + [1] * b
            nxt = len(pat)
            if idx + 1 < len(hints):
                pat.append(0)
                nxt += 1
            rec(idx + 1, nxt, pat)

    rec(0, 0, [])
    return res


def solve_independent(w, h, row_hints, col_hints, limit=2):
    row_pats = [generate_patterns(w, hts) for hts in row_hints]
    col_pats = [generate_patterns(h, hts) for hts in col_hints]

    # ラインソルバーによる事前簡約
    grid = [[-1] * w for _ in range(h)]
    changed = True
    while changed:
        changed = False
        for r in range(h):
            valid = [p for p in row_pats[r] if all(grid[r][c] == -1 or grid[r][c] == p[c] for c in range(w))]
            row_pats[r] = valid
            if not valid:
                return []
            for c in range(w):
                if grid[r][c] == -1:
                    vals = {p[c] for p in valid}
                    if len(vals) == 1:
                        grid[r][c] = vals.pop()
                        changed = True
        for c in range(w):
            valid = [p for p in col_pats[c] if all(grid[r][c] == -1 or grid[r][c] == p[r] for r in range(h))]
            col_pats[c] = valid
            if not valid:
                return []
            for r in range(h):
                if grid[r][c] == -1:
                    vals = {p[r] for p in valid}
                    if len(vals) == 1:
                        grid[r][c] = vals.pop()
                        changed = True

    # 全て確定していれば即解を返却（一意解保証）
    if all(grid[r][c] != -1 for r in range(h) for c in range(w)):
        return ["".join(str(grid[i][j]) for i in range(h) for j in range(w))]

    # 未定マスが残る場合のみDFS
    sols = []
    def dfs(r, cur_grid):
        if len(sols) >= limit:
            return
        if r == h:
            sols.append("".join(str(cur_grid[i][j]) for i in range(h) for j in range(w)))
            return

        for p in row_pats[r]:
            valid = True
            for c in range(w):
                pref = [cur_grid[i][c] for i in range(r)] + [p[c]]
                if not any(cp[: r + 1] == pref for cp in col_pats[c]):
                    valid = False
                    break
            if valid:
                cur_grid.append(p)
                dfs(r + 1, cur_grid)
                cur_grid.pop()

    dfs(0, [])
    return sols


def main():
    try:
        puzzles = load_from_html()
        source = "index.html"
    except Exception:
        puzzles = load_from_json()
        source = "tools/puzzles.json"

    print(f"--- ピクセル独立QA検証 (source: {source}, total: {len(puzzles)}問) ---")
    fail = 0

    for p in puzzles:
        no = p["no"]
        title = p["title"]
        tier = p["tier"]
        w = p["w"]
        h = p["h"]
        row_hints = p["rowHints"]
        col_hints = p["colHints"]
        expected_sol = p["solution"]

        sols = solve_independent(w, h, row_hints, col_hints, limit=2)
        if len(sols) != 1:
            print(f"[FAIL] No.{no:02d} {title} ({tier}): 解の数={len(sols)} != 1")
            fail += 1
        elif sols[0] != expected_sol:
            print(f"[FAIL] No.{no:02d} {title} ({tier}): 解が期待値と不一致")
            fail += 1
        else:
            print(f"[OK] No.{no:02d} {title} ({tier}, {w}x{h}) - 一意解確認完了")

    print("--------------------------------------------------")
    if fail == 0:
        print(f"ALL {len(puzzles)} PASSED: 全問で一意解かつ正解一致を確認。")
        return 0
    else:
        print(f"{fail} 件のテストが失敗しました。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
