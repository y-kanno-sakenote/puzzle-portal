# -*- coding: utf-8 -*-
"""ピクセル 問題生成・検証スクリプト
    python3 gen_puzzles.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def parse_art(art_str):
    lines = [line.strip() for line in art_str.strip().splitlines() if line.strip()]
    h = len(lines)
    w = len(lines[0])
    grid = []
    for r in range(h):
        if len(lines[r]) != w:
            raise ValueError(f"Line {r} length {len(lines[r])} != {w}")
        row = []
        for c in range(w):
            row.append(1 if lines[r][c] == "#" else 0)
        grid.append(row)
    return w, h, grid


def get_hints(grid, w, h):
    row_hints = []
    for r in range(h):
        counts = []
        cur = 0
        for c in range(w):
            if grid[r][c] == 1:
                cur += 1
            elif cur > 0:
                counts.append(cur)
                cur = 0
        if cur > 0:
            counts.append(cur)
        row_hints.append(counts if counts else [0])

    col_hints = []
    for c in range(w):
        counts = []
        cur = 0
        for r in range(h):
            if grid[r][c] == 1:
                cur += 1
            elif cur > 0:
                counts.append(cur)
                cur = 0
        if cur > 0:
            counts.append(cur)
        col_hints.append(counts if counts else [0])

    return row_hints, col_hints


def generate_line_patterns(length, hints):
    if hints == [0]:
        return [[0] * length]

    results = []

    def build(hint_idx, pos, current):
        if hint_idx == len(hints):
            results.append(current + [0] * (length - len(current)))
            return
        block_len = hints[hint_idx]
        rem_blocks = hints[hint_idx + 1 :]
        min_needed = block_len + (sum(rem_blocks) + len(rem_blocks))
        for start in range(pos, length - min_needed + 1):
            pattern = current + [0] * (start - len(current)) + [1] * block_len
            next_pos = len(pattern)
            if hint_idx + 1 < len(hints):
                pattern.append(0)
                next_pos += 1
            build(hint_idx + 1, next_pos, pattern)

    build(0, 0, [])
    return results


def solve_line(w, h, row_hints, col_hints):
    """仮定なしラインソルバー"""
    row_patterns = [generate_line_patterns(w, hts) for hts in row_hints]
    col_patterns = [generate_line_patterns(h, hts) for hts in col_hints]

    grid = [[-1] * w for _ in range(h)]
    changed = True

    while changed:
        changed = False
        for r in range(h):
            valid = []
            for p in row_patterns[r]:
                match = True
                for c in range(w):
                    if grid[r][c] != -1 and grid[r][c] != p[c]:
                        match = False
                        break
                if match:
                    valid.append(p)
            row_patterns[r] = valid
            if not valid:
                return False, grid
            for c in range(w):
                if grid[r][c] == -1:
                    vals = {p[c] for p in valid}
                    if len(vals) == 1:
                        grid[r][c] = vals.pop()
                        changed = True

        for c in range(w):
            valid = []
            for p in col_patterns[c]:
                match = True
                for r in range(h):
                    if grid[r][c] != -1 and grid[r][c] != p[r]:
                        match = False
                        break
                if match:
                    valid.append(p)
            col_patterns[c] = valid
            if not valid:
                return False, grid
            for r in range(h):
                if grid[r][c] == -1:
                    vals = {p[r] for p in valid}
                    if len(vals) == 1:
                        grid[r][c] = vals.pop()
                        changed = True

    complete = all(grid[r][c] != -1 for r in range(h) for c in range(w))
    if not complete:
        unsolved = [(r, c) for r in range(h) for c in range(w) if grid[r][c] == -1]
        print(f"DEBUG: {len(unsolved)} cells unsolved: {unsolved}")
    return complete, grid


def count_all_solutions(w, h, row_hints, col_hints, limit=2):
    """バックトラックによる全解カウント"""
    row_patterns = [generate_line_patterns(w, hts) for hts in row_hints]
    col_patterns = [generate_line_patterns(h, hts) for hts in col_hints]

    sols = []

    def search(r, cur_grid):
        if len(sols) >= limit:
            return
        if r == h:
            sols.append([row[:] for row in cur_grid])
            return

        for p in row_patterns[r]:
            ok = True
            for c in range(w):
                prefix = [cur_grid[i][c] for i in range(r)] + [p[c]]
                if not any(cp[: r + 1] == prefix for cp in col_patterns[c]):
                    ok = False
                    break
            if ok:
                cur_grid.append(p)
                search(r + 1, cur_grid)
                cur_grid.pop()

    search(0, [])
    return len(sols)


ART_5X5 = [
    (
        "じゅうじ",
        """
