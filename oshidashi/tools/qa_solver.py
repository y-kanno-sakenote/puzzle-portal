# 担当: ✅ 検証係（マンガー×ファインマン）
"""おしだし v0.2（宝を順に回る）の独立ソルバー。spec.md v0.2 の規則だけから書いた。
gen_levels.py と index.html のロジックは読んでいない。Python 標準ライブラリのみ。

使い方:
  python3 qa_solver.py levels.json [--range 0-29] [--html index.html] [--noprune] [--rand 4000] [--jobs 8]
出力: 各問の実測と、spec の採用条件の合否、OVERALL。
注意: 上級は1問あたりメモリ約5GB・約4分。--jobs は3以下（既定3）。全40問は約6分。
上級は「3回に分けて拾う盤を半分以上」を取りやめ済み（中級だけ minpick=3 が5問以上を合否に使う）。初手の上限は上級10・他5。
「解の数>段の中央値×5」は範囲に段の10問が全部入っているときだけ判定される。
"""
import json, sys, re, random, statistics, argparse
from multiprocessing import Pool

N = 5
DIRS = {1: (-1, 0, 4), 2: (0, 1, 8), 4: (1, 0, 1), 8: (0, -1, 2)}  # 腕: (dr, dc, 相手の腕)
NEI = []
for i in range(N * N):
    r, c = divmod(i, N)
    lst = []
    for b, (dr, dc, ob) in DIRS.items():
        rr, cc = r + dr, c + dc
        if 0 <= rr < N and 0 <= cc < N:
            lst.append((b, rr * N + cc, ob))
    NEI.append(lst)

# 押し込み口 → 入口から出口へのマス列
LINES = []
for op in range(8):
    k, rev = divmod(op, 2)
    if k < 2:
        row = 1 + 2 * k
        line = [row * N + c for c in range(N)]
    else:
        col = 1 + 2 * (k - 2)
        line = [r * N + col for r in range(N)]
    if rev:
        line = line[::-1]
    LINES.append(line)
LINESET = [set(l) for l in LINES]
# 駒・宝の移り先
PMAP, TMAP = [], []
for op in range(8):
    L = LINES[op]
    pm = list(range(N * N))
    for k in range(N - 1):
        pm[L[k]] = L[k + 1]
    pm[L[-1]] = L[0]  # 駒は回り込む
    tm = dict((i, i) for i in range(N * N))
    for k in range(N - 1):
        tm[L[k]] = L[k + 1]
    tm[L[-1]] = -1  # 宝は手持ちへ
    tm[-1] = L[0]   # 手持ちの宝は入口へ
    PMAP.append(pm)
    TMAP.append(tm)
# 各押し込み列について「列の外から列へ腕を伸ばしているか」を見るためのマス集合
TOUCH = []
for op in range(8):
    s = LINESET[op]
    t = set(s)
    for i in range(N * N):
        if i in s:
            continue
        for b, j, ob in NEI[i]:
            if j in s:
                t.add(i)
    TOUCH.append(t)


def rot1(t):
    return ((t << 1) | (t >> 3)) & 15


def orients(t, rot):
    if not rot:
        return [t]
    out, x = [], t
    for _ in range(4):
        if x not in out:
            out.append(x)
        x = rot1(x)
    return out


def canon(t):
    return min(orients(t, 1))


def comp(cells, s):
    seen = {s}
    st = [s]
    while st:
        i = st.pop()
        ci = cells[i]
        for b, j, ob in NEI[i]:
            if ci & b and cells[j] & ob and j not in seen:
                seen.add(j)
                st.append(j)
    return seen


def touches(cset, cells, op):
    """成分 cset が押し込み列 op に入っている／腕を伸ばしているか"""
    s = LINESET[op]
    for i in cset:
        if i in s:
            return True
        ci = cells[i]
        for b, j, ob in NEI[i]:
            if ci & b and j in s:
                return True
    return False


