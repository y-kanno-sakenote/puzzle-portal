#!/usr/bin/env python3
"""にげこみ 独立検証ソルバー（qa係・2026-10-02）。標準ライブラリのみ。
実装者のコード（gen_levels.py / index.html のロジック）を読まずに docs/spec.md の規則だけから書いた。

使い方: python3 qa_solver.py [levels.json] [index.html] [--json out.json]
検証項目:
  1 解ける・最短手数一致   2 鬼の候補が全到達局面で一意   3 素直な最短路は全部負け
  4 段の分布・地図の類似(Jaccard 左右反転込み)・難易度指標・上級の鬼の重なり
  5 線の交差・点の上を通る線・線の長さ・点と線の近さ
  埋め込み一致: index.html の LEVELS と levels.json が同一か
規則の解釈（spec §規則）:
  あなた: 隣へ必ず1歩 → 🏠なら勝ち（🏠に鬼がいても勝ち＝spec 2026-10-02 訂正。逆順でも解いて最短が変わらないか比べる）
  → 鬼の点なら負け → 各鬼が「あなたまでの道のり(線の本数)」最小の隣へ1歩 → 重なったら負け
"""
import json, sys, math, re, itertools
from collections import deque

def load_levels(path):
    return json.load(open(path, encoding='utf-8'))

def embedded_levels(html_path):
    s = open(html_path, encoding='utf-8').read()
    m = re.search(r'var LEVELS = (\[.*?\]);\s*/\* LEVELS-END', s, re.S)
    return json.loads(m.group(1)) if m else None

class Map:
    def __init__(self, lv):
        self.P = [tuple(p) for p in lv['nodes']]
        n = len(self.P)
        self.adj = [[] for _ in range(n)]
        for a, b in lv['edges']:
            self.adj[a].append(b); self.adj[b].append(a)
        self.dist = [self._bfs(s) for s in range(n)]
        self.home = lv['home']
    def _bfs(self, s):
        d = [None] * len(self.P); d[s] = 0; q = deque([s])
        while q:
            u = q.popleft()
            for w in self.adj[u]:
                if d[w] is None: d[w] = d[u] + 1; q.append(w)
        return d
    def oni_cands(self, o, you):
        best = min(self.dist[w][you] for w in self.adj[o])
        return [w for w in self.adj[o] if self.dist[w][you] == best]
    def clock_pick(self, o, cands):
        # 保険の決めごと: 鬼から見て12時から時計回り（画面は y 下向き）
        ox, oy = self.P[o]
        def ang(w):
            x, y = self.P[w]; return math.atan2(x - ox, -(y - oy)) % (2 * math.pi)
        return min(cands, key=ang)

def step(m, state, v, home_win=True, ties=None):
    """state=(you, onis tuple 鬼ごとの順序を保持)。戻り値 ('win'|'lose'|'go', newstate)"""
    you, onis = state
    if home_win and v == m.home: return 'win', None
    if v in onis: return 'lose', None
    if v == m.home: return 'win', None
    new = []
    for o in onis:
        c = m.oni_cands(o, v)
        if len(c) > 1:
            if ties is not None: ties.append((you, onis, v, o, tuple(c)))
            c = [m.clock_pick(o, c)]
        new.append(c[0])
    if v in new: return 'lose', None
    return 'go', (v, tuple(new))

def explore(lv, home_win=True):
    m = Map(lv)
    s0 = (lv['you'], tuple(o[0] for o in lv['onis']))
    seen = {s0: 0}; par = {s0: None}; q = deque([s0]); ties = []
    edges = {}; win_moves = {}; best = None; nonterm_oni_moves = 0
    while q:
        s = q.popleft(); edges[s] = []; win_moves[s] = []
        for v in m.adj[s[0]]:
            r, ns = step(m, s, v, home_win, ties)
            if r == 'go':
                nonterm_oni_moves += 1
                edges[s].append((v, ns))
                if ns not in seen:
                    seen[ns] = seen[s] + 1; par[ns] = s; q.append(ns)
            elif r == 'win':
                win_moves[s].append(v)
                if best is None: best = seen[s] + 1
    # 残り手数（勝ちまで）: 逆向きBFS
    dtw = {s: 1 for s in seen if win_moves[s]}
    rev = {}
    for s, es in edges.items():
        for v, ns in es: rev.setdefault(ns, []).append(s)
    q = deque(dtw)
    while q:
        s = q.popleft()
        for p in rev.get(s, []):
            if p not in dtw: dtw[p] = dtw[s] + 1; q.append(p)
    return dict(m=m, s0=s0, seen=seen, edges=edges, win_moves=win_moves, best=best,
                dtw=dtw, ties=ties, oni_moves=nonterm_oni_moves)

def optimal_lines(ex, limit=200000):
    """最短解（手順＋各手後の鬼の位置）をすべて列挙"""
    out = []
    def rec(s, path):
        if len(out) >= limit: return
        d = ex['dtw'].get(s)
        if d == 1:
            for v in ex['win_moves'][s]: out.append(path + [(v, None)])
            return
        for v, ns in ex['edges'][s]:
            if ex['dtw'].get(ns) == d - 1: rec(ns, path + [(v, ns[1])])
    rec(ex['s0'], [])
    return out

