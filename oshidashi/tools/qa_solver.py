#!/usr/bin/env python3
"""おしだし 独立検証ソルバー（qa係・spec.md の規則だけから書いた別実装。gen_levels.py / index.html のロジックは読んでいない）
使い方: python3 qa_solver.py <oshidashi/tools/levels.json> [<oshidashi/index.html>] [--fast]
標準ライブラリのみ。全数列挙（深さ=最短手数まで）で 最短・解の数・初手の数 を出し、素直な手(a)(b)・打ち消し禁止なし・ランダム・データ整合を測る。
"""
import json, re, sys, random, itertools
from multiprocessing import Pool

N_, E_, S_, W_ = 1, 2, 4, 8
STRAIGHT = {5, 10}; CORNER = {3, 6, 12, 9}; TEE = {7, 14, 13, 11}

def rot(v): return ((v << 1) | (v >> 3)) & 15
def rots(v):
    out = []
    for _ in range(4):
        if v not in out: out.append(v)
        v = rot(v)
    return out
def canon(v): return min(rots(v))

def lines(n):  # op -> (kind, index, dir)  kind 'r'/'c', dir +1 = 左から/上から
    ops = []
    for k in range(1, n, 2): ops += [('r', k, +1), ('r', k, -1)]
    for k in range(1, n, 2): ops += [('c', k, +1), ('c', k, -1)]
    return ops

def push(n, cells, hand, piece, op):
    """cells: list of ints. 戻り値 (新cells, 押し出された1枚, 新piece)"""
    kind, k, d = lines(n)[op]
    idx = [k * n + c for c in range(n)] if kind == 'r' else [r * n + k for r in range(n)]
    seq = [cells[i] for i in idx]
    if d > 0: new = [hand] + seq[:-1]; out = seq[-1]
    else:     new = seq[1:] + [hand]; out = seq[0]
    nc = list(cells)
    for i, v in zip(idx, new): nc[i] = v
    np_ = piece
    if piece in idx:
        p = idx.index(piece)
        p2 = p + d
        if p2 >= n: p2 = 0
        if p2 < 0: p2 = n - 1
        np_ = idx[p2]
    return nc, out, np_

def reach(n, cells, start):
    seen = {start}; st = [start]
    while st:
        i = st.pop(); r, c = divmod(i, n); v = cells[i]
        if v & N_ and r > 0 and cells[i - n] & S_ and i - n not in seen: seen.add(i - n); st.append(i - n)
        if v & S_ and r < n - 1 and cells[i + n] & N_ and i + n not in seen: seen.add(i + n); st.append(i + n)
        if v & E_ and c < n - 1 and cells[i + 1] & W_ and i + 1 not in seen: seen.add(i + 1); st.append(i + 1)
        if v & W_ and c > 0 and cells[i - 1] & E_ and i - 1 not in seen: seen.add(i - 1); st.append(i - 1)
    return seen

def connected(n, cells, piece, goal):
    return goal in reach(n, cells, piece)

def parse(L):
    return L['n'], [int(ch, 16) for ch in L['cells']], int(L['hand'], 16), L['piece'], L['goal'], bool(L['rot'])

def moves(n, hand, forbidden, can_rot, allowed_ops=None):
    ops = range(len(lines(n))) if allowed_ops is None else allowed_ops
    hs = rots(hand) if can_rot else [hand]
    for op in ops:
        if op == forbidden: continue
        for h in hs: yield op, h