def parse(lv):
    cells = bytes(int(ch, 16) for ch in lv["cells"])
    return (cells, int(lv["hand"], 16), lv["piece"], tuple(lv["tre"]), -1)


def push(state, op, h):
    """押し込み＋拾う。戻り値 (新局面, 拾った数, 未拾得の宝を押し出したか)"""
    cells, hand, piece, tre, ban = state
    L = LINES[op]
    nc = list(cells)
    for k in range(N - 1, 0, -1):
        nc[L[k]] = cells[L[k - 1]]
    nc[L[0]] = h
    nh = cells[L[-1]]
    npce = PMAP[op][piece]
    tm = TMAP[op]
    ntre = tuple(tm[t] for t in tre)
    ej = any(t == L[-1] for t in tre)
    nc = bytes(nc)
    picked = 0
    if ntre and ntre[0] != -1:
        cs = comp(nc, npce)
        while ntre and ntre[0] != -1 and ntre[0] in cs:
            npce = ntre[0]
            ntre = ntre[1:]
            picked += 1
    return (nc, nh, npce, ntre, op ^ 1), picked, ej


def key(state, rot):
    cells, hand, piece, tre, ban = state
    return (cells, canon(hand) if rot else hand, piece, tre, ban)


def moves(state, rot):
    cells, hand, piece, tre, ban = state
    for op in range(8):
        if op == ban:
            continue
        for h in orients(hand, rot):
            yield op, h


def last_ok(state, op, prune):
    """最後の1手で拾える可能性があるか（必要条件・プルーン）"""
    if not prune:
        return True
    cells, hand, piece, tre, ban = state
    cp = comp(cells, piece)
    if not touches(cp, cells, op):
        return False
    t = tre[0]
    if t != -1 and t not in LINESET[op]:
        ct = comp(cells, t)
        if not touches(ct, cells, op):
            return False
    return True


def solve(lv, maxd=8, rot=None, prune=True, full=True):
    """最短手数と、最短解の数・初手の数・拾う手の最小/最大・入れ直し解の数・解の1例"""
    if rot is None:
        rot = lv["rot"]
    s0 = parse(lv)
    # 初期で①とつながっていないか
    k0 = key(s0, rot)
    seen = {k0: 0}
    # layer: key -> [state, cnt, cnt_ej, minpk, maxpk, firstset, examplepath]
    layer = {k0: [s0, 1, 0, 0, 0, frozenset(), ()]}
    for d in range(1, maxd + 1):
        last = True  # 次の層で解けるか先に全部調べる
        sols = 0; solej = 0; firsts = set(); mnp = 99; mxp = 0; ex = None
        for k, (st, cnt, cej, mnk, mxk, fs, path) in layer.items():
            for op, h in moves(st, rot):
                if not last_ok(st, op, prune):
                    continue
                ns, pk, ej = push(st, op, h)
                if not ns[3]:
                    sols += cnt
                    solej += cej if not ej else cnt
                    firsts |= (fs if d > 1 else {(op, h)})
                    mnp = min(mnp, mnk + 1); mxp = max(mxp, mxk + 1)
                    if ex is None:
                        ex = path + ((op, h),)
        if sols:
            return dict(min=d, nsol=sols, firsts=len(firsts), minpick=mnp, maxpick=mxp, ej=solej,
                        sol=[list(m) for m in ex], states=len(seen))
        if d == maxd:
            break
        nl = {}
        for k, (st, cnt, cej, mnk, mxk, fs, path) in layer.items():
            for op, h in moves(st, rot):
                ns, pk, ej = push(st, op, h)
                if not ns[3]:
                    continue
                nk = key(ns, rot)
                if nk in seen and seen[nk] < d:
                    continue
                f2 = fs if d > 1 else frozenset([(op, h)])
                p1 = 1 if pk else 0
                e = cnt if ej else cej
                if nk in nl:
                    v = nl[nk]
                    v[1] += cnt; v[2] += e
                    v[3] = min(v[3], mnk + p1); v[4] = max(v[4], mxk + p1)
                    if full:
                        v[5] = v[5] | f2
                else:
                    seen[nk] = d
                    nl[nk] = [ns, cnt, e, mnk + p1, mxk + p1, f2, path + ((op, h),)]
        layer = nl
    return dict(min=None, states=len(seen))


