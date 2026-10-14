#!/usr/bin/env python3
"""はたたて（運の無い、数字から穴を読むパズル）のレベル生成器。Python3 標準ライブラリのみ。

ランダムに地雷を置く → 開始時に開くマス（0のマス1つ＋そこから連鎖で開く範囲）を決める →
段階ソルバーで「当てずっぽう無しに全安全マスを開けられるか」「最も強い推論が何段か」を判定 → 採用。

使い方:
  python3 tools/gen_levels.py                                   # 生成して tools/levels.json へ
  python3 tools/gen_levels.py --embed index.html                # 生成して index.html にも埋め込む
  python3 tools/gen_levels.py --keep tools/levels.json --embed index.html   # 埋め込みだけ（min は計算し直して JSON にも書き戻す）
  python3 tools/gen_levels.py --check tools/levels.json         # 解き直して段を表示するだけ

推論の段（spec.md と index.html の window.Hatatate.solve と同じ定義）:
  段1: 1つの数字だけで決まる（残り地雷数 = 閉じたマスの数なら全部地雷、0なら全部安全）。
       盤全体の残り地雷数だけで決まる場合（残り0なら閉じたマスは全部安全／閉じたマスの数と同じなら全部地雷）も段1
  段2: 2つの数字の比べ合い（重なる2つの数字を連立し、どの解でも同じになるマスを確定）
  段3: 3つ以上の数字の連立（数字でつながったひとかたまりの全解で、どの解でも同じになるマスを確定）
  段4: 盤全体の残り地雷数を数字と組み合わせて使う（かたまりどうし＋数字に接しないマスを、残り地雷数で連立）
各回、弱い段から試し、何か決まった段の発見を「全部まとめて」適用して段1に戻る（適用順に依存しない）。

min（クエストの最小手数・quest/docs/spec.md §4）: 始まりの状態から全安全マスを開くのに要る最少のタップ数（3BV の考え方）。
  まだ開いていない「0のマスのつながり」の数 ＋ どの0のつながりの連鎖でも開かない数字マスの数。盤からの機械計算で、手で書かない。
"""
import argparse
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

# 段ごとの盤（列 w × 行 h・地雷数）。縦長。幅360pxでマス36px以上（spec.md）
TIERS = [
    # 名前, 必要な段, w, h, 地雷
    ("入門", 1, 6, 8, 8),
    ("初級", 2, 8, 10, 14),
    ("中級", 3, 8, 12, 19),
    ("上級", 4, 9, 14, 26),
]
PER_TIER = 10
OPEN_MAX = 0.30          # 開始時に開いている割合（安全マスに対して）の上限
OPEN_MIN = 0.08          # 下限（入口が小さすぎると段1で進めない盤ばかりになる。叩き台）
SIM_MAX = 0.5            # 地雷配置の重なり（Jaccard、反転・回転込み）がこれ以上なら似すぎ
ENUM_CAP = 200000        # 段3・4 の全解列挙の上限（超えたら重すぎるとして捨てる。JS も同じ上限）
POOL = 200               # 段ごとに集める候補の数（ここから10問を選ぶ）
# 段ごとの採用条件（uses＝段1..4を使った回数）。上級は段4に加えて段3も要る（段4はほぼ終盤の1回なので）
MUST = {1: lambda u: True,
        2: lambda u: u[1] >= 2,
        3: lambda u: u[2] >= 1,
        4: lambda u: u[2] >= 1 and u[3] >= 1}


class TooHeavy(Exception):
    pass


def neighbors(w, h):
    nb = []
    for i in range(w * h):
        r, c = divmod(i, w)
        lst = []
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                rr, cc = r + dr, c + dc
                if 0 <= rr < h and 0 <= cc < w:
                    lst.append(rr * w + cc)
        nb.append(lst)
    return nb


def numbers(w, h, mines, nb):
    return [sum(1 for j in nb[i] if mines[j]) for i in range(w * h)]


def cascade(start, nums, mines, nb, opened):
    """start を開ける（0なら周りへ連鎖）。opened（list[bool]）を書き換え、新しく開いたマスを返す"""
    out = []
    if opened[start] or mines[start]:
        return out
    stack = [start]
    opened[start] = True
    while stack:
        i = stack.pop()
        out.append(i)
        if nums[i] == 0:
            for j in nb[i]:
                if not opened[j] and not mines[j]:
                    opened[j] = True
                    stack.append(j)
    return out


