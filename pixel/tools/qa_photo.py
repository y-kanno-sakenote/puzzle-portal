#!/usr/bin/env python3
# 担当: qa係 独立検証スクリプト（photo.html を直接読み込み、実装者コードを再利用せず検証）
#
# 実行: python3 tools/qa_photo.py
# 前提: node が使えること（photo.html の先頭 <script>＝PixelPhoto を node の vm で実走する）
#
# 検証項目（依頼の1〜6に対応）:
#   1. ラインソルバー: 自前(全パターン列挙)ソルバー(line_forced系) vs PixelPhoto.lineSolve/solveMetrics
#      index.html 43問 + ランダム二値画像 402枚(15/20/25、白色ノイズ/なめらかブロブ)
#   2. 修復ループ: 反転数が6%上限を超えないか・反転後に実際に解けるか・反転マスがしきい値付近から選ばれているか
#   3. 共有ハッシュ: encode/decode 往復402件 + 壊れハッシュ15パターン + URL長
#   4. 難度ラベル: なめらか乱数画像(otsu二値化→必要ならrepair) 各N100枚でDの分布を実測し、
#      現行の固定閾値(入門<=118/初級<=128/中級<=156/上級)での偏りを見る
#   5. localStorage 'pixel-photo' 壊れ値 16パターンで例外が出ないか（vm+DOMスタブ）
#   6. 写真本体を保存・送信していないか（コード読解: grepで確認）
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
from itertools import product  # noqa: F401 (line_forced 系で使用しないが将来の拡張用に保持しない: 実際は未使用)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHOTO_HTML = os.path.join(ROOT, 'photo.html')

# ---------------------------------------------------------------- 自前ラインソルバー(全パターン列挙・qa_indep.py 系を再実装)
UNK, BLACK, WHITE = -1, 1, 0

def gen_arrangements(hints, length):
    if hints == [0]:
        return [tuple([0] * length)]
    blocks = hints
    n = len(blocks)
    total_block = sum(blocks)
    slack = length - total_block - (n - 1)
    if slack < 0:
        return []
    results = []

    def rec2(i, pos, arr, budget):
        if i == n:
            results.append(tuple(arr + [0] * (length - pos)))
            return
        min_gap = 1 if i > 0 else 0
        for extra in range(0, budget + 1):
            gap = min_gap + extra
            newpos = pos + gap
            newarr = arr + [0] * gap + [1] * blocks[i]
            rec2(i + 1, newpos + blocks[i], newarr, budget - extra)

    rec2(0, 0, [], slack)
    return results


def line_forced(hints, length, known):
    arrs = gen_arrangements(hints, length)
    valid = [a for a in arrs if all(known[i] == UNK or known[i] == a[i] for i in range(length))]
    if not valid:
        return None
    forced = list(known)
    for i in range(length):
        vals = set(a[i] for a in valid)
        if len(vals) == 1:
            forced[i] = vals.pop()
    return forced


def solve_line_iter(row_hints, col_hints, w, h):
    """行・列の反復伝播のみ（仮定なし）。戻り値: (ok, grid) grid は UNK混じりの最終盤面。矛盾なら (False, None)"""
    grid = [[UNK] * w for _ in range(h)]
    while True:
        changed = 0
        for r in range(h):
            row = grid[r]
            forced = line_forced(row_hints[r], w, row)
            if forced is None:
                return False, None
            for c in range(w):
                if forced[c] != UNK and grid[r][c] == UNK:
                    grid[r][c] = forced[c]
                    changed += 1
        for c in range(w):
            col = [grid[r][c] for r in range(h)]
            forced = line_forced(col_hints[c], h, col)
            if forced is None:
                return False, None
            for r in range(h):
                if forced[r] != UNK and grid[r][c] == UNK:
                    grid[r][c] = forced[r]
                    changed += 1
        if changed == 0:
            break
    flat = [grid[r][c] for r in range(h) for c in range(w)]
    ok = all(v != UNK for v in flat)
    return ok, flat