def enumerate_all(L, depth_max, ban=True, only_piece_lines=False):
    """全数列挙。戻り値: (最短 or None, 最短の解の数, 最短につながる初手集合)"""
    n, cells, hand, piece, goal, can_rot = parse(L)
    counts = {}; firsts = {}
    def piece_ops(p):
        r, c = divmod(p, n); ops = []
        for o, (kind, k, d) in enumerate(lines(n)):
            if (kind == 'r' and k == r) or (kind == 'c' and k == c): ops.append(o)
        return ops
    def dfs(cells, hand, piece, forb, depth, first):
        if depth == depth_max: return
        allowed = piece_ops(piece) if only_piece_lines else None
        for op, h in moves(n, hand, forb if ban else None, can_rot, allowed):
            nc, out, np_ = push(n, cells, h, piece, op)
            f = first if first is not None else (op, h)
            if connected(n, nc, np_, goal):
                counts[depth + 1] = counts.get(depth + 1, 0) + 1
                firsts.setdefault(depth + 1, set()).add(f)
                continue  # つながった時点でクリア（その先は数えない）
            dfs(nc, out, np_, op ^ 1, depth + 1, f)
    dfs(cells, hand, piece, None, 0, None)
    if not counts: return None, 0, set()
    m = min(counts)
    return m, counts[m], firsts[m]

def bfs_min(L, depth_max, ban=True):
    """重複除去つき幅優先（局面=盤・手持ち（回せる段は形）・駒・禁止口）。最短手数だけ返す"""
    n, cells, hand, piece, goal, can_rot = parse(L)
    key = lambda c, h, p, f: (bytes(c), canon(h) if can_rot else h, p, f if ban else None)
    frontier = [(cells, hand, piece, None)]; seen = {key(cells, hand, piece, None)}
    for d in range(1, depth_max + 1):
        nxt = []
        for c, h0, p, f in frontier:
            for op, h in moves(n, h0, f if ban else None, can_rot):
                nc, out, np_ = push(n, c, h, p, op)
                if connected(n, nc, np_, goal): return d, len(seen)
                k = key(nc, out, np_, op ^ 1)
                if k not in seen: seen.add(k); nxt.append((nc, out, np_, op ^ 1))
        frontier = nxt
    return None, len(seen)

