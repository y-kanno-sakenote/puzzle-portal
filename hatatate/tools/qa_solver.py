#!/usr/bin/env python3
"""担当: 検証係（独立実装）— はたたて 独立ソルバー（標準ライブラリのみ）

実装者のコード（gen_levels.py / index.html のロジック部）を読まずに spec.md の規則だけから書いた。
  python3 qa_solver.py tools/levels.json [index.html]
検証項目:
  A 完全推論（数字に接する閉マスの全配置＋盤全体の残り地雷数）で当てずっぽう無しに全安全マスが開くか
  B spec の段1〜4 を自前実装し「必要な一番強い段」と各段の使用回数を出してデータと突合
  C データ整合（盤サイズ・地雷数・start が0・開始の開きに地雷無し・開き＝0のマス1つ＋連鎖・open 数・割合8〜30%）
  D 似すぎ（同段 Jaccard、4変換の最大 >=0.5）・完全重複
  E 段の採用条件・段内の並び
  F index.html 埋め込み LEVELS と levels.json の一致（引数があれば）
--trace N で第N問（0始まり）の段階ソルバーの手順を JSON で出す（画面の自動プレイ用）
"""
import json
import re
import sys
from itertools import combinations

TIER_SPEC = {"入門": (6, 8, 8, 1), "初級": (8, 10, 14, 2), "中級": (8, 12, 19, 3), "上級": (9, 14, 26, 4)}


class Board:
    def __init__(self, lv):
        self.w, self.h = lv["w"], lv["h"]
        self.N = self.w * self.h
        self.mine = [c == "1" for c in lv["mines"]]
        assert len(self.mine) == self.N, "mines length"
        self.total = sum(self.mine)
        self.nb = []
        for i in range(self.N):
            x, y = i % self.w, i // self.w
            l = []
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    xx, yy = x + dx, y + dy
                    if 0 <= xx < self.w and 0 <= yy < self.h:
                        l.append(yy * self.w + xx)
            self.nb.append(l)
        self.num = [sum(self.mine[j] for j in self.nb[i]) for i in range(self.N)]


def flood(b, opened, i):
    """i を開ける（安全前提）。0なら連鎖。新しく開いたマスの集合を返す"""
    new = set()
    st = [i]
    while st:
        c = st.pop()
        if c in opened:
            continue
        assert not b.mine[c], "opened a mine"
        opened.add(c)
        new.add(c)
        if b.num[c] == 0:
            for j in b.nb[c]:
                if j not in opened:
                    st.append(j)
    return new


def constraints(b, opened, flags):
    """(閉じた未確定隣 frozenset, 残り地雷数) のリスト（未確定隣が無いものは除く）"""
    cons = []
    for i in opened:
        if b.num[i] == 0:
            continue
        unk = frozenset(j for j in b.nb[i] if j not in opened and j not in flags)
        if not unk:
            continue
        r = b.num[i] - sum(1 for j in b.nb[i] if j in flags)
        cons.append((unk, r))
    # 同じ集合の制約は1つに（矛盾は無い前提だが一応確認）
    d = {}
    for u, r in cons:
        if u in d:
            assert d[u] == r
        d[u] = r
    return [(u, r) for u, r in d.items()]


def unknown_cells(b, opened, flags):
    return [i for i in range(b.N) if i not in opened and i not in flags]


# ---------- 段1 ----------
def stage1(b, opened, flags):
    safe, mines = set(), set()
    for u, r in constraints(b, opened, flags):
        if r == 0:
            safe |= u
        elif r == len(u):
            mines |= u
    unk = unknown_cells(b, opened, flags)
    left = b.total - len(flags)
    if unk and left == 0:
        safe |= set(unk)
    elif unk and left == len(unk):
        mines |= set(unk)
    return safe, mines


# ---------- 段2 ----------
def stage2(b, opened, flags):
    safe, mines = set(), set()
    cons = constraints(b, opened, flags)
    for (ua, ra), (ub, rb) in combinations(cons, 2):
        c = ua & ub
        if not c:
            continue
        a_only, b_only = ua - ub, ub - ua
        feas = []
        for k in range(0, len(c) + 1):
            ka, kb = ra - k, rb - k
            if 0 <= ka <= len(a_only) and 0 <= kb <= len(b_only):
                feas.append((ka, k, kb))
        assert feas, "pair contradiction"
        for idx, reg in ((0, a_only), (1, c), (2, b_only)):
            if not reg:
                continue
            vals = {f[idx] for f in feas}
            if vals == {0}:
                safe |= reg
            elif vals == {len(reg)}:
                mines |= reg
    return safe, mines