..#..
..#..
#####
..#..
..#..
""",
    ),
    (
        "リボン",
        """
#...#
##.##
.###.
##.##
#...#
""",
    ),
    (
        "さんかく",
        """
..#..
..#..
.###.
.###.
#####
""",
    ),
    (
        "はた",
        """
####.
####.
####.
#....
#....
""",
    ),
    (
        "チューリップ",
        """
#.#.#
#####
.###.
..#..
.###.
""",
    ),
    (
        "やじるし",
        """
..#..
.###.
#####
..#..
..#..
""",
    ),
    (
        "ばつ",
        """
#...#
##.##
..#..
##.##
#...#
""",
    ),
    (
        "ハート",
        """
.#.#.
#####
#####
.###.
..#..
""",
    ),
    (
        "ダイヤ",
        """
..#..
.###.
#####
.###.
..#..
""",
    ),
    (
        "ほし",
        """
..#..
#####
.###.
.#.#.
#...#
""",
    ),
]

ART_10X10 = [
    (
        "アイスクリーム",
        """
...####...
..######..
.########.
..######..
..######..
...####...
...####...
....##....
....##....
.....#....
""",
    ),
    (
        "きのこ",
        """
...####...
..######..
.########.
##.#####.#
##########
....##....
....##....
...####...
...####...
..######..
""",
    ),
    (
        "かさ",
        """
....##....
..######..
.########.
##########
##########
....##....
....##....
....##....
..####....
..##......
""",
    ),
    (
        "りんご",
        """
....###...
....#.....
..######..
.########.
##########
##########
.########.
.########.
..##..##..
..........
""",
    ),
    (
        "かお",
        """
..######..
.##....##.
##......##
##.#..#.##
##......##
##.#..#.##
##.####.##
.##....##.
..######..
..........
""",
    ),
    (
        "いえ",
        """
....##....
...####...
..######..
.########.
##########
..######..
..######..
..##..##..
..##..##..
..##..##..
""",
    ),
    (
        "カップ",
        """
..#..#....
...#..#...
..#..#....
..........
#######...
#######.##
#######..#
#######.##
#######...
.#####....
""",
    ),
    (
        "つき",
        """
...####...
..######..
.#####....
.####.....
.####.....
.####.....
.####.....
.#####....
..######..
...####...
""",
    ),
    (
        "かぎ",
        """
.#####....
.##.##....
.##.##....
.#####....
..###.....
..###.....
..###.....
..#####...
..###.....
..#####...
""",
    ),
    (
        "おんぷ",
        """
.....#####
.....##..#
.....##.##
.....####.
.....##...
.....##...
.....##...
..#####...
.######...
..#####...
""",
    ),
    (
        "ネコ",
        """
..#....#..
..##..##..
..######..
.########.
.#.####.#.
.########.
.##.##.##.
.########.
..######..
..........
""",
    ),
    (
        "さかな",
        """
..........
.....###..
#...#####.
##.#######
########.#
##########
##.#######
#...#####.
.....###..
..........
""",
    ),
    (
        "ヨット",
        """
....#.....
....##....
....###...
....####..
....#####.
....######
....#.....
.########.
..######..
..........
""",
    ),
    (
        "とっくり",
        """
...####...
...####...
....##....
....##....
...####...
..######..
.########.
.########.
.########.
..######..
""",
    ),
    (
        "おちょこ",
        """
..........
..........
##########
##########
.########.
.########.
..######..
..######..
...####...
..........
""",
    ),
    (
        "かんむり",
        """
..........
.#..##..#.
.#.####.#.
.########.
.########.
.##.##.##.
.########.
.########.
.########.
..........
""",
    ),
    (
        "ちょうちょ",
        """
#........#
.#......#.
.##....##.
####..####
##########
.##.##.##.
##########
####..####
.##....##.
..........
""",
    ),
    (
        "ロケット",
        """
....##....
...####...
...####...
...####...
..######..
..######..
##.####.##
##.####.##
...####...
....##....
""",
    ),
    (
        "ゆきのけっしょう",
        """
....##....
....##....
#.######.#
.########.
..#.##.#..
..#.##.#..
.########.
#.######.#
....##....
....##....
""",
    ),
    (
        "てんとうむし",
        """
