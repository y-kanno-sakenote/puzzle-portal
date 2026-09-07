#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""担当: qa係
窓わけ 独立検証ツール（実装者の gen_puzzles.py / index.html のコードは使わない。
探索の順序・データ構造を変えて書き直した自前ソルバーで再検証する）

使い方:
  python3 qa_check.py                 # 40本を自前ソルバーで再検証
  python3 qa_check.py --brute         # 小盤（3x3）で総当りと自前ソルバーを照合（正しさの土台）
  python3 qa_check.py --minimize      # 入門・初級20本の記号最小性を点検（品質メモ）
"""
import json
import os
import sys
import time
from itertools import product

HERE = os.path.dirname(os.path.abspath(__file__))
COLORS = "RBY"
IDCHARS = "abcdefghijklmnopqrstuvwxyz"


def neighbors(n):
    """マスごとの上下左右隣接（行優先ではなく素朴に4方向を都度計算）"""
    out = []
    for i in range(n * n):
        r, c = i // n, i % n
        ns = []
        if r > 0:
            ns.append(i - n)
        if r < n - 1:
            ns.append(i + n)
        if c > 0:
            ns.append(i - 1)
        if c < n - 1:
            ns.append(i + 1)
        out.append(tuple(ns))
    return out


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


def groups_of(part):
    g = {}
    for i, p in enumerate(part):
        g.setdefault(p, []).append(i)
    return g


def is_connected(cells_idx, NB):
    s = set(cells_idx)
    if not s:
        return True
    start = next(iter(s))
    seen = {start}
    stack = [start]
    while stack:
        v = stack.pop()
        for w in NB[v]:
            if w in s and w not in seen:
                seen.add(w)
                stack.append(w)
    return len(seen) == len(s)


def check_rules(n, cells, rules, part):
    """独立実装のルール判定。gen_puzzles.py / index.html のコードは見ずに
    docs/spec.md の記述だけから書いた。違反ルール名の一覧（構造違反は 'region'）"""
    N = n * n
    NB = neighbors(n)
    bad = []
    if len(part) != N or any(p is None for p in part):
        return ["region"]
    grp = groups_of(part)
    structural = False
    for cs in grp.values():
        if len(cs) < 2 or not is_connected(cs, NB):
            structural = True
    if structural:
        bad.append("region")

    for rule in rules:
        viol = False
        if rule == "star":
            for cs in grp.values():
                stars = sum(1 for i in cs if cells[i] == "*")
                if stars != 1:
                    viol = True
                    break
        elif rule == "size":
            for cs in grp.values():
                nums = [int(cells[i]) for i in cs if cells[i].isdigit()]
                if len(nums) > 1 or (len(nums) == 1 and nums[0] != len(cs)):
                    viol = True
                    break
        elif rule == "color":
            for cs in grp.values():
                cols = {cells[i] for i in cs if cells[i] in COLORS}
                if len(cols) > 1:
                    viol = True
                    break
        elif rule == "rect":
            for cs in grp.values():
                rows = [i // n for i in cs]
                cols2 = [i % n for i in cs]
                area = (max(rows) - min(rows) + 1) * (max(cols2) - min(cols2) + 1)
                if area != len(cs):
                    viol = True
                    break
        elif rule == "nosame":
            sizeof = {gid: len(cs) for gid, cs in grp.items()}
            for i in range(N):
                for w in NB[i]:
                    if part[w] != part[i] and sizeof[part[w]] == sizeof[part[i]]:
                        viol = True
                        break
                if viol:
                    break
        else:
            raise ValueError("unknown rule " + rule)
        if viol:
            bad.append(rule)
    return bad


class Budget(Exception):
    pass


def count_solutions(n, cells, rules, limit=2, node_budget=2_000_000):
    """自前の解数え上げ（region-growth）。gen_puzzles.py 由来のコードは使わず
    候補リストを毎回そのマス番号の昇順に並べ直す点・打ち切り判定の書き方を変えている。
    戻り値: (個数, ノード数)"""
    N = n * n
    NB = neighbors(n)
    r_star = "star" in rules
    r_size = "size" in rules
    r_color = "color" in rules
    r_rect = "rect" in rules
    r_nosame = "nosame" in rules

    is_star = [c == "*" for c in cells]
    dig = [int(c) if c.isdigit() else 0 for c in cells]
    col = [c if c in COLORS else "" for c in cells]

    owner = [-1] * N
    closed_sizes = []  # region-id -> size（確定済み領域だけ）
    state = {"count": 0, "nodes": 0}

    def feasible_rest():
        """未割当マスの連結成分ごとに、残りルールで詰みでないか粗くふるう"""
        seen = [False] * N
        for i in range(N):
            if owner[i] != -1 or seen[i]:
                continue
            comp = []
            stack = [i]
            seen[i] = True
            while stack:
                v = stack.pop()
                comp.append(v)
                for w in NB[v]:
                    if owner[w] == -1 and not seen[w]:
                        seen[w] = True
                        stack.append(w)
            sz = len(comp)
            if sz < 2:
                return False
            if r_star:
                s = sum(1 for v in comp if is_star[v])
                if s == 0 or s * 2 > sz:
                    return False
            if r_size:
                tot = 0
                for v in comp:
                    if dig[v]:
                        if dig[v] > sz:
                            return False
                        tot += dig[v]
                if tot > sz:
                    return False
        return True

    def region_ok(reg, nstar, ndig, ncol):
        if r_star and nstar != 1:
            return False
        if r_size and ndig and ndig != len(reg):
            return False
        if r_rect:
            rows = [v // n for v in reg]
            cols2 = [v % n for v in reg]
            area = (max(rows) - min(rows) + 1) * (max(cols2) - min(cols2) + 1)
            if area != len(reg):
                return False
        if r_nosame:
            sz = len(reg)
            regset = set(reg)
            touch = set()
            for v in reg:
                for w in NB[v]:
                    o = owner[w]
                    if o != -1 and w not in regset:
                        touch.add(o)
            for o in touch:
                if closed_sizes[o] == sz:
                    return False
        return True

    def expand(reg, frontier, banned, rid, nstar, ndig, ncol):
        state["nodes"] += 1
        if state["nodes"] > node_budget:
            raise Budget()
        if state["count"] >= limit:
            return
        if len(reg) >= 2 and region_ok(reg, nstar, ndig, ncol):
            closed_sizes.append(len(reg))
            if feasible_rest():
                place_next_region()
            closed_sizes.pop()
            if state["count"] >= limit:
                return
        # 候補はマス番号の昇順で試す（元コードは発見順=挿入順。ここでは毎回並べ替える）
        ordered = sorted(frontier)
        for k, v in enumerate(ordered):
            if v in banned:
                continue
            nstar2 = nstar + (1 if is_star[v] else 0)
            if r_star and nstar2 > 1:
                continue
            ndig2 = ndig
            if r_size and dig[v]:
                if ndig:
                    continue
                ndig2 = dig[v]
                if len(reg) + 1 > ndig2:
                    continue
            ncol2 = ncol
            if r_color and col[v]:
                if ncol and ncol != col[v]:
                    continue
                ncol2 = col[v]
            if r_rect:
                rows = [x // n for x in reg] + [v // n]
                cols2 = [x % n for x in reg] + [v % n]
                r0, r1, c0, c1 = min(rows), max(rows), min(cols2), max(cols2)
                blocked = False
                for rr in range(r0, r1 + 1):
                    for cc in range(c0, c1 + 1):
                        o = owner[rr * n + cc]
                        if o != -1 and o != rid:
                            blocked = True
                            break
                    if blocked:
                        break
                if blocked:
                    continue
            owner[v] = rid
            reg.append(v)
            newbanned = banned | set(ordered[:k])
            newfrontier = (frontier - {v}) | {w for w in NB[v] if owner[w] == -1}
            newfrontier -= newbanned
            expand(reg, newfrontier, newbanned, rid, nstar2, ndig2, ncol2)
            reg.pop()
            owner[v] = -1
            if state["count"] >= limit:
                return

    def place_next_region():
        seed = -1
        for i in range(N):
            if owner[i] == -1:
                seed = i
                break
        if seed < 0:
            state["count"] += 1
            return
        rid = len(closed_sizes)
        owner[seed] = rid
        frontier = {w for w in NB[seed] if owner[w] == -1}
        expand([seed], frontier, set(), rid, 1 if is_star[seed] else 0, dig[seed], col[seed])
        owner[seed] = -1

    try:
        place_next_region()
    except Budget:
        return -1, state["nodes"]
    return state["count"], state["nodes"]


# ---------------------------------------------------------------- brute force（総当り・別実装）

def restricted_growth_partitions(N):
    """restricted growth string で N 要素の集合分割を総当り列挙（領域分割探索とは無関係の別手法）"""
    a = [0] * N
    maxv = [0] * N

    def rec(i):
        if i == N:
            yield tuple(a)
            return
        for v in range(maxv[i - 1] + 2 if i > 0 else 1):
            a[i] = v
            maxv[i] = max(maxv[i - 1] if i > 0 else -1, v)
            yield from rec(i + 1)

    yield from rec(0)


def brute_count(n, cells, rules):
    N = n * n
    NB = neighbors(n)
    cnt = 0
    for part in restricted_growth_partitions(N):
        grp = groups_of(part)
        ok = True
        for cs in grp.values():
            if len(cs) < 2 or not is_connected(cs, NB):
                ok = False
                break
        if not ok:
            continue
        if check_rules(n, cells, rules, list(part)):
            continue
        cnt += 1
    return cnt


def run_brute():
    print("[brute] 3x3 総当り（restricted growth string・領域分割探索と無関係の別手法）")
    n = 3
    cells = "." * (n * n)
    total = brute_count(n, cells, [])
    print("  ルール無し・つながった2マス以上の分割の総数 =", total,
          "(decision_log.md の実測 147 と比較)")
    c2, nodes2 = count_solutions(n, cells, [], limit=10 ** 9)
    print("  自前ソルバーの同条件の数 =", c2, "一致" if c2 == total else "不一致 FAIL")

    # n=4 (16マス) は Bell(16)=約104億通りで総当り不可能なため n=3 (Bell(9)=21147) に限定する
    rnd_cases = [
        (3, "*........", ["star"]),
        (3, "2........", ["size"]),
        (3, "R.B......", ["color"]),
        (3, "*...2....", ["star", "size"]),
        (3, "*..R..B..", ["star", "color"]),
        (3, ".........", ["rect"]),
        (3, ".........", ["nosame"]),
    ]
    all_ok = True
    for n, cells, rules in rnd_cases:
        cells = (cells + "." * (n * n))[: n * n]
        bc = brute_count(n, cells, rules)
        sc, _ = count_solutions(n, cells, rules, limit=10 ** 9)
        ok = bc == sc
        all_ok &= ok
        print("  n=%d rules=%s 総当り=%d 自前ソルバー=%d %s" %
              (n, "+".join(rules), bc, sc, "一致" if ok else "不一致 FAIL"))
    print("[brute] 総合:", "PASS" if all_ok else "FAIL")


# ---------------------------------------------------------------- 40本の検証

def load_puzzles():
    with open(os.path.join(HERE, "puzzles.json"), encoding="utf-8") as f:
        return json.load(f)


def run_main():
    puzzles = load_puzzles()
    print("[本数] puzzles.json =", len(puzzles))
    fails = []
    max_ms = 0.0
    max_ms_idx = -1
    for idx, p in enumerate(puzzles):
        n = p["n"]
        cells = p["cells"]
        rules = p["rules"]
        sol_str = p["solution"]
        if len(cells) != n * n or len(sol_str) != n * n:
            fails.append((idx, "長さ不一致"))
            continue
        sol = [IDCHARS.index(ch) for ch in sol_str]

        # 2: solution の妥当性（自前判定）
        viol = check_rules(n, cells, rules, sol)
        if viol:
            fails.append((idx, "solution がルール違反(自前判定): %r" % viol))

        # 1: 自前ソルバーで解を2つまで数える
        t0 = time.time()
        try:
            cnt, nodes = count_solutions(n, cells, rules, limit=2, node_budget=3_000_000)
        except Exception as e:
            fails.append((idx, "自前ソルバーで例外: %r" % e))
            continue
        ms = (time.time() - t0) * 1000
        if ms > max_ms:
            max_ms = ms
            max_ms_idx = idx
        if cnt == -1:
            fails.append((idx, "自前ソルバーがノード上限で打ち切り"))
            continue
        if cnt != 1:
            fails.append((idx, "自前ソルバーの解数=%d (期待1)" % cnt))
            continue

        # 1続き: その解が solution と同じ分割か（自前ソルバーで実際に解を復元して比較）
        # count_solutions は個数のみ返すため、別途1個だけ探して分割を復元する
        found = find_one_solution(n, cells, rules)
        if found is None:
            fails.append((idx, "自前ソルバーで解を復元できず"))
        elif not same_partition(found, sol):
            fails.append((idx, "自前ソルバーの解が solution と不一致"))

    print("[1+2] 自前ソルバー(Python, 探索順・打ち切り判定を変更) 40本結果")
    print("  最遅個体: index=%d %.1fms" % (max_ms_idx, max_ms))
    if fails:
        print("  FAIL 件数:", len(fails))
        for idx, msg in fails:
            print("   -", idx, msg)
    else:
        print("  PASS: 40本すべて自前ソルバーで解1個、solutionと同一分割")
    return fails


def find_one_solution(n, cells, rules):
    """count_solutions と同じ探索を limit=1 で行い、実際の分割を1つ復元する"""
    N = n * n
    NB = neighbors(n)
    r_star = "star" in rules
    r_size = "size" in rules
    r_color = "color" in rules
    r_rect = "rect" in rules
    r_nosame = "nosame" in rules
    is_star = [c == "*" for c in cells]
    dig = [int(c) if c.isdigit() else 0 for c in cells]
    col = [c if c in COLORS else "" for c in cells]
    owner = [-1] * N
    closed_sizes = []
    result = {"found": None}

    def feasible_rest():
        seen = [False] * N
        for i in range(N):
            if owner[i] != -1 or seen[i]:
                continue
            comp = []
            stack = [i]
            seen[i] = True
            while stack:
                v = stack.pop()
                comp.append(v)
                for w in NB[v]:
                    if owner[w] == -1 and not seen[w]:
                        seen[w] = True
                        stack.append(w)
            sz = len(comp)
            if sz < 2:
                return False
            if r_star:
                s = sum(1 for v in comp if is_star[v])
                if s == 0 or s * 2 > sz:
                    return False
            if r_size:
                tot = 0
                for v in comp:
                    if dig[v]:
                        if dig[v] > sz:
                            return False
                        tot += dig[v]
                if tot > sz:
                    return False
        return True

    def region_ok(reg, nstar, ndig, ncol):
        if r_star and nstar != 1:
            return False
        if r_size and ndig and ndig != len(reg):
            return False
        if r_rect:
            rows = [v // n for v in reg]
            cols2 = [v % n for v in reg]
            if (max(rows) - min(rows) + 1) * (max(cols2) - min(cols2) + 1) != len(reg):
                return False
        if r_nosame:
            sz = len(reg)
            regset = set(reg)
            touch = set()
            for v in reg:
                for w in NB[v]:
                    o = owner[w]
                    if o != -1 and w not in regset:
                        touch.add(o)
            for o in touch:
                if closed_sizes[o] == sz:
                    return False
        return True

    def expand(reg, frontier, banned, rid, nstar, ndig, ncol):
        if result["found"] is not None:
            return
        if len(reg) >= 2 and region_ok(reg, nstar, ndig, ncol):
            closed_sizes.append(len(reg))
            if feasible_rest():
                place_next_region()
            closed_sizes.pop()
            if result["found"] is not None:
                return
        ordered = sorted(frontier)
        for k, v in enumerate(ordered):
            if v in banned:
                continue
            nstar2 = nstar + (1 if is_star[v] else 0)
            if r_star and nstar2 > 1:
                continue
            ndig2 = ndig
            if r_size and dig[v]:
                if ndig:
                    continue
                ndig2 = dig[v]
                if len(reg) + 1 > ndig2:
                    continue
            ncol2 = ncol
            if r_color and col[v]:
                if ncol and ncol != col[v]:
                    continue
                ncol2 = col[v]
            if r_rect:
                rows = [x // n for x in reg] + [v // n]
                cols2 = [x % n for x in reg] + [v % n]
                r0, r1, c0, c1 = min(rows), max(rows), min(cols2), max(cols2)
                blocked = False
                for rr in range(r0, r1 + 1):
                    for cc in range(c0, c1 + 1):
                        o = owner[rr * n + cc]
                        if o != -1 and o != rid:
                            blocked = True
                            break
                    if blocked:
                        break
                if blocked:
                    continue
            owner[v] = rid
            reg.append(v)
            newbanned = banned | set(ordered[:k])
            newfrontier = (frontier - {v}) | {w for w in NB[v] if owner[w] == -1}
            newfrontier -= newbanned
            expand(reg, newfrontier, newbanned, rid, nstar2, ndig2, ncol2)
            reg.pop()
            owner[v] = -1
            if result["found"] is not None:
                return

    def place_next_region():
        seed = -1
        for i in range(N):
            if owner[i] == -1:
                seed = i
                break
        if seed < 0:
            result["found"] = list(owner)
            return
        rid = len(closed_sizes)
        owner[seed] = rid
        frontier = {w for w in NB[seed] if owner[w] == -1}
        expand([seed], frontier, set(), rid, 1 if is_star[seed] else 0, dig[seed], col[seed])
        owner[seed] = -1

    place_next_region()
    return result["found"]


# ---------------------------------------------------------------- 記号の最小性（品質メモ）

def run_minimize():
    puzzles = load_puzzles()
    target = [p for p in puzzles if p["tier"] in ("入門", "初級")]
    print("[3] 記号の最小性点検（入門・初級 %d本、削っても一意なら記録・FAILにはしない）" % len(target))
    total_redundant = 0
    for p in puzzles:
        if p["tier"] not in ("入門", "初級"):
            continue
        n, cells, rules, sol_str = p["n"], p["cells"], p["rules"], p["solution"]
        sol = [IDCHARS.index(ch) for ch in sol_str]
        idxs = [i for i, ch in enumerate(cells) if ch != "."]
        redundant = []
        for i in idxs:
            trial = cells[:i] + "." + cells[i + 1:]
            if check_rules(n, trial, rules, sol):
                continue  # この記号を抜くと solution 自体がルール違反になる→抜けない
            cnt, _ = count_solutions(n, trial, rules, limit=2, node_budget=1_000_000)
            if cnt == 1:
                redundant.append(i)
        if redundant:
            total_redundant += len(redundant)
            print("  idx=%d tier=%s 記号%d個中 %d個は削っても一意 (マス位置 %r)" %
                  (puzzles.index(p), p["tier"], len(idxs), len(redundant), redundant))
    print("  合計:", total_redundant, "個の記号が『あっても一意性に寄与していない』")


def main():
    if "--brute" in sys.argv:
        run_brute()
        return
    if "--minimize" in sys.argv:
        run_minimize()
        return
    run_brute()
    print()
    fails = run_main()
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