def straight_paths(m, a, b):
    d = m.dist[b]; out = []
    def rec(u, p):
        if u == b: out.append(p); return
        for w in m.adj[u]:
            if d[w] == d[u] - 1: rec(w, p + [w])
    rec(a, [])
    return out

def play_path(m, s0, path, home_win=True):
    s = s0
    for i, v in enumerate(path):
        r, s = step(m, s, v, home_win)
        if r != 'go': return r, i + 1
    return 'unfinished', len(path)

def win_rate_horizon(ex, horizon=40):
    """spec の勝率: 即死しない手から等確率（🏠へ入る手も1候補）、安全な手が無ければ負け、horizon 手以内に🏠"""
    opts = {s: [('win', None)] * len(ex['win_moves'][s]) + [('go', ns) for _, ns in ex['edges'][s]] for s in ex['seen']}
    V = {s: 0.0 for s in ex['seen']}
    for _ in range(horizon):
        V = {s: (sum(1.0 if r == 'win' else V[ns] for r, ns in o) / len(o) if o else 0.0) for s, o in opts.items()}
    return V[ex['s0']]

def win_prob_safe_random(ex, iters=3000):
    """即死の手だけ避けて残りから一様ランダムに選ぶ遊び手の勝率（吸収マルコフ連鎖の反復）"""
    m = ex['m']; V = {s: 0.0 for s in ex['seen']}
    opts = {}
    for s in ex['seen']:
        safe = [('win', None)] * len(ex['win_moves'][s]) + [('go', ns) for _, ns in ex['edges'][s]]
        opts[s] = safe
    for _ in range(iters):
        delta = 0
        for s, o in opts.items():
            if not o: nv = 0.0
            else: nv = sum(1.0 if r == 'win' else V[ns] for r, ns in o) / len(o)
            delta = max(delta, abs(nv - V[s])); V[s] = nv
        if delta < 1e-12: break
    return V[ex['s0']]

# ---- 地図の幾何 ----
def seg_cross(p1, p2, p3, p4):
    def orient(a, b, c): return (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])
    def onseg(a, b, c): return min(a[0],b[0]) <= c[0] <= max(a[0],b[0]) and min(a[1],b[1]) <= c[1] <= max(a[1],b[1])
    d1, d2, d3, d4 = orient(p3,p4,p1), orient(p3,p4,p2), orient(p1,p2,p3), orient(p1,p2,p4)
    if ((d1 > 0) != (d2 > 0)) and d1 and d2 and ((d3 > 0) != (d4 > 0)) and d3 and d4: return True
    if d1 == 0 and onseg(p3,p4,p1): return True
    if d2 == 0 and onseg(p3,p4,p2): return True
    if d3 == 0 and onseg(p1,p2,p3): return True
    if d4 == 0 and onseg(p1,p2,p4): return True
    return False

def pt_seg_dist(p, a, b):
    ax, ay = a; bx, by = b; px, py = p
    dx, dy = bx-ax, by-ay; L = dx*dx + dy*dy
    t = max(0, min(1, ((px-ax)*dx + (py-ay)*dy) / L))
    return math.hypot(px - (ax + t*dx), py - (ay + t*dy))

def geometry(lv):
    P = [tuple(p) for p in lv['nodes']]; E = lv['edges']; bad = []
    if len(set(P)) != len(P): bad.append('点の重複')
    for x, y in P:
        if not (0 <= x <= 3 and 0 <= y <= 5): bad.append(f'格子外 {x},{y}')
    for a, b in E:
        if abs(P[a][0]-P[b][0]) > 2 or abs(P[a][1]-P[b][1]) > 2: bad.append(f'長い線 {a}-{b}')
    if len({tuple(sorted(e)) for e in E}) != len(E): bad.append('線の重複')
    for (a, b), (c, d) in itertools.combinations(E, 2):
        if len({a, b, c, d}) < 4: continue
        if seg_cross(P[a], P[b], P[c], P[d]): bad.append(f'交差 {a}-{b} x {c}-{d}')
    mind = 9
    for (a, b) in E:
        for k, p in enumerate(P):
            if k in (a, b): continue
            dd = pt_seg_dist(p, P[a], P[b])
            if dd < 1e-9: bad.append(f'点{k}が線{a}-{b}の上')
            mind = min(mind, dd)
    # 共有端点の2本の線のなす角の最小（重なって見えるか）
    minang = 180
    for u in range(len(P)):
        nb = [b if a == u else a for a, b in E if u in (a, b)]
        for v, w in itertools.combinations(nb, 2):
            a1 = math.atan2(P[v][1]-P[u][1], P[v][0]-P[u][0]); a2 = math.atan2(P[w][1]-P[u][1], P[w][0]-P[u][0])
            ang = abs(math.degrees(a1 - a2)) % 360; ang = min(ang, 360 - ang); minang = min(minang, ang)
    # 連結
    m = Map(lv)
    if any(d is None for d in m.dist[0]): bad.append('非連結')
    return bad, mind, minang

