#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""車をだせ！ レベル生成器（Python3 標準ライブラリのみ）

6x6 のラッシュアワー型盤面をランダム生成し、BFS で最短手数（1手＝1台を任意距離
滑らせる）を求め、解ける／最短3手以上のものだけを難度4段階に振り分けて出力する。

  入門 3〜5 / 初級 6〜10 / 中級 11〜18 / 上級 19〜   各10本・計40本
  難度ラベルは実測の最短手数からのみ決める（手で貼らない）。

出力: JSON 配列 [{"board": "36文字", "min": n, "tier": "入門"}, ...] を標準出力へ。
盤面記法: 36文字（row-major）。o=空 / A=赤い車（長さ2・横・y=2）/ B〜=他の車。

使い方:
  python3 tools/gen_levels.py --seed 20260906 > tools/levels.json
  # index.html への埋め込みは LEVELS-BEGIN / LEVELS-END の間を差し替える
"""

import argparse
import json
import random
import sys
from collections import deque

W = 6            # 盤の一辺
EXIT_Y = 2       # 出口の行（上から3行目）
RED_LEN = 2      # 赤い車の長さ
LETTERS = "BCDEFGHIJKLMNOPQRSTUVWXYZ"

TIERS = [
    ("入門", 3, 5),
    ("初級", 6, 10),
    ("中級", 11, 18),
    ("上級", 19, 10**9),
]
PER_TIER = 10


# ---------------------------------------------------------------- 盤面の表現
# 車 = (x, y, length, orient)   orient: 0=横, 1=縦
# 状態 = 各車の可変座標のタプル（横なら x, 縦なら y）

def car_cells(car, pos=None):
    x, y, L, o = car
    if o == 0:
        x = pos if pos is not None else x
        return [(x + i, y) for i in range(L)]
    else:
        y = pos if pos is not None else y
        return [(x, y + i) for i in range(L)]


def var_pos(car):
    return car[0] if car[3] == 0 else car[1]


def masks_for(car):
    """可変座標 -> ビットマスク（範囲外は None）"""
    x, y, L, o = car
    out = [None] * (W + 1)
    for p in range(0, W - L + 1):
        m = 0
        for (cx, cy) in car_cells(car, p):
            m |= 1 << (cy * W + cx)
        out[p] = m
    return out


def added_cell_bit(car, p, direction):
    """位置 p から direction(+1/-1) に1マス動いたとき新たに占める1マスのビット"""
    x, y, L, o = car
    if direction < 0:
        q = p - 1
    else:
        q = p + L
    if o == 0:
        if q < 0 or q >= W:
            return None
        return 1 << (y * W + q)
    else:
        if q < 0 or q >= W:
            return None
        return 1 << (q * W + x)


# ---------------------------------------------------------------- BFS ソルバ
def solve(cars, node_limit=2_000_000):
    """最短手数を返す。解けなければ -1。1手＝1台を任意距離。"""
    n = len(cars)
    masks = [masks_for(c) for c in cars]
    limits = [W - c[2] for c in cars]  # 可変座標の上限
    # p から -1 / +1 に1マス動くとき新たに占めるマスのビット（先に表にしておく）
    neg = []
    pos = []
    for c in cars:
        nb = [0] * (W + 1)
        pb = [0] * (W + 1)
        for p in range(0, W - c[2] + 1):
            b = added_cell_bit(c, p, -1)
            nb[p] = b if b is not None else 0
            b = added_cell_bit(c, p, 1)
            pb[p] = b if b is not None else 0
        neg.append(nb)
        pos.append(pb)

    start = tuple(var_pos(c) for c in cars)
    goal_pos = W - cars[0][2]  # 赤い車が右端に着いたら勝ち（そこから盤外へ抜ける）
    if start[0] == goal_pos:
        return 0

    seen = {start}
    q = deque([(start, 0)])
    nodes = 0
    rng_n = range(n)
    while q:
        state, d = q.popleft()
        nodes += 1
        if nodes > node_limit:
            return -1
        nd = d + 1
        occ = 0
        for i in rng_n:
            occ |= masks[i][state[i]]
        for i in rng_n:
            rest = occ ^ masks[i][state[i]]
            lim = limits[i]
            nb = neg[i]
            pb = pos[i]
            p = state[i]
            while p > 0 and not (rest & nb[p]):
                p -= 1
                ns = state[:i] + (p,) + state[i + 1:]
                if i == 0 and p == goal_pos:
                    return nd
                if ns not in seen:
                    seen.add(ns)
                    q.append((ns, nd))
            p = state[i]
            while p < lim and not (rest & pb[p]):
                p += 1
                ns = state[:i] + (p,) + state[i + 1:]
                if i == 0 and p == goal_pos:
                    return nd
                if ns not in seen:
                    seen.add(ns)
                    q.append((ns, nd))
    return -1


# ---------------------------------------------------------------- 文字列変換
def to_board(cars):
    grid = ["o"] * (W * W)
    for i, car in enumerate(cars):
        ch = "A" if i == 0 else LETTERS[i - 1]
        for (x, y) in car_cells(car):
            grid[y * W + x] = ch
    return "".join(grid)


def normalize(cars):
    """赤を先頭に、他の車を左上から順（row-major）に並べ替える（重複判定の正規形）"""
    red = cars[0]
    others = sorted(cars[1:], key=lambda c: (c[1] * W + c[0]))
    return [red] + others


# ---------------------------------------------------------------- 盤面の生成
def place_ok(cars, cand):
    cells = set()
    for c in cars:
        cells |= set(car_cells(c))
    for cell in car_cells(cand):
        if cell in cells:
            return False
    return True


def random_board(rng, ncars):
    """赤1台＋ncars台。置けなければ None"""
    red_x = rng.randint(0, W - RED_LEN - 1)  # 0..3（いきなりクリア済みは作らない）
    cars = [(red_x, EXIT_Y, RED_LEN, 0)]
    tries = 0
    while len(cars) - 1 < ncars and tries < 200:
        tries += 1
        L = rng.choice([2, 2, 3])
        o = rng.randint(0, 1)
        if o == 0:
            x = rng.randint(0, W - L)
            y = rng.randint(0, W - 1)
        else:
            x = rng.randint(0, W - 1)
            y = rng.randint(0, W - L)
        cand = (x, y, L, o)
        if place_ok(cars, cand):
            cars.append(cand)
    if len(cars) - 1 < ncars:
        return None
    return normalize(cars)


def perturb(rng, cars):
    """山登り用のゆらぎ: 1台をどかして置き直す／長さ・向きを変える／増減させる"""
    cars = list(cars)
    n_other = len(cars) - 1
    op = rng.random()
    if op < 0.15 and n_other < 10:   # 他の車は最大10台（仕様）
        mode = "add"
    elif op < 0.25 and n_other > 4:
        mode = "del"
    else:
        mode = "move"

    if mode == "del":
        i = rng.randint(1, n_other)
        cars.pop(i)
        return normalize(cars)

    if mode == "move":
        i = rng.randint(1, n_other)
        removed = cars.pop(i)
    for _ in range(60):
        L = rng.choice([2, 2, 3])
        o = rng.randint(0, 1)
        if o == 0:
            x = rng.randint(0, W - L)
            y = rng.randint(0, W - 1)
        else:
            x = rng.randint(0, W - 1)
            y = rng.randint(0, W - L)
        cand = (x, y, L, o)
        if place_ok(cars, cand):
            cars.append(cand)
            return normalize(cars)
    if mode == "move":
        cars.append(removed)
    return normalize(cars)


def tier_of(m):
    for name, lo, hi in TIERS:
        if lo <= m <= hi:
            return name
    return None


# ---------------------------------------------------------------- 探索
def collect(rng, rounds, pool, log):
    """ランダム生成 → BFS → プールへ"""
    for _ in range(rounds):
        ncars = rng.choice([4, 5, 6, 7, 8, 8, 9, 9, 10, 10])
        cars = random_board(rng, ncars)
        if cars is None:
            continue
        board = to_board(cars)
        if board in pool["seen"]:
            continue
        pool["seen"].add(board)
        m = solve(cars)
        if m < 3:
            continue
        t = tier_of(m)
        if t is None:
            continue
        pool["by_tier"].setdefault(t, []).append({"board": board, "min": m, "cars": cars})
        if m > pool["best_min"]:
            pool["best_min"] = m
            pool["best_cars"] = cars


def climb(rng, pool, seeds, steps, log):
    """山登り: 難しい盤を少しずつ崩して、さらに難しい盤を探す（上級を出すため）"""
    for cars0 in seeds:
        cur = cars0
        cur_m = solve(cur)
        if cur_m < 0:
            continue
        for _ in range(steps):
            cand = perturb(rng, cur)
            if len(cand) - 1 < 4:
                continue
            board = to_board(cand)
            if board in pool["seen"]:
                continue
            pool["seen"].add(board)
            m = solve(cand)
            if m < 3:
                continue
            t = tier_of(m)
            if t:
                pool["by_tier"].setdefault(t, []).append({"board": board, "min": m, "cars": cand})
            if m >= cur_m:          # 同点も受け入れて平地を歩く
                cur, cur_m = cand, m
            elif rng.random() < 0.05:
                cur, cur_m = cand, m


def pick(cands, k):
    """最短手数の値をなるべく散らして k 本選ぶ"""
    by_min = {}
    for c in cands:
        by_min.setdefault(c["min"], []).append(c)
    keys = sorted(by_min)
    out = []
    while len(out) < k:
        progressed = False
        for key in keys:
            if by_min[key]:
                out.append(by_min[key].pop(0))
                progressed = True
                if len(out) >= k:
                    break
        if not progressed:
            break
    return sorted(out, key=lambda c: c["min"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20260906)
    ap.add_argument("--rounds", type=int, default=4000, help="ランダム生成の試行回数")
    ap.add_argument("--climb-steps", type=int, default=400, help="山登り1本あたりの歩数")
    ap.add_argument("--embed", metavar="HTML",
                    help="この HTML の LEVELS-BEGIN / LEVELS-END の間へ直接埋め込む")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    log = (lambda *a: None) if args.quiet else (lambda *a: print(*a, file=sys.stderr))

    pool = {"seen": set(), "by_tier": {}, "best_min": -1, "best_cars": None}

    log("[1/3] ランダム生成 ...")
    collect(rng, args.rounds, pool, log)
    for name, _, _ in TIERS:
        log("   ", name, len(pool["by_tier"].get(name, [])))

    # 上級（19手以上）はランダムだとほぼ出ないので、難しい盤から山登りする
    log("[2/3] 山登り（上級ねらい）...")
    for wave in range(6):
        need = PER_TIER - len(pool["by_tier"].get("上級", []))
        if need <= 0:
            break
        allc = []
        for name, _, _ in TIERS:
            allc += pool["by_tier"].get(name, [])
        allc.sort(key=lambda c: -c["min"])
        seeds = [c["cars"] for c in allc[:14]]
        if not seeds:
            break
        climb(rng, pool, seeds, args.climb_steps, log)
        log("   wave", wave, "上級", len(pool["by_tier"].get("上級", [])),
            "中級", len(pool["by_tier"].get("中級", [])))

    log("[3/3] 選抜 ...")
    levels = []
    shortfall = []
    for name, _, _ in TIERS:
        cands = pool["by_tier"].get(name, [])
        chosen = pick(cands, PER_TIER)
        if len(chosen) < PER_TIER:
            shortfall.append((name, len(chosen)))
        levels += chosen

    # 足りない段階があっても嘘のラベルは貼らない。
    # 不足分は「実際に一番難しい盤」で埋め、そのラベルは実測どおりに付ける。
    total = len(levels)
    if total < PER_TIER * len(TIERS):
        used = {l["board"] for l in levels}
        rest = []
        for name, _, _ in TIERS:
            for c in pool["by_tier"].get(name, []):
                if c["board"] not in used:
                    rest.append(c)
        rest.sort(key=lambda c: -c["min"])
        for c in rest[: PER_TIER * len(TIERS) - total]:
            levels.append(c)

    levels.sort(key=lambda c: (c["min"], c["board"]))
    out = [{"board": c["board"], "min": c["min"], "tier": tier_of(c["min"])} for c in levels]

    # 分布を標準エラーへ
    dist = {}
    for o in out:
        dist.setdefault(o["tier"], []).append(o["min"])
    for name, _, _ in TIERS:
        v = dist.get(name, [])
        if v:
            log("分布 %s: %d本 min=%d..%d" % (name, len(v), min(v), max(v)))
        else:
            log("分布 %s: 0本" % name)
    if shortfall:
        log("不足:", shortfall)

    body = "var LEVELS = [\n" + ",\n".join(
        '  {"board":"%s","min":%d,"tier":"%s"}' % (o["board"], o["min"], o["tier"])
        for o in out) + "\n];\n"

    if args.embed:
        with open(args.embed, encoding="utf-8") as f:
            html = f.read()
        b = html.index("/* LEVELS-BEGIN")
        b = html.index("\n", b) + 1
        e = html.index("/* LEVELS-END")
        html = html[:b] + body + html[e:]
        with open(args.embed, "w", encoding="utf-8") as f:
            f.write(html)
        log("埋め込み完了:", args.embed)

    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
