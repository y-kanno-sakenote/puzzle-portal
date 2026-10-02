#!/usr/bin/env python3
"""にげこみ 独立検証ソルバー（qa係・2026-10-02）。標準ライブラリのみ。
実装者のコード（gen_levels.py / index.html のロジック）を読まずに docs/spec.md の規則だけから書いた。

使い方: python3 qa_solver.py [levels.json] [index.html] [--json out.json]
検証項目（spec 2026-10-02「全部の線に役目がある」版に合わせる）:
  1 解ける・最短手数一致   2 鬼の候補が全到達局面で一意   3 素直な最短路は全部負け
  4 段: 最短手数の条件・勝率(40手以内・即死回避ランダム)の帯と rate 一致・段の中は勝率降順・段どうしの逆転0
    地図の類似(Jaccard 左右反転込み ≤0.5)・最初の鬼は道のり2以上
  5 上級: (a) どちらの鬼を外しても最短が縮む (b) 最短解のすべての筋で2体が重ならない
  6 線の交差・点の上を通る線・線の長さ・連結
  7 いらない線0本（spec 2026-10-02 改訂）: いらない線＝消しても (1)最短手数 (2)素直な道は全部負け (3)同点0
    (4)上級(a)(b)＋連結＋判定順を逆にしても最短が同じ、が保たれ、かつ最短の筋の上の罠の手の数が減らない線
    （旧定義＝(1)〜(4)だけ、の本数も参考に出す）
  8 罠と読みどころ: 罠の手＝すぐ捕まらないのに勝てない局面へ落ちる手。罠の手の数＝最短の筋に乗る全局面の罠の合計。
    読みどころ＝筋の上で罠のある手番の数（筋が複数なら最小）。下限 入門1/初級2/中級3/上級4、初級以上は初手2通り以上
    罠の型（参考）: 枝＝行き止まりの枝へ入る／家側＝家のある側へ橋を渡る(早まる)／戻り＝家と反対側へ橋を戻る／輪＝輪の上の線
  9 同じ問題の描き直し: 駒・家の位置込みでグラフ同型な問題の組（鬼の動きは道のりだけで決まり同点も無いので、
    同型なら遊びとして同じ問題。座標の Jaccard では見つからない）
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

TIERS = {  # spec §段: (鬼, 最短の下限, 最短の上限, 勝率の下限, 下限を含む, 勝率の上限, 上限を含む)
    '入門': (1, 4, 6, 0.35, True, 0.75, True),
    '初級': (1, 6, 9, 0.15, True, 0.35, False),
    '中級': (1, 8, 99, 0.06, True, 0.15, False),
    '上級': (2, 8, 99, 0.0, True, 0.06, False),
}

def problem_ok(lv, ref_min):
    """spec「問題が変わらない」の (1)〜(4)＋連結。崩れた理由の一覧を返す（空なら問題は変わらない）"""
    m = Map(lv); why = []
    if any(d is None for d in m.dist[0]): return ['非連結']
    ex = explore(lv)
    if ex['best'] != ref_min: why.append(f"(1)最短{ex['best']}")
    if ex['best'] is None: return why
    if explore(lv, home_win=False)['best'] != ex['best']: why.append('判定順で最短が変わる')
    for p in straight_paths(m, lv['you'], lv['home']):
        if play_path(m, ex['s0'], p)[0] != 'lose': why.append('(2)素直な道で勝てる'); break
    if ex['ties']: why.append('(3)同点')
    if len(lv['onis']) == 2:
        solo = [explore(dict(lv, onis=[o]))['best'] for o in lv['onis']]
        if not all(x is not None and x < ex['best'] for x in solo): why.append(f'(4a)solo{solo}')
        if any(any(on and on[0] == on[1] for _, on in ln) for ln in optimal_lines(ex)): why.append('(4b)重なる')
    return why

def remove_edge(lv, k):
    """線 k を消し、孤立した点は点ごと消す。駒・家の点が孤立したら None"""
    E = [e for j, e in enumerate(lv['edges']) if j != k]
    deg = [0] * len(lv['nodes'])
    for a, b in E: deg[a] += 1; deg[b] += 1
    keep = [i for i in range(len(lv['nodes'])) if deg[i] > 0]
    special = {lv['you'], lv['home']} | {o[0] for o in lv['onis']}
    if any(deg[i] == 0 for i in special): return None
    idx = {old: new for new, old in enumerate(keep)}
    return dict(lv, nodes=[lv['nodes'][i] for i in keep], edges=[[idx[a], idx[b]] for a, b in E],
                you=idx[lv['you']], home=idx[lv['home']], onis=[[idx[o[0]], o[1]] for o in lv['onis']])

def bridges_side(m, home):
    """各有向辺 (u,v) について: 橋でなければ 'ring'。橋なら v 側に家があれば 'home'、無ければ枝(v側が木)か 'back'"""
    n = len(m.adj); kind = {}
    for u in range(n):
        for v in m.adj[u]:
            seen = {v}; st = [v]
            while st:
                x = st.pop()
                for y in m.adj[x]:
                    if (x, y) in ((v, u), (u, v)) or y in seen: continue
                    seen.add(y); st.append(y)
            if u in seen: kind[(u, v)] = 'ring'; continue
            if home in seen: kind[(u, v)] = 'home'; continue
            nv = len(seen); ne = sum(len(m.adj[x]) for x in seen) // 2
            kind[(u, v)] = 'branch' if ne == nv - 1 else 'back'   # v側が木＝行き止まりの枝
    return kind

def trap_info(ex):
    """spec §罠の手と読みどころ。戻り値 (罠の手の数, 読みどころ, [(局面, 行き先)...])"""
    best = ex['best']
    if best is None: return 0, 0, []
    on = [s for s in ex['seen'] if s in ex['dtw'] and ex['seen'][s] + ex['dtw'][s] == best]
    traps = [(s, v) for s in on for v, ns in ex['edges'][s] if ns not in ex['dtw']]
    has = {s: any(ns not in ex['dtw'] for _, ns in ex['edges'][s]) for s in on}
    memo = {}
    def f(s):
        if s in memo: return memo[s]
        d = ex['dtw'][s]
        r = int(has[s]) + (0 if d == 1 else min(f(ns) for _, ns in ex['edges'][s] if ex['dtw'].get(ns) == d - 1))
        memo[s] = r; return r
    return len(traps), f(ex['s0']), traps

def removable_edges(lv, new_def=True):
    """いらない線の一覧。new_def=False は旧定義（(1)〜(4) だけ）"""
    out = []; base = trap_info(explore(lv))[0]
    for k in range(len(lv['edges'])):
        nl = remove_edge(lv, k)
        if nl is None or problem_ok(nl, lv['min']): continue
        if new_def and trap_info(explore(nl))[0] < base: continue
        out.append(lv['edges'][k])
    return out

def _labels(lv):
    lab = ['.'] * len(lv['nodes']); lab[lv['you']] = 'Y'; lab[lv['home']] = 'H'
    for o in lv['onis']: lab[o[0]] += 'O'
    return lab

def isomorphic(a, b):
    """駒・家の役割つきのグラフ同型（バックトラック）"""
    if len(a['nodes']) != len(b['nodes']) or len(a['edges']) != len(b['edges']): return False
    ma, mb = Map(a), Map(b); la, lb = _labels(a), _labels(b); n = len(a['nodes'])
    sa = [(la[v], len(ma.adj[v]), tuple(sorted(ma.dist[v]))) for v in range(n)]
    sb = [(lb[v], len(mb.adj[v]), tuple(sorted(mb.dist[v]))) for v in range(n)]
    if sorted(sa) != sorted(sb): return False
    order = sorted(range(n), key=lambda v: -len(ma.adj[v])); mp = {}; used = set()
    def rec(k):
        if k == n: return True
        v = order[k]
        for w in range(n):
            if w in used or sa[v] != sb[w]: continue
            if all((mp[u] in mb.adj[w]) == (u in ma.adj[v]) for u in mp):
                mp[v] = w; used.add(w)
                if rec(k + 1): return True
                del mp[v]; used.discard(w)
        return False
    return rec(0)

def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    lvp = args[0] if args else 'tools/levels.json'
    htp = args[1] if len(args) > 1 else 'index.html'
    L = load_levels(lvp); E = embedded_levels(htp)
    res = {'embed_equal': E == L, 'n': len(L)}
    print(f'levels={len(L)} embed_equal={E == L}')
    fails = []; rows = []
    if E != L: fails.append('埋め込み不一致')
    for i, lv in enumerate(L):
        if any(o[1] != 1 for o in lv['onis']): fails.append(f'#{i} 鬼の歩数!=1 {lv["onis"]}')
        ex = explore(lv); exB = explore(lv, home_win=False); m = ex['m']
        if ex['best'] != lv['min']: fails.append(f'#{i} 最短 自前{ex["best"]} != データ{lv["min"]}')
        if exB['best'] != ex['best']: fails.append(f'#{i} 判定順を逆にすると最短が変わる 家先={ex["best"]} 鬼先={exB["best"]}')
        if ex['ties']: fails.append(f'#{i} 同点 {len(ex["ties"])}件 例 {ex["ties"][0]}')
        sp = straight_paths(m, lv['you'], lv['home'])
        sres = [play_path(m, ex['s0'], p) for p in sp]
        if any(r != 'lose' for r, _ in sres): fails.append(f'#{i} 素直な道で負けない')
        lines = optimal_lines(ex); merge = solo = None
        if len(lv['onis']) == 2:
            solo = [explore(dict(lv, onis=[o]))['best'] for o in lv['onis']]
            if not all(x is not None and x < ex['best'] for x in solo): fails.append(f'#{i} (a) 鬼を外しても縮まない solo={solo}')
            merge = sum(1 for ln in lines if any(on and on[0] == on[1] for _, on in ln))
            if merge: fails.append(f'#{i} (b) 最短解 {merge}/{len(lines)} 筋で重なる')
        rate = win_rate_horizon(ex)
        if lv.get('rate') is None or abs(rate - lv['rate']) > 5e-5: fails.append(f'#{i} 勝率 自前{rate:.4f} != データ{lv.get("rate")}')
        t = TIERS.get(lv['tier'])
        if t is None: fails.append(f'#{i} 段名 {lv["tier"]}')
        else:
            no, lo, hi, rlo, rloi, rhi, rhii = t
            if len(lv['onis']) != no: fails.append(f'#{i} 鬼の数')
            if not (lo <= ex['best'] <= hi): fails.append(f'#{i} 最短{ex["best"]}が段の条件外')
            if not ((rate >= rlo if rloi else rate > rlo) and (rate <= rhi if rhii else rate < rhi)): fails.append(f'#{i} 勝率{rate:.4f}が帯の外')
        oni0 = min(m.dist[o[0]][lv['you']] for o in lv['onis'])
        if oni0 < 2: fails.append(f'#{i} 最初の鬼が近い {oni0}')
        bad, mind, minang = geometry(lv)
        if bad: fails.append(f'#{i} 幾何 {bad}')
        rem = removable_edges(lv); rem_old = removable_edges(lv, new_def=False)
        if rem: fails.append(f'#{i} いらない線 {len(rem)}本 {rem}')
        first = len(m.adj[lv['you']]); first_win = sum(1 for v, ns in ex['edges'][ex['s0']] if ns in ex['dtw']) + len(ex['win_moves'][ex['s0']])
        ntrap, rp, traps = trap_info(ex)
        kind = bridges_side(m, lv['home']); tk = {}
        for st_, v in traps: tk[kind[(st_[0], v)]] = tk.get(kind[(st_[0], v)], 0) + 1
        lower = {'入門': 1, '初級': 2, '中級': 3, '上級': 4}.get(lv['tier'], 0)
        if rp < lower: fails.append(f'#{i} 読みどころ{rp} < 下限{lower}')
        if lv['tier'] != '入門' and first < 2: fails.append(f'#{i} 初手が{first}通り')
        rows.append(dict(i=i, tier=lv['tier'], onis=len(lv['onis']), nodes=len(lv['nodes']), edges=len(lv['edges']),
                         min=ex['best'], dist=m.dist[lv['you']][lv['home']], detour=ex['best'] - m.dist[lv['you']][lv['home']],
                         rate=round(rate, 4), first=f'{first_win}/{first}', reading=rp, traps=ntrap, trap_kind=tk, removable_old=len(rem_old), n_opt=len(lines),
                         states=len(ex['seen']), straight_caught_at=[k for _, k in sres], oni0=oni0, solo=solo,
                         min_pt_edge=round(mind, 3), min_angle=round(minang, 1), removable=len(rem)))
    # 段の中は勝率降順・段どうしの逆転
    order = ['入門', '初級', '中級', '上級']; prev_min = None
    for tn in order:
        rs = [r['rate'] for r in rows if r['tier'] == tn]
        if rs != sorted(rs, reverse=True): fails.append(f'{tn} 段の中が勝率降順でない')
        if rs and prev_min is not None and max(rs) >= prev_min: fails.append(f'{tn} の最高勝率 {max(rs)} >= 前の段の最低 {prev_min}')
        if rs: prev_min = min(rs)
    sims = []
    for i, j in itertools.combinations(range(len(L)), 2):
        A = edge_set(L[i]); B = edge_set(L[j]); Bm = edge_set(L[j], lambda x, y: (3 - x, y))
        Bv = edge_set(L[j], lambda x, y: (x, 5 - y)); Br = edge_set(L[j], lambda x, y: (3 - x, 5 - y))
        sims.append((round(max(jacc(A, B), jacc(A, Bm)), 3), round(max(jacc(A, Bv), jacc(A, Br)), 3), i, j))
    sims.sort(reverse=True)
    if sims and sims[0][0] > 0.5: fails.append(f'似すぎた地図 {sims[0]}')
    groups = []
    for i in range(len(L)):
        for g in groups:
            if isomorphic(L[g[0]], L[i]): g.append(i); break
        else: groups.append([i])
    dup = [g for g in groups if len(g) > 1]
    print(f'異なる問題 {len(groups)}/{len(L)}（同型の組 {dup}）')
    if dup: fails.append(f'同じ問題の描き直し（同型） {dup}')
    res.update(rows=rows, fails=fails, top_sim_lr=sims[:5], top_sim_ud=sorted(sims, key=lambda t: -t[1])[:5])
    for r in rows: print(r)
    for tn in order:
        rs = [r for r in rows if r['tier'] == tn]
        if rs: print(tn, '線 平均', round(sum(r['edges'] for r in rs) / len(rs), 1), '点 平均', round(sum(r['nodes'] for r in rs) / len(rs), 1),
                     '最短', min(r['min'] for r in rs), '〜', max(r['min'] for r in rs), '回り道', min(r['detour'] for r in rs), '〜', max(r['detour'] for r in rs),
                     '勝率', min(r['rate'] for r in rs), '〜', max(r['rate'] for r in rs),
                     '読みどころ', min(r['reading'] for r in rs), '〜', max(r['reading'] for r in rs),
                     '初手1通り', sum(1 for r in rs if r['first'].endswith('/1')), '旧定義の消せる線', sum(r['removable_old'] for r in rs),
                     '罠の型', {k: sum(r['trap_kind'].get(k, 0) for r in rs) for k in ('branch', 'home', 'back', 'ring')})
    print('top Jaccard (同一/左右反転):', sims[:3])
    print('top Jaccard (上下反転/180度):', res['top_sim_ud'][:3])
    print('FAILS:', len(fails)); [print(' ', f) for f in fails]
    if '--json' in sys.argv:
        json.dump(res, open(sys.argv[sys.argv.index('--json') + 1], 'w'), ensure_ascii=False, indent=1)
    print('OVERALL', 'PASS' if not fails else 'FAIL')
    return 0 if not fails else 1

if __name__ == '__main__':
    sys.exit(main())
