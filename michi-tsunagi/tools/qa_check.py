#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""担当: qa係
みちつなぎ 独立QAスクリプト（実装者のコードは読まずに書いたクリーンルーム版）。

python3 tools/qa_check.py [tools/puzzles.json]

1) 自前ソルバー（生成器とは別のデータ構造・別の探索順）で40問の解数を数え、
   solutionと一致するか
2) 盤面妥当性（端点2つずつ・全マス被覆・各対連結・1マス道なし・一筆で歩けるか・重複なし）
3) 難度ノード数の実測とspec.mdの閾値照合・段階順の逆転チェック
4) index.html 先頭<script>のJSロジック（countSolutions/isComplete）をNodeで実走し
   自前ソルバーと突き合わせ、isCompleteはわざと壊した状態でfalseになるか
5) localStorageの壊れ値で画面スクリプトの初期化が落ちないか（最小DOMスタブ）

Node（`node`コマンド）が必要。無ければ4)5)はSKIPと明示する。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import deque

DIGITS = "123456789abcdefghijklmnopqrstuvwxyz"
HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)


def load_puzzles(path):
    return json.load(open(path, encoding="utf-8"))


# ------------------------------------------------------------ 1) 自前ソルバー
def neighbors(n):
    nb = []
    for i in range(n * n):
        r, c = divmod(i, n)
        a = []
        # 独立実装として探索順を生成器と変える: 右・下・左・上
        if c + 1 < n:
            a.append(i + 1)
        if r + 1 < n:
            a.append(i + n)
        if c > 0:
            a.append(i - 1)
        if r > 0:
            a.append(i - n)
        nb.append(a)
    return nb


class Solver:
    """クリーンルーム実装。生成器とは別データ構造（list + deque BFS）で
    到達可能性の枝刈りを毎回フルスキャンで行う（dropped-cell最適化はしない）。
    探索順（近傍順）も生成器とは変えてある。"""

    def __init__(self, n, pairs):
        self.n = n
        self.N = n * n
        self.pairs = pairs
        self.K = len(pairs)
        self.nb = neighbors(n)
        self.endpair = [-1] * self.N
        for k, (a, b) in enumerate(pairs):
            self.endpair[a] = k
            self.endpair[b] = k
        self.occ = [False] * self.N
        for a, b in pairs:
            self.occ[a] = True
            self.occ[b] = True

    def available(self, c, head, curk):
        if not self.occ[c]:
            return True
        if c == head or c == self.pairs[curk][1]:
            return True
        if self.endpair[c] > curk:
            return True
        return False

    def is_open(self, c, head, curk):
        if c == head or c == self.pairs[curk][1]:
            return True
        return self.endpair[c] > curk

    def feasible(self, head, curk):
        N, nb = self.N, self.nb
        for c in range(N):
            if self.occ[c]:
                continue
            t = 0
            for v in nb[c]:
                if self.available(v, head, curk):
                    t += 1
                    if t >= 2:
                        break
            if t < 2:
                return False
        seen = [False] * N
        for start in range(N):
            if seen[start] or not self.available(start, head, curk):
                continue
            q = deque([start])
            seen[start] = True
            comp = [start]
            has_open = self.is_open(start, head, curk)
            while q:
                c = q.popleft()
                for v in nb[c]:
                    if not seen[v] and self.available(v, head, curk):
                        seen[v] = True
                        comp.append(v)
                        if self.is_open(v, head, curk):
                            has_open = True
                        q.append(v)
            if not has_open:
                return False
            compset = set(comp)
            if (head in compset) != (self.pairs[curk][1] in compset):
                return False
            for j in range(curk + 1, self.K):
                a, b = self.pairs[j]
                if (a in compset) != (b in compset):
                    return False
        return True

    def solve(self, limit=2, maxnodes=2_000_000):
        owner = [-1] * self.N
        for k, (a, b) in enumerate(self.pairs):
            owner[a] = k
            owner[b] = k
        result = {"count": 0, "nodes": 0, "cap": False, "first": None}

        def dfs(k, head):
            if result["count"] >= limit or result["cap"]:
                return
            result["nodes"] += 1
            if result["nodes"] > maxnodes:
                result["cap"] = True
                return
            goal = self.pairs[k][1]
            for v in self.nb[head]:
                if result["count"] >= limit or result["cap"]:
                    return
                if v == goal:
                    if k + 1 == self.K:
                        if all(self.occ):
                            result["count"] += 1
                            if result["first"] is None:
                                result["first"] = owner[:]
                    else:
                        nk = k + 1
                        nh = self.pairs[nk][0]
                        if self.feasible(nh, nk):
                            dfs(nk, nh)
                elif not self.occ[v]:
                    self.occ[v] = True
                    owner[v] = k
                    if self.feasible(v, k):
                        dfs(k, v)
                    self.occ[v] = False
                    owner[v] = -1

        if self.K == 0:
            return result
        if self.feasible(self.pairs[0][0], 0):
            dfs(0, self.pairs[0][0])
        return result


