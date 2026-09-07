#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 担当: ✅ 検証係（マンガー×ファインマン）
"""独立ソルバー（実装者の gen_levels.py / index.html のロジックを一切呼ばない。クリーンルーム実装）

- levels.json / index.html 埋め込み LEVELS の40本を自前BFSで解き、最短手数とtierを照合
- 盤面20文字の妥当性（長方形・娘1つ2x2・空き>=2・全単射）を検査
- 駒配置(x,y,w,h)集合の相互Jaccardを自前計算
- Node で index.html の <script> を抜いて Hakoiri.solve / canMove / applyMove / isSolved を実走
  - 40/40 の solve() 一致、canMove/applyMove の境界値、自前最短経路のautoplayを検証
  - localStorage 壊れ値でのクラッシュ有無（DOMスタブで <script> をそのまま実行）

使い方:
  python3 tools/qa_solver.py
"""
import json
import re
import subprocess
import sys
import tempfile
import time
from collections import deque, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
W, H = 4, 5
GOAL = (1, 3)
SCRATCH = Path("/private/tmp/claude-501/-Users-ymacmini-Documents-claudecode-macmini"
                "/84792f8b-2118-477f-8a4f-455403769681/scratchpad")


# ============================================================ 盤面パース＆妥当性
def parse_board(board):
    """20文字 -> (pieces, errors)。pieces=[{ch,x,y,w,h}]（出現順、A含む）"""
    errors = []
    if len(board) != W * H:
        return [], [f"長さ{len(board)}≠{W*H}"]
    cells = defaultdict(list)
    order = []
    for i, ch in enumerate(board):
        if ch == "o":
            continue
        if ch not in cells:
            order.append(ch)
        cells[ch].append(i)
    pieces = []
    for ch in order:
        idx = cells[ch]
        xs = [i % W for i in idx]
        ys = [i // W for i in idx]
        x0, y0 = min(xs), min(ys)
        w, h = max(xs) - x0 + 1, max(ys) - y0 + 1
        if w * h != len(idx):
            errors.append(f"{ch} 長方形でない w={w} h={h} 実マス数={len(idx)}")
        else:
            expect = {(y0 + j) * W + (x0 + i) for j in range(h) for i in range(w)}
            if expect != set(idx):
                errors.append(f"{ch} 範囲内に穴/欠け")
        pieces.append({"ch": ch, "x": x0, "y": y0, "w": w, "h": h})
    a = [p for p in pieces if p["ch"] == "A"]
    if len(a) != 1:
        errors.append(f"A(娘)の個数={len(a)}")
    elif not (a[0]["w"] == 2 and a[0]["h"] == 2):
        errors.append(f"A(娘)が2x2でない w={a[0]['w']} h={a[0]['h']}")
    empties = board.count("o")
    if empties < 2:
        errors.append(f"空き{empties}マス<2")
    total = sum(p["w"] * p["h"] for p in pieces) + empties
    if total != W * H:
        errors.append(f"総マス数{total}≠{W*H}（不正文字/文字漏れ）")
    if len(a) == 1:
        others = [p for p in pieces if p["ch"] != "A"]
        pieces = a + others
    return pieces, errors


def shape_set(pieces):
    return frozenset((p["x"], p["y"], p["w"], p["h"]) for p in pieces)


def jaccard(a, b):
    u = len(a | b)
    return (len(a & b) / u) if u else 0.0


# ============================================================ 自前BFS（クリーンルーム）
def make_canon(pieces):
    groups = defaultdict(list)
    for i, p in enumerate(pieces):
        groups[(p["w"], p["h"])].append(i)
    group_list = list(groups.values())

    def canon(state):
        st = list(state)
        for idxs in group_list:
            vals = sorted(st[i] for i in idxs)
            for i, v in zip(idxs, vals):
                st[i] = v
        return tuple(st)
    return canon


def occ_grid(pieces, state):
    g = [-1] * (W * H)
    for i, p in enumerate(pieces):
        x, y = state[i]
        for j in range(p["h"]):
            for k in range(p["w"]):
                g[(y + j) * W + (x + k)] = i
    return g


def slide_positions(pieces, state, g, i):
    p = pieces[i]
    w, h = p["w"], p["h"]
    x0, y0 = state[i]
    out = []
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        x, y = x0, y0
        while True:
            nx, ny = x + dx, y + dy
            if nx < 0 or ny < 0 or nx + w > W or ny + h > H:
                break
            if dx:
                ex = nx + (w - 1 if dx > 0 else 0)
                blocked = any(g[(ny + j) * W + ex] not in (-1, i) for j in range(h))
            else:
                ey = ny + (h - 1 if dy > 0 else 0)
                blocked = any(g[ey * W + (nx + j)] not in (-1, i) for j in range(w))
            if blocked:
                break
            x, y = nx, ny
            out.append((x, y))
    return out


def solve_with_path(pieces, start, node_limit=3_000_000):
    """(最短手数, 経路) を返す。経路=[(w,h,from_xy,to_xy), ...]。解けなければ (-1, None)。"""
    canon = make_canon(pieces)
    start = canon(start)
    if start[0] == GOAL:
        return 0, []
    seen = {start: None}   # canon-state -> (prev_canon_state, piece_i, from_xy, to_xy)
    q = deque([start])
    nodes = 0
    while q:
        state = q.popleft()
        nodes += 1
        if nodes > node_limit:
            return -1, None
        g = occ_grid(pieces, state)
        for i in range(len(pieces)):
            for pos in slide_positions(pieces, state, g, i):
                if i == 0 and pos == GOAL:
                    path = [(pieces[i]["w"], pieces[i]["h"], state[i], pos)]
                    cur = state
                    while seen[cur] is not None:
                        prev, pi, frm, to = seen[cur]
                        path.append((pieces[pi]["w"], pieces[pi]["h"], frm, to))
                        cur = prev
                    path.reverse()
                    return len(path), path
                ns = list(state)
                ns[i] = pos
                ns = canon(tuple(ns))
                if ns not in seen:
                    seen[ns] = (state, i, state[i], pos)
                    q.append(ns)
    return -1, None


# ============================================================ tier
TIERS = [("入門", 5, 15), ("初級", 16, 35), ("中級", 36, 70), ("上級", 71, 10 ** 9)]


def tier_of(m):
    for name, lo, hi in TIERS:
        if lo <= m <= hi:
            return name
    return None


# ============================================================ JS harness
def extract_script(html):
    m = re.search(r"<script>(.*)</script>", html, re.S)
    assert m, "index.html に <script> が見つからない"
    return m.group(1)


def node_batch_solve(script, boards):
    """Node で Hakoiri.solve(board) を全件計測。[(board, ms_min, ms)]"""
    payload = json.dumps(boards)
    js = script + f"""
var boards = {payload};
var out = [];
for (var i=0;i<boards.length;i++) {{
  var t0 = Date.now();
  var m = Hakoiri.solve(boards[i]);
  var ms = Date.now() - t0;
  out.push([m, ms]);
}}
console.log(JSON.stringify(out));
"""
    p = SCRATCH / "hakoiri_solve.js"
    p.write_text(js, encoding="utf-8")
    r = subprocess.run(["node", str(p)], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError("node実行失敗:\n" + r.stderr)
    return json.loads(r.stdout.strip().splitlines()[-1])


def node_boundary_tests(script):
    js = script + """
var results = {};
var board = "BAACBAACDEEFDGHFIooJ"; // 横刀立馬相当
var st = Hakoiri.parse(board);
results.canMove_offboard_left = Hakoiri.canMove(st, 0, -99, 0);
results.canMove_offboard_down = Hakoiri.canMove(st, 0, 0, 99);
results.canMove_zero = Hakoiri.canMove(st, 0, 0, 0);
results.canMove_diagonal = Hakoiri.canMove(st, 0, 1, 1);
results.canMove_bad_id_neg = Hakoiri.canMove(st, -1, 1, 0);
results.canMove_bad_id_big = Hakoiri.canMove(st, 999, 1, 0);
results.applyMove_bad_returns_null = (Hakoiri.applyMove(st, 0, 1, 1) === null);
// 衝突確認: 隣接駒方向へ1マスなら止まる(false)ことを、盤面から機械的に探す
var blockedFound = false, freeFound = false;
for (var i=0;i<st.length;i++) {
  var dirs = [[1,0],[-1,0],[0,1],[0,-1]];
  for (var d=0; d<4; d++) {
    var can1 = Hakoiri.canMove(st, i, dirs[d][0], dirs[d][1]);
    var can2 = Hakoiri.canMove(st, i, dirs[d][0]*2, dirs[d][1]*2);
    if (can1) freeFound = true;
    if (!can1) blockedFound = true;
  }
}
results.blockedFound = blockedFound;
results.freeFound = freeFound;
console.log(JSON.stringify(results));
"""
    p = SCRATCH / "hakoiri_boundary.js"
    p.write_text(js, encoding="utf-8")
    r = subprocess.run(["node", str(p)], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError("node境界テスト失敗:\n" + r.stderr)
    return json.loads(r.stdout.strip().splitlines()[-1])


def node_autoplay(script, board, path):
    """path = [(w,h,from_xy,to_xy), ...] を JS の applyMove で1手ずつ適用し isSolved を確認"""
    payload = json.dumps({"board": board, "path": path})
    js = script + f"""
var data = {payload};
var state = Hakoiri.parse(data.board);
var log = [];
for (var k=0;k<data.path.length;k++) {{
  var step = data.path[k];
  var w=step[0], h=step[1], fx=step[2][0], fy=step[2][1], tx=step[3][0], ty=step[3][1];
  var id = -1;
  for (var i=0;i<state.length;i++) {{
    if (state[i].w===w && state[i].h===h && state[i].x===fx && state[i].y===fy) {{ id = i; break; }}
  }}
  if (id === -1) {{ log.push("NG id-not-found step="+k); break; }}
  var dx = tx - fx, dy = ty - fy;
  if (!Hakoiri.canMove(state, id, dx, dy)) {{ log.push("NG canMove-false step="+k); break; }}
  var ns = Hakoiri.applyMove(state, id, dx, dy);
  if (!ns) {{ log.push("NG applyMove-null step="+k); break; }}
  state = ns;
}}
var solved = Hakoiri.isSolved(state);
console.log(JSON.stringify({{solved: solved, log: log, moves: data.path.length}}));
"""
    p = SCRATCH / "hakoiri_autoplay.js"
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
"""


def node_localstorage_crash_test(script):
    """localStorage の壊れ値でスクリプト全体（DOM込み）がクラッシュしないか"""
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
        p = SCRATCH / "hakoiri_ls.js"
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

    # embed 一致チェック
    embed_json_match = json.dumps(json.loads(re.search(r"var LEVELS = (\[.*?\]);",
                                                         script, re.S).group(1)))
    file_json_match = json.dumps(levels)
    embed_match = json.loads(embed_json_match) == json.loads(file_json_match)

    print("=== 1) 独立BFS: 40本の最短手数・tier照合 ===")
    all_ok = True
    boards = [l["board"] for l in levels]
    dup = len(boards) - len(set(boards))
    paths = {}
    empties_list = []
    shapes = []
    for k, lv in enumerate(levels):
        pieces, errs = parse_board(lv["board"])
        shapes.append(shape_set(pieces))
        empties_list.append(lv["board"].count("o"))
        if errs:
            print(f"NG #{k:02d} {lv['board']} 盤面エラー: {'; '.join(errs)}")
            all_ok = False
            continue
        start = tuple((p["x"], p["y"]) for p in pieces)
        t0 = time.time()
        m, path = solve_with_path(pieces, start)
        dt = time.time() - t0
        t = tier_of(m) if m >= 0 else None
        ok = (m == lv["min"]) and (t == lv["tier"])
        flag = "OK " if ok else "NG "
        name = f" {lv['name']}" if lv.get("name") else ""
        print(f"{flag}#{k:02d} impl_min={lv['min']:3d} qa_min={m:3d} "
              f"impl_tier={lv['tier']} qa_tier={t} {dt*1000:.0f}ms{name}")
        all_ok &= ok
        if ok:
            paths[k] = (lv["board"], path)

    print(f"\n盤面重複: {dup}本 / 総数{len(boards)}本")
    print(f"embed(index.html) と tools/levels.json 一致: {embed_match}")
    min_empty = min(empties_list)
    print(f"空きマス最小: {min_empty}マス（規定>=2）")

    print("\n=== 2) 相互Jaccard（(x,y,w,h)集合） ===")
    pairs_over = 0
    max_j = 0.0
    for i in range(len(shapes)):
        for j in range(i + 1, len(shapes)):
            jv = jaccard(shapes[i], shapes[j])
            max_j = max(max_j, jv)
            if jv > 0.5:
                pairs_over += 1
    print(f"最大Jaccard={max_j:.3f} / 0.5超のペア数={pairs_over}")

    print("\n=== 3) Node: Hakoiri.solve() 40/40一致 ===")
    js_res = node_batch_solve(script, boards)
    js_ok = True
    max_ms = 0
    max_ms_board = ""
    for k, (m, ms) in enumerate(js_res):
        max_ms = max(max_ms, ms)
        if ms == max_ms:
            max_ms_board = boards[k]
        expect = levels[k]["min"]
        if m != expect:
            js_ok = False
            print(f"NG #{k:02d} js_min={m} impl_min={expect} {boards[k]}")
    print(f"JS solve() 全一致: {js_ok} / 最長 {max_ms}ms（盤 {max_ms_board}）")

    print("\n=== 4) 境界値テスト（canMove/applyMove） ===")
    b = node_boundary_tests(script)
    print(json.dumps(b, ensure_ascii=False))
    boundary_ok = (
        b["canMove_offboard_left"] is False and
        b["canMove_offboard_down"] is False and
        b["canMove_zero"] is False and
        b["canMove_diagonal"] is False and
        b["canMove_bad_id_neg"] is False and
        b["canMove_bad_id_big"] is False and
        b["applyMove_bad_returns_null"] is True and
        b["blockedFound"] is True and b["freeFound"] is True
    )
    print(f"境界値 全PASS: {boundary_ok}")

    print("\n=== 5) 自動プレイ（自前最短経路をapplyMoveで適用） ===")
    autoplay_ok = True
    checked = 0
    for k in sorted(paths):
        board, path = paths[k]
        r = node_autoplay(script, board, path)
        checked += 1
        if not r["solved"] or r["log"]:
            autoplay_ok = False
            print(f"NG #{k:02d} {board} solved={r['solved']} log={r['log']}")
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
    overall = all_ok and dup == 0 and js_ok and boundary_ok and autoplay_ok and ls_ok and embed_match
    print(f"独立BFS一致={all_ok} 重複無し={dup==0} JS一致={js_ok} "
          f"境界値={boundary_ok} 自動プレイ={autoplay_ok} localStorage={ls_ok} embed一致={embed_match}")
    print(f"OVERALL {'PASS' if overall else 'FAIL'}")
    sys.exit(0 if overall else 1)


if __name__ == "__main__":
    main()
