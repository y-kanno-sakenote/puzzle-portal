#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 担当: ✅ 検証係（マンガー×ファインマン）
"""独立ソルバー（実装者の gen_levels.py / index.html のコードを一切使わない）

- 盤面36文字を自前で解釈し、形の妥当性（長さ2/3・一直線・重なり無し・赤は y=2 横）を検査
- BFS（1手＝1台を任意距離）で最短手数と最短経路 [(車index, delta), ...] を出す
- 車indexは index.html の parse と同じ順（A が 0、以降は盤面での初出順）に揃える

使い方:
  python3 tools/qa_solver.py tools/levels.json            # 検査＋最短手数の照合
  python3 tools/qa_solver.py tools/levels.json --paths out.json   # 経路をJSONに書き出す（JS自動プレイ用）
"""
import json
import sys
from collections import deque

W = 6
EXIT_Y = 2


def parse_board(board):
    """36文字 -> (cars, errors)。cars = [(ch, x, y, len, dir)] 初出順。"""
    errors = []
    if len(board) != W * W:
        errors.append("長さ%d≠36" % len(board))
        return [], errors
    cells = {}
    order = []
    for i, ch in enumerate(board):
        if ch == "o":
            continue
        if not ("A" <= ch <= "Z"):
            errors.append("不正文字 %r@%d" % (ch, i))
            continue
        if ch not in cells:
            cells[ch] = []
            order.append(ch)
        cells[ch].append(i)
    cars = []
    for ch in order:
        idx = cells[ch]
        xs = [i % W for i in idx]
        ys = [i // W for i in idx]
        L = len(idx)
        if L not in (2, 3):
            errors.append("%s 長さ%d" % (ch, L))
        if len(set(ys)) == 1 and xs == list(range(xs[0], xs[0] + L)):
            d = "h"
        elif len(set(xs)) == 1 and ys == list(range(ys[0], ys[0] + L)):
            d = "v"
        else:
            errors.append("%s 一直線でない %s" % (ch, idx))
            d = "?"
        cars.append((ch, xs[0], ys[0], L, d))
    if not cars or cars[0][0] != "A":
        # A を先頭へ（index.html の parse と同じ）
        a = [c for c in cars if c[0] == "A"]
        if not a:
            errors.append("赤A無し")
        else:
            cars = a + [c for c in cars if c[0] != "A"]
    if cars and cars[0][0] == "A":
        _, x, y, L, d = cars[0]
        if not (y == EXIT_Y and d == "h" and L == 2):
            errors.append("赤A y=%d dir=%s len=%d" % (y, d, L))
    # 重なりは cells の構築上起こり得ない（1マス1文字）——但し文字ごとの一直線性で担保
    return cars, errors


def cells_of(car, p):
    ch, x, y, L, d = car
    if d == "h":
        return [(p + i, y) for i in range(L)]
    return [(x, p + i) for i in range(L)]


def solve(cars):
    """(最短手数, 経路) を返す。解けなければ (-1, None)。経路は [(車index, delta)]。
    クリア条件: 赤（index0）の x が W-len（右端）に着いた手でクリア（decision_log と同じ）。"""
    n = len(cars)
    start = tuple(c[1] if c[4] == "h" else c[2] for c in cars)
    goal = W - cars[0][3]
    if start[0] == goal:
        return 0, []
    prev = {start: None}
    q = deque([start])
    while q:
        st = q.popleft()
        occ = set()
        for i, c in enumerate(cars):
            occ.update(cells_of(c, st[i]))
        for i, c in enumerate(cars):
            own = set(cells_of(c, st[i]))
            others = occ - own
            for sign in (-1, 1):
                p = st[i]
                while True:
                    p2 = p + sign
                    if p2 < 0 or p2 + c[3] > W:
                        break
                    if set(cells_of(c, p2)) & others:
                        break
                    p = p2
                    ns = st[:i] + (p,) + st[i + 1:]
                    if ns not in prev:
                        prev[ns] = (st, i, p - st[i])
                        if i == 0 and p == goal:
                            # 経路復元
                            path = []
                            cur = ns
                            while prev[cur] is not None:
                                ps, ci, dl = prev[cur]
                                path.append((ci, dl))
                                cur = ps
                            path.reverse()
                            return len(path), path
                        q.append(ns)
    return -1, None


def main():
    src = sys.argv[1]
    levels = json.load(open(src, encoding="utf-8"))
    out_paths = None
    if "--paths" in sys.argv:
        out_paths = sys.argv[sys.argv.index("--paths") + 1]
    tiers = [("入門", 3, 5), ("初級", 6, 10), ("中級", 11, 18), ("上級", 19, 31), ("達人", 32, 10**9)]

    def tier_of(m):
        for name, lo, hi in tiers:
            if lo <= m <= hi:
                return name
        return None

    results = []
    boards = [l["board"] for l in levels]
    dup = len(boards) - len(set(boards))
    ok_all = True
    for k, l in enumerate(levels):
        cars, errs = parse_board(l["board"])
        m, path = (solve(cars) if not errs else (-1, None))
        row = {
            "i": k, "board": l["board"], "impl_min": l["min"], "qa_min": m,
            "impl_tier": l["tier"], "qa_tier": tier_of(m) if m >= 0 else None,
            "ncars": len(cars), "errors": errs, "path": path,
        }
        row["ok"] = (not errs) and m == l["min"] and row["qa_tier"] == l["tier"]
        ok_all &= row["ok"]
        results.append(row)
        flag = "OK " if row["ok"] else "NG "
        print("%s #%02d min impl=%2d qa=%2d tier impl=%s qa=%s cars=%2d %s %s" % (
            flag, k, l["min"], m, l["tier"], row["qa_tier"], len(cars), l["board"],
            ("; ".join(errs) if errs else "")), flush=True)
    print("boards=%d dup=%d all_ok=%s" % (len(boards), dup, ok_all))
    if out_paths:
        json.dump(results, open(out_paths, "w", encoding="utf-8"), ensure_ascii=False)
    sys.exit(0 if ok_all and dup == 0 else 1)


if __name__ == "__main__":
    main()