def min_clicks(w, h, mines, start):
    """クエストの最小手数（3BV）。始まり（start の連鎖）で開いている分は除く。
    まだ閉じている0のマスを1つずつ連鎖で開け（1つにつき1手）、残った数字マスを1手ずつ数える"""
    nb = neighbors(w, h)
    nums = numbers(w, h, mines, nb)
    opened = [False] * (w * h)
    cascade(start, nums, mines, nb, opened)
    n = 0
    for i in range(w * h):
        if not opened[i] and not mines[i] and nums[i] == 0:
            cascade(i, nums, mines, nb, opened)
            n += 1
    n += sum(1 for i in range(w * h) if not opened[i] and not mines[i])
    return n


# ---------------------------------------------------------------- ソルバー

def constraints(st, nums, nb):
    """st: 0=閉じ（未確定） 1=開いた 2=地雷と確定。開いた数字ごとに (閉じた隣の組, 残り地雷数)"""
    cons = []
    for i, s in enumerate(st):
        if s != 1:
            continue
        unk = [j for j in nb[i] if st[j] == 0]
        if not unk:
            continue
        need = nums[i] - sum(1 for j in nb[i] if st[j] == 2)
        cons.append((tuple(unk), need))
    return cons


def level1(cons):
    safe, mine = set(), set()
    for cells, need in cons:
        if need == 0:
            safe.update(cells)
        elif need == len(cells):
            mine.update(cells)
    return safe, mine


def level2(cons):
    safe, mine = set(), set()
    sets = [frozenset(c) for c, _ in cons]
    by_cell = {}
    for k, (cells, _) in enumerate(cons):
        for x in cells:
            by_cell.setdefault(x, []).append(k)
    pairs = set()
    for ks in by_cell.values():
        for a in ks:
            for b in ks:
                if a < b:
                    pairs.add((a, b))
    for a, b in sorted(pairs):
        A, B = sets[a], sets[b]
        na, nb_ = cons[a][1], cons[b][1]
        I = A & B
        Ao, Bo = A - B, B - A
        xs = [x for x in range(0, len(I) + 1)
              if 0 <= na - x <= len(Ao) and 0 <= nb_ - x <= len(Bo)]
        if not xs:
            continue
        for region, vals in ((I, xs), (Ao, [na - x for x in xs]), (Bo, [nb_ - x for x in xs])):
            if not region:
                continue
            if all(v == 0 for v in vals):
                safe.update(region)
            elif all(v == len(region) for v in vals):
                mine.update(region)
    return safe, mine


def components(cons):
    """数字でつながったかたまり。[(変数リスト, 制約リスト[(添字タプル, need)])]（決まった順に並べる）"""
    parent = {}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for cells, _ in cons:
        for x in cells:
            parent.setdefault(x, x)
        for x in cells[1:]:
            ra, rb = find(cells[0]), find(x)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)
    groups = {}
    for x in sorted(parent):
        groups.setdefault(find(x), []).append(x)
    out = []
    for root in sorted(groups):
        vars_ = groups[root]
        vs = set(vars_)
        cs = [(cells, need) for cells, need in cons if cells[0] in vs]
        out.append((vars_, cs))
    return out


def enumerate_comp(vars_, cs):
    """かたまりの全解を数え、(feasK, mineK[v], safeK[v]) をビット集合（k=地雷数）で返す"""
    n = len(vars_)
    pos = {v: k for k, v in enumerate(vars_)}
    # 変数を「制約でつながる順」に並べ替える（枝刈りが早く効く）
    cidx = [[pos[x] for x in cells] for cells, _ in cs]
    need = [nd for _, nd in cs]
    var_cons = [[] for _ in range(n)]
    for k, lst in enumerate(cidx):
        for v in lst:
            var_cons[v].append(k)
    order, seen = [], [False] * n
    for start in range(n):
        if seen[start]:
            continue
        queue = [start]
        seen[start] = True
        while queue:
            v = queue.pop(0)
            order.append(v)
            for k in var_cons[v]:
                for u in cidx[k]:
                    if not seen[u]:
                        seen[u] = True
                        queue.append(u)
    assigned = [0] * len(cs)   # 置いた地雷数
    remaining = [len(l) for l in cidx]  # 未決の変数数
    val = [0] * n
    feasK = 0
    mineK = [0] * n
    safeK = [0] * n
    nodes = [0]

    def rec(d, m):
        nonlocal feasK
        nodes[0] += 1
        if nodes[0] > ENUM_CAP:
            raise TooHeavy()
        if d == n:
            bit = 1 << m
            feasK |= bit
            for v in range(n):
                if val[v]:
                    mineK[v] |= bit
                else:
                    safeK[v] |= bit
            return
        v = order[d]
        for x in (0, 1):
            ok = True
            for k in var_cons[v]:
                a = assigned[k] + x
                r = remaining[k] - 1
                if a > need[k] or a + r < need[k]:
                    ok = False
                    break
            if not ok:
                continue
            for k in var_cons[v]:
                assigned[k] += x
                remaining[k] -= 1
            val[v] = x
            rec(d + 1, m + x)
            for k in var_cons[v]:
                assigned[k] -= x
                remaining[k] += 1
        val[v] = 0

    rec(0, 0)
    return feasK, mineK, safeK