..........
..#....#..
...####...
..######..
.###..###.
.########.
.##.##.##.
.########.
..######..
..........
""",
    ),
    (
        "いかり",
        """
...####...
...#..#...
...####...
.########.
....##....
....##....
#...##...#
#...##...#
##.####.##
.########.
""",
    ),
    (
        "ペンギン",
        """
...####...
..######..
..#.##.#..
..######..
...####...
.########.
.##....##.
.##....##.
.########.
..#....#..
""",
    ),
    (
        "き",
        """
....##....
...####...
..######..
.########.
##########
.########.
..######..
....##....
....##....
..######..
""",
    ),
    (
        "かに",
        """
##......##
.##....##.
..#.##.#..
.########.
##########
##########
.########.
#.######.#
#........#
..........
""",
    ),
    (
        "とり",
        """
..........
......###.
.....#####
.....####.
...######.
..#######.
.########.
..######..
...#..#...
..........
""",
    ),
    (
        "ゆきだるま",
        """
...####...
...####...
..######..
...####...
..#.##.#..
...####...
#.######.#
.########.
.###..###.
..######..
""",
    ),
    (
        "ろうそく",
        """
....#.....
...##.....
...###....
....##....
.....#....
..######..
..######..
..######..
..######..
.########.
""",
    ),
    (
        "ちょうちん",
        """
....##....
...####...
..######..
.########.
.#.####.#.
.#.####.#.
.########.
..######..
...####...
....##....
""",
    ),
    (
        "くるま",
        """
..........
..........
..####....
.######...
.########.
##########
##########
.##.##.##.
.##....##.
..........
""",
    ),
    (
        "ギター",
        """
....##....
....##....
....##....
...####...
..######..
.###..###.
.########.
.########.
..######..
...####...
""",
    ),
]

ART_15X15 = [
    (
        "カメラ",
        """
...............
.....#####.....
....#######....
...#########...
.#############.
.#############.
.##..#####..##.
.##.#######.##.
.##.#######.##.
.##.#######.##.
.##..#####..##.
.#############.
.#############.
...............
...............
""",
    ),
    (
        "フクロウ",
        """
...............
...##.....##...
..####...####..
.######.######.
.#############.
.##.#######.##.
.#############.
..###########..
...#########...
....#######....
...#########...
..###########..
..#..#####..#..
.##.#######.##.
.##############
""",
    ),
]

ART_25X25 = [
    (
        "シバイヌ",
        """
