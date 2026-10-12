#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数独の問題生成器（Python3 標準ライブラリのみ）

やること
  1. ランダムな完成盤を作る
  2. 対称位置（i と 80-i）のペアで数字を消す。消すたびにバックトラックで
     解を2つまで数え、一意でなければ戻す
  3. 論理ソルバー（裸のシングル→隠れシングル→ロックド候補→裸のペア→隠れペア）で
     「解くのに要る一番強い推論」を求め、それで難度を決める
       入門 = 裸のシングルだけ / 初級 = 隠れシングルが要る
       中級 = ロックド候補かペアが要る / 上級 = それでも解けない
     （上級も一意性はバックトラックで保証済み）
  4. 段階ごとに10本、計40本。段階内はヒント数の多い順

使い方
  python3 gen_puzzles.py                       # tools/puzzles.json に書く
  python3 gen_puzzles.py --embed ../index.html # HTML の PUZZLES-BEGIN/END の間を差し替え
  python3 gen_puzzles.py --seed 123 --budget 300
"""

import argparse
import json
import random
import re
import sys
import time

N = 9
CELLS = 81
ALL = 0x1FF  # 候補9ビット（bit0=1, bit8=9）

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

# 技法（強い順に番号を振る）。この番号の最大値で段階が決まる
TECH = {1: "裸のシングル", 2: "隠れシングル", 3: "ロックド候補", 4: "裸のペア", 5: "隠れペア"}
UNSOLVED = "それ以上"
TIERS = ["入門", "初級", "中級", "上級"]


def tier_of(tech_name):
    if tech_name == TECH[1]:
        return "入門"
    if tech_name == TECH[2]:
        return "初級"
    if tech_name == UNSOLVED:
        return "上級"
    return "中級"


def popcount(x):
    return bin(x).count("1")


def bit2digit(b):
    return b.bit_length()


# ---------------------------------------------------------------- 基本

def parse(s):
    return [0 if c in "0." else int(c) for c in s]


def to_str(grid):
    return "".join(str(v) for v in grid)


def candidates(grid):
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
            cand[i] = ALL & ~(rows[ROW[i]] | cols[COL[i]] | boxes[BOX[i]])
    return cand


def place(grid, cand, i, d):
    grid[i] = d
    cand[i] = 0
    b = ~(1 << (d - 1))
    for j in PEERS[i]:
        cand[j] &= b


def is_valid_placement(grid, i, d):
    if d < 1 or d > 9:
        return False
    for j in PEERS[i]:
        if grid[j] == d:
            return False
    return True


def is_complete(grid):
    for i in range(CELLS):
        v = grid[i]
        if not isinstance(v, int) or v < 1 or v > 9:
            return False
    for unit in UNITS:
        seen = 0
        for i in unit:
            b = 1 << (grid[i] - 1)
            if seen & b:
                return False
            seen |= b
    return True


# ---------------------------------------------------------------- 一意性

def count_solutions(puzzle, limit=2):
    """解を limit 個まで数える（バックトラック・候補の少ないマスから）"""
    grid = parse(puzzle) if isinstance(puzzle, str) else list(puzzle)
    rows = [0] * 9
    cols = [0] * 9
    boxes = [0] * 9
    for i, v in enumerate(grid):
        if v:
            b = 1 << (v - 1)
            if (rows[ROW[i]] | cols[COL[i]] | boxes[BOX[i]]) & b:
                return 0
            rows[ROW[i]] |= b
            cols[COL[i]] |= b
            boxes[BOX[i]] |= b

    count = 0

    def rec():
        nonlocal count
        best = -1
        bestmask = 0
        bestn = 10
        for i in range(CELLS):
            if grid[i]:
                continue
            m = ALL & ~(rows[ROW[i]] | cols[COL[i]] | boxes[BOX[i]])
            n = popcount(m)
            if n == 0:
                return
            if n < bestn:
                bestn = n
                best = i
                bestmask = m
                if n == 1:
                    break
        if best < 0:
            count += 1
            return
        r, c, x = ROW[best], COL[best], BOX[best]
        m = bestmask
        while m:
            b = m & -m
            m ^= b
            grid[best] = bit2digit(b)
            rows[r] |= b
            cols[c] |= b
            boxes[x] |= b
            rec()
            rows[r] &= ~b
            cols[c] &= ~b
            boxes[x] &= ~b
            grid[best] = 0
            if count >= limit:
                return

    rec()
    return count


# ---------------------------------------------------------------- 論理ソルバー
# 各技法は「盤面を一度ぜんぶ走査して見つけたものをまとめて適用」する。
# 走査中は盤面を変えないので、適用順に依存しない（JS 側と同じ結果になる）。

def naked_single(grid, cand):
    moves = []
    for i in range(CELLS):
        if not grid[i] and popcount(cand[i]) == 1:
            moves.append((i, bit2digit(cand[i])))
    if not moves:
        return False
    for i, d in moves:
        if not grid[i]:
            place(grid, cand, i, d)
    return True


def hidden_single(grid, cand):
    moves = []
    for unit in UNITS:
        for d in range(1, 10):
            b = 1 << (d - 1)
            spots = [i for i in unit if not grid[i] and (cand[i] & b)]
            if len(spots) == 1:
                moves.append((spots[0], d))
    if not moves:
        return False
    changed = False
    for i, d in moves:
        if not grid[i]:
            place(grid, cand, i, d)
            changed = True
    return changed


def _apply(cand, elim):
    if not elim:
        return False
    for i, m in elim:
        cand[i] &= ~m
    return True


def locked_candidates(grid, cand):
    """ブロックと行列の絡み（pointing と claiming）"""
    elim = []
    # pointing: ブロック内でその数字が一行（一列）に固まる → その行（列）の外を消す
    for bx in range(9):
        for d in range(1, 10):
            b = 1 << (d - 1)
            spots = [i for i in BOXCELLS[bx] if not grid[i] and (cand[i] & b)]
            if len(spots) < 2:
                continue
            if len(set(ROW[i] for i in spots)) == 1:
                r = ROW[spots[0]]
                for i in ROWCELLS[r]:
                    if BOX[i] != bx and not grid[i] and (cand[i] & b):
                        elim.append((i, b))
            if len(set(COL[i] for i in spots)) == 1:
                c = COL[spots[0]]
                for i in COLCELLS[c]:
                    if BOX[i] != bx and not grid[i] and (cand[i] & b):
                        elim.append((i, b))
    # claiming: 行（列）内でその数字が一ブロックに固まる → そのブロックの外を消す
    for lines in (ROWCELLS, COLCELLS):
        for unit in lines:
            for d in range(1, 10):
                b = 1 << (d - 1)
                spots = [i for i in unit if not grid[i] and (cand[i] & b)]
                if len(spots) < 2:
                    continue
                if len(set(BOX[i] for i in spots)) == 1:
                    bx = BOX[spots[0]]
                    line = set(unit)
                    for i in BOXCELLS[bx]:
                        if i not in line and not grid[i] and (cand[i] & b):
                            elim.append((i, b))
    return _apply(cand, elim)


def naked_pair(grid, cand):
    elim = []
    for unit in UNITS:
        empt = [i for i in unit if not grid[i]]
        for a in range(len(empt)):
            i = empt[a]
            if popcount(cand[i]) != 2:
                continue
            for b_ in range(a + 1, len(empt)):
                j = empt[b_]
                if cand[j] != cand[i]:
                    continue
                for k in empt:
                    if k != i and k != j and (cand[k] & cand[i]):
                        elim.append((k, cand[k] & cand[i]))
    return _apply(cand, elim)


def hidden_pair(grid, cand):
    elim = []
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
                        elim.append((i, cand[i] & ~keep))
    return _apply(cand, elim)


STEPS = [
    (1, naked_single),
    (2, hidden_single),
    (3, locked_candidates),
    (4, naked_pair),
    (5, hidden_pair),
]


def rate(puzzle):
    """解くのに要った一番強い技法の名前を返す。解けなければ「それ以上」"""
    grid = parse(puzzle) if isinstance(puzzle, str) else list(puzzle)
    cand = candidates(grid)
    hardest = 0
    while True:
        if all(grid):
            break
        moved = False
        for rank, fn in STEPS:
            if fn(grid, cand):
                if rank > hardest:
                    hardest = rank
                moved = True
                break
        if not moved:
            break
    if not all(grid):
        return UNSOLVED
    return TECH[hardest] if hardest else TECH[1]


# ---------------------------------------------------------------- 生成

def full_grid(rnd):
    """ランダムな完成盤（バックトラック）"""
    grid = [0] * CELLS
    rows = [0] * 9
    cols = [0] * 9
    boxes = [0] * 9

    def rec(pos):
        if pos == CELLS:
            return True
        i = pos
        m = ALL & ~(rows[ROW[i]] | cols[COL[i]] | boxes[BOX[i]])
        ds = []
        while m:
            b = m & -m
            m ^= b
            ds.append(b)
        rnd.shuffle(ds)
        r, c, x = ROW[i], COL[i], BOX[i]
        for b in ds:
            grid[i] = bit2digit(b)
            rows[r] |= b
            cols[c] |= b
            boxes[x] |= b
            if rec(pos + 1):
                return True
            rows[r] &= ~b
            cols[c] &= ~b
            boxes[x] &= ~b
            grid[i] = 0
        return False

    rec(0)
    return grid


def dig(rnd, solution, target_givens, symmetric=True):
    """対称位置のペアで消す。一意でなくなったら戻す。target_givens まで減らしたら止める"""
    grid = list(solution)
    if symmetric:
        groups = [(i, 80 - i) for i in range(40)] + [(40,)]
    else:
        groups = [(i,) for i in range(CELLS)]
    rnd.shuffle(groups)
    givens = CELLS
    for g in groups:
        if givens <= target_givens:
            break
        keep = [grid[i] for i in g]
        for i in g:
            grid[i] = 0
        if count_solutions(grid, 2) == 1:
            givens -= len(g)
        else:
            for k, i in enumerate(g):
                grid[i] = keep[k]
    return grid, givens


def generate(seed, budget, per_tier, verbose=True):
    rnd = random.Random(seed)
    buckets = {t: [] for t in TIERS}
    seen = set()
    t0 = time.time()
    attempts = 0
    stats = {t: 0 for t in TIERS}

    # 段階ごとに「どこまで消すか」を変える。
    # 消す数が少なければ易しい盤、消し切れば難しい盤が出やすい。
    FLOOR = {"入門": 36, "初級": 28, "中級": 24, "上級": 17}
    plans = {
        "入門": (38, 46, True),
        "初級": (30, 38, True),
        "中級": (24, 30, True),
        "上級": (17, 26, False),  # 上級は対称を崩してさらに消す
    }

    while time.time() - t0 < budget:
        need = [t for t in TIERS if len(buckets[t]) < per_tier]
        if not need:
            break
        want = need[attempts % len(need)]
        lo, hi, sym = plans[want]
        target = rnd.randint(lo, hi)
        attempts += 1
        sol = full_grid(rnd)
        puz, givens = dig(rnd, sol, target, symmetric=sym)
        ps = to_str(puz)
        if ps in seen:
            continue
        seen.add(ps)
        hardest = rate(ps)
        tier = tier_of(hardest)
        stats[tier] += 1
        # 段階に見合わないヒント数（易しい段階なのに空白だらけ）は箱に入れない
        if givens < FLOOR[tier]:
            continue
        if len(buckets[tier]) < per_tier:
            buckets[tier].append({
                "puzzle": ps,
                "solution": to_str(sol),
                "tier": tier,
                "givens": givens,
                "hardest": hardest,
            })
            if verbose:
                print("  %s %2d/%d  ヒント%2d  %s" % (
                    tier, len(buckets[tier]), per_tier, givens, hardest),
                    file=sys.stderr)

    out = []
    for t in TIERS:
        b = sorted(buckets[t], key=lambda p: (-p["givens"], p["puzzle"]))
        out.extend(b)
    return out, {
        "seconds": time.time() - t0,
        "attempts": attempts,
        "produced": stats,
        "filled": {t: len(buckets[t]) for t in TIERS},
    }


# ---------------------------------------------------------------- 検証と出力

def verify(puzzles):
    """埋め込む前の自己点検。落ちたら生成しなおし"""
    bad = []
    for k, p in enumerate(puzzles):
        puz, sol = p["puzzle"], p["solution"]
        if len(puz) != 81 or len(sol) != 81:
            bad.append((k, "長さが81でない"))
            continue
        if count_solutions(puz, 3) != 1:
            bad.append((k, "解が一つでない"))
        if not is_complete(parse(sol)):
            bad.append((k, "solution が完成盤でない"))
        for i in range(CELLS):
            if puz[i] != "0" and puz[i] != sol[i]:
                bad.append((k, "ヒントが solution と食い違う"))
                break
        if puz.count("0") != 81 - p["givens"]:
            bad.append((k, "givens が合わない"))
        if tier_of(rate(puz)) != p["tier"]:
            bad.append((k, "tier が rate と合わない"))
    return bad


def embed(path, puzzles):
    src = open(path, encoding="utf-8").read()
    lines = ["var PUZZLES = ["]
    for k, p in enumerate(puzzles):
        lines.append('  {"puzzle":"%s","solution":"%s","tier":"%s","givens":%d,"hardest":"%s"}%s'
                     % (p["puzzle"], p["solution"], p["tier"], p["givens"], p["hardest"],
                        "," if k < len(puzzles) - 1 else ""))
    lines.append("];")
    body = "\n".join(lines)
    pat = re.compile(r"(/\* PUZZLES-BEGIN[^\n]*\*/\n).*?(\n/\* PUZZLES-END \*/)", re.S)
    if not pat.search(src):
        raise SystemExit("PUZZLES-BEGIN / PUZZLES-END が見つからない: " + path)
    src = pat.sub(lambda m: m.group(1) + body + m.group(2), src)
    open(path, "w", encoding="utf-8").write(src)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20260907)
    ap.add_argument("--budget", type=float, default=180.0, help="生成に使う秒数")
    ap.add_argument("--per-tier", type=int, default=10)
    ap.add_argument("--out", default=None, help="JSON の書き出し先")
    ap.add_argument("--embed", default=None, help="index.html の PUZZLES-BEGIN/END を差し替える")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    puzzles, info = generate(args.seed, args.budget, args.per_tier, verbose=not args.quiet)

    bad = verify(puzzles)
    print("", file=sys.stderr)
    print("生成 %.1f 秒 / 試行 %d 回" % (info["seconds"], info["attempts"]), file=sys.stderr)
    print("できた本数: " + " ".join("%s %d" % (t, info["filled"][t]) for t in TIERS), file=sys.stderr)
    print("試行の内訳: " + " ".join("%s %d" % (t, info["produced"][t]) for t in TIERS), file=sys.stderr)
    for t in TIERS:
        g = [p["givens"] for p in puzzles if p["tier"] == t]
        h = {}
        for p in puzzles:
            if p["tier"] == t:
                h[p["hardest"]] = h.get(p["hardest"], 0) + 1
        if g:
            print("  %s ヒント %d〜%d / %s" % (
                t, min(g), max(g), " ".join("%s×%d" % kv for kv in sorted(h.items()))),
                file=sys.stderr)
    if bad:
        print("検証で落ちた: %r" % (bad,), file=sys.stderr)
        raise SystemExit(1)
    print("検証: 一意性・完成盤・ヒント一致・難度、すべて通った", file=sys.stderr)

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
