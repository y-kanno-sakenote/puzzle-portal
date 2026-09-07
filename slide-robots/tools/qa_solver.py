#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 担当: ✅ 検証係（マンガー×ファインマン）
"""独立ソルバー（実装者の gen_levels.py / index.html のロジックを一切呼ばない。クリーンルーム実装）

- levels.json / index.html 埋め込み LEVELS の40本を自前BFSで解き、最短手数・tier・needsOthers を照合
- 壁の整合（あるマスのある向きの壁と、隣マスの反対向きの壁が両方立っているか）を検査
- 盤面妥当性（144文字・中央塊がwallsに含まれ体/的が塊に無い・的がL字角・4体重複無し・盤面重複無し）
- Node で index.html の <script> を抜いて SlideRobots.solve/slide/applyMove/isSolved を実走
  - 40/40 の solve() 一致・境界値・自前最短経路のautoplay
  - localStorage 壊れ値でのクラッシュ有無

使い方:
  python3 tools/qa_solver.py
"""
import json
import re
import subprocess
import sys
import time
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
W = 12
N = W * W
DIRS = ['N', 'E', 'S', 'W']
BIT = {'N': 1, 'E': 2, 'S': 4, 'W': 8}
DXY = {'N': (0, -1), 'E': (1, 0), 'S': (0, 1), 'W': (-1, 0)}
OPP = {'N': 'S', 'E': 'W', 'S': 'N', 'W': 'E'}
BLOCK = set()
for _bx in (W // 2 - 1, W // 2):
    for _by in (W // 2 - 1, W // 2):
        BLOCK.add(_by * W + _bx)
CORNER_VALUES = {3, 6, 9, 12}   # N+E, E+S, S+W, W+N
TIERS = [("入門", 3, 4), ("初級", 5, 6), ("中級", 7, 8), ("上級", 9, 10 ** 9)]
SCRATCH = Path("/private/tmp/claude-501/-Users-ymacmini-Documents-claudecode-macmini"
                "/84792f8b-2118-477f-8a4f-455403769681/scratchpad")


def tier_of(m):
    for name, lo, hi in TIERS:
        if lo <= m <= hi:
            return name
    return None


# ============================================================ 盤面パース＆妥当性
def parse_walls(s):
    return [int(ch, 16) for ch in s]


def check_wall_consistency(m):
    """あるマスのある向きの壁と、隣マスの反対向きの壁が両方立っているか（片側だけの壁を検出）"""
    errs = []
    for i in range(N):
        x, y = i % W, i // W
        for d in DIRS:
            if not (m[i] & BIT[d]):
                continue
            dx, dy = DXY[d]
            nx, ny = x + dx, y + dy
            if not (0 <= nx < W and 0 <= ny < W):
                continue  # 外周の外側は隣マスが無い＝片側だけでよい
            j = ny * W + nx
            if not (m[j] & BIT[OPP[d]]):
                errs.append(f"({x},{y}) の{d}壁に対し隣({nx},{ny})の{OPP[d]}壁が無い")
    return errs


def check_board(lv):
    """1件のレベルの妥当性エラー一覧を返す"""
    errs = []
    ws = lv["walls"]
    if len(ws) != N:
        errs.append(f"walls長さ{len(ws)}≠{N}")
        return errs
    m = parse_walls(ws)
    errs += check_wall_consistency(m)

    for c in BLOCK:
        if m[c] != 0xF:
            errs.append(f"中央塊セル{(c % W, c // W)}の壁が0xF未満(={m[c]:x})")

    robots = lv["robots"]
    positions = [(r[0], r[1]) for r in robots]
    if len(set(positions)) != 4:
        errs.append(f"4体が重複: {positions}")
    for x, y in positions:
        if (y * W + x) in BLOCK:
            errs.append(f"体{(x, y)}が中央塊の中")
        if not (0 <= x < W and 0 <= y < W):
            errs.append(f"体{(x, y)}が盤外")

    tx, ty, tcolor = lv["target"]
    tcell = ty * W + tx
    if tcell in BLOCK:
        errs.append(f"的{(tx, ty)}が中央塊の中")
    if not (0 <= tx < W and 0 <= ty < W):
        errs.append(f"的{(tx, ty)}が盤外")
    else:
        if m[tcell] not in CORNER_VALUES:
            errs.append(f"的{(tx, ty)}がL字の角でない(壁={m[tcell]:x})")
    colors = [r[2] for r in robots]
    if tcolor not in colors:
        errs.append(f"的の色{tcolor}に対応する体が無い")
    return errs


# ============================================================ 自前BFS（クリーンルーム）
def slide(m, occ, pos, d):
    """壁か他の体に当たるまで滑った先。1マスも動けなければ None。occ=集合（自分含まない）"""
    x, y = pos % W, pos // W
    dx, dy = DXY[d]
    cur = pos
    while True:
        if m[cur] & BIT[d]:
            break
        nx, ny = cur % W + dx, cur // W + dy
        ncell = ny * W + nx
        if ncell in occ:
            break
        cur = ncell
    return None if cur == pos else cur


def solve_full(m, target_start, others_start, goal, depth_cap=30, want_path=False):
    """状態=(target位置, 他3体位置をソートしたタプル)。目標=対象色の体がgoalに来ること。
       戻り値: (min手数, path) path=[(from_cell, dir), ...] or (-1, None)"""
    def canon(t, others):
        return (t, tuple(sorted(others)))

    start = canon(target_start, others_start)
    if start[0] == goal:
        return 0, []
    seen = {start: None}   # state -> (prev_state, from_cell, dir)
    q = deque([start])
    depth_of = {start: 0}
    while q:
        st = q.popleft()
        d0 = depth_of[st]
        if d0 >= depth_cap:
            continue
        t, others = st
        all_pos = (t,) + others
        occ_for = lambda idx: set(all_pos) - {all_pos[idx]}
        # 対象の体を動かす
        occ = occ_for(0)
        for d in DIRS:
            q2 = slide(m, occ, t, d)
            if q2 is None:
                continue
            if q2 == goal:
                if not want_path:
                    return d0 + 1, None
                path = [(t, d)]
                cur = st
                while seen[cur] is not None:
                    prev, frm, dd = seen[cur]
                    path.append((frm, dd))
                    cur = prev
                path.reverse()
                return d0 + 1, path
            ns = canon(q2, others)
            if ns not in seen:
                seen[ns] = (st, t, d)
                depth_of[ns] = d0 + 1
                q.append(ns)
        # 他の3体を動かす
        for k in range(3):
            occ = occ_for(k + 1)
            for d in DIRS:
                q2 = slide(m, occ, others[k], d)
                if q2 is None:
                    continue
                no = list(others)
                no[k] = q2
                ns = canon(t, tuple(no))
                if ns not in seen:
                    seen[ns] = (st, others[k], d)
                    depth_of[ns] = d0 + 1
                    q.append(ns)
    return -1, None


def solve_solo(m, target_start, others_fixed, goal, depth_cap=30):
    """的の色の体だけを動かして解けるか（他3体は動かず壁として固定）"""
    if target_start == goal:
        return 0
    occ = set(others_fixed)
    seen = {target_start}
    frontier = [target_start]
    depth = 0
    while frontier and depth < depth_cap:
        depth += 1
        nxt = []
        for p in frontier:
            for d in DIRS:
                q2 = slide(m, occ, p, d)
                if q2 is None:
                    continue
                if q2 == goal:
                    return depth
                if q2 not in seen:
                    seen.add(q2)
                    nxt.append(q2)
        frontier = nxt
    return -1


# ============================================================ JS harness
def extract_script(html):
    m = re.search(r"<script>(.*)</script>", html, re.S)
    assert m, "index.html に <script> が見つからない"
    return m.group(1)


def node_batch_solve(script, levels):
    payload = json.dumps(levels)
    js = script + f"""
var levels = {payload};
var out = [];
for (var i=0;i<levels.length;i++) {{
  var t0 = Date.now();
  var m = SlideRobots.solve(levels[i]);
  var ms = Date.now() - t0;
  out.push([m, ms]);
}}
console.log(JSON.stringify(out));
"""
    p = SCRATCH / "slide_solve.js"
    p.write_text(js, encoding="utf-8")
    r = subprocess.run(["node", str(p)], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError("node実行失敗:\n" + r.stderr)
    return json.loads(r.stdout.strip().splitlines()[-1])


def node_boundary_tests(script, sample_level):
    js = script + f"""
var lv = {json.dumps(sample_level)};
var state = SlideRobots.parse(lv);
var results = {{}};
// 存在しない体
results.slide_bad_id_neg = SlideRobots.slide(state, -1, 'N');
results.slide_bad_id_big = SlideRobots.slide(state, 99, 'N');
results.applyMove_bad_id_returns_null = (SlideRobots.applyMove(state, 99, 'N') === null);
// 存在しない方向
results.slide_bad_dir_str = SlideRobots.slide(state, 0, 'X');
results.slide_bad_dir_num = SlideRobots.slide(state, 0, 9);
// 壁際: 全ロボットを盤の四隅寄りへ動かし尽くして0マス(=null)になる向きを機械的に探す
var zeroFound = false, moveFound = false;
for (var trial=0; trial<40; trial++) {{
  for (var i=0;i<4;i++) {{
    for (var d=0; d<4; d++) {{
      var to = SlideRobots.slide(state, i, d);
      if (to === null) zeroFound = true; else moveFound = true;
    }}
  }}
  // 全体を壁際まで動かして、動けない向きが出やすくする
  var moved = false;
  for (var i2=0;i2<4;i2++) {{
    var to2 = SlideRobots.slide(state, i2, 0);
    if (to2 !== null) {{ var ns = SlideRobots.applyMove(state, i2, 0); if (ns) {{ state = ns; moved = true; }} }}
  }}
  if (!moved) break;
}}
results.zeroFound = zeroFound;
results.moveFound = moveFound;
// applyMove: 動けない場合は null を返し、元stateは変えない（参照比較でなく値比較）
var st2 = SlideRobots.parse(lv);
var before = JSON.stringify(st2.robots);
var nsBad = SlideRobots.applyMove(st2, 99, 'N');
results.applyMove_bad_returns_null2 = (nsBad === null);
results.state_unchanged_after_bad = (JSON.stringify(st2.robots) === before);
console.log(JSON.stringify(results));
"""
    p = SCRATCH / "slide_boundary.js"
    p.write_text(js, encoding="utf-8")
    r = subprocess.run(["node", str(p)], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError("node境界テスト失敗:\n" + r.stderr)
    return json.loads(r.stdout.strip().splitlines()[-1])


def node_offboard_hang_probe(script, sample_level):
    """robots配列を盤外座標に直接書き換えて slide() を呼ぶ。
       壁配列の外周ガードに頼っているだけなら、参照外(undefined & N = 0)で無限ループする恐れがある。
       短いタイムアウトで hang/crash/ok を判定する（本来のAPI経由では起きない入力だが、防御の甘さの記録用）"""
    js = script + f"""
var lv = {json.dumps(sample_level)};
var st = SlideRobots.parse(lv);
st.robots[0] = -50;
var r = SlideRobots.slide(st, 0, 'N');
console.log(JSON.stringify({{result: r}}));
"""
    p = SCRATCH / "slide_offboard.js"
    p.write_text(js, encoding="utf-8")
    try:
        r = subprocess.run(["node", str(p)], capture_output=True, text=True, timeout=3)
    except subprocess.TimeoutExpired:
        return "HANG（無限ループ・3秒でタイムアウト）"
    if r.returncode != 0:
        return f"CRASH: {r.stderr[-300:]}"
    return f"戻り値={r.stdout.strip()}"


def node_autoplay(script, level, path):
    """path=[(from_cell, dir), ...] を JS の applyMove で1手ずつ適用し isSolved を確認
       from_cell に居る体を探して dir へ動かす（識別はindexでなく位置で行う＝JSとPyの体順序差を吸収）"""
    payload = json.dumps({"level": level, "path": [[fc, d] for fc, d in path]})
    js = script + f"""
var data = {payload};
var state = SlideRobots.parse(data.level);
var log = [];
for (var k=0;k<data.path.length;k++) {{
  var fromCell = data.path[k][0], dir = data.path[k][1];
  var id = -1;
  for (var i=0;i<state.robots.length;i++) {{ if (state.robots[i] === fromCell) {{ id = i; break; }} }}
  if (id === -1) {{ log.push("NG id-not-found step="+k+" from="+fromCell); break; }}
  var to = SlideRobots.slide(state, id, dir);
  if (to === null) {{ log.push("NG slide-null step="+k); break; }}
  var ns = SlideRobots.applyMove(state, id, dir);
  if (!ns) {{ log.push("NG applyMove-null step="+k); break; }}
  state = ns;
}}
var solved = SlideRobots.isSolved(state);
console.log(JSON.stringify({{solved: solved, log: log, moves: data.path.length}}));
"""
    p = SCRATCH / "slide_autoplay.js"
    p.write_text(js, encoding="utf-8")
    r = subprocess.run(["node", str(p)], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError("node autoplay失敗:\n" + r.stderr)
    return json.loads(r.stdout.strip().splitlines()[-1])


DOM_STUB = r"""
function makeEl() {
  var e = {
    style: {}, dataset: {}, childNodes: [], _text: '', _hidden: false, disabled: false, className: '',
    classList: { add: function(){}, remove: function(){} },
    addEventListener: function(){}, removeEventListener: function(){},
    appendChild: function(c){ this.childNodes.push(c); return c; },
    removeChild: function(){},
    querySelectorAll: function(){ return []; },
    setPointerCapture: function(){}, releasePointerCapture: function(){},
    getBoundingClientRect: function(){ return {left:0, top:0, width:100, height:100}; },
    get textContent(){ return this._text; }, set textContent(v){ this._text = v; },
    get innerHTML(){ return ''; }, set innerHTML(v){},
    get hidden(){ return this._hidden; }, set hidden(v){ this._hidden = v; },
    clientWidth: 400
  };
  return e;
}
var document = {
  getElementById: function(id){ return makeEl(); },
  createElement: function(tag){ return makeEl(); }
};
var window = (typeof window !== 'undefined') ? window : {};
window.scrollTo = function(){};
function getComputedStyle(){ return { backgroundColor: '#000' }; }
"""


def node_localstorage_crash_test(script):
    cases = {
        "非JSON文字列": "not json at all {{{",
        "last小数": json.dumps({"cleared": {}, "last": 2.5}),
        "last負数": json.dumps({"cleared": {}, "last": -1}),
        "last巨大": json.dumps({"cleared": {}, "last": 99999}),
        "cleared文字列": json.dumps({"cleared": "oops", "last": 0}),
        "null": "null",
        "getItem例外": "__THROW__",
    }
    out = {}
    for name, raw in cases.items():
        if raw == "__THROW__":
            ls_code = """
var localStorage = { getItem: function(){ throw new Error('boom'); }, setItem: function(){ throw new Error('boom'); } };
"""
        else:
            ls_code = f"""
var localStorage = {{
  _v: {json.dumps(raw)},
  getItem: function(){{ return this._v; }},
  setItem: function(k,v){{ this._v = v; }}
}};
"""
        js = DOM_STUB + ls_code + "\n" + script + "\nconsole.log('OK');\n"
        p = SCRATCH / "slide_ls.js"
        p.write_text(js, encoding="utf-8")
        r = subprocess.run(["node", str(p)], capture_output=True, text=True, timeout=30)
        out[name] = {"ok": (r.returncode == 0 and "OK" in r.stdout), "stderr": r.stderr[-800:]}
    return out


# ============================================================ main
def main():
    SCRATCH.mkdir(parents=True, exist_ok=True)
    levels = json.load(open(ROOT / "tools/levels.json", encoding="utf-8"))
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    script = extract_script(html)

    embed_json = json.loads(re.search(r"var LEVELS = (\[.*?\]);", script, re.S).group(1))
    embed_match = embed_json == levels

    print("=== 1) 盤面妥当性（144文字・壁の整合・中央塊・的のL字角・4体重複無し） ===")
    board_ok = True
    for k, lv in enumerate(levels):
        errs = check_board(lv)
        if errs:
            board_ok = False
            print(f"NG #{k:02d}: {'; '.join(errs)}")
    print(f"盤面妥当性 全PASS: {board_ok}")

    keys = [(lv["walls"], tuple(tuple(r) for r in lv["robots"]), tuple(lv["target"])) for lv in levels]
    dup = len(keys) - len(set(keys))
    print(f"盤面重複: {dup}本 / 総数{len(keys)}本")
    print(f"embed(index.html) と tools/levels.json 一致: {embed_match}")

    print("\n=== 2) 独立BFS: 40本の最短手数・tier・needsOthers 照合 ===")
    all_ok = True
    paths = {}
    for k, lv in enumerate(levels):
        m = parse_walls(lv["walls"])
        robots = [(r[0] + r[1] * W, r[2]) for r in lv["robots"]]
        tcolor = lv["target"][2]
        tx, ty = lv["target"][0], lv["target"][1]
        goal = ty * W + tx
        t_start = next(c for c, col in robots if col == tcolor)
        others_start = tuple(c for c, col in robots if col != tcolor)

        t0 = time.time()
        mn, path = solve_full(m, t_start, others_start, goal, want_path=True)
        dt = time.time() - t0
        solo = solve_solo(m, t_start, others_start, goal)
        needs = (solo != mn) if mn >= 0 else None
        tname = tier_of(mn) if mn >= 0 else None
        ok = (mn == lv["min"]) and (tname == lv["tier"]) and (needs == lv["needsOthers"])
        flag = "OK " if ok else "NG "
        print(f"{flag}#{k:02d} impl_min={lv['min']:3d} qa_min={mn:3d} "
              f"impl_tier={lv['tier']} qa_tier={tname} "
              f"impl_needs={lv['needsOthers']} qa_needs={needs} {dt*1000:.0f}ms")
        all_ok &= ok
        if ok:
            paths[k] = path
    print(f"独立BFS 全一致: {all_ok}")

    print("\n=== 3) Node: SlideRobots.solve() 40/40一致 ===")
    js_res = node_batch_solve(script, levels)
    js_ok = True
    max_ms = 0
    max_ms_idx = -1
    for k, (m, ms) in enumerate(js_res):
        if ms > max_ms:
            max_ms, max_ms_idx = ms, k
        expect = levels[k]["min"]
        if m != expect:
            js_ok = False
            print(f"NG #{k:02d} js_min={m} impl_min={expect}")
    print(f"JS solve() 全一致: {js_ok} / 最長 {max_ms}ms（#{max_ms_idx:02d}）")

    print("\n=== 4) 境界値テスト（slide/applyMove） ===")
    b = node_boundary_tests(script, levels[0])
    print(json.dumps(b, ensure_ascii=False))
    boundary_ok = (
        b["slide_bad_id_neg"] is None and
        b["slide_bad_id_big"] is None and
        b["applyMove_bad_id_returns_null"] is True and
        b["slide_bad_dir_str"] is None and
        b["slide_bad_dir_num"] is None and
        b["zeroFound"] is True and b["moveFound"] is True and
        b["applyMove_bad_returns_null2"] is True and
        b["state_unchanged_after_bad"] is True
    )
    print(f"境界値 全PASS: {boundary_ok}")
    offboard = node_offboard_hang_probe(script, levels[0])
    print(f"盤外座標を直接書き換えてslide(): {offboard}")

    print("\n=== 5) 自動プレイ（自前最短経路をapplyMoveで適用） ===")
    autoplay_ok = True
    checked = 0
    for k in sorted(paths):
        r = node_autoplay(script, levels[k], paths[k])
        checked += 1
        if not r["solved"] or r["log"]:
            autoplay_ok = False
            print(f"NG #{k:02d} solved={r['solved']} log={r['log']}")
    print(f"自動プレイ {checked}/{len(levels)} 本 全成功: {autoplay_ok}")

    print("\n=== 6) localStorage 壊れ値でのクラッシュ有無 ===")
    ls = node_localstorage_crash_test(script)
    ls_ok = True
    for name, r in ls.items():
        flag = "OK " if r["ok"] else "NG "
        if not r["ok"]:
            ls_ok = False
            print(f"{flag}{name}: {r['stderr'][:300]}")
        else:
            print(f"{flag}{name}")
    print(f"localStorage 全ケースクラッシュ無し: {ls_ok}")

    print("\n=== 総合 ===")
    overall = (board_ok and dup == 0 and embed_match and all_ok and
               js_ok and boundary_ok and autoplay_ok and ls_ok)
    print(f"盤面妥当性={board_ok} 重複無し={dup==0} embed一致={embed_match} 独立BFS一致={all_ok} "
          f"JS一致={js_ok} 境界値={boundary_ok} 自動プレイ={autoplay_ok} localStorage={ls_ok}")
    print(f"OVERALL {'PASS' if overall else 'FAIL'}")
    sys.exit(0 if overall else 1)


if __name__ == "__main__":
    main()