def owner_to_solution(owner):
    return "".join(DIGITS[o] if o >= 0 else "?" for o in owner)


# ------------------------------------------------------------ 2) 盤面妥当性
def check_board_validity(p):
    errs = []
    n = p["n"]
    N = n * n
    pairs = p["pairs"]
    sol = p["solution"]
    K = len(pairs)
    if len(sol) != N:
        errs.append("solution長さ%d != N%d" % (len(sol), N))
        return errs
    endpoints = [x for pr in pairs for x in pr]
    if len(set(endpoints)) != len(endpoints):
        errs.append("端点の重複")
    if len(endpoints) != K * 2:
        errs.append("端点数不整合")
    used = set(sol)
    expect = set(DIGITS[:K])
    if used != expect:
        errs.append("solution文字集合が対の数と不一致 used=%s expect=%s" % (sorted(used), sorted(expect)))
    nb = neighbors(n)
    for k, (a, b) in enumerate(pairs):
        ch = DIGITS[k]
        cells = [i for i in range(N) if sol[i] == ch]
        if len(cells) < 2:
            errs.append("対%dが1マス以下" % k)
            continue
        if a not in cells or b not in cells:
            errs.append("対%dの端点がsolutionの持ち主と不一致" % k)
            continue
        S = set(cells)
        seen = {a}
        q = deque([a])
        while q:
            c = q.popleft()
            for v in nb[c]:
                if v in S and v not in seen:
                    seen.add(v)
                    q.append(v)
        if seen != S:
            errs.append("対%dが連結でない" % k)
        if b not in seen:
            errs.append("対%dの端点bへ到達不可" % k)
    return errs


def walkable_independent(n, cells, a, b, nb):
    """端から端まで一筆で全マスを歩けるか（独自DFS）"""
    S = set(cells)
    if a not in S or b not in S or a == b:
        return False
    need = len(S)
    seen = {a}

    def go(cur, cnt):
        if cur == b:
            return cnt == need
        for v in nb[cur]:
            if v in S and v not in seen:
                seen.add(v)
                if go(v, cnt + 1):
                    return True
                seen.discard(v)
        return False

    return go(a, 1)