def replay(lv, sol):
    st = parse(lv)
    segs, cnt = [], 0
    for op, h in sol:
        if op == st[4]:
            return None, "禁止口"
        if lv["rot"] == 0 and h != st[1]:
            return None, "入門で回転"
        if h not in orients(st[1], 1):
            return None, "形違い"
        st, pk, ej = push(st, op, h)
        cnt += 1
        if pk:
            segs.append(cnt); cnt = 0
            segs += [0] * (pk - 1)
    return (not st[3]), segs


def earliest(st, budget, rot):
    """st から次の宝を一番早く拾う押し込み数と、拾った直後の局面（同点は全部・同じ局面はまとめる）"""
    layer = {key(st, rot): st}
    seen = set(layer)
    for d in range(1, budget + 1):
        hits, nl = {}, {}
        for s in layer.values():
            for op, h in moves(s, rot):
                ns, pk, ej = push(s, op, h)
                k = key(ns, rot)
                if pk:
                    hits[k] = ns
                elif d < budget and k not in seen:
                    seen.add(k); nl[k] = ns
        if hits:
            return d, list(hits.values())
        layer = nl
    return None, []


def naive_perparent(lv, m):
    """親ごと：各局面から一番早く拾う手を全部たどる。m 手以内に全部拾えれば True"""
    rot = lv["rot"]
    s0 = parse(lv)
    front = {key(s0, rot): (s0, 0)}
    best = {}
    while front:
        nf = {}
        for k, (s, d) in front.items():
            dd, hs = earliest(s, m - d, rot)
            if dd is None:
                continue
            for ns in hs:
                if not ns[3]:
                    return True
                nk = key(ns, rot)
                if nk in best and best[nk] <= d + dd:
                    continue
                best[nk] = d + dd
                nf[nk] = (ns, d + dd)
        front = nf
    return False


def naive_global(lv, m):
    """全体：今の局面の集合から一番早く拾える手数で一斉に絞る"""
    rot = lv["rot"]
    s0 = parse(lv)
    front = [s0]; d = 0
    while front and d < m:
        layer = {key(s, rot): s for s in front}
        seen = set(layer)
        hits = {}
        for dd in range(1, m - d + 1):
            nl = {}
            for s in layer.values():
                for op, h in moves(s, rot):
                    ns, pk, ej = push(s, op, h)
                    k = key(ns, rot)
                    if pk:
                        hits[k] = ns
                    elif k not in seen:
                        seen.add(k); nl[k] = ns
            if hits:
                break
            layer = nl
        if not hits:
            return False
        d += dd
        if any(not s[3] for s in hits.values()):
            return True
        front = list(hits.values())
    return False


def random_rate(lv, runs, steps, seed=1):
    rnd = random.Random(seed)
    ok = 0
    for _ in range(runs):
        st = parse(lv)
        for _ in range(steps):
            ops = [o for o in range(8) if o != st[4]]
            op = rnd.choice(ops)
            h = st[1]
            if lv["rot"]:
                for _ in range(rnd.randrange(4)):
                    h = rot1(h)
            st, pk, ej = push(st, op, h)
            if not st[3]:
                ok += 1
                break
    return ok / runs


def analyze(args):
    i, lv, prune, runs = args
    r = solve(lv, prune=prune)
    out = dict(i=i, tier=lv["tier"], **{"my_" + k: v for k, v in r.items()})
    m = r["min"]
    s0 = parse(lv)
    out["start_linked"] = s0[3][0] in comp(s0[0], s0[2])
    ok, segs = replay(lv, lv["sol"])
    out["sol_ok"] = bool(ok) and len(lv["sol"]) == lv["min"]
    out["sol_seg"] = segs
    ok2, segs2 = replay(lv, r["sol"])
    out["mysol_ok"] = bool(ok2)
    out["mysol_seg"] = segs2
    if lv["rot"]:
        rr = solve(lv, maxd=m, rot=0, prune=prune, full=False)
        out["needrot"] = int(rr["min"] is None)
    else:
        out["needrot"] = 0
    out["naive_pp"] = naive_perparent(lv, m)
    out["naive_gl"] = naive_global(lv, m)
    out["rand"] = random_rate(lv, runs, 30)
    return out


