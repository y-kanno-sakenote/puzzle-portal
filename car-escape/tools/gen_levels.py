#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""車をだせ！ レベル生成器（Python3 標準ライブラリのみ）

6x6 のラッシュアワー型盤面をランダム生成し、BFS で最短手数（1手＝1台を任意距離
滑らせる）を求め、解ける／最短3手以上のものだけを難度4段階に振り分けて出力する。

  入門 3〜5 / 初級 6〜10 / 中級 11〜18 / 上級 19〜31 / 達人 32〜   各10本・計50本
  難度ラベルは実測の最短手数からのみ決める（手で貼らない）。

  「達人」だけは探索方式が違う（2026-09-07）。位置を揺らす山登りでは31手が頭打ちだったので、
  車の「並び方（各車の向き・固定座標・長さ）」の集合を焼きなましで動かし、その集合ごとに
  **全状態空間を逆向きBFS**（ゴール＝赤が右端の全状態からの多点BFS）して最遠の状態を採る。
  つまり集合内では位置の最適化を全数で済ませる。赤含め最大12台。

  選抜では「既採用盤との車形（各車の x,y,向き,長さ の集合）Jaccard 類似度 <= 0.5」を
  全段階に課す（qa 2026-09-06 差し戻し: 山登り由来の焼き直し家族を排除するため）。
  山登りは互いに無関係なランダム種盤から多数回・独立に走らせる。

出力: JSON 配列 [{"board": "36文字", "min": n, "tier": "入門"}, ...] を標準出力へ。
盤面記法: 36文字（row-major）。o=空 / A=赤い車（長さ2・横・y=2）/ B〜=他の車。

使い方:
  python3 tools/gen_levels.py --seed 20260906 > tools/levels.json          # 入門〜上級40本
  # 既存40本を固定したまま達人10本だけ足す（既存の盤面文字列と順番は触らない）
  python3 tools/gen_levels.py --keep tools/levels.json --tiers 達人 \
      --seed 20260907 --master-budget 480 > new.json          # 実測 481s
  # 出来た50本を index.html の LEVELS-BEGIN / LEVELS-END の間へ埋め込む（生成し直さない）
  python3 tools/gen_levels.py --keep new.json --tiers "" --embed index.html > tools/levels.json

  注: 達人の焼きなましは「秒数」で打ち切るので、同じ seed でも実行環境と負荷で結果が変わる。
      再現の正は tools/levels.json の方（生成し直さず --keep で読み込むこと）。