.........................
......##.........##......
.....####.......####.....
....######.....######....
....#######...#######....
...###################...
...###################...
...###################...
...##.#############.##...
...##.#############.##...
...###################...
....#################....
.....###############.....
......#############......
.....###############.....
....#################....
...###################...
...###################...
..#####################..
..#####################..
.#######################.
.#######################.
.##..###############..##.
.##...#############...##.
.........................
""",
    ),
]


# ---------------------------------------------------------------- 難度指標
def solve_with_metrics(w, h, row_hints, col_hints):
    """ラインソルバーを計測付きで走らせる。
    P  = 反復回数（行+列を一巡して何周で解け切ったか）
    W  = 新情報を生んだライン処理の回数
    R1 = 1周目を終えた時点で未確定のマス数
    S  = 行・列の候補パターン総数（探索空間の大きさ）
    """
    row_patterns = [generate_line_patterns(w, hts) for hts in row_hints]
    col_patterns = [generate_line_patterns(h, hts) for hts in col_hints]
    space = sum(len(p) for p in row_patterns) + sum(len(p) for p in col_patterns)

    grid = [[-1] * w for _ in range(h)]
    passes = 0
    work = 0
    rest1 = None
    changed = True

    while changed:
        changed = False
        passes += 1
        for r in range(h):
            valid = [p for p in row_patterns[r] if all(grid[r][c] == -1 or grid[r][c] == p[c] for c in range(w))]
            row_patterns[r] = valid
            if not valid:
                return False, grid, {"P": passes, "W": work, "R1": w * h, "S": space, "D": 10 ** 6}
            got = False
            for c in range(w):
                if grid[r][c] == -1:
                    vals = {p[c] for p in valid}
                    if len(vals) == 1:
                        grid[r][c] = vals.pop()
                        changed = True
                        got = True
            if got:
                work += 1
        for c in range(w):
            valid = [p for p in col_patterns[c] if all(grid[r][c] == -1 or grid[r][c] == p[r] for r in range(h))]
            col_patterns[c] = valid
            if not valid:
                return False, grid, {"P": passes, "W": work, "R1": w * h, "S": space, "D": 10 ** 6}
            got = False
            for r in range(h):
                if grid[r][c] == -1:
                    vals = {p[r] for p in valid}
                    if len(vals) == 1:
                        grid[r][c] = vals.pop()
                        changed = True
                        got = True
            if got:
                work += 1
        if passes == 1:
            rest1 = sum(1 for r in range(h) for c in range(w) if grid[r][c] == -1)

    if rest1 is None:
        rest1 = 0
    complete = all(grid[r][c] != -1 for r in range(h) for c in range(w))
    D = passes * 20 + work * 2 + rest1
    return complete, grid, {"P": passes, "W": work, "R1": rest1, "S": space, "D": D}


def build():
    """全モチーフを検証し、実測難度順に段階を割り当てる"""
    items = []
    for title, art_str in ART_5X5 + ART_10X10 + ART_15X15 + ART_25X25:
        w, h, grid = parse_art(art_str)
        row_hints, col_hints = get_hints(grid, w, h)
        solved, _, m = solve_with_metrics(w, h, row_hints, col_hints)
        sols = count_all_solutions(w, h, row_hints, col_hints, limit=2) if (w <= 10) else (1 if solved else 0)
        fill = sum(sum(r) for r in grid)
        items.append(
            {
                "title": title,
                "w": w,
                "h": h,
                "rowHints": row_hints,
                "colHints": col_hints,
                "solution": "".join(str(grid[r][c]) for r in range(h) for c in range(w)),
                "ok": solved and sols == 1,
                "line_solved": solved,
                "sols": sols,
                "fill": fill,
                "metrics": m,
            }
        )

    # 段階割り当て
    small = sorted([i for i in items if i["w"] == 5], key=lambda i: i["metrics"]["D"])
    mid = sorted([i for i in items if i["w"] == 10], key=lambda i: i["metrics"]["D"])
    large15 = [i for i in items if i["w"] == 15]
    large25 = [i for i in items if i["w"] == 25]

    for i in small:
        i["tier"] = "入門"
    for n, i in enumerate(mid):
        i["tier"] = ["初級", "中級", "上級"][n // 10]
    for i in large15:
        i["tier"] = "特級"
    for i in large25:
        i["tier"] = "達人"

    return small + mid + large15 + large25


def main():
    is_json = "--json" in sys.argv
    ordered = build()
    all_ok = all(i["ok"] for i in ordered)

    puzzles_json = []
    for idx, i in enumerate(ordered):
        puzzles_json.append(
            {
                "no": idx + 1,
                "title": i["title"],
                "tier": i["tier"],
                "w": i["w"],
                "h": i["h"],
                "rowHints": i["rowHints"],
                "colHints": i["colHints"],
                "solution": i["solution"],
            }
        )

    if is_json:
        print(json.dumps(puzzles_json, ensure_ascii=False, indent=2))
        return

    print(f"Checking {len(ordered)} puzzles...")
    for idx, i in enumerate(ordered):
        m = i["metrics"]
        status = "OK" if i["ok"] else "NG"
        print(
            f"[{idx+1:02d}] {i['title']:10s} ({i['tier']}, {i['w']}x{i['h']}) "
            f"fill={i['fill']:3d} line={i['line_solved']} sols={i['sols']} "
            f"P={m['P']} W={m['W']} R1={m['R1']} S={m['S']} D={m['D']} -> {status}"
        )

    print("--- 段階ごとの D レンジ ---")
    for tier in ("入門", "初級", "中級", "上級"):
        ds = [i["metrics"]["D"] for i in ordered if i["tier"] == tier]
        ss = [i["metrics"]["S"] for i in ordered if i["tier"] == tier]
        print(f"  {tier}: D={min(ds)}〜{max(ds)}  S={min(ss)}〜{max(ss)}")

    if all_ok:
        print("ALL 40 PUZZLES ARE VALID (Unique solution & Line solvable without guessing)!")
    else:
        print("SOME PUZZLES FAILED.")

    payload = json.dumps(puzzles_json, ensure_ascii=False)
    print(f"Total payload size: {len(payload)} bytes")
    (ROOT / "tools" / "puzzles.json").write_text(
        json.dumps(puzzles_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("wrote tools/puzzles.json")


if __name__ == "__main__":
    main()