# ---- 同型・似すぎ ----
def transforms():
    res = []
    for refl in (0, 1):
        for k in range(4):
            res.append((refl, k))
    return res


def tf_pos(p, refl, k):
    r, c = divmod(p, N)
    if refl:
        c = N - 1 - c
    for _ in range(k):
        r, c = c, N - 1 - r
    return r * N + c


def tf_tile(t, refl, k):
    if refl:
        t = (t & 5) | ((t & 2) << 2) | ((t & 8) >> 2)
    for _ in range(k):
        t = rot1(t)
    return t


def tf_level(lv, refl, k):
    cells = [0] * (N * N)
    for p, ch in enumerate(lv["cells"]):
        cells[tf_pos(p, refl, k)] = tf_tile(int(ch, 16), refl, k)
    h = tf_tile(int(lv["hand"], 16), refl, k)
    return (tuple(cells), canon(h) if lv["rot"] else h, tf_pos(lv["piece"], refl, k),
            tuple(tf_pos(t, refl, k) for t in lv["tre"]))


def sim(a, b):
    return sum(x == y for x, y in zip(a, b)) / len(a)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("levels")
    ap.add_argument("--range", default="0-39")
    ap.add_argument("--html")
    ap.add_argument("--noprune", action="store_true")
    ap.add_argument("--rand", type=int, default=4000)
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--json")
    a = ap.parse_args()
    D = json.load(open(a.levels))
    LV = D["levels"] if isinstance(D, dict) else D
    lo, hi = map(int, a.range.split("-"))
    idx = list(range(lo, hi + 1))
    fails = []
    if a.html:
        txt = open(a.html, encoding="utf-8").read()
        m = re.search(r"var LEVELS = (\[.*?\n\]);", txt, re.S)
        H = json.loads(m.group(1))
        diff = [i for i in idx if H[i] != LV[i]]
        print("index.html LEVELS == levels.json:", "一致" if not diff else f"不一致 {diff}")
        if diff:
            fails.append("html不一致")
    with Pool(a.jobs) as pool:
        res = pool.map(analyze, [(i, LV[i], not a.noprune, a.rand) for i in idx], chunksize=1)
    TB = {"入門": (2, 4, 5, 0), "初級": (2, 4, 5, 1), "中級": (3, 5, 5, 1), "上級": (3, 6, 6, 1)}
    bytier = {}
    for r in res:
        bytier.setdefault(r["tier"], []).append(r)
    for r in res:
        lv = LV[r["i"]]
        ntre, lo_, hi_, rot = TB[lv["tier"]]
        bad = []
        if r["my_min"] != lv["min"]: bad.append(f"min {r['my_min']}≠{lv['min']}")
        for k in ("nsol", "firsts", "ej", "minpick"):
            if k in lv and r["my_" + k] != lv[k]: bad.append(f"{k} {r['my_'+k]}≠{lv[k]}")
        if not r["sol_ok"]: bad.append("data sol が解けない")
        elif r["sol_seg"] != lv["seg"]: bad.append(f"seg {r['sol_seg']}≠{lv['seg']}")
        if r["start_linked"]: bad.append("初期で①とつながる")
        if not (lo_ <= r["my_min"] <= hi_): bad.append("帯外")
        if len(lv["tre"]) != ntre or lv["rot"] != rot: bad.append("宝数/回転")
        if r["naive_pp"]: bad.append("素直(親ごと)で届く")
        if r["my_minpick"] < 2: bad.append("拾う手1回")
        if rot and not r["needrot"]: bad.append("回さず解ける")
        if r["needrot"] != lv["needrot"]: bad.append("needrot不一致")
        fl = 10 if lv["tier"] == "上級" else 5
        if r["my_firsts"] > fl: bad.append(f"初手>{fl}")
        med = statistics.median(x["my_nsol"] for x in bytier[lv["tier"]])
        if len(bytier[lv["tier"]]) == 10 and r["my_nsol"] > 5 * med: bad.append("解の数>中央値×5")
        r["bad"] = bad
        if bad: fails.append(f"#{r['i']}:" + ",".join(bad))
        print(f"#{r['i']:2d} {r['tier']} min={r['my_min']} nsol={r['my_nsol']} firsts={r['my_firsts']} "
              f"minpick={r['my_minpick']} maxpick={r['my_maxpick']} ej={r['my_ej']} needrot={r['needrot']} "
              f"naive親ごと={int(r['naive_pp'])} naive全体={int(r['naive_gl'])} rand={r['rand']:.3f} "
              f"seg={r['sol_seg']} states={r['my_states']} {'OK' if not bad else 'NG '+','.join(bad)}")
    for t, rs in bytier.items():
        if t in ("中級", "上級") and len(rs) == 10:
            n3 = sum(r["my_minpick"] == 3 for r in rs)
            print(f"{t}: minpick=3 の問 {n3}/10" + ("（上級は半分以上の条件を取りやめ・合否に使わない）" if t == "上級" else ""))
            if t == "中級" and n3 < 5: fails.append(f"{t} minpick=3 が{n3}問")
    # 同型・似すぎ（範囲内の全組。範囲外とも照合）
    allidx = list(range(len(LV)))
    iso, close, maxsim = [], [], 0
    for i in idx:
        for j in allidx:
            if j == i or (j in idx and j < i):
                continue
            s = sim(LV[i]["cells"], LV[j]["cells"])
            maxsim = max(maxsim, s)
            if s > 0.5: close.append((i, j, s))
            base = tf_level(LV[j], 0, 0)
            for refl, k in transforms():
                tl = tf_level(LV[i], refl, k)
                if tl == base or tl[0] == base[0]:
                    iso.append((i, j, refl, k))
    print(f"同型 {len(iso)} 組 {iso[:5]}／同位置同タイル>0.5 {len(close)} 組 {close[:5]}／最大 {maxsim:.2f}")
    if iso: fails.append("同型あり")
    if close: fails.append("似すぎあり")
    # 段ごとの表
    print("段 | 最短 | 初手 | 解の数 | でたらめ30手の到達率(中央値・範囲)")
    for t, rs in bytier.items():
        f = lambda k: (min(r[k] for r in rs), max(r[k] for r in rs))
        rd = sorted(r["rand"] for r in rs)
        print(f"{t} | {f('my_min')} | {f('my_firsts')} | {f('my_nsol')} | {statistics.median(rd):.3f} ({rd[0]:.3f}〜{rd[-1]:.3f})")
        # 段の中の並び：spec の並べ方（最短昇順、同じなら初手・解の多い順）
        order = [r["i"] for r in sorted(rs, key=lambda r: (r["my_min"], -r["my_firsts"], -r["my_nsol"]))]
        print(f"  spec順で並べ直し {order} {'=データ順' if order == [r['i'] for r in rs] else '≠データ順'}")
        inv = sum(1 for a_ in range(len(rs)) for b_ in range(a_ + 1, len(rs)) if rs[a_]["rand"] < rs[b_]["rand"])
        print(f"  到達率で見た段内の逆転（前の問の方が届きにくい組）{inv}/{len(rs)*(len(rs)-1)//2}")
    if a.json:
        json.dump(res, open(a.json, "w"), ensure_ascii=False, indent=1)
    print("FAIL:", fails)
    print("OVERALL:", "PASS" if not fails else "FAIL")


if __name__ == "__main__":
    main()