def hints_of_bits(bits, w, h):
    row_hints = []
    for r in range(h):
        row = bits[r * w:(r + 1) * w]
        arr, cur = [], 0
        for ch in row:
            if ch == '1':
                cur += 1
            elif cur:
                arr.append(cur); cur = 0
        if cur:
            arr.append(cur)
        row_hints.append(arr if arr else [0])
    col_hints = []
    for c in range(w):
        col = ''.join(bits[r * w + c] for r in range(h))
        arr, cur = [], 0
        for ch in col:
            if ch == '1':
                cur += 1
            elif cur:
                arr.append(cur); cur = 0
        if cur:
            arr.append(cur)
        col_hints.append(arr if arr else [0])
    return row_hints, col_hints


# ---------------------------------------------------------------- node 経由で PixelPhoto (photo.html 先頭 <script>) を呼ぶ
def extract_pixelphoto_js():
    html = open(PHOTO_HTML, encoding='utf-8').read()
    blocks = re.findall(r'<script>([\s\S]*?)</script>', html)
    assert len(blocks) == 2, f'expected 2 <script> blocks in photo.html, got {len(blocks)}'
    logic_js, ui_js = blocks
    assert 'window.PixelPhoto = PixelPhoto' in logic_js
    # solveMetrics をテスト用に export へ追加（photo.html 自体は変更しない。node 実行用コピーのみ）
    logic_js = logic_js.replace('lineSolve: lineSolve,', 'lineSolve: lineSolve,\n    solveMetrics: solveMetrics,')
    return logic_js, ui_js