def sumset(a, b):
    out = 0
    k = 0
    while a:
        if a & 1:
            out |= b << k
        a >>= 1
        k += 1
    return out


def level34(cons, st, total_mines, use_count):
    safe, mine = set(), set()
    comps = components(cons)
    infos = []
    for vars_, cs in comps:
        infos.append((vars_,) + enumerate_comp(vars_, cs))
    if not use_count:
        for vars_, feas, mk, sk in infos:
            for k, v in enumerate(vars_):
                if mk[k] == 0:
                    safe.add(v)
                elif sk[k] == 0:
                    mine.add(v)
        return safe, mine
    frontier = set()
    for vars_, _ in comps:
        frontier.update(vars_)
    interior = [i for i, s in enumerate(st) if s == 0 and i not in frontier]
    R = total_mines - sum(1 for s in st if s == 2)
    I = len(interior)
    lo, hi = R - I, R
    window = 0
    for t in range(max(lo, 0), hi + 1):
        window |= 1 << t
    nC = len(infos)
    # 前後からの和集合で「自分以外の全かたまり」の地雷数の集合を作る
    pre = [1] * (nC + 1)
    for j in range(nC):
        pre[j + 1] = sumset(pre[j], infos[j][1])
    suf = [1] * (nC + 1)
    for j in range(nC - 1, -1, -1):
        suf[j] = sumset(suf[j + 1], infos[j][1])
    for j, (vars_, feas, mk, sk) in enumerate(infos):
        others = sumset(pre[j], suf[j + 1])
        for k, v in enumerate(vars_):
            can_mine = sumset(mk[k], others) & window
            can_safe = sumset(sk[k], others) & window
            if not can_mine:
                safe.add(v)
            elif not can_safe:
                mine.add(v)
    if I:
        totals = pre[nC] & window
        if totals and totals == (1 << R):          # 数字の周りで残り全部 → 内側は全部安全
            safe.update(interior)
        elif totals and lo >= 0 and totals == (1 << lo):       # 内側が全部地雷
            mine.update(interior)
    return safe, mine


def solve(w, h, mines, start):
    """戻り値 {solved, hardest, uses:[段1..4の回数], opened0, steps}。地雷を開けることは無い（確定したものだけ開く）"""
    nb = neighbors(w, h)
    nums = numbers(w, h, mines, nb)
    N = w * h
    total = sum(mines)
    opened = [False] * N
    cascade(start, nums, mines, nb, opened)
    opened0 = sum(opened)
    st = [1 if opened[i] else 0 for i in range(N)]
    uses = [0, 0, 0, 0]
    safe_total = N - total
    while True:
        if sum(1 for s in st if s == 1) == safe_total:
            break
        cons = constraints(st, nums, nb)
        found = None
        for lv in (1, 2, 3, 4):
            if lv == 1:
                s, m = level1(cons)
                # 残り地雷数だけで決まる（0なら閉じたマスは全部安全、閉じたマスの数と同じなら全部地雷）は段1に含める
                unk = [i for i in range(N) if st[i] == 0]
                R = total - sum(1 for x in st if x == 2)
                if R == 0:
                    s = s | set(unk)
                elif R == len(unk):
                    m = m | set(unk)
            elif lv == 2:
                s, m = level2(cons)
            else:
                s, m = level34(cons, st, total, lv == 4)
            if s or m:
                found = (lv, s, m)
                break
        if not found:
            break
        lv, s, m = found
        uses[lv - 1] += 1
        for x in s:
            assert not mines[x], "ソルバーが地雷を安全と判定した"
        for x in m:
            assert mines[x], "ソルバーが安全マスを地雷と判定した"
            st[x] = 2
        for x in sorted(s):
            if st[x] == 0:
                for y in cascade(x, nums, mines, nb, opened):
                    st[y] = 1
    solved = sum(1 for s in st if s == 1) == safe_total
    hardest = max((k + 1 for k in range(4) if uses[k]), default=0)
    return {"solved": solved, "hardest": hardest, "uses": uses, "opened0": opened0}