# ---------- 全解列挙（かたまり単位） ----------
class TooHeavy(Exception):
    pass


def components(cons):
    """制約を共有セルでつないだかたまりに分ける。[(cells(list), cons_list)]"""
    n = len(cons)
    parent = list(range(n))

    def f(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    owner = {}
    for k, (u, r) in enumerate(cons):
        for c in u:
            if c in owner:
                parent[f(k)] = f(owner[c])
            else:
                owner[c] = k
    groups = {}
    for k in range(n):
        groups.setdefault(f(k), []).append(k)
    out = []
    for ks in groups.values():
        cl = [cons[k] for k in ks]
        cells = sorted(set().union(*[u for u, _ in cl]))
        out.append((cells, cl))
    return out


def enumerate_comp(cells, cl, limit=2_000_000):
    """かたまりの全解。戻り値: {mine数k: (解の数, 各セルが地雷になった回数のリスト)}"""
    idx = {c: i for i, c in enumerate(cells)}
    # セル順は制約の多い順にしたほうが早いが、正しさには不要。単純な深さ優先＋前向き検査
    cons_idx = [([idx[c] for c in u], r) for u, r in cl]
    cell_cons = [[] for _ in cells]
    for k, (cs, r) in enumerate(cons_idx):
        for i in cs:
            cell_cons[i].append(k)
    n = len(cells)
    assign = [None] * n
    cur = [0] * len(cons_idx)       # 制約ごとの確定地雷数
    left = [len(cs) for cs, _ in cons_idx]  # 制約ごとの未割当セル数
    res = {}
    nodes = [0]

    def rec(i, k):
        nodes[0] += 1
        if nodes[0] > limit:
            raise TooHeavy()
        if i == n:
            e = res.get(k)
            if e is None:
                e = [0, [0] * n]
                res[k] = e
            e[0] += 1
            for t in range(n):
                if assign[t]:
                    e[1][t] += 1
            return
        for v in (0, 1):
            ok = True
            for kk in cell_cons[i]:
                r = cons_idx[kk][1]
                nc = cur[kk] + v
                nl = left[kk] - 1
                if nc > r or nc + nl < r:
                    ok = False
                    break
            if not ok:
                continue
            assign[i] = v
            for kk in cell_cons[i]:
                cur[kk] += v
                left[kk] -= 1
            rec(i + 1, k + v)
            for kk in cell_cons[i]:
                cur[kk] -= v
                left[kk] += 1
            assign[i] = None

    rec(0, 0)
    assert res, "component contradiction"
    return {k: (v[0], v[1]) for k, v in res.items()}, nodes[0]


def stage3(b, opened, flags):
    safe, mines = set(), set()
    for cells, cl in components(constraints(b, opened, flags)):
        res, _ = enumerate_comp(cells, cl)
        tot = sum(v[0] for v in res.values())
        for t, c in enumerate(cells):
            m = sum(v[1][t] for v in res.values())
            if m == 0:
                safe.add(c)
            elif m == tot:
                mines.add(c)
    return safe, mines


def stage4(b, opened, flags):
    """完全推論：全かたまりの解＋数字に接しないマスを、盤全体の残り地雷数で連立"""
    safe, mines = set(), set()
    comps = components(constraints(b, opened, flags))
    front = set()
    for cells, _ in comps:
        front |= set(cells)
    rest = [c for c in unknown_cells(b, opened, flags) if c not in front]
    R = len(rest)
    M = b.total - len(flags)
    results = [enumerate_comp(cells, cl)[0] for cells, cl in comps]

    def sums_excluding(skip):
        s = {0}
        for j, res in enumerate(results):
            if j == skip:
                continue
            s = {a + k for a in s for k in res}
        return s

    for j, (cells, _) in enumerate(comps):
        others = sums_excluding(j)
        res = results[j]
        okk = [k for k in res if any(0 <= M - k - o <= R for o in others)]
        assert okk
        for t, c in enumerate(cells):
            can_m = any(res[k][1][t] > 0 for k in okk)
            can_s = any(res[k][1][t] < res[k][0] for k in okk)
            if not can_m:
                safe.add(c)
            elif not can_s:
                mines.add(c)
    if R:
        allk = sums_excluding(-1)
        rs = {M - s for s in allk if 0 <= M - s <= R}
        assert rs
        if max(rs) == 0:
            safe |= set(rest)
        elif min(rs) == R:
            mines |= set(rest)
    return safe, mines


STAGES = [stage1, stage2, stage3, stage4]


def start_state(b, lv):
    opened = set()
    flood(b, opened, lv["start"])
    return opened


def solve(lv, max_stage=4, trace=None):
    """段階ソルバー。弱い段から試し、決まった段の発見を全部適用して段1へ戻る"""
    b = Board(lv)
    opened = start_state(b, lv)
    flags = set()
    uses = [0, 0, 0, 0]
    safe_total = b.N - b.total
    stuck = None
    while len(opened) < safe_total:
        got = False
        for s in range(max_stage):
            sf, mn = STAGES[s](b, opened, flags)
            # 正しさの自己検査（推論が真の答えと矛盾しないこと）
            assert all(not b.mine[c] for c in sf), f"stage{s+1} wrong safe"
            assert all(b.mine[c] for c in mn), f"stage{s+1} wrong mine"
            if sf or mn:
                uses[s] += 1
                if trace is not None:
                    trace.append({"stage": s + 1, "safe": sorted(sf), "mines": sorted(mn)})
                flags |= mn
                for c in sorted(sf):
                    if c not in opened:
                        flood(b, opened, c)
                got = True
                break
        if not got:
            stuck = (sorted(opened), sorted(flags))
            break
    hardest = max([s + 1 for s in range(4) if uses[s]] or [0])
    return {"solved": len(opened) == safe_total, "uses": uses, "hardest": hardest, "stuck": stuck,
            "opened0": len(start_state(b, lv))}


def full_only(lv):
    """完全推論だけを繰り返す（段の区別なし）"""
    b = Board(lv)
    opened = start_state(b, lv)
    flags = set()
    safe_total = b.N - b.total
    rounds = 0
    while len(opened) < safe_total:
        sf, mn = stage4(b, opened, flags)
        assert all(not b.mine[c] for c in sf) and all(b.mine[c] for c in mn)
        if not sf and not mn:
            return False, rounds, (sorted(opened), sorted(flags))
        rounds += 1
        flags |= mn
        for c in sf:
            if c not in opened:
                flood(b, opened, c)
    return True, rounds, None


def transforms(lv):
    w, h = lv["w"], lv["h"]
    s = {i for i, c in enumerate(lv["mines"]) if c == "1"}
    out = []
    for fx, fy in ((0, 0), (1, 0), (0, 1), (1, 1)):
        t = set()
        for i in s:
            x, y = i % w, i // w
            if fx:
                x = w - 1 - x
            if fy:
                y = h - 1 - y
            t.add(y * w + x)
        out.append(t)
    return out


def jaccard(a, b):
    return len(a & b) / len(a | b) if a | b else 1.0


def main():
    args = sys.argv[1:]
    if args and args[0] == "--trace":
        n = int(args[1])
        levels = json.load(open(args[2]))
        tr = []
        r = solve(levels[n], trace=tr)
        print(json.dumps({"result": r, "trace": tr}))
        return
    levels = json.load(open(args[0]))
    fails = []
    print(f"levels: {len(levels)}")
    rows = []
    for n, lv in enumerate(levels):
        b = Board(lv)
        tier = lv["tier"]
        W, H, Mn, need = TIER_SPEC[tier]
        # C データ整合
        if (lv["w"], lv["h"]) != (W, H):
            fails.append(f"#{n} size {lv['w']}x{lv['h']}")
        if b.total != Mn:
            fails.append(f"#{n} mines {b.total} != {Mn}")
        if b.mine[lv["start"]] or b.num[lv["start"]] != 0:
            fails.append(f"#{n} start not a safe 0")
        op = start_state(b, lv)
        if any(b.mine[c] for c in op):
            fails.append(f"#{n} start opens mine")
        if len(op) != lv["open"]:
            fails.append(f"#{n} open {len(op)} != data {lv['open']}")
        ratio = len(op) / (b.N - b.total)
        if not (0.08 <= ratio <= 0.30):
            fails.append(f"#{n} open ratio {ratio:.3f} out of 8-30%")
        # A 完全推論
        ok, rounds, st = full_only(lv)
        if not ok:
            fails.append(f"#{n} FULL-INFERENCE STUCK opened={len(st[0])} flags={len(st[1])}")
        # B 段階
        r = solve(lv)
        if not r["solved"]:
            fails.append(f"#{n} tiered stuck")
        if r["hardest"] != lv["hardest"]:
            fails.append(f"#{n} hardest {r['hardest']} != data {lv['hardest']}")
        if r["uses"] != lv["uses"]:
            fails.append(f"#{n} uses {r['uses']} != data {lv['uses']}")
        # 弱い段で止まることの確認（必要な一番強い段）
        if r["hardest"] > 1:
            r2 = solve(lv, max_stage=r["hardest"] - 1)
            if r2["solved"]:
                fails.append(f"#{n} solvable with stage<= {r['hardest']-1}")
        # E 採用条件
        u = r["uses"]
        cond = {"入門": r["hardest"] == 1,
                "初級": r["hardest"] == 2 and u[1] >= 2,
                "中級": r["hardest"] == 3,
                "上級": r["hardest"] == 4 and u[2] >= 1}[tier]
        if not cond:
            fails.append(f"#{n} tier condition fails ({tier} uses={u})")
        rows.append((n, tier, ratio, u, r["hardest"], rounds))
    # E 並び（spec order_key：小さい順。「開始時に開いているマス数の多い順」は −open）
    for tier in TIER_SPEC:
        tr = [x for x in rows if x[1] == tier]
        def okey(x):
            u, lv = x[3], levels[x[0]]
            tail = (-lv["open"], lv["start"])
            if tier == "入門": return (u[0],) + tail
            if tier == "初級": return (u[1],) + tail
            if tier == "中級": return (u[2], u[1]) + tail
            return (u[2] + u[3], u[1]) + tail
        key = [okey(x) for x in tr]
        if key != sorted(key):
            fails.append(f"{tier} order_key not ascending: {key}")
        print(tier, "ratio %.0f-%.0f%% avg %.0f%%" % (min(x[2] for x in tr) * 100, max(x[2] for x in tr) * 100,
                                                    sum(x[2] for x in tr) / len(tr) * 100),
              "uses", [x[3] for x in tr])
    # G 始まりに見える盤（開いたマスの位置と数字・4変換同一視）の重複
    def view(lv):
        b = Board(lv); op = start_state(b, lv); w, h = lv["w"], lv["h"]
        vs = []
        for fx, fy in ((0, 0), (1, 0), (0, 1), (1, 1)):
            t = []
            for i in op:
                x, y = i % w, i // w
                if fx: x = w - 1 - x
                if fy: y = h - 1 - y
                t.append((y * w + x, b.num[i]))
            vs.append((w, h, tuple(sorted(t))))
        return min(vs)
    vmap = {}
    for n, lv in enumerate(levels):
        vmap.setdefault(view(lv), []).append(n)
    for k, ns in vmap.items():
        if len(ns) > 1:
            tiers = {levels[n]["tier"] for n in ns}
            if len(tiers) == 1:
                fails.append(f"same opening view in tier: {ns}")
            else:
                print("REF cross-tier same opening view:", ns)
    print("opening views distinct:", len(vmap), "/", len(levels))
    # H start の区画（3×3、x*3//w, y*3//h）
    for tier in TIER_SPEC:
        from collections import Counter
        cnt = Counter()
        for lv in levels:
            if lv["tier"] == tier:
                x, y = lv["start"] % lv["w"], lv["start"] // lv["w"]
                cnt[(x * 3 // lv["w"], y * 3 // lv["h"])] += 1
        print(tier, "start regions", len(cnt), "max per region", max(cnt.values()))
    # D 似すぎ・重複
    seen = {}
    for n, lv in enumerate(levels):
        k = (lv["w"], lv["h"], lv["mines"])
        if k in seen:
            fails.append(f"duplicate #{seen[k]} #{n}")
        seen[k] = n
    for tier in TIER_SPEC:
        idx = [n for n, lv in enumerate(levels) if lv["tier"] == tier]
        mx = (0, None)
        for a, c in combinations(idx, 2):
            sa = transforms(levels[a])[0]
            j = max(jaccard(sa, t) for t in transforms(levels[c]))
            if j > mx[0]:
                mx = (j, (a, c))
            if j >= 0.5:
                fails.append(f"{tier} too similar #{a} #{c} J={j:.3f}")
        print(tier, "max Jaccard %.3f" % mx[0], mx[1])
    # 段ごとの数
    from collections import Counter
    print("per tier:", dict(Counter(lv["tier"] for lv in levels)))
    # F 埋め込み一致
    if len(args) > 1:
        html = open(args[1], encoding="utf-8").read()
        m = re.search(r"/\* LEVELS-BEGIN[^\n]*\n\s*var LEVELS\s*=\s*(\[.*?\]);\s*/\* LEVELS-END", html, re.S)
        emb = json.loads(m.group(1))
        print("embedded equal to levels.json:", emb == levels)
        if emb != levels:
            fails.append("embedded LEVELS != levels.json")
    print("FAILS:", len(fails))
    for f in fails:
        print("  ", f)
    print("OVERALL", "PASS" if not fails else "FAIL")


if __name__ == "__main__":
    main()
