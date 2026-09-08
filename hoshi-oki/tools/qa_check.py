# 担当: qa係
# -*- coding: utf-8 -*-
"""星おき 独立検証（実装者の gen_puzzles.py / index.html のコードは使わない）
    python3 qa_check.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IDCHARS = "abcdefghijklmnopqrstuvwxyz"


def load_from_html():
    src = (ROOT / "index.html").read_text(encoding="utf-8")
    m = re.search(r"var PUZZLES = (\[.*?\]);", src, re.S)
    if not m:
        raise SystemExit("PUZZLES 配列が見つからない")
    return json.loads(m.group(1))


def load_from_json():
    return json.loads((ROOT / "tools/puzzles.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 独立ソルバー（総当り・行ごと）
def count_solutions(n, reg, limit=2):
    """行ごとに★の列を選ぶ素朴なバックトラック。実装者のビット演算コードは使わない。"""
    sols = []

    def bt(r, used_cols, used_regs, star_cells):
        if len(sols) >= limit:
            return
        if r == n:
            sols.append(list(star_cells))
            return
        for c in range(n):
            if c in used_cols:
                continue
            cell = r * n + c
            k = reg[cell]
            if k in used_regs:
                continue
            ok = True
            for (pr, pc) in star_cells:
                if abs(pr - r) <= 1 and abs(pc - c) <= 1:
                    ok = False
                    break
            if not ok:
                continue
            star_cells.append((r, c))
            used_cols.add(c)
            used_regs.add(k)
            bt(r + 1, used_cols, used_regs, star_cells)
            star_cells.pop()
            used_cols.discard(c)
            used_regs.discard(k)
            if len(sols) >= limit:
                return

    bt(0, set(), set(), [])
    return sols


# ---------------------------------------------------------------- 盤面妥当性
def region_id_map(regions_str):
    return [IDCHARS.index(ch) for ch in regions_str]


def check_validity(idx, p):
    errs = []
    n = p["n"]
    N = n * n
    reg = region_id_map(p["regions"])
    if len(reg) != N:
        errs.append("領域文字数が N*N でない")
        return errs
    nregions = len(set(reg))
    if nregions != n:
        errs.append("領域数が N でない(%d)" % nregions)

    # 連結性（4近傍BFS、自前実装）
    cells_by_region = {}
    for i, k in enumerate(reg):
        cells_by_region.setdefault(k, []).append(i)
    for k, cells in cells_by_region.items():
        seen = {cells[0]}
        stack = [cells[0]]
        cellset = set(cells)
        while stack:
            i = stack.pop()
            r, c = divmod(i, n)
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                rr, cc = r + dr, c + dc
                if 0 <= rr < n and 0 <= cc < n:
                    j = rr * n + cc
                    if j in cellset and j not in seen:
                        seen.add(j)
                        stack.append(j)
        if len(seen) != len(cells):
            errs.append("領域%sが連結でない" % IDCHARS[k])

    sol = p["solution"]
    if len(sol) != N:
        errs.append("solution文字数が N*N でない")
        return errs
    stars = [i for i in range(N) if sol[i] == "1"]
    if len(stars) != n:
        errs.append("★の数が N でない(%d)" % len(stars))
    rows = [i // n for i in stars]
    cols = [i % n for i in stars]
    if len(set(rows)) != len(rows):
        errs.append("行に★が2つ以上ある行がある")
    if len(set(cols)) != len(cols):
        errs.append("列に★が2つ以上ある列がある")
    regs_of_stars = [reg[i] for i in stars]
    if len(set(regs_of_stars)) != len(regs_of_stars):
        errs.append("同じ領域に★が2つ以上ある")
    if len(set(regs_of_stars)) != n if len(regs_of_stars) == n else False:
        pass
    for a in range(len(stars)):
        for b in range(a + 1, len(stars)):
            ra, ca = divmod(stars[a], n)
            rb, cb = divmod(stars[b], n)
            if abs(ra - rb) <= 1 and abs(ca - cb) <= 1:
                errs.append("★同士が隣接(%d,%d)" % (stars[a], stars[b]))
    return errs


# ---------------------------------------------------------------- 簡易論理ソルバー（自前・独立実装）
def logic_solve(n, reg):
    """候補1つ確定／領域候補が1行1列に収まれば消す／確定★の周囲8近傍+行+列+領域を消す、
    をfixpointまで繰り返す。st: 0=未定,1=不可,2=★。解けきったら True。"""
    N = n * n
    st = [0] * N
    rowcells = [[r * n + c for c in range(n)] for r in range(n)]
    colcells = [[r * n + c for r in range(n)] for c in range(n)]
    regcells = {}
    for i, k in enumerate(reg):
        regcells.setdefault(k, []).append(i)

    def neighbors8(i):
        r, c = divmod(i, n)
        out = []
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                rr, cc = r + dr, c + dc
                if 0 <= rr < n and 0 <= cc < n:
                    out.append(rr * n + cc)
        return out

    def place(i):
        if st[i] == 1:
            return False
        st[i] = 2
        r, c = divmod(i, n)
        for j in rowcells[r] + colcells[c] + regcells[reg[i]] + neighbors8(i):
            if j != i:
                if st[j] == 2:
                    return False
                st[j] = 1
        return True

    changed = True
    while changed:
        changed = False
        units = rowcells + colcells + list(regcells.values())
        for unit in units:
            if any(st[c] == 2 for c in unit):
                continue
            cands = [c for c in unit if st[c] == 0]
            if len(cands) == 0:
                return False, st  # 矛盾（この問題は起きないはず）
            if len(cands) == 1:
                if not place(cands[0]):
                    return False, st
                changed = True
        if changed:
            continue
        for k, unit in regcells.items():
            if any(st[c] == 2 for c in unit):
                continue
            cands = [c for c in unit if st[c] == 0]
            if not cands:
                continue
            rows = set(c // n for c in cands)
            if len(rows) == 1:
                rr = rows.pop()
                for c in rowcells[rr]:
                    if reg[c] != k and st[c] == 0:
                        st[c] = 1
                        changed = True
            cols = set(c % n for c in cands)
            if len(cols) == 1:
                cc = cols.pop()
                for c in colcells[cc]:
                    if reg[c] != k and st[c] == 0:
                        st[c] = 1
                        changed = True
    return st.count(2) == n, st


def main():
    html_puzzles = load_from_html()
    json_puzzles = load_from_json()

    print("=== 0. index.html と puzzles.json の一致 ===")
    if html_puzzles == json_puzzles:
        print("PASS: 完全一致 (%d本)" % len(html_puzzles))
    else:
        print("FAIL: 内容が異なる（件数 html=%d json=%d）" % (len(html_puzzles), len(json_puzzles)))
        for i, (a, b) in enumerate(zip(html_puzzles, json_puzzles)):
            if a != b:
                print("  差分 index %d" % i)

    puzzles = html_puzzles
    print("\n=== 1. 独立ソルバーで一意性再検証 (自前バックトラック, limit=2) ===")
    uniq_fail = []
    mismatch_fail = []
    for i, p in enumerate(puzzles):
        n = p["n"]
        reg = region_id_map(p["regions"])
        sols = count_solutions(n, reg, limit=2)
        if len(sols) != 1:
            uniq_fail.append((i, len(sols)))
            continue
        sol_cells = set(r * n + c for (r, c) in sols[0])
        given = set(k for k in range(n * n) if p["solution"][k] == "1")
        if sol_cells != given:
            mismatch_fail.append(i)
    if not uniq_fail and not mismatch_fail:
        print("PASS: 40/40 一意解、かつ独立ソルバーの解が solution と一致")
    else:
        if uniq_fail:
            print("FAIL 一意性: %s" % uniq_fail)
        if mismatch_fail:
            print("FAIL solution不一致: %s" % mismatch_fail)

    print("\n=== 2. 盤面妥当性（領域/連結/★配置/隣接） ===")
    all_errs = {}
    for i, p in enumerate(puzzles):
        errs = check_validity(i, p)
        if errs:
            all_errs[i] = errs
    if not all_errs:
        print("PASS: 40/40 妥当")
    else:
        print("FAIL:")
        for i, errs in all_errs.items():
            print("  index %d: %s" % (i, errs))

    print("\n=== 3. 難度の実態（自前・簡易論理ソルバーのみで解けるか） ===")
    from collections import defaultdict
    tier_total = defaultdict(int)
    tier_logic_ok = defaultdict(int)
    tier_nodes_claim = defaultdict(list)
    per_index_logic = []
    for i, p in enumerate(puzzles):
        n = p["n"]
        reg = region_id_map(p["regions"])
        solved, st = logic_solve(n, reg)
        tier_total[p["tier"]] += 1
        if solved:
            tier_logic_ok[p["tier"]] += 1
        else:
            per_index_logic.append((i, p["tier"], p.get("nodes")))
        tier_nodes_claim[p["tier"]].append(p.get("nodes"))
    for t in ["入門", "初級", "中級", "上級"]:
        tot = tier_total.get(t, 0)
        ok = tier_logic_ok.get(t, 0)
        print("  %s: 論理だけで解けた %d/%d本  nodes記載範囲=%s" %
              (t, ok, tot, (min(tier_nodes_claim[t]), max(tier_nodes_claim[t])) if tier_nodes_claim.get(t) else None))
    print("  論理で解けなかった問題（index, tier, 申告nodes）:")
    for row in per_index_logic:
        print("    ", row)
    # spec.md の主張チェック：入門/初級は nodes==0（=申告上は論理だけで解けるはず）
    spec_claim_violations = []
    for i, p in enumerate(puzzles):
        n = p["n"]
        reg = region_id_map(p["regions"])
        solved, st = logic_solve(n, reg)
        if p["tier"] in ("入門", "初級") and p.get("nodes") == 0 and not solved:
            spec_claim_violations.append(i)
    if spec_claim_violations:
        print("  【要注意】nodes=0申告(論理で解けるはず)なのに自前の簡易論理ソルバーでは解けない index:", spec_claim_violations)
        print("  (自前ソルバーのルール網羅が実装者版より弱い可能性あり。まず実装者版propagateとの規則差を疑う)")
    else:
        print("  nodes=0申告分はすべて自前簡易論理ソルバーでも解けた（整合）")


if __name__ == "__main__":
    main()