def score(n, cells, piece, goal):
    gr, gc = divmod(goal, n)
    return min(abs(i // n - gr) + abs(i % n - gc) for i in reach(n, cells, piece))

def greedy_b(L, depth_max, cap=400):
    """素直な手(b): 毎手、駒から届く範囲とゴールの距離が一番小さくなる手を、同点は全部残して（最大cap局面）進める"""
    n, cells, hand, piece, goal, can_rot = parse(L)
    frontier = [(cells, hand, piece, None)]
    for d in range(1, depth_max + 1):
        best = None; kids = []
        for c, h0, p, f in frontier:
            for op, h in moves(n, h0, f, can_rot):
                nc, out, np_ = push(n, c, h, p, op)
                s = score(n, nc, np_, goal)
                if s == 0: return d
                if best is None or s < best: best = s; kids = [(nc, out, np_, op ^ 1)]
                elif s == best and len(kids) < cap: kids.append((nc, out, np_, op ^ 1))
        frontier = kids
    return None

def greedy_b_parent(L, depth_max, cap=300000):
    """(b)親ごとの読み（spec v0.1改）: 局面ごとに一番の手（同点は全部）を選び、全分岐を打ち切りなしで調べる。
    同じ局面はまとめる。cap局面を超えたら素直とみなす（戻り値 'cap'）"""
    n, cells, hand, piece, goal, can_rot = parse(L)
    key = lambda c, h, p, f: (bytes(c), canon(h) if can_rot else h, p, f)
    frontier = [(cells, hand, piece, None)]; seen = {key(cells, hand, piece, None)}
    for d in range(1, depth_max + 1):
        kids = []
        for c, h0, p, f in frontier:
            best = None; mine = []
            for op, h in moves(n, h0, f, can_rot):
                nc, out, np_ = push(n, c, h, p, op)
                s = score(n, nc, np_, goal)
                if s == 0: return d
                if best is None or s < best: best = s; mine = [(nc, out, np_, op ^ 1)]
                elif s == best: mine.append((nc, out, np_, op ^ 1))
            for k in mine:
                kk = key(*k)
                if kk not in seen: seen.add(kk); kids.append(k)
            if len(seen) > cap: return 'cap'
        frontier = kids
    return None

def random_play(L, steps, trials, seed):
    n, cells0, hand0, piece0, goal, can_rot = parse(L)
    rng = random.Random(seed); hit = [0] * (steps + 1)
    nops = len(lines(n))
    for _ in range(trials):
        cells, hand, piece, forb = cells0, hand0, piece0, None
        for t in range(1, steps + 1):
            op = rng.choice([o for o in range(nops) if o != forb])
            h = rng.choice(rots(hand)) if can_rot else hand
            cells, hand, piece = push(n, cells, h, piece, op); forb = op ^ 1
            if connected(n, cells, piece, goal): hit[t] += 1; break
    cum = list(itertools.accumulate(hit))
    return [x / trials for x in cum]

def replay(L, sol):
    n, cells, hand, piece, goal, can_rot = parse(L)
    forb = None
    for i, (op, h) in enumerate(sol):
        if op == forb: return f'禁止口を使用(手{i+1})'
        if (h not in rots(hand)) if can_rot else (h != hand): return f'手持ちと違う向き(手{i+1}: {h} vs {hand})'
        cells, hand, piece = push(n, cells, h, piece, op); forb = op ^ 1
        if connected(n, cells, piece, goal): return 'OK' if i == len(sol) - 1 else f'早すぎるクリア(手{i+1})'
    return 'つながらない'

def check_one(args):
    idx, L, fast = args
    m = L['min']; res = {'i': idx, 'tier': L['tier'], 'min_data': m, 'firsts_data': L['firsts']}
    n, cells, hand, piece, goal, can_rot = parse(L)
    res['start_connected'] = connected(n, cells, piece, goal)
    res['replay'] = replay(L, L['sol'])
    mm, cnt, fs = enumerate_all(L, m)
    res.update(min_enum=mm, nsol=cnt, firsts=len(fs))
    res['min_bfs'] = bfs_min(L, m)[0]
    res['noban_min'] = enumerate_all(L, m - 1, ban=False)[0] if m > 1 else None  # None=縮まない
    res['naive_a'] = enumerate_all(L, m, only_piece_lines=True)[0]
    res['naive_b'] = greedy_b(L, m)
    res['naive_b2'] = greedy_b_parent(L, m)
    if L['rot']:
        L0 = dict(L); L0['rot'] = 0
        res['norot_min'] = bfs_min(L0, m)[0]  # None=回さないと最短で届かない
    if not fast:
        res['rand'] = random_play(L, 30, 4000, 1000 + idx)
    return res

def tsym(v, k, mirror):
    if mirror: v = (v & (N_ | S_)) | (E_ if v & W_ else 0) | (W_ if v & E_ else 0)
    for _ in range(k): v = rot(v)
    return v

def sym_variants(n, cells):
    out = []
    for mirror in (False, True):
        for k in range(4):
            g = [0] * (n * n)
            for i, v in enumerate(cells):
                r, c = divmod(i, n)
                if mirror: c = n - 1 - c
                for _ in range(k): r, c = c, n - 1 - r
                g[r * n + c] = tsym(v, k, mirror)
            out.append(g)
    return out

def data_checks(levels):
    errs = []
    for i, L in enumerate(levels):
        n = L['n']
        if n not in (5, 7) or len(L['cells']) != n * n: errs.append(f'{i}: 盤サイズ')
        exp_n = 5 if L['tier'] in ('入門', '初級') else 7
        if n != exp_n: errs.append(f'{i}: 段と盤が不一致')
        if L['rot'] != (0 if L['tier'] == '入門' else 1): errs.append(f'{i}: rot')
        for ch in L['cells'] + L['hand']:
            if int(ch, 16) not in STRAIGHT | CORNER | TEE: errs.append(f'{i}: タイル種 {ch}')
        gr, gc = divmod(L['goal'], n); pr, pc = divmod(L['piece'], n)
        if gr % 2 or gc % 2: errs.append(f'{i}: ゴールが動くマス')
        if pr % 2 == 0 and pc % 2 == 0: errs.append(f'{i}: 駒が動かないマス')
        if len(L['sol']) != L['min']: errs.append(f'{i}: sol長')
    sims = []; symdup = []
    for i, j in itertools.combinations(range(len(levels)), 2):
        a, b = levels[i], levels[j]
        if a['n'] != b['n']: continue
        s = sum(x == y for x, y in zip(a['cells'], b['cells'])) / len(a['cells'])
        sims.append((s, i, j))
        bc = [int(ch, 16) for ch in b['cells']]
        for g in sym_variants(a['n'], [int(ch, 16) for ch in a['cells']]):
            s2 = sum(x == y for x, y in zip(g, bc)) / len(bc)
            if s2 > 0.5: symdup.append((round(s2, 2), i, j))
    return errs, max(sims), symdup

def html_levels(path):
    t = open(path, encoding='utf-8').read()
    m = re.search(r'LEVELS-BEGIN.*?\n(.*?)/\* LEVELS-END', t, re.S).group(1)
    body = m[m.index('['):m.rindex(']') + 1]
    return json.loads(body)

if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]; fast = '--fast' in sys.argv
    levels = json.load(open(args[0], encoding='utf-8'))['levels']
    if len(args) > 1:
        print('HTML埋め込みとlevels.json一致:', html_levels(args[1]) == levels)
    errs, maxsim, symdup = data_checks(levels)
    print('データ整合エラー:', errs or 'なし', '／同大きさ最大一致率', maxsim, '／対称変換で0.5超', symdup or 'なし')
    with Pool() as pool:
        rs = pool.map(check_one, [(i, L, fast) for i, L in enumerate(levels)])
    json.dump(rs, open('qa_result.json', 'w'), ensure_ascii=False, indent=0)
    import statistics
    med = {t: statistics.median(r['nsol'] for r in rs if r['tier'] == t) for t in {r['tier'] for r in rs}}
    order_bad = []
    for a, b in zip(rs, rs[1:]):
        if a['tier'] != b['tier']: continue
        ka = (a['min_enum'], -a['firsts'], -a['nsol']); kb = (b['min_enum'], -b['firsts'], -b['nsol'])
        if kb < ka: order_bad.append(f"#{a['i']+1}->#{b['i']+1}")
    print('段の中の並び（最短昇順・同じなら初手/解の多い順）の逆転:', order_bad or 'なし')
    bad = 0
    for r in rs:
        flags = []
        if r['firsts'] > 5: flags.append(f"初手{r['firsts']}>5")
        if r['nsol'] > 5 * med[r['tier']]: flags.append(f"解{r['nsol']}>中央値{med[r['tier']]}x5")
        if 'norot_min' in r and r['norot_min'] is not None: flags.append(f"回さず{r['norot_min']}手")
        if r['start_connected']: flags.append('最初からつながる')
        if r['replay'] != 'OK': flags.append('sol再生:' + r['replay'])
        if r['min_enum'] != r['min_data'] or r['min_bfs'] != r['min_data']: flags.append(f"最短不一致 enum={r['min_enum']} bfs={r['min_bfs']}")
        if r['firsts'] != r['firsts_data']: flags.append(f"firsts不一致 {r['firsts']}")
        if r['noban_min'] is not None: flags.append(f"禁止なしで{r['noban_min']}手")
        if r['naive_a'] is not None: flags.append(f"素直(a)で{r['naive_a']}手")
        if r['naive_b'] is not None: flags.append(f"素直(b)で{r['naive_b']}手")
        if r['naive_b2'] is not None: flags.append(f"素直(b親ごと)で{r['naive_b2']}手")
        bad += bool(flags)
        rd = r.get('rand')
        rtxt = f" rand≤min={rd[r['min_data']]:.3f} ≤10={rd[10]:.3f} ≤30={rd[30]:.3f}" if rd else ''
        print(f"#{r['i']+1:2d} {r['tier']} min={r['min_data']} 解={r['nsol']} 初手={r['firsts']}{rtxt} {' '.join(flags) or 'OK'}")
    print('問題あり', bad, '/', len(rs))
    ok = bad == 0 and not order_bad and not errs and not symdup and maxsim[0] <= 0.5 and (len(args) < 2 or html_levels(args[1]) == levels)
    print('OVERALL', 'PASS' if ok else 'FAIL')
    sys.exit(0 if ok else 1)