def edge_set(lv, f=lambda x, y: (x, y)):
    P = lv['nodes']
    return {tuple(sorted((f(*P[a]), f(*P[b])))) for a, b in lv['edges']}

def jacc(A, B): return len(A & B) / len(A | B)

def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    lvp = args[0] if args else 'tools/levels.json'
    htp = args[1] if len(args) > 1 else 'index.html'
    L = load_levels(lvp); E = embedded_levels(htp)
    res = {'embed_equal': E == L, 'n': len(L)}
    print(f'levels={len(L)} embed_equal={E == L}')
    fails = []
    rows = []
    for i, lv in enumerate(L):
        if any(o[1] != 1 for o in lv['onis']): fails.append(f'#{i} 鬼の速さ!=1 {lv["onis"]}')
        ex = explore(lv); exB = explore(lv, home_win=False)
        m = ex['m']
        if ex['best'] != lv['min']: fails.append(f'#{i} 最短 自前{ex["best"]} != データ{lv["min"]}')
        if exB['best'] != ex['best']: fails.append(f'#{i} 🏠に鬼の解釈で最短が変わる A={ex["best"]} B={exB["best"]}')
        if ex['ties']: fails.append(f'#{i} 同点 {len(ex["ties"])}件 例 you{ex["ties"][0][0]} onis{ex["ties"][0][1]} 行先{ex["ties"][0][2]} 鬼{ex["ties"][0][3]} 候補{ex["ties"][0][4]}')
        sp = straight_paths(m, lv['you'], lv['home'])
        sres = [play_path(m, ex['s0'], p) for p in sp]
        if any(r != 'lose' for r, _ in sres): fails.append(f'#{i} 素直な道で負けない {[(p, r) for p, (r, _) in zip(sp, sres) if r != "lose"]}')
        lines = optimal_lines(ex)
        merge = None
        if len(lv['onis']) == 2:
            ms = []
            for ln in lines:
                st = next((k + 1 for k, (v, on) in enumerate(ln) if on and on[0] == on[1]), None)
                ms.append(st)
            merge = dict(n_lines=len(lines), n_merge=sum(x is not None for x in ms),
                         earliest=min([x for x in ms if x], default=None),
                         latest=max([x for x in ms if x], default=None))
        if merge is not None:
            solo = [explore(dict(lv, onis=[o]))['best'] for o in lv['onis']]
            if not all(x is None or x < ex['best'] for x in solo): fails.append(f'#{i} (a)鬼を外しても縮まない solo={solo} min={ex["best"]}')
            if merge['n_merge']: fails.append(f'#{i} (b)最短解で重なる {merge}')
        first_win = sum(1 for v, ns in ex['edges'][ex['s0']] if ns in ex['dtw']) + len(ex['win_moves'][ex['s0']])
        bad, mind, minang = geometry(lv)
        if bad: fails.append(f'#{i} 幾何 {bad}')
        row = dict(i=i, tier=lv['tier'], onis=len(lv['onis']), min=ex['best'], dist=m.dist[lv['you']][lv['home']],
                   detour=ex['best'] - m.dist[lv['you']][lv['home']], states=len(ex['seen']),
                   oni_moves=ex['oni_moves'], ties=len(ex['ties']), straight=len(sp),
                   straight_caught_at=[k for _, k in sres], first_win=f'{first_win}/{len(m.adj[lv["you"]])}',
                   n_opt=len(lines), p_safe=round(win_prob_safe_random(ex), 3), rate40=round(win_rate_horizon(ex), 4),
                   rate_data=lv.get('rate'), solo=[explore(dict(lv, onis=[o]))['best'] for o in lv['onis']] if len(lv['onis']) == 2 else None,
                   oni0_dist=min(m.dist[o[0]][lv['you']] for o in lv['onis']),
                   min_pt_edge=round(mind, 3), min_angle=round(minang, 1), merge=merge)
        rows.append(row)
    # 類似
    sims = []
    for i, j in itertools.combinations(range(len(L)), 2):
        A = edge_set(L[i]); B = edge_set(L[j]); Bm = edge_set(L[j], lambda x, y: (3 - x, y))
        Bv = edge_set(L[j], lambda x, y: (x, 5 - y)); Br = edge_set(L[j], lambda x, y: (3 - x, 5 - y))
        sims.append((round(max(jacc(A, B), jacc(A, Bm)), 3), round(max(jacc(A, Bv), jacc(A, Br)), 3), i, j))
    sims.sort(reverse=True)
    res.update(rows=rows, fails=fails, top_sim_lr=sims[:5],
               top_sim_ud=sorted(sims, key=lambda t: -t[1])[:5])
    for r in rows: print(r)
    print('top Jaccard (同一/左右反転):', sims[:5])
    print('top Jaccard (上下反転/180度):', res['top_sim_ud'])
    print('FAILS:', len(fails)); [print(' ', f) for f in fails]
    if '--json' in sys.argv:
        json.dump(res, open(sys.argv[sys.argv.index('--json') + 1], 'w'), ensure_ascii=False, indent=1)
    print('OVERALL', 'PASS' if not fails and res['embed_equal'] else 'FAIL')

if __name__ == '__main__':
    main()