# ------------------------------------------------------------ 4)5) JS/Node検証
LOGIC_TEST_JS = r"""
const fs = require('fs');
const vm = require('vm');
const logicSrc = fs.readFileSync(process.argv[2], 'utf8');
const ctx = { console };
vm.createContext(ctx);
vm.runInContext(logicSrc, ctx);
const MT = ctx.MichiTsunagi;
const puzzles = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const DIGITS = "123456789abcdefghijklmnopqrstuvwxyz";

function neighbors(n) {
  const nb = [];
  for (let i = 0; i < n * n; i++) {
    const r = Math.floor(i / n), c = i % n, a = [];
    if (r > 0) a.push(i - n);
    if (r + 1 < n) a.push(i + n);
    if (c > 0) a.push(i - 1);
    if (c + 1 < n) a.push(i + 1);
    nb.push(a);
  }
  return nb;
}
function orderedPath(n, cells, a, b) {
  const S = new Set(cells), nb = neighbors(n), need = cells.length;
  const seen = new Set([a]), path = [a];
  function go(cur) {
    if (cur === b) return path.length === need;
    for (const v of nb[cur]) {
      if (S.has(v) && !seen.has(v)) {
        seen.add(v); path.push(v);
        if (go(v)) return true;
        seen.delete(v); path.pop();
      }
    }
    return false;
  }
  return go(a) ? path : null;
}
function buildPaths(p) {
  const n = p.n, N = n * n, paths = [];
  for (let k = 0; k < p.pairs.length; k++) {
    const ch = DIGITS[k], cells = [];
    for (let c = 0; c < N; c++) if (p.solution[c] === ch) cells.push(c);
    paths.push(orderedPath(n, cells, p.pairs[k][0], p.pairs[k][1]));
  }
  return paths;
}

const out = { countMismatch: [], msMax: 0, okFail: [], breakCases: [] };
for (let i = 0; i < puzzles.length; i++) {
  const t0 = Date.now();
  const c = MT.countSolutions(puzzles[i], 2);
  out.msMax = Math.max(out.msMax, Date.now() - t0);
  if (c !== 1) out.countMismatch.push([i, c]);
}
for (let i = 0; i < puzzles.length; i++) {
  const p = puzzles[i], paths = buildPaths(p);
  if (paths.some(x => x === null)) { out.okFail.push([i, 'no-order-path']); continue; }
  if (!MT.isComplete(p, paths)) out.okFail.push([i, 'isComplete-false-on-correct']);
}

// 壊した状態
const p0 = puzzles[0];
const base = buildPaths(p0);
{
  const idxLong = base.findIndex(pp => pp.length >= 3);
  const paths = base.map(pp => pp.slice());
  paths[idxLong] = paths[idxLong].slice(0, paths[idxLong].length - 1);
  out.breakCases.push(['1マス空き(端点まで届かない)', MT.isComplete(p0, paths) === false]);
}
{
  const paths = base.map(pp => pp.slice());
  paths[0] = [p0.pairs[0][0]];
  out.breakCases.push(['対が未接続(長さ1)', MT.isComplete(p0, paths) === false]);
}
{
  const paths = base.map(pp => pp.slice());
  paths[0] = paths[1].slice();
  out.breakCases.push(['完全重複path(別対と同一セル群)', MT.isComplete(p0, paths) === false]);
}
{
  // 両端接続だが全マス未被覆(近道)。端点が隣接し元の道が4マス以上ある対を探す
  let found = false;
  for (let i = 0; i < puzzles.length && !found; i++) {
    const p = puzzles[i], n = p.n;
    for (let k = 0; k < p.pairs.length; k++) {
      const [a, b] = p.pairs[k];
      const adj = (Math.abs(a - b) === 1 && Math.floor(a / n) === Math.floor(b / n)) || Math.abs(a - b) === n;
      if (!adj) continue;
      const ch = DIGITS[k];
      let cnt = 0;
      for (let c = 0; c < n * n; c++) if (p.solution[c] === ch) cnt++;
      if (cnt >= 4) {
        const paths = buildPaths(p);
        paths[k] = [a, b];
        out.breakCases.push(['両端接続だが全マス未被覆(近道) puzzles[' + i + ']', MT.isComplete(p, paths) === false]);
        found = true;
        break;
      }
    }
  }
}
console.log(JSON.stringify(out));
"""