# ---------------------------------------------------------------- 生成

def transforms(w, h):
    """同じ大きさの盤の対称（恒等・左右・上下・180度）"""
    def f(kind):
        def g(i):
            r, c = divmod(i, w)
            if kind & 1:
                c = w - 1 - c
            if kind & 2:
                r = h - 1 - r
            return r * w + c
        return g
    return [f(k) for k in range(4)]


def view_key(w, h, nums, mines, nb, start):
    """開始時に見える盤（開いたマスの位置と数字）を、左右・上下反転・180度で同一視した正準形"""
    op = [False] * (w * h)
    cells = cascade(start, nums, mines, nb, op)
    return min(tuple(sorted((t(i), nums[i]) for i in cells)) for t in transforms(w, h))


def zone(w, h, i):
    """始まりのマスが盤のどのあたりか（3×3の区画）"""
    r, c = divmod(i, w)
    return (r * 3 // h, c * 3 // w)


def similar(a, b, w, h):
    sa = a
    for t in transforms(w, h):
        sb = frozenset(t(i) for i in b)
        j = len(sa & sb) / len(sa | sb)
        if j >= SIM_MAX:
            return True
    return False


def gen_tier(name, need_lv, w, h, nm, rng, tries, log):
    N = w * h
    nb = neighbors(w, h)
    found = []
    stats = {"boards": 0, "heavy": 0, "solvable": 0, "by_lv": [0, 0, 0, 0, 0]}
    t0 = time.time()
    for _ in range(tries):
        mines = [False] * N
        for i in rng.sample(range(N), nm):
            mines[i] = True
        nums = numbers(w, h, mines, nb)
        stats["boards"] += 1
        # 0のマスの連鎖（同じ範囲になるものは1つにまとめる）
        regions, seen = [], [False] * N
        for i in range(N):
            if mines[i] or nums[i] != 0 or seen[i]:
                continue
            op = [False] * N
            cells = cascade(i, nums, mines, nb, op)
            for c in cells:
                if nums[c] == 0:
                    seen[c] = True
            regions.append((len(cells), i))
        safe_total = N - nm
        rng.shuffle(regions)
        regions.sort(key=lambda x: x[0])   # 小さい入口から試す（入口は最小限に）
        for size, start in regions:
            ratio = size / safe_total
            if ratio < OPEN_MIN or ratio > OPEN_MAX:
                continue
            try:
                r = solve(w, h, mines, start)
            except TooHeavy:
                stats["heavy"] += 1
                continue
            if not r["solved"]:
                continue
            stats["solvable"] += 1
            stats["by_lv"][r["hardest"]] += 1
            if r["hardest"] != need_lv or not MUST[need_lv](r["uses"]):
                continue
            ms = frozenset(i for i in range(N) if mines[i])
            if any(similar(ms, f[0], w, h) for f in found):
                continue
            vk = view_key(w, h, nums, mines, nb, start)
            if any(vk == f[3] for f in found):      # 始まりに見える盤が同じ（遊び手には同じ問題）
                continue
            found.append((ms, start, r, vk))
            break
        if len(found) >= POOL:
            break
    log("%s: 盤%d枚 解けた%d 重すぎ%d 段の内訳(段1..4)=%s 候補%d 時間%.1fs"
        % (name, stats["boards"], stats["solvable"], stats["heavy"], stats["by_lv"][1:], len(found), time.time() - t0))
    return found, stats


def select_key(f, need_lv):
    """選ぶときの優先（大きいほど先）。入門は入口の小さい順、ほかはその段（上級は段3＋段4）を使う回数の多い順"""
    u = f[2]["uses"]
    if need_lv == 1:
        return (-f[2]["opened0"], 0)
    if need_lv == 2:
        return (u[1], 0)
    if need_lv == 3:
        return (u[2], u[1])
    return (u[2] + u[3], u[1])


def order_key(f, need_lv):
    """段の中の並び（やさしい順）。spec.md「段の中の並び」と同じ。
    入門：段1の回数 / 初級：段2の回数 / 中級：段3の回数→段2の回数 / 上級：段3＋段4の回数→段2の回数
    の少ない順 → 開始時に開いているマス数の多い順 → start の番号の小さい順"""
    u = f[2]["uses"]
    main = {1: (u[0], 0), 2: (u[1], 0), 3: (u[2], u[1]), 4: (u[2] + u[3], u[1])}[need_lv]
    return main + (-f[2]["opened0"], f[1])


def pick(found, need_lv, w, h):
    """候補から10問。選ぶ優先は select_key、始まりのマスは3×3の区画ごとに2問まで（足りなければ緩める）"""
    cand = sorted(found, key=lambda f: (select_key(f, need_lv), -f[1]), reverse=True)
    for cap in (2, 3, PER_TIER):
        chosen, per = [], {}
        for f in cand:
            z = zone(w, h, f[1])
            if per.get(z, 0) >= cap:
                continue
            per[z] = per.get(z, 0) + 1
            chosen.append(f)
            if len(chosen) == PER_TIER:
                break
        if len(chosen) == PER_TIER:
            break
    chosen.sort(key=lambda f: order_key(f, need_lv))
    return chosen


def embed(path, levels):
    body = "var LEVELS = [\n" + ",\n".join(
        "  " + json.dumps(l, ensure_ascii=False, separators=(",", ":")) for l in levels) + "\n];\n"
    with open(path, encoding="utf-8") as f:
        html = f.read()
    b = html.index("/* LEVELS-BEGIN")
    b = html.index("\n", b) + 1
    e = html.index("/* LEVELS-END")
    html = html[:b] + body + html[e:]
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def to_level(name, need_lv, w, h, f):
    ms, start, r = f[:3]
    N = w * h
    return {"tier": name, "w": w, "h": h,
            "mines": "".join("1" if i in ms else "0" for i in range(N)),
            "start": start, "hardest": r["hardest"], "uses": r["uses"],
            "open": r["opened0"],
            "min": min_clicks(w, h, [i in ms for i in range(N)], start)}


def check(levels, log):
    ok = True
    for i, L in enumerate(levels):
        mines = [ch == "1" for ch in L["mines"]]
        r = solve(L["w"], L["h"], mines, L["start"])
        mn = min_clicks(L["w"], L["h"], mines, L["start"])
        bad = ((not r["solved"]) or r["hardest"] != L["hardest"] or r["uses"] != L["uses"] or r["opened0"] != L["open"]
               or L.get("min") != mn or not mn > 0)
        ok = ok and not bad
        log("%2d %s %dx%d 地雷%d 開始%d/%d(%.0f%%) 段%d 回数%s 最小%d手 %s" % (
            i, L["tier"], L["w"], L["h"], sum(mines), r["opened0"], len(mines) - sum(mines),
            100 * r["opened0"] / (len(mines) - sum(mines)), r["hardest"], r["uses"], mn, "NG" if bad else "ok"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20261013)
    ap.add_argument("--tries", type=int, default=60000, help="段ごとの盤の試行上限")
    ap.add_argument("--keep", metavar="JSON", help="生成せずこの JSON を使う")
    ap.add_argument("--embed", metavar="HTML", help="LEVELS-BEGIN / LEVELS-END の間へ埋め込む")
    ap.add_argument("--check", metavar="JSON", help="解き直して段を確かめるだけ")
    args = ap.parse_args()
    log = lambda *a: print(*a, file=sys.stderr)
    if args.check:
        with open(args.check, encoding="utf-8") as f:
            sys.exit(0 if check(json.load(f), log) else 1)
    if args.keep:
        with open(args.keep, encoding="utf-8") as f:
            levels = json.load(f)
        # 盤・地雷・始まりは変えず、min だけ計算し直して書き戻す（min は盤から決まる派生値）
        for L in levels:
            L["min"] = min_clicks(L["w"], L["h"], [ch == "1" for ch in L["mines"]], L["start"])
        with open(args.keep, "w", encoding="utf-8") as f:
            f.write("[\n" + ",\n".join("  " + json.dumps(l, ensure_ascii=False, separators=(",", ":")) for l in levels) + "\n]\n")
    else:
        rng = random.Random(args.seed)
        levels = []
        for name, lv, w, h, nm in TIERS:
            found, _ = gen_tier(name, lv, w, h, nm, rng, args.tries, log)
            if len(found) < PER_TIER:
                log("%s: 候補が%d問しか無い" % (name, len(found)))
                sys.exit(1)
            for f in pick(found, lv, w, h):
                levels.append(to_level(name, lv, w, h, f))
        # 全体で似すぎが無いか（同じ大きさどうし）
        with open(os.path.join(HERE, "levels.json"), "w", encoding="utf-8") as f:
            f.write("[\n" + ",\n".join("  " + json.dumps(l, ensure_ascii=False, separators=(",", ":")) for l in levels) + "\n]\n")
        check(levels, log)
    if args.embed:
        embed(args.embed, levels)
        log("埋め込み: %s" % args.embed)
    print(json.dumps({"n": len(levels)}))


if __name__ == "__main__":
    main()
