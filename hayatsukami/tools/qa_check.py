#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""担当: qa係
はやつかみ 独立検証スクリプト（実装者の gen_cards.py / index.html のロジックは読んだ上で、
自分の言葉で spec.md から再構成して書く。答え合わせ用に別実装を用いる）。

    python3 qa_check.py
"""
import itertools
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 品は5つ。形と色は1対1（spec.mdより）
SHAPE_TO_COLOR = {
    "ハート": "赤", "しずく": "青", "ほし": "黄", "はっぱ": "緑", "つき": "黒",
}
COLOR_TO_SHAPE = {v: k for k, v in SHAPE_TO_COLOR.items()}
SHAPES = list(SHAPE_TO_COLOR.keys())
COLORS = list(SHAPE_TO_COLOR.values())


def my_answer(motif_a, motif_b):
    """自分の理解（spec.md準拠）で正解を求める。定まらなければ None。
    戻り値: (正解の形, 種類) / None"""
    (sa, ca), (sb, cb) = motif_a, motif_b
    if sa == sb:
        return None  # 形の重複
    if ca == cb:
        return None  # 色の重複
    hits = []
    if SHAPE_TO_COLOR[sa] == ca:
        hits.append(sa)
    if SHAPE_TO_COLOR[sb] == cb:
        hits.append(sb)
    if len(hits) == 2:
        return None  # 上級札（v0.1では使わない）
    if len(hits) == 1:
        return (hits[0], 1)
    # 一致0個: 形としても色としても出ていない品を探す
    mentioned_as_shape = {sa, sb}
    mentioned_as_color_owner = {COLOR_TO_SHAPE[ca], COLOR_TO_SHAPE[cb]}
    untouched = [s for s in SHAPES if s not in mentioned_as_shape and s not in mentioned_as_color_owner]
    if len(untouched) != 1:
        return None
    return (untouched[0], 2)


def enumerate_valid_cards():
    """25通りの絵柄から2つ選ぶ組み合わせを全部作り、採用すべき札集合を独自に求める"""
    motifs = [(s, c) for s in SHAPES for c in COLORS]
    assert len(motifs) == 25
    total = 0
    valid = []  # (frozenset key, a, b, answer, kind)
    kind_tally = {1: 0, 2: 0}
    reject_tally = {"形重複": 0, "色重複": 0, "一致2つ": 0, "定まらない": 0}
    for a, b in itertools.combinations(motifs, 2):
        total += 1
        got = my_answer(a, b)
        if got is None:
            if a[0] == b[0]:
                reject_tally["形重複"] += 1
            elif a[1] == b[1]:
                reject_tally["色重複"] += 1
            else:
                hits = sum(1 for s, c in (a, b) if SHAPE_TO_COLOR[s] == c)
                reject_tally["一致2つ" if hits == 2 else "定まらない"] += 1
            continue
        ans, kind = got
        kind_tally[kind] += 1
        valid.append((a, b, ans, kind))
    return total, valid, kind_tally, reject_tally


def card_key(a, b):
    """向き（a/bの順）を無視した札の同一性キー"""
    return tuple(sorted([tuple(a), tuple(b)]))


def load_embedded_cards(index_html_path):
    src = open(index_html_path, encoding="utf-8").read()
    beg = src.index("/* CARDS-BEGIN")
    beg = src.index("var CARDS = [", beg)
    end = src.index("];", beg) + 1
    js_array_text = src[src.index("[", beg):end]
    return json.loads(js_array_text)


def report(ok, label, detail=""):
    mark = "PASS" if ok else "FAIL"
    print("[%s] %s%s" % (mark, label, ("  " + detail) if detail else ""))
    return ok


def main():
    all_ok = True

    total, valid, kind_tally, reject_tally = enumerate_valid_cards()
    all_ok &= report(total == 300, "組み合わせ総数(自前)", "実測=%d 期待=300 (C(25,2))" % total)

    my_set = {}
    dup = 0
    for a, b, ans, kind in valid:
        k = card_key(a, b)
        if k in my_set:
            dup += 1
        my_set[k] = (ans, kind)
    all_ok &= report(dup == 0, "自前集合に重複札なし", "重複=%d" % dup)
    all_ok &= report(len(my_set) == 120, "自前で採用すべき札の総数", "実測=%d 期待=120" % len(my_set))
    all_ok &= report(kind_tally[1] + kind_tally[2] == len(my_set), "kind内訳の合計一致",
                      "種類1=%d 種類2=%d 合計=%d" % (kind_tally[1], kind_tally[2], sum(kind_tally.values())))
    print("      内訳: 種類1=%d 種類2=%d / 除外内訳=%s" % (kind_tally[1], kind_tally[2], reject_tally))

    # --- cards.json との突合 ---
    cards_json_path = os.path.join(ROOT, "tools", "cards.json")
    cj = json.load(open(cards_json_path, encoding="utf-8"))
    all_ok &= report(len(cj) == 120, "cards.json の枚数", "実測=%d" % len(cj))

    cj_set = {}
    cj_dup = 0
    for c in cj:
        k = card_key(tuple(c["a"]), tuple(c["b"]))
        if k in cj_set:
            cj_dup += 1
        cj_set[k] = (c["answer"], c["kind"])
    all_ok &= report(cj_dup == 0, "cards.json 内に重複札なし", "重複=%d" % cj_dup)

    missing_in_cj = set(my_set) - set(cj_set)
    extra_in_cj = set(cj_set) - set(my_set)
    all_ok &= report(not missing_in_cj and not extra_in_cj, "cards.json ⇔ 自前集合が過不足なく一致",
                      "不足=%d 余剰=%d" % (len(missing_in_cj), len(extra_in_cj)))

    mismatch = [k for k in (set(my_set) & set(cj_set)) if my_set[k] != cj_set[k]]
    all_ok &= report(not mismatch, "answer/kind が一致する札のみ", "不一致=%d件 例=%s" % (len(mismatch), mismatch[:3]))

    # --- index.html 埋め込み CARDS との突合 ---
    index_html_path = os.path.join(ROOT, "index.html")
    embedded = load_embedded_cards(index_html_path)
    all_ok &= report(len(embedded) == 120, "index.html embedded CARDS の枚数", "実測=%d" % len(embedded))
    emb_set = {}
    for c in embedded:
        k = card_key(tuple(c["a"]), tuple(c["b"]))
        emb_set[k] = (c["answer"], c["kind"])
    all_ok &= report(set(emb_set) == set(cj_set), "index.html の CARDS が cards.json と同一集合")
    emb_mismatch = [k for k in (set(my_set) & set(emb_set)) if my_set[k] != emb_set[k]]
    all_ok &= report(not emb_mismatch, "index.html の answer/kind が自前と一致", "不一致=%d件" % len(emb_mismatch))

    # --- JS側 (answerOf / isValidCard) の実走テスト ---
    js_ok = run_js_tests(index_html_path, my_set)
    all_ok &= js_ok

    # --- 画面ロジック（お手つき・7枚決着・localStorage壊れ値）の実走テスト ---
    dom_ok = run_dom_playthrough(index_html_path)
    all_ok &= dom_ok

    # --- 先着判定（新仕様: 先に引き切った方が取る。pointerdown時刻は見ない） ---
    race_ok = run_grab_rules_test(index_html_path)
    all_ok &= race_ok

    print()
    print("=== 総合: %s ===" % ("PASS" if all_ok else "FAIL"))
    sys.exit(0 if all_ok else 1)


def run_js_tests(index_html_path, my_set):
    """Node で index.html 先頭の <script>（純粋ロジック）を vm で実走して検証する"""
    src = open(index_html_path, encoding="utf-8").read()
    beg = src.index("<script>")
    end = src.index("</script>", beg)
    logic_js = src[beg + len("<script>"):end]

    # 壊れ値パターン（自前で作る。実装コードのテストケースを流用しない）
    broken_cases_js = r"""
    var brokenCases = [
      {label:"形重複", card:{a:["ハート","赤"], b:["ハート","青"]}},
      {label:"色重複", card:{a:["ハート","赤"], b:["しずく","赤"]}},
      {label:"一致2つ", card:{a:["ハート","赤"], b:["しずく","青"]}},
      {label:"残り0個(作為的整合)", card:{a:["ハート","青"], b:["しずく","黄"]}},
      {label:"未知の形", card:{a:["さんかく","赤"], b:["しずく","青"]}},
      {label:"未知の色", card:{a:["ハート","紫"], b:["しずく","青"]}},
      {label:"null札", card:null},
      {label:"要素不足a", card:{a:["ハート"], b:["しずく","青"]}},
      {label:"aがnull", card:{a:null, b:["しずく","青"]}},
      {label:"answerフィールド無し(単に配列)", card:["ハート","赤"]},
    ];
    """

    node_script = logic_js + "\n" + broken_cases_js + r"""
    var out = {results: [], brokenResults: [], n: Hayatsukami.CARDS.length};
    for (var i = 0; i < Hayatsukami.CARDS.length; i++) {
      var c = Hayatsukami.CARDS[i];
      var ans = Hayatsukami.answerOf(c);
      var valid = Hayatsukami.isValidCard(c);
      out.results.push({a: c.a, b: c.b, answer: ans, kind: c.kind, expected: c.answer, valid: valid});
    }
    for (var j = 0; j < brokenCases.length; j++) {
      var bc = brokenCases[j];
      var v;
      try { v = Hayatsukami.isValidCard(bc.card); } catch (e) { v = "THROW:" + e.message; }
      out.brokenResults.push({label: bc.label, valid: v});
    }
    console.log(JSON.stringify(out));
    """
    tmp_path = os.path.join("/private/tmp/claude-501", "hayatsukami_qa_node.js")
    os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(node_script)
    try:
        r = subprocess.run(["node", tmp_path], capture_output=True, text=True, timeout=20)
    except Exception as e:
        return report(False, "Node実行", "起動失敗: %s" % e)
    if r.returncode != 0:
        return report(False, "Node実行", "exit=%d stderr=%s" % (r.returncode, r.stderr[:500]))
    data = json.loads(r.stdout)

    ok = True
    ok &= report(data["n"] == 120, "JS側 CARDS.length", "実測=%d" % data["n"])

    bad = [x for x in data["results"] if x["answer"] != x["expected"]]
    ok &= report(not bad, "JS answerOf が埋め込み answer と全件一致", "不一致=%d件 例=%s" % (len(bad), bad[:2]))

    not_valid = [x for x in data["results"] if not x["valid"]]
    ok &= report(not not_valid, "JS isValidCard が全120枚で true", "false件数=%d" % len(not_valid))

    # 自前集合との突合（JS側 answerOf の結果 vs 自分で計算した正解）
    js_vs_mine_mismatch = []
    for x in data["results"]:
        k = card_key(tuple(x["a"]), tuple(x["b"]))
        mine = my_set.get(k)
        if mine is None:
            js_vs_mine_mismatch.append(("自前集合に無い札", x))
        elif mine[0] != x["answer"]:
            js_vs_mine_mismatch.append(("answer不一致", x, mine))
    ok &= report(not js_vs_mine_mismatch, "JS answerOf が自前計算(独立実装)と全件一致",
                 "不一致=%d件" % len(js_vs_mine_mismatch))

    print("      壊れ値テスト結果:")
    all_false = True
    for br in data["brokenResults"]:
        v = br["valid"]
        is_false = (v is False)
        if not is_false:
            all_false = False
        print("        %-20s -> %r" % (br["label"], v))
    ok &= report(all_false, "壊れ値10パターンすべて isValidCard=false")

    return ok


def run_dom_playthrough(index_html_path):
    """画面ロジック（第2 <script>）を最小 document/localStorage スタブで実走し、
    お手つき・7枚決着・localStorage壊れ値耐性を検証する（vm+DOMスタブ手法）。"""
    src = open(index_html_path, encoding="utf-8").read()
    first_end = src.index("</script>", src.index("<script>")) + len("</script>")
    second_beg = src.index("<script>", first_end) + len("<script>")
    second_end = src.index("</script>", second_beg)
    logic_js = src[src.index("<script>") + len("<script>"):src.index("</script>", src.index("<script>"))]
    screen_js = src[second_beg:second_end]

    harness = r"""
    'use strict';
    const vm = require('vm');

    // --- 表示定数（drawMotif の逆引き用。qa係が index.html から書き写した固定値） ---
    const D_TO_SHAPE = {
      "M50 87C22 66 9 51 9 35 9 21 20 11 32 11 41 11 47 16 50 23 53 16 59 11 68 11 80 11 91 21 91 35 91 51 78 66 50 87Z": "ハート",
      "M50 8C50 8 83 47 83 63 83 81 68 92 50 92 32 92 17 81 17 63 17 47 50 8 50 8Z": "しずく",
      "M50 8L60.6 37.4 91.9 38.4 67.1 57.6 75.9 87.6 50 70 24.1 87.6 32.9 57.6 8.2 38.4 39.4 37.4Z": "ほし",
      "M12 88C12 40 40 12 88 12 88 60 60 88 12 88Z": "はっぱ",
      "M57 8.6A42 42 0 1 0 57 91.4A50 50 0 0 1 57 8.6Z": "つき"
    };
    const FILL_TO_COLOR = {
      "#d94f43": "赤", "#2f7fd4": "青", "#e0a90c": "黄", "#3f9b52": "緑", "#2b2b2b": "黒"
    };

    class El {
      constructor(tag) { this.tag = tag; this.children = []; this._attrs = {}; this._listeners = {};
        this._className = ''; this._html = ''; this._text = ''; this._rect = {top:0,bottom:0,left:0,right:0,width:0,height:0}; }
      get childNodes() { return this.children; }
      get firstChild() { return this.children.length ? this.children[0] : null; }
      appendChild(c) { this.children.push(c); return c; }
      removeChild(c) { const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); return c; }
      setAttribute(k, v) { this._attrs[k] = v; }
      getAttribute(k) { return this._attrs[k]; }
      addEventListener(type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); }
      setPointerCapture() {}
      get classList() { const self = this; if (!self.__cl) self.__cl = new Set();
        return { add: c => self.__cl.add(c), remove: c => self.__cl.delete(c), contains: c => self.__cl.has(c) }; }
      set className(v) { this._className = v; }
      get className() { return this._className; }
      set innerHTML(v) { this._html = v; this.children = []; }
      get innerHTML() { return this._html; }
      set textContent(v) { this._text = v; }
      get textContent() { return this._text; }
      get style() { if (!this._style) this._style = {}; return this._style; }
      getBoundingClientRect() { return this._rect; }
    }

    function decodeMotif(svgEl) {
      var path = svgEl.children[0];
      var d = path._attrs.d, fill = path._attrs.fill;
      return [D_TO_SHAPE[d], FILL_TO_COLOR[fill]];
    }

    function buildSandbox(getItemImpl) {
      const ids = ['rotate', 'app', 'countTop', 'cardTop', 'mid', 'noteTop', 'items',
                   'noteBottom', 'countBottom', 'cardBottom', 'over', 'resTop', 'again', 'resBottom'];
      const elements = {};
      ids.forEach(id => { elements[id] = new El('div'); });
      elements.mid._rect = { top: 0, bottom: 300, left: 0, right: 500, width: 500, height: 300 };
      elements.items._rect = { top: 100, bottom: 200, left: 0, right: 500, width: 500, height: 100 };

      const savedCalls = [];
      const localStorage = {
        getItem: getItemImpl,
        setItem: (k, v) => { savedCalls.push([k, v]); }
      };

      const timers = [];
      const sandbox = {
        console, Math, JSON, Date,
        document: {
          getElementById: id => elements[id],
          createElement: tag => new El(tag),
          createElementNS: (ns, tag) => new El(tag)
        },
        window: undefined,
        localStorage,
        setTimeout: (fn, ms) => { fn(); return 0; },   // 即時実行（判定ロジック自体の検証が目的）
        clearTimeout: () => {},
        requestAnimationFrame: (fn) => { fn(); return 0; },
      };
      const ctx = vm.createContext(sandbox);
      return { ctx, elements, savedCalls };
    }

    function fireCorrectPick(ctx, elements, side, seq) {
      var Hy = vm.runInContext('Hayatsukami', ctx);
      var SHAPES = Hy.SHAPES;
      var a = decodeMotif(elements.cardBottom.children[0]);
      var b = decodeMotif(elements.cardBottom.children[1]);
      var want = Hy.answerOf({ a: a, b: b });
      if (want === null) throw new Error('現在の札の正解が求まらない: ' + JSON.stringify([a, b]));
      var idx = SHAPES.indexOf(want);
      firePick(elements, side, idx, seq);
      return { a: a, b: b, want: want };
    }

    function firePick(elements, side, idx, pointerId) {
      var x = idx * 100 + 50, y0 = 150;
      var down = elements.mid._listeners['pointerdown'][0];
      down({ clientX: x, clientY: y0, pointerId: pointerId, timeStamp: pointerId, preventDefault: () => {} });
      var y1 = side === 'bottom' ? y0 + 60 : y0 - 60;
      var move = elements.mid._listeners['pointermove'][0];
      move({ clientX: x, clientY: y1, pointerId: pointerId, preventDefault: () => {} });
    }

    function readCount(el) {
      var m = /^(\d+)/.exec(el._html || '0');
      return m ? parseInt(m[1], 10) : 0;
    }

    const GAME_JS = %(GAME_JS)s;

    function runScenario(label, getItemImpl, expectBaseBottom) {
      const out = { label: label, ok: true, notes: [] };
      try {
        const { ctx, elements, savedCalls } = buildSandbox(getItemImpl);
        vm.runInContext(GAME_JS, ctx);

        var pid = 1;

        // 1) 0枚のときのお手つき: top はまだ0枚 -> 誤答させて何も起きないことを確認
        var before = { a: decodeMotif(elements.cardBottom.children[0]), b: decodeMotif(elements.cardBottom.children[1]) };
        var Hy = vm.runInContext('Hayatsukami', ctx);
        var want0 = Hy.answerOf(before);
        var wrongIdx0 = (Hy.SHAPES.indexOf(want0) + 1) % 5;
        firePick(elements, 'top', wrongIdx0, pid++);
        var afterWrong = { a: decodeMotif(elements.cardBottom.children[0]), b: decodeMotif(elements.cardBottom.children[1]) };
        out.notes.push('0枚時お手つき: top=' + readCount(elements.countTop) + ' bottom=' + readCount(elements.countBottom)
          + ' 札据え置き=' + (JSON.stringify(before) === JSON.stringify(afterWrong)));
        if (readCount(elements.countTop) !== 0 || readCount(elements.countBottom) !== 0) out.ok = false;
        if (JSON.stringify(before) !== JSON.stringify(afterWrong)) out.ok = false;

        // 2) bottom を7枚まで正解させ、3枚目に達した直後に1回だけ bottom の誤答（お手つき）を挟む
        var wins = 0, penalized = false;
        while (wins < 7) {
          if (wins === 3 && !penalized) {
            var cur = { a: decodeMotif(elements.cardBottom.children[0]), b: decodeMotif(elements.cardBottom.children[1]) };
            var wantP = Hy.answerOf(cur);
            var wrongIdxP = (Hy.SHAPES.indexOf(wantP) + 1) % 5;
            var beforeScore = { top: readCount(elements.countTop), bottom: readCount(elements.countBottom) };
            firePick(elements, 'bottom', wrongIdxP, pid++);
            var afterScore = { top: readCount(elements.countTop), bottom: readCount(elements.countBottom) };
            var curAfter = { a: decodeMotif(elements.cardBottom.children[0]), b: decodeMotif(elements.cardBottom.children[1]) };
            out.notes.push('お手つき(保有時): before=' + JSON.stringify(beforeScore) + ' after=' + JSON.stringify(afterScore)
              + ' 札据え置き=' + (JSON.stringify(cur) === JSON.stringify(curAfter)));
            if (!(afterScore.bottom === beforeScore.bottom - 1 && afterScore.top === beforeScore.top + 1)) out.ok = false;
            if (JSON.stringify(cur) !== JSON.stringify(curAfter)) out.ok = false;
            penalized = true;
            wins = afterScore.bottom;
            continue;
          }
          fireCorrectPick(ctx, elements, 'bottom', pid++);
          wins = readCount(elements.countBottom);
        }

        out.notes.push('決着: over画面表示=' + (elements.over._html !== undefined && elements.over.hidden));
        var resText = elements.resBottom._html || '';
        var m = /通算 (\d+) 勝/.exec(resText);
        var shownTotal = m ? parseInt(m[1], 10) : null;
        out.notes.push('resBottom=' + resText + ' savedCalls=' + JSON.stringify(savedCalls));
        if (shownTotal !== expectBaseBottom + 1) { out.ok = false; out.notes.push('期待通算=' + (expectBaseBottom + 1) + ' 実測=' + shownTotal); }
        if (!savedCalls.length || savedCalls[savedCalls.length - 1][0] !== 'hayatsukami') { out.ok = false; out.notes.push('setItem未呼び出し'); }
      } catch (e) {
        out.ok = false;
        out.notes.push('EXCEPTION: ' + (e && e.stack || e));
      }
      return out;
    }

    const scenarios = [
      ['空(localStorage未使用)', (k) => null, 0],
      ['非JSON', (k) => 'not-json{', 0],
      ['wins型不正(top文字列/bottom正常)', (k) => JSON.stringify({ wins: { top: '3', bottom: 2 } }), 2],
      ['負数(top負/bottom正常)', (k) => JSON.stringify({ wins: { top: -3, bottom: 5 } }), 5],
      ['getItem例外', (k) => { throw new Error('boom'); }, 0],
    ];

    const results = scenarios.map(s => runScenario(s[0], s[1], s[2]));
    console.log(JSON.stringify(results));
    """
    harness = harness.replace("%(GAME_JS)s", json.dumps(logic_js + "\n" + screen_js))

    tmp_path = "/private/tmp/claude-501/hayatsukami_qa_dom.js"
    os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(harness)
    try:
        r = subprocess.run(["node", tmp_path], capture_output=True, text=True, timeout=30)
    except Exception as e:
        return report(False, "DOM実走テスト起動", "失敗: %s" % e)
    if r.returncode != 0:
        return report(False, "DOM実走テスト実行", "exit=%d stderr=%s" % (r.returncode, r.stderr[:1500]))
    try:
        results = json.loads(r.stdout)
    except Exception:
        return report(False, "DOM実走テスト出力パース", "stdout=%s stderr=%s" % (r.stdout[:800], r.stderr[:800]))

    ok = True
    for res in results:
        good = report(res["ok"], "DOM実走: %s" % res["label"])
        ok &= good
        for n in res["notes"]:
            print("        - %s" % n)
    return ok


def run_grab_rules_test(index_html_path):
    """新仕様（decision_log.md 2026-09-13 最上段）の再検証:
    「先に引き切った方（しきい値到達順）が取る。pointerdownの時刻は見ない」
    「札が出る前は指を置いても越えられない／出た後に起点リセット」
    「札が消えたら触れている指は全部無効。離して触り直すまで戻らない」
    「同じ札への二重取得はしない」
    実装(Grab)はpending/rAF待ちを持たない即時判定に変わったため、シナリオは
    5本とも独立した VM コンテキストで実行し、前のシナリオの状態を持ち越さない。"""
    src = open(index_html_path, encoding="utf-8").read()
    logic_js = src[src.index("<script>") + len("<script>"):src.index("</script>", src.index("<script>"))]
    first_end = src.index("</script>", src.index("<script>")) + len("</script>")
    second_beg = src.index("<script>", first_end) + len("<script>")
    second_end = src.index("</script>", second_beg)
    screen_js = src[second_beg:second_end]

    harness = r"""
    'use strict';
    const vm = require('vm');

    const D_TO_SHAPE = {
      "M50 87C22 66 9 51 9 35 9 21 20 11 32 11 41 11 47 16 50 23 53 16 59 11 68 11 80 11 91 21 91 35 91 51 78 66 50 87Z": "ハート",
      "M50 8C50 8 83 47 83 63 83 81 68 92 50 92 32 92 17 81 17 63 17 47 50 8 50 8Z": "しずく",
      "M50 8L60.6 37.4 91.9 38.4 67.1 57.6 75.9 87.6 50 70 24.1 87.6 32.9 57.6 8.2 38.4 39.4 37.4Z": "ほし",
      "M12 88C12 40 40 12 88 12 88 60 60 88 12 88Z": "はっぱ",
      "M57 8.6A42 42 0 1 0 57 91.4A50 50 0 0 1 57 8.6Z": "つき"
    };
    const FILL_TO_COLOR = { "#d94f43": "赤", "#2f7fd4": "青", "#e0a90c": "黄", "#3f9b52": "緑", "#2b2b2b": "黒" };

    class El {
      constructor(tag) { this.tag = tag; this.children = []; this._attrs = {}; this._listeners = {};
        this._className = ''; this._html = ''; this._text = ''; this._rect = {top:0,bottom:0,left:0,right:0,width:0,height:0}; }
      get childNodes() { return this.children; }
      get firstChild() { return this.children.length ? this.children[0] : null; }
      appendChild(c) { this.children.push(c); return c; }
      removeChild(c) { const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); return c; }
      setAttribute(k, v) { this._attrs[k] = v; }
      addEventListener(type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); }
      setPointerCapture() {}
      get classList() { const self = this; if (!self.__cl) self.__cl = new Set();
        return { add: c => self.__cl.add(c), remove: c => self.__cl.delete(c), contains: c => self.__cl.has(c) }; }
      set className(v) { this._className = v; }
      get className() { return this._className; }
      set innerHTML(v) { this._html = v; this.children = []; }
      get innerHTML() { return this._html; }
      set textContent(v) { this._text = v; }
      get textContent() { return this._text; }
      get style() { if (!this._style) this._style = {}; return this._style; }
      getBoundingClientRect() { return this._rect; }
    }

    function decodeMotif(svgEl) {
      var path = svgEl.children[0];
      return [D_TO_SHAPE[path._attrs.d], FILL_TO_COLOR[path._attrs.fill]];
    }
    function readCount(el) { var m = /^(\d+)/.exec(el._html || '0'); return m ? parseInt(m[1], 10) : 0; }

    const GAME_JS = %(GAME_JS)s;

    // 独立した document/localStorage スタブを毎回新規に作る（シナリオ間で状態を共有しない）
    function buildSandbox() {
      const ids = ['rotate', 'app', 'countTop', 'cardTop', 'mid', 'noteTop', 'items',
                   'noteBottom', 'countBottom', 'cardBottom', 'over', 'resTop', 'again', 'resBottom'];
      const elements = {};
      ids.forEach(id => { elements[id] = new El('div'); });
      elements.mid._rect = { top: 0, bottom: 300, left: 0, right: 500, width: 500, height: 300 };
      elements.items._rect = { top: 100, bottom: 200, left: 0, right: 500, width: 500, height: 100 };

      let TIMERQ = [];
      const sandbox = {
        console, Math, JSON, Date,
        document: {
          getElementById: id => elements[id],
          createElement: tag => new El(tag),
          createElementNS: (ns, tag) => new El(tag)
        },
        window: undefined,
        localStorage: { getItem: () => null, setItem: () => {} },
        // setTimeout はキューに貯めるだけ。「札が出る前」の状態を手動で作るために即時実行にしない
        setTimeout: (fn, ms) => { TIMERQ.push(fn); return TIMERQ.length; },
        clearTimeout: () => {},
        requestAnimationFrame: (fn) => { fn(); return 0; },  // 新実装は rAF を使わないため単純即時実行でよい
      };
      const ctx = vm.createContext(sandbox);
      vm.runInContext(GAME_JS, ctx);   // 内部で loadStore(); start(); まで走る（dealTimer が積まれるだけ）
      var Hy = vm.runInContext('Hayatsukami', ctx);
      function flushTimers() { const q = TIMERQ; TIMERQ = []; q.forEach(fn => fn()); }
      return { elements, Hy, flushTimers };
    }

    function currentCard(elements, Hy) {
      var a = decodeMotif(elements.cardBottom.children[0]);
      var b = decodeMotif(elements.cardBottom.children[1]);
      return { a: a, b: b, want: Hy.answerOf({ a: a, b: b }) };
    }
    function down(elements, pid, idx) {
      var x = idx * 100 + 50, y0 = 150;
      elements.mid._listeners['pointerdown'][0]({ clientX: x, clientY: y0, pointerId: pid, preventDefault: () => {} });
      return { x: x, y: y0 };
    }
    // xy は直近の座標を保持するオブジェクト。呼ぶたびに dyAbs だけ「同じ向きへ」追加移動する
    function move(elements, pid, xy, dyAbs, side) {
      var y1 = side === 'bottom' ? xy.y + dyAbs : xy.y - dyAbs;
      elements.mid._listeners['pointermove'][0]({ clientX: xy.x, clientY: y1, pointerId: pid, preventDefault: () => {} });
      xy.y = y1;
    }
    function up(elements, pid) {
      elements.mid._listeners['pointerup'][0]({ pointerId: pid });
    }

    const out = { scenarios: [] };
    function scenario(name, fn) {
      const checks = [];
      function check(label, cond, detail) { checks.push({ label: label, pass: !!cond, detail: detail }); }
      try {
        fn(check);
      } catch (e) {
        checks.push({ label: 'EXCEPTION', pass: false, detail: String(e && e.stack || e) });
      }
      out.scenarios.push({ name: name, checks: checks });
    }

    // --- 1&2) 先着はしきい値到達順。pointerdownが先でも引き切りが遅ければ負ける ---
    scenario('先着=しきい値到達順（触れた順ではない）', function (check) {
      const { elements, Hy, flushTimers } = buildSandbox();
      flushTimers();  // 最初の札を出す
      var c = currentCard(elements, Hy);
      var idx = Hy.SHAPES.indexOf(c.want);
      var topXY = down(elements, 1, idx);   // TOP: 先に touch（pointerdown）
      var botXY = down(elements, 2, idx);   // BOTTOM: 後に touch
      move(elements, 2, botXY, 60, 'bottom');           // BOTTOM が先に引き切る
      var afterBottom = { top: readCount(elements.countTop), bottom: readCount(elements.countBottom) };
      check('先にtouchしたTOPでなく先に引き切ったBOTTOMが得点', afterBottom.bottom === 1 && afterBottom.top === 0, JSON.stringify(afterBottom));
      move(elements, 1, topXY, 60, 'top');              // TOP が遅れて引き切る（同じ札への2回目の引き）
      var afterTop = { top: readCount(elements.countTop), bottom: readCount(elements.countBottom) };
      check('遅れて引き切ったTOPは無効（スコア不変・誤爆なし）', afterTop.top === 0 && afterTop.bottom === afterBottom.bottom, JSON.stringify(afterTop));
    });

    // --- 3) 札が出る前はしきい値を越えられない。出た後は同じ指で有効になる ---
    scenario('札が出る前は無効、出た後は同じ指で有効', function (check) {
      const { elements, Hy, flushTimers } = buildSandbox();
      // ここでは flushTimers() をまだ呼ばない＝札はまだ配られていない（open=false）
      var xy = down(elements, 3, 0);
      move(elements, 3, xy, 60, 'bottom');
      var noteBefore = elements.noteBottom._text;
      var scoreBefore = { top: readCount(elements.countTop), bottom: readCount(elements.countBottom) };
      check('札が出る前は引いても判定されない(note未変化)', noteBefore !== 'とった！' && String(noteBefore).indexOf('おてつき') === -1, JSON.stringify(noteBefore));
      check('札が出る前はスコアも変化しない', scoreBefore.top === 0 && scoreBefore.bottom === 0, JSON.stringify(scoreBefore));

      flushTimers();  // 札が配られる。deal() が押されたままの指の起点をリセットする
      move(elements, 3, xy, 60, 'bottom');  // 同じ指(id=3)でもう一度引く
      var noteAfter = elements.noteBottom._text;
      check('札が出た後は同じ指で引けば判定される', noteAfter === 'とった！' || String(noteAfter).indexOf('おてつき') >= 0, JSON.stringify(noteAfter));
    });

    // --- 4) 前の札の指を離さず次の札で引いても誤爆しない。離して触り直せば取れる ---
    scenario('前の札の指は次の札へ持ち越されない（離せば復活）', function (check) {
      const { elements, Hy, flushTimers } = buildSandbox();
      flushTimers();
      var cardA = currentCard(elements, Hy);
      // 札Aの間、pid=9 は正解でない適当な場所に触れたままにしておく（動かさない＝doneにしない）
      var otherIdx = (Hy.SHAPES.indexOf(cardA.want) + 1) % 5;
      down(elements, 9, otherIdx);
      // 別指(pid=20)で札Aの正解を引いて取る → nextCard() が呼ばれ、Grab.clear() で pid=9 も無効化されるはず
      var idxA = Hy.SHAPES.indexOf(cardA.want);
      var xyA = down(elements, 20, idxA);
      move(elements, 20, xyA, 60, 'bottom');
      check('札Aは正解で取れている', readCount(elements.countBottom) === 1, readCount(elements.countBottom));

      flushTimers();  // 札Bが配られる
      var cardB = currentCard(elements, Hy);
      // pid=9（離していない指）で札Bの正解方向へ引いても無効なはず
      var idxB = Hy.SHAPES.indexOf(cardB.want);
      // pid=9 の idx は otherIdx 固定なので、idxB と一致しない場合は誤爆しても不正解(おてつき)にしかならず判定が甘くなる。
      // 「無効」であること自体を note 不変で確認する（お手つきの note も出ないはず）。
      var noteBottomBefore = elements.noteBottom._text;
      move(elements, 9, { x: otherIdx * 100 + 50, y: 150 }, 60, 'bottom');
      var noteBottomAfter = elements.noteBottom._text;
      var scoreAfterGhost = { top: readCount(elements.countTop), bottom: readCount(elements.countBottom) };
      check('離さずに持ち越した指は次の札に無反応（note不変）', noteBottomAfter === noteBottomBefore, JSON.stringify([noteBottomBefore, noteBottomAfter]));
      check('離さずに持ち越した指はスコアも変えない', scoreAfterGhost.bottom === 1 && scoreAfterGhost.top === 0, JSON.stringify(scoreAfterGhost));

      up(elements, 9);  // 離す
      var xyB2 = down(elements, 9, idxB);  // 触り直す
      move(elements, 9, xyB2, 60, 'bottom');
      check('離して触り直せば同じ指でも有効になる', readCount(elements.countBottom) === 2, readCount(elements.countBottom));
    });

    // --- 5) 同じ札にほぼ同時の引き切りが来ても二重取得しない（呼ばれた順で決まる） ---
    ['top', 'bottom'].forEach(function (firstSide) {
      scenario('二重取得しない（先に呼ばれた方=' + firstSide + '）', function (check) {
        const { elements, Hy, flushTimers } = buildSandbox();
        flushTimers();
        var c = currentCard(elements, Hy);
        var idx = Hy.SHAPES.indexOf(c.want);
        var topXY = down(elements, 1, idx);
        var botXY = down(elements, 2, idx);
        var order = firstSide === 'top' ? [['top', 1, topXY], ['bottom', 2, botXY]] : [['bottom', 2, botXY], ['top', 1, topXY]];
        move(elements, order[0][1], order[0][2], 60, order[0][0]);
        move(elements, order[1][1], order[1][2], 60, order[1][0]);
        var score = { top: readCount(elements.countTop), bottom: readCount(elements.countBottom) };
        var total = score.top + score.bottom;
        check('得点は合計ちょうど1（二重取得なし）', total === 1, JSON.stringify(score));
        check('得点したのは先に呼ばれた側(' + firstSide + ')', score[firstSide] === 1, JSON.stringify(score));
      });
    });

    console.log(JSON.stringify(out));
    """
    harness = harness.replace("%(GAME_JS)s", json.dumps(logic_js + "\n" + screen_js))

    tmp_path = "/private/tmp/claude-501/hayatsukami_qa_grab.js"
    os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(harness)
    try:
        r = subprocess.run(["node", tmp_path], capture_output=True, text=True, timeout=20)
    except Exception as e:
        return report(False, "先着(新仕様)再現テスト起動", "失敗: %s" % e)
    if r.returncode != 0:
        return report(False, "先着(新仕様)再現テスト実行", "exit=%d stderr=%s" % (r.returncode, r.stderr[:1500]))
    data = json.loads(r.stdout)

    ok = True
    for sc in data["scenarios"]:
        sc_ok = all(c["pass"] for c in sc["checks"])
        ok &= report(sc_ok, "先着(新仕様): %s" % sc["name"])
        for c in sc["checks"]:
            if not c["pass"]:
                print("        NG: %s  detail=%s" % (c["label"], c["detail"]))
            else:
                print("        ok: %s" % c["label"])
    return ok


if __name__ == "__main__":
    main()