STORAGE_TEST_JS = r"""
const fs = require('fs');
const vm = require('vm');

class El {
  constructor(tag) {
    this.tag = tag; this.children = []; this.attrs = {};
    this._className = ''; this._textContent = ''; this._listeners = {};
    this.dataset = {}; this.disabled = false; this.hidden = false;
  }
  get childNodes() { return this.children; }
  get firstChild() { return this.children.length ? this.children[0] : null; }
  appendChild(c) { this.children.push(c); return c; }
  removeChild(c) { const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); return c; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k]; }
  addEventListener(ev, fn) { (this._listeners[ev] = this._listeners[ev] || []).push(fn); }
  get className() { return this._className; }
  set className(v) { this._className = v; }
  get textContent() { return this._textContent; }
  set textContent(v) { this._textContent = v; }
  getBoundingClientRect() { return { left: 0, top: 0, width: 0, height: 0 }; }
  setPointerCapture() {}
  querySelectorAll(sel) {
    const cls = sel.replace('.', ''); const out = [];
    (function walk(node) {
      if (node._className && node._className.split(' ').indexOf(cls) >= 0) out.push(node);
      for (const c of node.children || []) walk(c);
    })(this);
    return out;
  }
}
function makeDocument() {
  const byId = {};
  ['title', 'board', 'svg', 'undo', 'reset', 'clear', 'next', 'msg', 'levels'].forEach(id => {
    const e = new El(id === 'svg' ? 'svg' : 'div'); byId[id] = e;
  });
  return { getElementById: (id) => byId[id] || null, createElement: (t) => new El(t), createElementNS: (ns, t) => new El(t), _byId: byId };
}
function makeLocalStorage(behavior) {
  const store = {};
  return {
    getItem(k) { if (behavior.getThrows) throw new Error('boom-get'); if ('raw' in behavior) return behavior.raw; return store[k] !== undefined ? store[k] : null; },
    setItem(k, v) { if (behavior.setThrows) throw new Error('boom-set'); store[k] = v; },
    removeItem(k) { delete store[k]; },
  };
}
function runOnce(logicSrc, screenSrc, raw, behavior) {
  behavior = behavior || {};
  if (raw !== undefined) behavior.raw = raw;
  const doc = makeDocument();
  const ctx = { console, document: doc, localStorage: makeLocalStorage(behavior), window: {} };
  ctx.window.scrollTo = () => {};
  vm.createContext(ctx);
  vm.runInContext(logicSrc, ctx);
  vm.runInContext(screenSrc, ctx);
  return ctx;
}

const logicSrc = fs.readFileSync(process.argv[2], 'utf8');
const screenSrc = fs.readFileSync(process.argv[3], 'utf8');
const cases = [
  ['非JSON文字列', '{not json', {}],
  ['last が小数2.5', JSON.stringify({ cleared: {}, last: 2.5, paths: {} }), {}],
  ['last が負', JSON.stringify({ cleared: {}, last: -1, paths: {} }), {}],
  ['last が範囲外(9999)', JSON.stringify({ cleared: {}, last: 9999, paths: {} }), {}],
  ['paths が配列', JSON.stringify({ cleared: {}, last: 0, paths: [1, 2, 3] }), {}],
  ['pathsの中身が壊れた文字列', JSON.stringify({ cleared: {}, last: 0, paths: { '0': 'xx.yy|zz|garbage|' } }), {}],
  ['cleared が文字列', JSON.stringify({ cleared: 'oops', last: 0, paths: {} }), {}],
  ['トップレベルが配列', JSON.stringify([1, 2, 3]), {}],
  ['トップレベルがnull', 'null', {}],
  ['getItemが例外', undefined, { getThrows: true }],
  ['setItemが例外', undefined, { setThrows: true }],
  ['lastが文字列"3"', JSON.stringify({ cleared: {}, last: "3", paths: {} }), {}],
];
const out = { fails: [], passNames: [] };
for (const [name, raw, behavior] of cases) {
  try {
    const ctx = runOnce(logicSrc, screenSrc, raw, behavior);
    const title = ctx.document._byId.title.textContent;
    if (!title) out.fails.push([name, '起動したがtitleが空']);
    else out.passNames.push(name);
  } catch (e) {
    out.fails.push([name, String(e && e.stack ? e.stack.split('\n')[0] : e)]);
  }
}
console.log(JSON.stringify(out));
"""


def extract_scripts(index_html_path):
    src = open(index_html_path, encoding="utf-8").read()
    scripts = re.findall(r"<script>(.*?)</script>", src, re.S)
    if len(scripts) < 2:
        raise SystemExit("index.htmlの<script>が2本見つからない")
    return scripts[0], scripts[1]