def run_node(js_src, node_args=None):
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as f:
        f.write(js_src)
        path = f.name
    try:
        r = subprocess.run(['node', path] + (node_args or []), capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise RuntimeError('node failed: ' + r.stderr[-4000:])
        return r.stdout
    finally:
        os.unlink(path)


def js_module_wrapper(logic_js):
    return logic_js  # 既に module.exports = PixelPhoto を含む


# ================================================================ 1. ラインソルバー突き合わせ
def check_line_solver(logic_js):
    print('\n=== 1. ラインソルバー突き合わせ ===')
    puzzles = json.load(open(os.path.join(ROOT, 'tools', 'puzzles.json')))
    tmpdir = tempfile.mkdtemp()
    logic_path = os.path.join(tmpdir, 'pixelphoto_logic.js')
    open(logic_path, 'w', encoding='utf-8').write(logic_js)

    # --- 43問 ---
    runner = """
const P = require(process.argv[2]);
const puzzles = JSON.parse(require('fs').readFileSync(process.argv[3], 'utf-8'));
const out = puzzles.map(p => {
  const grid = P.lineSolve(p.rowHints, p.colHints, p.w, p.h);
  const sol = grid ? grid.map(v => v===1?'1':'0').join('') : null;
  return { no: p.no, ok: !!grid, matches: grid ? sol === p.solution : null };
});
console.log(JSON.stringify(out));
"""
    out = json.loads(run_node(runner, [logic_path, os.path.join(ROOT, 'tools', 'puzzles.json')]))
    not_solved = [r for r in out if not r['ok']]
    mismatch = [r for r in out if r['ok'] and not r['matches']]
    print(f'  index.html 43問: JSラインソルバーで解けなかった={len(not_solved)}, 解は出たが不一致={len(mismatch)}')

    # --- ランダム画像 402枚 (白色ノイズ + なめらかブロブ, N=15/20/25) ---
    rng = random.Random(1)
    items = []
    idx = 0
    for N in (15, 20, 25):
        for _ in range(67):
            bits = ''.join(rng.choice('01') for _ in range(N * N))
            idx += 1
            rh, ch = hints_of_bits(bits, N, N)
            items.append({'id': idx, 'w': N, 'h': N, 'rowHints': rh, 'colHints': ch})
    rng2 = random.Random(2)
    for N in (15, 20, 25):
        for _ in range(67):
            cx, cy = rng2.uniform(N * 0.3, N * 0.7), rng2.uniform(N * 0.3, N * 0.7)
            rad = rng2.uniform(min(N, N) * 0.2, min(N, N) * 0.45)
            bits = ''
            for r in range(N):
                for c in range(N):
                    d = math.hypot(c + 0.5 - cx, r + 0.5 - cy) + rng2.uniform(-1.2, 1.2)
                    bits += '1' if d < rad else '0'
            idx += 1
            rh, ch = hints_of_bits(bits, N, N)
            items.append({'id': idx, 'w': N, 'h': N, 'rowHints': rh, 'colHints': ch})

    items_path = os.path.join(tmpdir, 'items.json')
    json.dump(items, open(items_path, 'w'))
    runner2 = """
const P = require(process.argv[2]);
const items = JSON.parse(require('fs').readFileSync(process.argv[3], 'utf-8'));
const out = items.map(it => {
  const m = P.solveMetrics(it.rowHints, it.colHints, it.w, it.h);
  return { id: it.id, ok: m.ok, grid: m.grid };
});
console.log(JSON.stringify(out));
"""
    js_out = {r['id']: r for r in json.loads(run_node(runner2, [logic_path, items_path]))}

    ok_mismatch, grid_mismatch, contradictions = 0, 0, 0
    for it in items:
        py_ok, py_grid = solve_line_iter(it['rowHints'], it['colHints'], it['w'], it['h'])
        j = js_out[it['id']]
        if py_grid is None:
            contradictions += 1
            continue
        if py_ok != j['ok']:
            ok_mismatch += 1
        elif py_ok and py_grid != j['grid']:
            grid_mismatch += 1
    print(f'  ランダム402枚: 自前ソルバーで矛盾={contradictions}, 解けた/解けない判定の不一致={ok_mismatch}, 解の不一致={grid_mismatch}')
    shutil.rmtree(tmpdir)
    return len(not_solved) == 0 and len(mismatch) == 0 and contradictions == 0 and ok_mismatch == 0 and grid_mismatch == 0


# ================================================================ 2. 修復ループ
def check_repair(logic_js):
    print('\n=== 2. 修復ループ ===')
    tmpdir = tempfile.mkdtemp()
    logic_path = os.path.join(tmpdir, 'pixelphoto_logic.js')
    open(logic_path, 'w', encoding='utf-8').write(logic_js)

    rng = random.Random(7)
    items = []
    idx = 0
    for N in (15, 20, 25):
        for _ in range(20):
            gray = [rng.uniform(0, 255) for _ in range(N * N)]
            thr = 128
            bits = ''.join('1' if g < thr else '0' for g in gray)
            idx += 1
            items.append({'id': idx, 'w': N, 'h': N, 'bits': bits, 'gray': gray})
    items_path = os.path.join(tmpdir, 'items.json')
    json.dump(items, open(items_path, 'w'))

    runner = """
const P = require(process.argv[2]);
const items = JSON.parse(require('fs').readFileSync(process.argv[3], 'utf-8'));
const out = items.map(it => {
  const hs0 = P.hints(it.bits, it.w, it.h);
  const m0 = P.solveMetrics(hs0.rowHints, hs0.colHints, it.w, it.h);
  const maxFlips = Math.round(it.w * it.h * 0.06);
  if (m0.ok) return { id: it.id, alreadyOk: true };
  const rep = P.repair(it.bits, it.gray, it.w, it.h, maxFlips);
  if (!rep) return { id: it.id, alreadyOk: false, gaveUp: true, maxFlips };
  const flipped = [];
  for (let i = 0; i < it.bits.length; i++) if (it.bits.charAt(i) !== rep.bits.charAt(i)) flipped.push(i);
  const hs = P.hints(rep.bits, it.w, it.h);
  const mf = P.solveMetrics(hs.rowHints, hs.colHints, it.w, it.h);
  return { id: it.id, alreadyOk: false, gaveUp: false, flips: rep.flips, flippedIdx: flipped, finalSolves: mf.ok, maxFlips };
});
console.log(JSON.stringify(out));
"""
    out = {r['id']: r for r in json.loads(run_node(runner, [logic_path, items_path]))}
    items_by_id = {it['id']: it for it in items}

    needed = [r for r in out.values() if not r.get('alreadyOk')]
    gaveup = [r for r in needed if r.get('gaveUp')]
    repaired = [r for r in needed if not r.get('gaveUp')]
    over_limit = [r for r in repaired if r['flips'] > r['maxFlips']]
    not_solved = [r for r in repaired if not r['finalSolves']]

    total_flips = sum(r['flips'] for r in repaired)
    far_flips = 0
    for r in repaired:
        it = items_by_id[r['id']]
        gray, thr = it['gray'], 128
        devs = sorted(abs(g - thr) for g in gray)
        n = len(devs)
        for i in r['flippedIdx']:
            d = abs(gray[i] - thr)
            rank = sum(1 for x in devs if x <= d) / n
            if rank > 0.5:
                far_flips += 1

    print(f'  60枚中、修復不要={len(items)-len(needed)}, 修復要={len(needed)}, 諦め={len(gaveup)}, 修復成功={len(repaired)}')
    print(f'  6%上限超過={len(over_limit)}, 修復後に実際は解けない={len(not_solved)}')
    print(f'  反転総数={total_flips}, うち中央値より外側(遠い)の反転={far_flips} ({100*far_flips/total_flips:.1f}%)' if total_flips else '  反転総数=0')
    shutil.rmtree(tmpdir)
    return len(over_limit) == 0 and len(not_solved) == 0


# ================================================================ 3. 共有ハッシュ
def check_hash(logic_js):
    print('\n=== 3. 共有ハッシュ ===')
    tmpdir = tempfile.mkdtemp()
    logic_path = os.path.join(tmpdir, 'pixelphoto_logic.js')
    open(logic_path, 'w', encoding='utf-8').write(logic_js)

    runner = """
const P = require(process.argv[2]);
function randBits(n){ let s=''; for(let i=0;i<n;i++) s+= Math.random()<0.5?'1':'0'; return s; }
const poolArr = Array.from('写真日本語タイトルAaBb0123 🍣<>&\\".v1_-');
function randTitle(){ const len=Math.floor(Math.random()*21); let s=''; for(let i=0;i<len;i++) s+=poolArr[Math.floor(Math.random()*poolArr.length)]; return s; }
let n=0, mismatches=[];
for (const N of [15,20,25]) {
  for (let i=0;i<134;i++) {
    n++;
    const bits = randBits(N*N);
    const title = randTitle();
    const h = P.encode(bits, N, N, title);
    const d = P.decode(h);
    if (!d) { mismatches.push('decode null'); continue; }
    if (d.bits !== bits || d.w !== N || d.h !== N) mismatches.push('bits/w/h mismatch');
    const expectTitle = ((title || '写真').slice(0,30)) || '写真';
    if (d.title !== expectTitle) mismatches.push('title mismatch');
  }
}
const results = { roundtrip_total: n, roundtrip_mismatches: mismatches.length };

// 壊れハッシュ
const cases = [
  '#v1.20.20.' + 'A'.repeat(10) + '.t',
  '#v1.20.20.' + '!'.repeat(66) + '.t',
  '', '#', 'garbage',
  '#v2.20.20.' + 'A'.repeat(66) + '.t',
  '#v1.2.2.AAA.t',
  '#v1.100.100.' + 'A'.repeat(2000) + '.t',
  '#v1.20.20',
  null, undefined, 12345,
  '#v1.NaN.20.' + 'A'.repeat(66) + '.t',
];
let thrown = 0, notNull = 0;
for (const c of cases) {
  try { const d = P.decode(c); if (d !== null) notNull++; } catch(e) { thrown++; }
}
results.malformed_thrown = thrown;
results.malformed_not_rejected = notNull;

// encode の lone-surrogate 例外有無（クリップボード等からの壊れ文字列を想定）
let encodeThrows = false;
try { P.encode('1'.repeat(400), 20, 20, '\\uD83C'); } catch(e) { encodeThrows = true; }
results.encode_throws_on_lone_surrogate = encodeThrows;

// URL長 (25x25 + 20字題名)
const bits25 = '1'.repeat(625);
const longTitle = 'あ'.repeat(20);
const hash = P.encode(bits25, 25, 25, longTitle);
results.hash_len_25x25_20char = hash.length;

console.log(JSON.stringify(results));
"""
    r = json.loads(run_node(runner, [logic_path]))
    print(f"  往復402件: mismatches={r['roundtrip_mismatches']}")
    print(f"  壊れハッシュ13件: 例外={r['malformed_thrown']}, null以外を返した={r['malformed_not_rejected']}")
    print(f"  encode()にlone surrogate titleを渡すと例外: {r['encode_throws_on_lone_surrogate']}")
    print(f"  25x25+20字題名のハッシュ長: {r['hash_len_25x25_20char']} 文字")
    shutil.rmtree(tmpdir)
    return r['roundtrip_mismatches'] == 0 and r['malformed_thrown'] == 0 and r['malformed_not_rejected'] == 0


# ================================================================ 4. 難度ラベル
def check_tier_distribution(logic_js):
    print('\n=== 4. 難度ラベルの分布（なめらか乱数ブロブ、実運用と同じ otsu+repair 経路） ===')
    tmpdir = tempfile.mkdtemp()
    logic_path = os.path.join(tmpdir, 'pixelphoto_logic.js')
    open(logic_path, 'w', encoding='utf-8').write(logic_js)

    rng = random.Random(42)
    items = []
    idx = 0
    for N in (15, 20, 25):
        for _ in range(100):
            cx = rng.uniform(N * 0.3, N * 0.7)
            cy = rng.uniform(N * 0.3, N * 0.7)
            rad = rng.uniform(N * 0.2, N * 0.42)
            noise_amp = rng.uniform(0.5, 2.0)
            gray = []
            for r in range(N):
                for c in range(N):
                    d = math.hypot(c + 0.5 - cx, r + 0.5 - cy)
                    v = (d - rad) * (255.0 / (N * 0.15))
                    v += rng.uniform(-noise_amp * 10, noise_amp * 10)
                    gray.append(max(0, min(255, v)))
            idx += 1
            items.append({'id': idx, 'w': N, 'h': N, 'gray': gray})
    items_path = os.path.join(tmpdir, 'items.json')
    json.dump(items, open(items_path, 'w'))

    runner = """
const P = require(process.argv[2]);
const items = JSON.parse(require('fs').readFileSync(process.argv[3], 'utf-8'));
const out = items.map(it => {
  const N = it.w;
  const g = P.stretch(it.gray);
  const thr = P.otsu(g);
  let bits = P.binarize(g, N, thr);
  let hs = P.hints(bits, N, N);
  let m = P.solveMetrics(hs.rowHints, hs.colHints, N, N);
  if (!m.ok) {
    const rep = P.repair(bits, g, N, N, Math.round(N*N*0.06));
    if (rep) { bits = rep.bits; hs = P.hints(bits, N, N); m = P.solveMetrics(hs.rowHints, hs.colHints, N, N); }
  }
  return { id: it.id, N: N, ok: m.ok, D: m.D, tier: m.ok ? P.tierOf(m.D) : null };
});
console.log(JSON.stringify(out));
"""
    out = json.loads(run_node(runner, [logic_path, items_path]))
    from collections import Counter, defaultdict
    by_n = defaultdict(list)
    for r in out:
        by_n[r['N']].append(r)
    for N in (15, 20, 25):
        rows = [r for r in by_n[N] if r['ok']]
        tiers = Counter(r['tier'] for r in rows)
        ds = sorted(r['D'] for r in rows)
        n = len(ds)
        def pct(p):
            return ds[min(n - 1, int(n * p))] if n else None
        print(f'  N={N}: playable={n}/100  tier分布={dict(tiers)}')
        if n:
            print(f'    D: min={ds[0]} p25={pct(0.25)} p50={pct(0.5)} p75={pct(0.75)} max={ds[-1]}  -> 提案閾値(この実測に基づく): 入門<= {pct(0.25)} / 初級<= {pct(0.5)} / 中級<= {pct(0.75)} / 上級> {pct(0.75)}')
    shutil.rmtree(tmpdir)


# ================================================================ 5. localStorage 壊れ値
def check_localstorage(ui_js, logic_js):
    print('\n=== 5. localStorage壊れ値 (vm+DOMスタブ) ===')
    dom_stub = r"""
const fs = require('fs');
const vm = require('vm');
const logicSrc = fs.readFileSync(process.argv[2], 'utf-8');
const uiSrc = fs.readFileSync(process.argv[3], 'utf-8');

class El {
  constructor(tag){ this.tagName=(tag||'div').toUpperCase(); this._children=[]; this.dataset={}; this._classes=new Set();
    this._hidden=false; this._innerHTML=''; this.style={}; this.value=''; this.textContent=''; this.width=0; this.height=0; }
  get children(){ return this._children; }
  get childNodes(){ return this._children; }
  get classList(){ const self=this; return { add:(...c)=>c.forEach(x=>self._classes.add(x)), remove:(...c)=>c.forEach(x=>self._classes.delete(x)),
    toggle:(c,f)=>{ if(f===undefined){ self._classes.has(c)?self._classes.delete(c):self._classes.add(c);} else if(f) self._classes.add(c); else self._classes.delete(c);},
    contains:(c)=>self._classes.has(c) }; }
  set className(v){ this._classes=new Set(String(v).split(' ').filter(Boolean)); }
  get className(){ return Array.from(this._classes).join(' '); }
  set hidden(v){ this._hidden=v; } get hidden(){ return this._hidden; }
  set innerHTML(v){ this._innerHTML=v; this._children=[]; } get innerHTML(){ return this._innerHTML; }
  appendChild(c){ this._children.push(c); return c; }
  addEventListener(){} removeEventListener(){} setPointerCapture(){} closest(){return null;} contains(){return false;}
  getContext(){ return { fillRect(){}, drawImage(){}, getImageData(){return {data:new Uint8ClampedArray(4)};}, clearRect(){} }; }
  toDataURL(){ return 'data:image/jpeg;base64,'; }
  getBoundingClientRect(){ return {width:100,height:100,left:0,top:0}; }
}
function makeDoc(){
  const ids = ['screenPick','screenCrop','screenPlay','levelName','zoomBtn','fileInput','pickBtn','pickMsg','cropCanvas',
    'previewCanvas','zoomRange','sizeSeg','thrRange','thrLabel','invertBtn','autoThrBtn','titleInput','makeBtn','rePickBtn',
    'backToPlayBtn','makeMsg','stageWrapper','grid','colHints','rowHints','clearBanner','artTitle','compare','artCanvas',
    'photoCanvas','photoFig','modeFill','modeCross','undoBtn','resetBtn','shareBtn','againBtn','toast','made','madeList'];
  const els={}; for(const id of ids){ els[id]=new El('div'); els[id].id=id; }
  for(let i=0;i<3;i++) els['sizeSeg'].appendChild(new El('button'));
  return { getElementById:(id)=>els[id]||null, createElement:(t)=>new El(t), addEventListener:()=>{}, body:new El('body') };
}
function runOnce(raw, opts){
  opts=opts||{};
  const storage = { getItem:()=>{ if(opts.getItemThrows) throw new Error('getItem boom'); return raw; },
    setItem:()=>{ if(opts.setItemThrows) throw new Error('setItem boom'); }, removeItem:()=>{} };
  const doc = makeDoc();
  const windowStub = { innerWidth:400, scrollTo:()=>{}, addEventListener:()=>{}, location:{hash:'',origin:'https://x',pathname:'/p.html'},
    navigator:{share:undefined, clipboard:undefined}, localStorage:storage, document:doc, console, URL:{createObjectURL:()=>'blob:x',revokeObjectURL:()=>{}},
    Image:function(){this.addEventListener=()=>{};}, setTimeout:(fn)=>fn() };
  const ctx = { window: windowStub, document: doc, localStorage: storage, location: windowStub.location, navigator: windowStub.navigator,
    console, setTimeout: windowStub.setTimeout, URL: windowStub.URL, Image: windowStub.Image, Math, JSON, Date, Array, Object, String,
    Number, RegExp, Promise, Uint8ClampedArray, module: undefined };
  vm.createContext(ctx);
  try { vm.runInContext(logicSrc, ctx); vm.runInContext(uiSrc, ctx); return null; } catch(e) { return e.message; }
}
const cases = [
  ['null未使用', null], ['壊れJSON', '{not json'], ['空文字', ''], ['配列直書き', '[1,2,3]'],
  ['madeがオブジェクト', JSON.stringify({made:{foo:'bar'},progress:{}})],
  ['madeが文字列', JSON.stringify({made:'oops',progress:{}})],
  ['made.bitsが数値', JSON.stringify({made:[{bits:123,w:20,h:20,title:'t',tier:'中級',date:'2026-01-01'}],progress:{}})],
  ['made.bits長さ不一致', JSON.stringify({made:[{bits:'101',w:20,h:20,title:'t',tier:'中級',date:'2026-01-01'}],progress:{}})],
  ['made.wが0', JSON.stringify({made:[{bits:'',w:0,h:0,title:'t',tier:'中級',date:'2026-01-01'}],progress:{}})],
  ['progressが配列', JSON.stringify({made:[],progress:[1,2,3]})],
  ['トップレベル配列', JSON.stringify([1,2,3])], ['トップレベル文字列', JSON.stringify('hello')], ['トップレベル数値', JSON.stringify(12345)],
  ['made21件(上限超過)', JSON.stringify({made:Array.from({length:25},(_,i)=>({bits:'1'.repeat(400),w:20,h:20,title:'t'+i,tier:'中級',date:'2026-01-01'})),progress:{}})],
];
let fails=[];
for (const [label, raw] of cases) { const err = runOnce(raw,{}); if (err) fails.push(label+': '+err); }
for (const [label, opts] of [['getItem throws',{getItemThrows:true}],['setItem throws',{setItemThrows:true}]]) { const err = runOnce('{}',opts); if (err) fails.push(label+': '+err); }
console.log(JSON.stringify({ total: cases.length+2, fails }));
"""
    tmpdir = tempfile.mkdtemp()
    logic_path = os.path.join(tmpdir, 'logic.js')
    ui_path = os.path.join(tmpdir, 'ui.js')
    open(logic_path, 'w', encoding='utf-8').write(logic_js)
    open(ui_path, 'w', encoding='utf-8').write(ui_js)
    r = json.loads(run_node(dom_stub, [logic_path, ui_path]))
    print(f"  {r['total']}パターン中、例外発生={len(r['fails'])}")
    for f in r['fails']:
        print('   FAIL', f)
    shutil.rmtree(tmpdir)
    return len(r['fails']) == 0


# ================================================================ 6. 写真の保存/送信有無
def check_no_photo_leak():
    print('\n=== 6. 写真本体の保存・送信有無（コード読解） ===')
    html = open(PHOTO_HTML, encoding='utf-8').read()
    net_calls = re.findall(r'fetch\(|XMLHttpRequest|WebSocket|sendBeacon', html)
    ls_writes = re.findall(r'localStorage\.setItem\([^)]*\)', html)
    session_photo_in_ls = 'sessionPhotos' in ''.join(ls_writes)
    print(f'  fetch/XHR/WebSocket/sendBeacon 呼び出し数: {len(net_calls)}')
    print(f'  localStorage.setItem 呼び出し: {ls_writes}')
    print(f'  setItem の中に sessionPhotos(写真dataURL) が含まれるか: {session_photo_in_ls}')
    return len(net_calls) == 0 and not session_photo_in_ls


def main():
    logic_js, ui_js = extract_pixelphoto_js()
    results = {}
    results['1_line_solver'] = check_line_solver(logic_js)
    results['2_repair'] = check_repair(logic_js)
    results['3_hash'] = check_hash(logic_js)
    check_tier_distribution(logic_js)  # 数値提示のみ、合否判定はしない(叩き台のため)
    results['5_localstorage'] = check_localstorage(ui_js, logic_js)
    results['6_no_leak'] = check_no_photo_leak()

    print('\n=== まとめ ===')
    for k, v in results.items():
        print(f'  {k}: {"PASS" if v else "FAIL"}')


if __name__ == '__main__':
    main()