"""

import argparse
import json
import math
import random
import sys
import time
from collections import deque

W = 6            # 盤の一辺
EXIT_Y = 2       # 出口の行（上から3行目）
RED_LEN = 2      # 赤い車の長さ
LETTERS = "BCDEFGHIJKLMNOPQRSTUVWXYZ"

TIERS = [
    ("入門", 3, 5),
    ("初級", 6, 10),
    ("中級", 11, 18),
    ("上級", 19, 31),
    ("達人", 32, 10**9),
]
PER_TIER = 10
MASTER = "達人"          # 車種集合の焼きなましで作る段階（他とは探索方式が違う）
MASTER_MAX_OTHER = 11    # 赤を含めて12台まで（上級までは赤＋10台）


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


def parse_board(board):
    """36文字 -> cars。--keep で既存レベルを読み直すときに使う（車形の照合用）"""
    cells = {}
    for i, ch in enumerate(board):
        if ch == "o":
            continue
        cells.setdefault(ch, []).append(i)
    cars = []
    for ch in sorted(cells, key=lambda c: (c != "A", c)):
        idx = cells[ch]
        xs = [i % W for i in idx]
        ys = [i // W for i in idx]
        o = 0 if len(set(ys)) == 1 else 1
        cars.append((min(xs), min(ys), len(idx), o))
    return normalize(cars)


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


# ------------------------------------------------------------ 類似度（焼き直し検出）
MAX_J = 0.5      # 既採用盤との車形 Jaccard の上限（qa 2026-09-06 差し戻し条件）


def shape_set(cars):
    """盤面の「車形集合」: 各車の (x, y, 向き, 長さ)。赤も含める。"""
    return frozenset((c[0], c[1], c[3], c[2]) for c in cars)


def jaccard(a, b):
    u = len(a | b)
    return (len(a & b) / u) if u else 0.0


def far_enough(shape, chosen):
    for c in chosen:
        if jaccard(shape, c["shape"]) > MAX_J:
            return False
    return True


# ------------------------------------------- 達人: 車種集合ごとに全状態空間を見る
# 「車種集合」= 各車の (固定座標, 長さ, 向き) の並び。可変座標（横なら x、縦なら y）だけが
# 状態になる。集合を固定すれば状態空間は有限で、ゴール（赤が右端）からの多点BFSで
# 全状態の「ゴールまでの最短手数」が一度に出る（1手＝任意距離の滑りは可逆なので逆向きに歩ける）。
# その最遠の状態こそ、この集合で作れる最難の盤。位置の探索は全数で済むので、
# 焼きなましは集合の形だけを動かせばよい。

def slot_masks(fixed, L, o):
    out = []
    for p in range(W - L + 1):
        m = 0
        for i in range(L):
            m |= 1 << (fixed * W + p + i) if o == 0 else 1 << ((p + i) * W + fixed)
        out.append(m)
    return out


def slot_added(fixed, L, o):
    """位置 p から -1 / +1 に1マス動くとき新たに占めるマスのビット"""
    neg = [0] * (W - L + 1)
    pos = [0] * (W - L + 1)
    for p in range(W - L + 1):
        if p - 1 >= 0:
            neg[p] = 1 << (fixed * W + p - 1) if o == 0 else 1 << ((p - 1) * W + fixed)
        if p + L < W:
            pos[p] = 1 << (fixed * W + p + L) if o == 0 else 1 << ((p + L) * W + fixed)
    return neg, pos


def hardest_of(carset, state_limit=250000):
    """車種集合の全状態空間を歩き、(最遠の手数, 位置リスト, 状態数) を返す。
    置けない／状態数が上限を超えたら None。"""
    n = len(carset)
    masks = [slot_masks(*c) for c in carset]
    negb, posb = [], []
    for c in carset:
        a, b = slot_added(*c)
        negb.append(a)
        posb.append(b)
    limits = [W - c[1] for c in carset]
    goal = limits[0]
    dist = {}
    q = deque()

    def enum(i, occ, code):
        """ゴール状態（赤が右端）を全列挙して多点BFSの始点にする"""
        if i == n:
            if code not in dist:
                dist[code] = 0
                q.append((code, occ, 0))
            return True
        mi = masks[i]
        sh = 3 * i
        for p in range(limits[i] + 1):
            m = mi[p]
            if not (occ & m):
                if not enum(i + 1, occ | m, code | (p << sh)):
                    return False
                if len(dist) > state_limit:
                    return False
        return True

    if not enum(1, masks[0][goal], goal) or not dist:
        return None

    best_d = 0
    best_code = None
    rn = range(n)
    while q:
        code, occ, d = q.popleft()
        if d > best_d:
            best_d = d
            best_code = code
        nd = d + 1
        for i in rn:
            sh = 3 * i
            p0 = (code >> sh) & 7
            mi = masks[i]
            rest = occ ^ mi[p0]
            nb = negb[i]
            pb = posb[i]
            lim = limits[i]
            p = p0
            while p > 0 and not (rest & nb[p]):
                p -= 1
                nc = code - ((p0 - p) << sh)
                if nc not in dist:
                    dist[nc] = nd
                    q.append((nc, rest | mi[p], nd))
            p = p0
            while p < lim and not (rest & pb[p]):
                p += 1
                nc = code + ((p - p0) << sh)
                if nc not in dist:
                    dist[nc] = nd
                    q.append((nc, rest | mi[p], nd))
        if len(dist) > state_limit:
            return None
    if best_code is None:
        return None
    return best_d, [(best_code >> (3 * i)) & 7 for i in range(n)], len(dist)


def cars_of(carset, poss):
    out = []
    for (fixed, L, o), p in zip(carset, poss):
        out.append((p, fixed, L, 0) if o == 0 else (fixed, p, L, 1))
    return out


def random_carset(rng, n_other):
    """実際に置ける盤から車種集合を取る（置けない集合を掴まないため）"""
    occ = 0
    cs = [(EXIT_Y, RED_LEN, 0)]
    rx = rng.randint(0, W - RED_LEN - 1)
    for i in range(RED_LEN):
        occ |= 1 << (EXIT_Y * W + rx + i)
    tries = 0
    while len(cs) - 1 < n_other and tries < 300:
        tries += 1
        L = rng.choice([2, 2, 2, 3])
        o = rng.randint(0, 1)
        fixed = rng.randint(0, W - 1)
        p = rng.randint(0, W - L)
        m = 0
        for k in range(L):
            m |= 1 << ((fixed * W + p + k) if o == 0 else ((p + k) * W + fixed))
        if occ & m:
            continue
        occ |= m
        cs.append((fixed, L, o))
    return cs if len(cs) - 1 == n_other else None


def perturb_carset(rng, carset, min_other=7):
    """集合のゆらぎ: 1台の固定座標/向き/長さを変える・足す・減らす"""
    cs = list(carset)
    n_other = len(cs) - 1
    r = rng.random()
    if r < 0.12 and n_other < MASTER_MAX_OTHER:
        cs.append((rng.randint(0, W - 1), rng.choice([2, 2, 2, 3]), rng.randint(0, 1)))
    elif r < 0.22 and n_other > min_other:
        cs.pop(rng.randint(1, n_other))
    else:
        i = rng.randint(1, n_other)
        fixed, L, o = cs[i]
        k = rng.random()
        if k < 0.5:
            fixed = rng.randint(0, W - 1)
        elif k < 0.75:
            o = 1 - o
        else:
            L = 5 - L       # 2 <-> 3
        cs[i] = (fixed, L, o)
    return cs


def carset_key(cs):
    return tuple(sorted(cs[1:]))


def select_master(rng, cands, k, fixed, attempts=4000):
    """達人の選抜。候補が少ないので、ランダム貪欲を何度も回して
    「Jaccard <= MAX_J で最も多く取れる組」を探す（同点なら手数の散らばりが大きい方）。"""
    best = None
    for _ in range(attempts):
        order = cands[:]
        rng.shuffle(order)
        chosen = []
        for c in order:
            if len(chosen) >= k:
                break
            if far_enough(c["shape"], fixed + chosen):
                chosen.append(c)
        maxj = 0.0
        for i in range(len(chosen)):
            for j in range(i + 1, len(chosen)):
                maxj = max(maxj, jaccard(chosen[i]["shape"], chosen[j]["shape"]))
        score = (len(chosen), len({c["min"] for c in chosen}), sum(c["min"] for c in chosen), -maxj)
        if best is None or score > best[0]:
            best = (score, chosen)
        if best[0][0] >= k and best[0][1] >= k:
            break
    return sorted(best[1], key=lambda c: (c["min"], c["board"]))


def master_search(rng, budget, target, state_limit, log):
    """焼きなまし（悪化も温度で受け入れる）。手数が同じなら状態空間の広い方を good とする。
    target 手以上に達した車種集合はすべてアーカイブへ（1集合＝1盤）。"""
    t0 = time.time()
    archive = {}
    seen = set()
    evals = 0
    best_seen = 0
    elite = []
    while time.time() - t0 < budget:
        if elite and rng.random() < 0.25:
            cur = list(rng.choice(elite))          # 良かった集合の近所を掘り直す
            for _ in range(rng.randint(1, 4)):     # そのまま座り込まないよう突き放す
                cur = perturb_carset(rng, cur)
        else:
            cur = None
            for _ in range(30):
                cur = random_carset(rng, rng.choice([9, 10, 10, 11, 11]))
                if cur is not None:
                    break
            if cur is None:
                continue
        r = hardest_of(cur, state_limit)
        if r is None:
            continue
        cur_score = r[0] + r[2] / 1e7
        steps = 300
        for st in range(steps):
            if time.time() - t0 > budget:
                break
            cand = perturb_carset(rng, cur)
            key = carset_key(cand)
            if key in seen:
                continue
            seen.add(key)
            rr = hardest_of(cand, state_limit)
            evals += 1
            if rr is None:
                continue
            d, poss, ns = rr
            best_seen = max(best_seen, d)
            if d >= target:
                archive[key] = (d, list(cand), poss, ns)
            score = d + ns / 1e7
            T = max(0.35, 5.0 * (1 - st / steps))
            if score >= cur_score or rng.random() < math.exp((score - cur_score) / T):
                cur, cur_score = cand, score
        elite = [v[1] for v in sorted(archive.values(), key=lambda v: -v[0])[:40]]
        log("   達人 %3.0fs 評価%5d 到達%2d手以上の集合 %3d件（最大 %d手）"
            % (time.time() - t0, evals, target, len(archive), best_seen))
    return archive, best_seen


# ---------------------------------------------------------------- 探索
def add_cand(pool, cars, m, run):
    pool["by_tier"].setdefault(tier_of(m), []).append(
        {"board": to_board(cars), "min": m, "cars": cars, "shape": shape_set(cars), "run": run})


def collect(rng, rounds, pool, log):
    """ランダム生成 → BFS → プールへ（run=-1: 山登り由来でない盤）"""
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
        if m < 3 or tier_of(m) is None:
            continue
        add_cand(pool, cars, m, -1)


def random_start(rng, min_m=4, tries=25):
    """山登りの出発点: 無関係なランダム盤のうち、そこそこ解きごたえのあるもの"""
    fallback = None
    for _ in range(tries):
        cars = random_board(rng, rng.choice([6, 7, 8, 8, 9, 9, 10, 10]))
        if cars is None:
            continue
        m = solve(cars)
        if m >= min_m:
            return cars
        if m >= 3 and fallback is None:
            fallback = cars
    return fallback


def climb_run(rng, pool, start, steps, run):
    """1本の独立した山登り。通過点はすべて run 番号つきでプールへ。"""
    cur = start
    cur_m = solve(cur)
    if cur_m < 0:
        return 0
    best = cur_m
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
        if tier_of(m) is not None:
            add_cand(pool, cand, m, run)
        if m >= cur_m:          # 同点も受け入れて平地を歩く
            cur, cur_m = cand, m
        elif rng.random() < 0.05:
            cur, cur_m = cand, m
        best = max(best, cur_m)
    return best


def diverse_count(cands, need):
    """この候補群から Jaccard <= MAX_J で何本まで取れるか（貪欲・上限 need）"""
    chosen = []
    for c in sorted(cands, key=lambda c: -c["min"]):
        if far_enough(c["shape"], chosen):
            chosen.append(c)
            if len(chosen) >= need:
                break
    return len(chosen)


# ---------------------------------------------------------------- 選抜
def select_tier(rng, cands, k, chosen):
    """最短手数を散らしつつ、既採用（chosen）と Jaccard <= MAX_J の盤だけ k 本選ぶ"""
    by_min = {}
    for c in cands:
        by_min.setdefault(c["min"], []).append(c)
    for v in by_min.values():
        rng.shuffle(v)
    keys = sorted(by_min)
    out = []
    while len(out) < k:
        progressed = False
        for key in keys:
            if len(out) >= k:
                break
            bucket = by_min[key]
            if not bucket:
                continue
            used_runs = {c["run"] for c in chosen + out if c["run"] >= 0}
            hit = None
            for pref in (0, 1):     # まだ使っていない山登り run を優先
                for idx, c in enumerate(bucket):
                    if pref == 0 and c["run"] in used_runs:
                        continue
                    if far_enough(c["shape"], chosen + out):
                        hit = idx
                        break
                if hit is not None:
                    break
            if hit is None:
                by_min[key] = []    # 条件は厳しくなる一方なので、この min は打ち切り
                continue
            out.append(bucket.pop(hit))
            progressed = True
        if not progressed:
            break
    return out


def select_all(rng, pool, attempts, cap, log, order=None, fixed=None):
    """段階ごとに選抜。難しい段階（候補が少ない）から先に確保する。
    ランダム順で複数回試し、一番よく埋まった組を採る。
    fixed: --keep で固定済みの盤（Jaccard の相手にはするが選抜し直さない）"""
    if order is None:
        order = ["上級", "中級", "初級", "入門"]
    fixed = fixed or []
    pools = {}
    for name in order:
        cands = pool["by_tier"].get(name, [])
        if len(cands) > cap:        # 選抜の総当たりが重くなりすぎない程度に間引く
            cands = rng.sample(cands, cap)
        pools[name] = cands

    best = None
    for _ in range(attempts):
        chosen = list(fixed)
        per = {}
        for name in order:
            got = select_tier(rng, pools[name], PER_TIER, chosen)
            per[name] = got
            chosen += got
        chosen = chosen[len(fixed):]
        maxj = 0.0
        for i in range(len(chosen)):
            for j in range(i + 1, len(chosen)):
                maxj = max(maxj, jaccard(chosen[i]["shape"], chosen[j]["shape"]))
        spread = sum(len({c["min"] for c in per[n]}) for n in order)
        score = (len(chosen), spread, -maxj)
        if best is None or score > best[0]:
            best = (score, chosen, per, maxj)
    log("   選抜: %d本 / 最短手数の種類 %d / 相互Jaccard最大 %.2f"
        % (best[0][0], best[0][1], best[3]))
    return best[1], best[2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20260906)
    ap.add_argument("--tiers", default="入門,初級,中級,上級",
                    help="生成する段階（カンマ区切り）。達人だけを足すなら --tiers 達人")
    ap.add_argument("--keep", metavar="JSON",
                    help="既存レベルをそのまま先頭に残す（順序・文字列を一切変えない）")
    ap.add_argument("--rounds", type=int, default=6000, help="ランダム生成の試行回数")
    ap.add_argument("--climb-steps", type=int, default=300, help="山登り1本あたりの歩数")
    ap.add_argument("--climb-runs", type=int, default=120,
                    help="独立した山登りの最大本数（種盤は毎回ランダムに作り直す）")
    ap.add_argument("--select-attempts", type=int, default=25, help="選抜のやり直し回数")
    ap.add_argument("--pool-cap", type=int, default=300, help="段階ごとに選抜へ回す候補数の上限")
    ap.add_argument("--master-budget", type=float, default=420.0,
                    help="達人の焼きなましに使う秒数")
    ap.add_argument("--master-target", type=int, default=32, help="達人の下限手数")
    ap.add_argument("--state-limit", type=int, default=250000,
                    help="達人の全状態空間BFSの打ち切り（超えたらその集合は捨てる）")
    ap.add_argument("--embed", metavar="HTML",
                    help="この HTML の LEVELS-BEGIN / LEVELS-END の間へ直接埋め込む")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    t0 = time.time()
    rng = random.Random(args.seed)
    log = (lambda *a: None) if args.quiet else (lambda *a: print(*a, file=sys.stderr))

    want = [t.strip() for t in args.tiers.split(",") if t.strip()]
    for t in want:
        if t not in [n for n, _, _ in TIERS]:
            sys.exit("知らない段階: %s" % t)

    # --- 既存レベル（--keep）は文字列も順番もそのまま。Jaccard の相手にだけ使う
    kept = []
    if args.keep:
        with open(args.keep, encoding="utf-8") as f:
            for l in json.load(f):
                cars = parse_board(l["board"])
                kept.append({"board": l["board"], "min": l["min"], "tier": l["tier"],
                             "cars": cars, "shape": shape_set(cars), "run": -1})
        log("固定（--keep）: %d本" % len(kept))

    pool = {"seen": set(k["board"] for k in kept), "by_tier": {}}
    classic = [t for t in want if t != MASTER]
    new_levels = []

    if classic:
        log("[1/3] ランダム生成 ...")
        collect(rng, args.rounds, pool, log)
        for name, _, _ in TIERS:
            log("   ", name, len(pool["by_tier"].get(name, [])))

        # 上級（19手以上）はランダムだとほぼ出ないので山登りで作る。
        # ただし種盤は毎回「無関係なランダム盤」から取り、1本の山を掘り続けない
        # （同じ山の通過点＝1〜3台違いの家族になるため。qa 2026-09-06）
        log("[2/3] 山登り（独立多点スタート）...")
        for run in range(args.climb_runs):
            target = PER_TIER + 4    # 選抜（手数の散らばりも見る）に余裕を持たせる
            if diverse_count(pool["by_tier"].get("上級", []), target) >= target:
                log("   run %d で上級の別盤が %d 本そろった" % (run, target))
                break
            start = random_start(rng)
            if start is None:
                continue
            climb_run(rng, pool, start, args.climb_steps, run)
            if run % 10 == 9:
                log("   run %3d 上級候補 %4d（別盤 %d/%d） 経過 %.0fs"
                    % (run + 1, len(pool["by_tier"].get("上級", [])),
                       diverse_count(pool["by_tier"].get("上級", []), target),
                       target, time.time() - t0))

        log("[3/3] 選抜（Jaccard <= %.2f）..." % MAX_J)
        order = [n for n in ["上級", "中級", "初級", "入門"] if n in classic]
        got, per = select_all(rng, pool, args.select_attempts, args.pool_cap, log,
                              order=order, fixed=kept)
        new_levels += got
        for n in order:
            if len(per[n]) < PER_TIER:
                log("不足: %s %d本" % (n, len(per[n])))

    if MASTER in want:
        log("[達人] 車種集合の焼きなまし＋全状態空間BFS（予算 %.0fs）..." % args.master_budget)
        archive, best_seen = master_search(rng, args.master_budget, args.master_target,
                                           args.state_limit, log)
        cands = []
        for d, cs, poss, ns in archive.values():
            cars = normalize(cars_of(cs, poss))
            board = to_board(cars)
            if board in pool["seen"]:
                continue
            pool["seen"].add(board)
            cands.append({"board": board, "min": d, "cars": cars,
                          "shape": shape_set(cars), "run": -1, "states": ns})
        got = select_master(rng, cands, PER_TIER, kept + new_levels)
        log("   候補 %d件 / 採用 %d本（最大 %d手）" % (len(cands), len(got), best_seen))
        if len(got) < PER_TIER:
            log("不足: %s %d本（32手以上の別盤が足りない）" % (MASTER, len(got)))
        new_levels += got

    new_levels.sort(key=lambda c: (c["min"], c["board"]))
    out = [{"board": c["board"], "min": c["min"], "tier": c["tier"]} for c in kept]
    out += [{"board": c["board"], "min": c["min"], "tier": tier_of(c["min"])}
            for c in new_levels]

    # 分布を標準エラーへ
    dist = {}
    for o in out:
        dist.setdefault(o["tier"], []).append(o["min"])
    for name, _, _ in TIERS:
        v = dist.get(name, [])
        log("分布 %s: %d本 min=%s" % (name, len(v), ("%d..%d" % (min(v), max(v))) if v else "-"))
    shapes = [shape_set(parse_board(o["board"])) for o in out]
    mj = max((jaccard(shapes[i], shapes[j])
              for i in range(len(shapes)) for j in range(i + 1, len(shapes))), default=0.0)
    log("相互Jaccard最大 %.2f / 所要 %.0fs" % (mj, time.time() - t0))

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