def check_embed_drift(index_html_path, puzzles_json_path):
    src = open(index_html_path, encoding="utf-8").read()
    m = re.search(r"var PUZZLES = \[(.*?)\];", src, re.S)
    if not m:
        return False, "PUZZLESブロックが見つからない"
    embedded = json.loads("[" + m.group(1) + "]")
    j = load_puzzles(puzzles_json_path)
    if len(embedded) != len(j):
        return False, "件数不一致 embed=%d json=%d" % (len(embedded), len(j))
    diffs = [i for i in range(len(j)) if embedded[i] != j[i]]
    if diffs:
        return False, "差分 idx=%s" % diffs[:5]
    return True, "index.html埋め込み = tools/puzzles.json 完全一致"


def node_available():
    return shutil.which("node") is not None


def run_js_logic_check(puzzles_path, logic_src):
    with tempfile.TemporaryDirectory() as td:
        logic_path = os.path.join(td, "logic.js")
        test_path = os.path.join(td, "test_logic.js")
        with open(logic_path, "w", encoding="utf-8") as f:
            f.write(logic_src)
        with open(test_path, "w", encoding="utf-8") as f:
            f.write(LOGIC_TEST_JS)
        p = subprocess.run(["node", test_path, logic_path, puzzles_path],
                            capture_output=True, text=True, timeout=60)
        if p.returncode != 0:
            return None, p.stderr
        return json.loads(p.stdout.strip().splitlines()[-1]), None


def run_js_storage_check(logic_src, screen_src):
    with tempfile.TemporaryDirectory() as td:
        logic_path = os.path.join(td, "logic.js")
        screen_path = os.path.join(td, "screen.js")
        test_path = os.path.join(td, "test_storage.js")
        open(logic_path, "w", encoding="utf-8").write(logic_src)
        open(screen_path, "w", encoding="utf-8").write(screen_src)
        open(test_path, "w", encoding="utf-8").write(STORAGE_TEST_JS)
        p = subprocess.run(["node", test_path, logic_path, screen_path],
                            capture_output=True, text=True, timeout=60)
        if p.returncode != 0:
            return None, p.stderr
        return json.loads(p.stdout.strip().splitlines()[-1]), None


def main():
    puzzles_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(PROJECT, "tools", "puzzles.json")
    index_html_path = os.path.join(PROJECT, "index.html")
    puzzles = load_puzzles(puzzles_path)

    print("=== 1) 独自ソルバーで解数チェック ===")
    fails = []
    node_records = []
    t0 = time.time()
    for i, p in enumerate(puzzles):
        s = Solver(p["n"], p["pairs"])
        r = s.solve(limit=2)
        node_records.append((i, p["tier"], r["nodes"], p["nodes"]))
        if r["cap"]:
            fails.append((i, "打ち切り(maxnodes到達) nodes=%d" % r["nodes"]))
            continue
        if r["count"] != 1:
            fails.append((i, "解の数=%d" % r["count"]))
            continue
        got_sol = owner_to_solution(r["first"])
        if got_sol != p["solution"]:
            fails.append((i, "solution不一致 got=%s want=%s" % (got_sol, p["solution"])))
    dt = time.time() - t0
    if fails:
        print("FAIL 解数/一致チェック: %d件" % len(fails))
        for i, why in fails[:10]:
            print("  idx=%d: %s" % (i, why))
    else:
        print("PASS 40/40 解=1・自前ソルバーの解がsolutionと一致 (計%.1fs)" % dt)

    print("\n=== 2) 盤面妥当性 ===")
    v_fails = []
    for i, p in enumerate(puzzles):
        for e in check_board_validity(p):
            v_fails.append((i, e))
    if v_fails:
        print("FAIL 盤面妥当性: %d件" % len(v_fails))
        for i, e in v_fails[:20]:
            print("  idx=%d: %s" % (i, e))
    else:
        print("PASS 端点2つずつ・solution全マス被覆・各対連結・1マス道なし")

    walk_fails = []
    nb_cache = {}
    for i, p in enumerate(puzzles):
        n = p["n"]
        if n not in nb_cache:
            nb_cache[n] = neighbors(n)
        nb = nb_cache[n]
        N = n * n
        sol = p["solution"]
        for k, (a, b) in enumerate(p["pairs"]):
            ch = DIGITS[k]
            cells = [c for c in range(N) if sol[c] == ch]
            if not walkable_independent(n, cells, a, b, nb):
                walk_fails.append((i, k))
    print(("FAIL 一筆で歩けない対: %s" % walk_fails[:10]) if walk_fails
          else "PASS 全対が端から端まで一筆で歩ける（自己接触込み）")

    keys = [(p["n"], tuple(map(tuple, p["pairs"])), p["solution"]) for p in puzzles]
    dup = len(keys) != len(set(keys))
    print(("FAIL" if dup else "PASS") + " 盤面文字列の重複なし (dup=%s)" % dup)

    ok, msg = check_embed_drift(index_html_path, puzzles_path)
    print(("PASS " if ok else "FAIL ") + msg)

    print("\n=== 3) 難度ノード数（自前ソルバーの実測） ===")
    by_tier = {}
    for i, tier, mynodes, embednodes in node_records:
        by_tier.setdefault(tier, []).append((i, mynodes, embednodes))
    order = ["入門", "初級", "中級", "上級"]
    for t in order:
        rows = by_tier.get(t, [])
        mine = sorted(r[1] for r in rows)
        emb = sorted(r[2] for r in rows)
        print("%s: n=%d件  自前nodes %d〜%d(中央%d)  embed nodes %d〜%d" % (
            t, len(rows), mine[0], mine[-1], mine[len(mine)//2], emb[0], emb[-1]))

    spec_ranges = {"入門": (0, 120), "初級": (80, 1200), "中級": (300, 5000), "上級": (3000, None)}
    range_fail = []
    for i, tier, mynodes, embednodes in node_records:
        lo, hi = spec_ranges[tier]
        if embednodes < lo or (hi is not None and embednodes > hi):
            range_fail.append((i, tier, embednodes))
    print(("FAIL spec.md閾値を外れる問題: %s" % range_fail) if range_fail
          else "PASS 40問ともspec.md記載の閾値範囲内")

    medians = []
    for t in order:
        rows = by_tier.get(t, [])
        if not rows:
            continue
        mine = sorted(r[1] for r in rows)
        medians.append((t, mine[len(mine)//2]))
    inv = any(medians[i][1] >= medians[i+1][1] for i in range(len(medians)-1))
    print(("FAIL" if inv else "PASS") + " 自前nodes中央値の段階順が単調増加 %s" % medians)

    pair_ranges = {}
    for p in puzzles:
        pair_ranges.setdefault(p["n"], []).append(len(p["pairs"]))
    print("対の数レンジ(実測): " + " / ".join(
        "n=%d:%d-%d" % (n, min(v), max(v)) for n, v in sorted(pair_ranges.items())))

    print("\n=== 4) JSロジック（Node実走） ===")
    if not node_available():
        print("SKIP nodeコマンドが見つからない")
    else:
        logic_src, screen_src = extract_scripts(index_html_path)
        res, err = run_js_logic_check(puzzles_path, logic_src)
        if err:
            print("FAIL Node実行エラー: %s" % err[:500])
        else:
            print(("FAIL countSolutions!=1: %s" % res["countMismatch"]) if res["countMismatch"]
                  else "PASS countSolutions 40/40 が1（最長%dms）" % res["msMax"])
            print(("FAIL isComplete(正解)がfalse: %s" % res["okFail"]) if res["okFail"]
                  else "PASS isComplete(正解) 40/40 true")
            for name, passed in res["breakCases"]:
                print(("PASS " if passed else "FAIL ") + "isComplete(壊れ状態): " + name)

        print("\n=== 5) localStorage 壊れ値（最小DOMスタブでNode実走） ===")
        res2, err2 = run_js_storage_check(logic_src, screen_src)
        if err2:
            print("FAIL Node実行エラー: %s" % err2[:500])
        elif res2["fails"]:
            print("FAIL %d件クラッシュ/異常:" % len(res2["fails"]))
            for name, why in res2["fails"]:
                print("  FAIL %s :: %s" % (name, why))
        else:
            print("PASS 全%d ケースで起動時クラッシュなし" % len(res2["passNames"]))


if __name__ == "__main__":
    main()
