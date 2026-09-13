#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""かぶせっこ 規則の機械検査

index.html の先頭 <script>（window.Kabusekko）を Node で読み込み、
このファイルが docs/spec.md から独立に組み直した Python 実装と突き合わせる。
実装のテストケースを流用せず、盤面は全部「初手からの手順」で作る。

    python3 tools/qa_check.py

標準ライブラリのみ。node が要る。
"""

import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, "index.html")

LINES = [
    (0, 1, 2), (3, 4, 5), (6, 7, 8),
    (0, 3, 6), (1, 4, 7), (2, 5, 8),
    (0, 4, 8), (2, 4, 6),
]
HAND = [3, 3, 2, 2, 1, 1]          # 各自 大2・中2・小2

_fail = []


def report(ok, label, detail=""):
    print(("  OK  " if ok else "  NG  ") + label + (("   " + detail) if detail else ""))
    if not ok:
        _fail.append(label)
    return ok


# =====================================================================
# spec.md から組み直した Python 実装（index.html のコードは見ないで書く）
# 状態: {"board": [[{owner,size}, ...] × 9], "hands": {top:[...], bottom:[...]},
#        "turn": "top"|"bottom", "winner": None|"top"|"bottom"}
# =====================================================================

def py_initial():
    return {
        "board": [[] for _ in range(9)],
        "hands": {"top": list(HAND), "bottom": list(HAND)},
        "turn": "bottom",
        "winner": None,
    }


def py_clone(s):
    return {
        "board": [[dict(p) for p in st] for st in s["board"]],
        "hands": {k: list(v) for k, v in s["hands"].items()},
        "turn": s["turn"],
        "winner": s["winner"],
    }


def py_other(p):
    return "bottom" if p == "top" else "top"


def py_top(s, cell):
    if not isinstance(cell, int) or isinstance(cell, bool) or not (0 <= cell <= 8):
        return None
    st = s["board"][cell]
    return st[-1] if st else None


def py_can_place(under, size):
    return under is None or under["size"] < size


def py_legal(s, move):
    """規則に合う手か。合わなければ False（例外は投げない）"""
    if s["winner"]:
        return False
    if not isinstance(move, dict):
        return False
    player = move.get("player", s["turn"])
    if player not in ("top", "bottom"):
        return False
    if player != s["turn"]:          # 手番でない側は指せない
        return False
    to = move.get("to")
    if not isinstance(to, int) or isinstance(to, bool) or not (0 <= to <= 8):
        return False
    frm = move.get("from")
    if frm == "hand":
        size = move.get("size")
        if size not in (1, 2, 3):
            return False
        if size not in s["hands"][player]:
            return False
    else:
        if not isinstance(frm, int) or isinstance(frm, bool) or not (0 <= frm <= 8):
            return False
        if frm == to:
            return False
        p = py_top(s, frm)
        if p is None or p["owner"] != player:      # 相手の駒は動かせない
            return False
        size = p["size"]
        if move.get("size") is not None and move.get("size") != size:
            return False
    return py_can_place(py_top(s, to), size)       # 同大・より大きい駒の上は不可


def py_legal_moves(s, player):
    out = []
    if s["winner"] or player not in ("top", "bottom"):
        return out
    for size in sorted(set(s["hands"][player]), reverse=True):
        for c in range(9):
            if py_can_place(py_top(s, c), size):
                out.append({"player": player, "from": "hand", "size": size, "to": c})
    for c in range(9):
        p = py_top(s, c)
        if p is None or p["owner"] != player:
            continue
        for d in range(9):
            if d == c:
                continue
            if py_can_place(py_top(s, d), p["size"]):
                out.append({"player": player, "from": c, "size": p["size"], "to": d})
    return out


def py_winners(s):
    """見えている駒だけで3並びができている持ち主（複数ありうる）"""
    out = []
    for a, b, c in LINES:
        pa, pb, pc = py_top(s, a), py_top(s, b), py_top(s, c)
        if pa and pb and pc and pa["owner"] == pb["owner"] == pc["owner"]:
            if pa["owner"] not in out:
                out.append(pa["owner"])
    return out


def py_judge(s, mover):
    w = py_winners(s)
    if mover in w:
        return mover
    return w[0] if w else None


def py_apply(s, move):
    assert py_legal(s, move), "反則の手を適用しようとした: %r" % (move,)
    player = move.get("player", s["turn"])
    ns = py_clone(s)
    if move["from"] == "hand":
        size = move["size"]
        ns["hands"][player].remove(size)
    else:
        size = ns["board"][move["from"]].pop()["size"]
    ns["board"][move["to"]].append({"owner": player, "size": size})
    ns["winner"] = py_judge(ns, player)
    ns["turn"] = player if ns["winner"] else py_other(player)
    return ns


def key(m):
    """手を比較用の文字列に"""
    return "%s|%s|%s|%s" % (m["player"], m["from"], m.get("size"), m["to"])


def integrity(s):
    """状態が壊れていないか（駒の数・積み重ねの大きさの順）。壊れていれば理由を返す"""
    for side in ("top", "bottom"):
        cnt = sorted(list(s["hands"][side]))
        for st in s["board"]:
            for p in st:
                if p["owner"] == side:
                    cnt.append(p["size"])
        if sorted(cnt) != sorted(HAND):
            return "%s の駒の内訳が %s" % (side, sorted(cnt))
    for i, st in enumerate(s["board"]):
        for j in range(1, len(st)):
            if st[j]["size"] <= st[j - 1]["size"]:
                return "マス%d の積みが %s" % (i, [p["size"] for p in st])
        if len(st) > 6:
            return "マス%d が %d 段" % (i, len(st))
    return None


# =====================================================================
# Node 側の実行
# =====================================================================

SCENARIOS = [
    # name, 初手からの手順, 試す手（合法であるべきか）
    {
        "name": "同じ大きさの上には置けない",
        "setup": [{"player": "bottom", "from": "hand", "size": 2, "to": 4}],
        "probes": [
            ({"player": "top", "from": "hand", "size": 2, "to": 4}, False, "相手の中に中をかぶせる"),
            ({"player": "top", "from": "hand", "size": 3, "to": 4}, True, "相手の中に大をかぶせる"),
        ],
    },
    {
        "name": "自分より大きい駒の上には置けない",
        "setup": [{"player": "bottom", "from": "hand", "size": 3, "to": 0}],
        "probes": [
            ({"player": "top", "from": "hand", "size": 1, "to": 0}, False, "大の上に小"),
            ({"player": "top", "from": "hand", "size": 2, "to": 0}, False, "大の上に中"),
            ({"player": "top", "from": "hand", "size": 3, "to": 0}, False, "大の上に大"),
            ({"player": "top", "from": "hand", "size": 1, "to": 1}, True, "空きマスに小"),
        ],
    },
    {
        "name": "相手の駒は動かせない／自分の駒は動かせる",
        "setup": [
            {"player": "bottom", "from": "hand", "size": 1, "to": 4},
            {"player": "top", "from": "hand", "size": 2, "to": 4},
            {"player": "bottom", "from": "hand", "size": 3, "to": 0},
        ],
        "probes": [
            ({"player": "top", "from": 0, "to": 5}, False, "上が下の大を動かす"),
            ({"player": "bottom", "from": 4, "to": 5}, False, "下が埋まった自分の小を動かす"),
            ({"player": "top", "from": 4, "to": 5}, True, "上が自分の中を動かす"),
            ({"player": "bottom", "from": 0, "to": 0}, False, "同じマスへ"),
            ({"player": "bottom", "from": 0, "to": 5}, False, "手番でない下が自分の大を動かす"),
        ],
    },
    {
        "name": "かぶせた駒は下に残り、上が動くとまた現れる",
        "setup": [
            {"player": "bottom", "from": "hand", "size": 1, "to": 4},
            {"player": "top", "from": "hand", "size": 2, "to": 4},
            {"player": "bottom", "from": "hand", "size": 3, "to": 0},
            {"player": "top", "from": 4, "to": 8},
        ],
        "probes": [],
        "expect_top4": {"owner": "bottom", "size": 1},
        "expect_stack4": 1,
    },
    {
        "name": "勝ち：指した本人の3並び",
        "setup": [
            {"player": "bottom", "from": "hand", "size": 3, "to": 0},
            {"player": "top", "from": "hand", "size": 3, "to": 8},
            {"player": "bottom", "from": "hand", "size": 3, "to": 1},
            {"player": "top", "from": "hand", "size": 2, "to": 6},
            {"player": "bottom", "from": "hand", "size": 2, "to": 2},
        ],
        "probes": [
            ({"player": "top", "from": "hand", "size": 1, "to": 3}, False, "決着後は指せない"),
        ],
        "expect_winner": "bottom",
    },
    {
        "name": "勝ち：どけて相手の列が現れたら相手の勝ち",
        "setup": [
            {"player": "bottom", "from": "hand", "size": 1, "to": 2},
            {"player": "top", "from": "hand", "size": 2, "to": 2},
            {"player": "bottom", "from": "hand", "size": 3, "to": 0},
            {"player": "top", "from": "hand", "size": 3, "to": 8},
            {"player": "bottom", "from": "hand", "size": 3, "to": 1},
            {"player": "top", "from": 2, "to": 5},
        ],
        "probes": [],
        "expect_winner": "bottom",
    },
    {
        "name": "勝ち：同時に成立したら指した本人",
        "setup": [
            {"player": "bottom", "from": "hand", "size": 1, "to": 2},
            {"player": "top", "from": "hand", "size": 2, "to": 2},
            {"player": "bottom", "from": "hand", "size": 3, "to": 0},
            {"player": "top", "from": "hand", "size": 3, "to": 3},
            {"player": "bottom", "from": "hand", "size": 3, "to": 1},
            {"player": "top", "from": "hand", "size": 3, "to": 4},
            {"player": "bottom", "from": "hand", "size": 2, "to": 6},
            {"player": "top", "from": 2, "to": 5},
        ],
        "probes": [],
        "expect_winner": "top",
        "expect_winners_both": True,
    },
    {
        "name": "壊れた入力を合法と言わない",
        "setup": [{"player": "bottom", "from": "hand", "size": 2, "to": 4}],
        "probes": [
            ({"player": "top", "from": "hand", "size": 4, "to": 0}, False, "無い大きさ"),
            ({"player": "top", "from": "hand", "size": 2, "to": 9}, False, "盤外のマス"),
            ({"player": "top", "from": "hand", "size": 2, "to": -1}, False, "負のマス"),
            ({"player": "top", "from": 9, "to": 0}, False, "盤外から"),
            ({"player": "top", "from": 0, "to": 1}, False, "空きマスから動かす"),
            ({"player": "side", "from": "hand", "size": 2, "to": 0}, False, "居ない手番"),
            ({"player": "top", "from": "hand", "size": 2}, False, "行き先なし"),
            ({"player": "top", "from": 4, "size": 3, "to": 0}, False, "大きさの申告が違う"),
        ],
    },
]

NODE_HARNESS = r"""
__LOGIC__

var SCEN = __SCEN__;

function keyOf(m){ return m.player + "|" + m.from + "|" + (m.size===undefined?null:m.size) + "|" + m.to; }
function dumpBoard(s){
  return s.board.map(function(st){ return st.map(function(p){ return [p.owner, p.size]; }); });
}

/* ---- 手順で作った盤面ごとの調べ物 ---- */
var scenOut = [];
for (var i = 0; i < SCEN.length; i++) {
  var sc = SCEN[i];
  var st = Kabusekko.initialState();
  var err = null;
  for (var k = 0; k < sc.setup.length; k++) {
    try { st = Kabusekko.applyMove(st, sc.setup[k]); }
    catch (e) { err = "setup[" + k + "]: " + e.message; break; }
  }
  var rec = { name: sc.name, error: err };
  if (!err) {
    rec.board = dumpBoard(st);
    rec.hands = { top: st.hands.top.slice(), bottom: st.hands.bottom.slice() };
    rec.turn = st.turn;
    rec.winner = st.winner;
    rec.winners = Kabusekko.winnerOf(st);
    rec.tops = [];
    for (var c = 0; c < 9; c++) {
      var p = Kabusekko.topOf(st, c);
      rec.tops.push(p ? [p.owner, p.size] : null);
    }
    rec.moves = {
      top: Kabusekko.legalMoves(st, 'top').map(keyOf).sort(),
      bottom: Kabusekko.legalMoves(st, 'bottom').map(keyOf).sort()
    };
    rec.probes = [];
    for (var q = 0; q < sc.probes.length; q++) {
      var mv = sc.probes[q][0], v;
      try { v = Kabusekko.isLegal(st, mv); }
      catch (e) { v = "THROW:" + e.message; }
      var applied = null;
      if (v === true) { applied = "ok"; }
      else {
        try { Kabusekko.applyMove(st, mv); applied = "適用できてしまった"; }
        catch (e) { applied = "throw"; }
      }
      rec.probes.push({ legal: v, applied: applied });
    }
    /* 状態を書き換えていないか（applyMove は元を変えない） */
    var before = JSON.stringify(dumpBoard(st));
    Kabusekko.legalMoves(st, 'top'); Kabusekko.legalMoves(st, 'bottom');
    var ms = Kabusekko.legalMoves(st, st.turn);
    if (ms.length) { Kabusekko.applyMove(st, ms[0]); }
    rec.immutable = (JSON.stringify(dumpBoard(st)) === before);
  }
  scenOut.push(rec);
}

/* ---- 乱数（種を固定して再現できるようにする） ---- */
var seed = 20260913;
function rnd() {
  seed ^= seed << 13; seed |= 0;
  seed ^= seed >>> 17;
  seed ^= seed << 5;  seed |= 0;
  return ((seed >>> 0) % 1000000) / 1000000;
}

function playGame(cap, avoidWin) {
  var st = Kabusekko.initialState();
  var moves = [], counts = [], handEmpty = [];
  var ply = 0;
  while (!st.winner && ply < cap) {
    var ms = Kabusekko.legalMoves(st, st.turn);
    counts.push(ms.length);
    handEmpty.push(st.hands[st.turn].length === 0 ? 1 : 0);
    if (!ms.length) break;                 /* 合法手ゼロ＝報告対象 */
    var pick = ms[Math.floor(rnd() * ms.length)];
    if (avoidWin) {
      var safe = [];
      for (var j = 0; j < ms.length; j++) {
        var t = Kabusekko.applyMove(st, ms[j]);
        if (!t.winner) safe.push(ms[j]);
      }
      if (safe.length) pick = safe[Math.floor(rnd() * safe.length)];
    }
    moves.push([pick.player, pick.from === 'hand' ? -1 : pick.from,
                pick.size === undefined ? null : pick.size, pick.to]);
    st = Kabusekko.applyMove(st, pick);
    ply++;
  }
  return {
    moves: moves, counts: counts, handEmpty: handEmpty,
    winner: st.winner, board: dumpBoard(st),
    hands: { top: st.hands.top.slice(), bottom: st.hands.bottom.slice() },
    stopped: (!st.winner && ply >= cap) ? 1 : 0,
    zero: (!st.winner && ply < cap) ? 1 : 0
  };
}

var games = [], longGames = [], g;
for (g = 0; g < 1000; g++) games.push(playGame(400, false));
for (g = 0; g < 100; g++) longGames.push(playGame(150, true));

console.log(JSON.stringify({ scen: scenOut, games: games, longGames: longGames }));
"""


def run_node():
    src = open(INDEX, encoding="utf-8").read()
    beg = src.index("<script>")
    end = src.index("</script>", beg)
    logic = src[beg + len("<script>"):end]
    if "window.Kabusekko" not in logic:
        print("  NG  先頭の <script> に window.Kabusekko が無い")
        sys.exit(1)

    script = (NODE_HARNESS.replace("__LOGIC__", logic)
                          .replace("__SCEN__", json.dumps(SCENARIOS, ensure_ascii=False)))
    tmp = os.path.join(tempfile.gettempdir(), "kabusekko_qa_node.js")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(script)
    r = subprocess.run(["node", tmp], capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        print("  NG  Node 実行 exit=%d\n%s" % (r.returncode, r.stderr[:2000]))
        sys.exit(1)
    return json.loads(r.stdout)


# =====================================================================
# 突き合わせ
# =====================================================================

def check_scenarios(data):
    print("\n[1] 規則ひとつずつ（Python の独立実装と突き合わせ）")
    for sc, rec in zip(SCENARIOS, data["scen"]):
        name = sc["name"]
        if rec["error"]:
            report(False, name, "手順が組めない: " + rec["error"])
            continue
        st = py_initial()
        ok = True
        for mv in sc["setup"]:
            if not py_legal(st, mv):
                ok = report(False, name, "Python 側で手順が合法でない: %r" % (mv,)) and ok
                break
            st = py_apply(st, mv)
        else:
            # 盤・持ち駒・手番・勝者
            py_board = [[[p["owner"], p["size"]] for p in stk] for stk in st["board"]]
            ok &= report(py_board == rec["board"], name + " / 盤の中身が一致",
                         "" if py_board == rec["board"] else "JS=%s PY=%s" % (rec["board"], py_board))
            ok &= report(sorted(st["hands"]["top"]) == sorted(rec["hands"]["top"]) and
                         sorted(st["hands"]["bottom"]) == sorted(rec["hands"]["bottom"]),
                         name + " / 持ち駒が一致")
            ok &= report(st["turn"] == rec["turn"], name + " / 手番が一致",
                         "JS=%s PY=%s" % (rec["turn"], st["turn"]))
            ok &= report(st["winner"] == rec["winner"], name + " / 勝者が一致",
                         "JS=%s PY=%s" % (rec["winner"], st["winner"]))
            # 一番上の駒
            py_tops = []
            for c in range(9):
                p = py_top(st, c)
                py_tops.append([p["owner"], p["size"]] if p else None)
            ok &= report(py_tops == rec["tops"], name + " / topOf が一致")
            # 合法手の集合そのもの
            for side in ("top", "bottom"):
                mine = sorted(key(m) for m in py_legal_moves(st, side))
                theirs = rec["moves"][side]
                same = mine == theirs
                detail = ""
                if not same:
                    only_js = [k for k in theirs if k not in mine][:4]
                    only_py = [k for k in mine if k not in theirs][:4]
                    detail = "JSだけ=%s PYだけ=%s" % (only_js, only_py)
                ok &= report(same, name + " / 合法手の集合が一致(%s, %d通り)" % (side, len(mine)), detail)
            # 個別の手
            for (mv, want, label), got in zip(sc["probes"], rec["probes"]):
                js = got["legal"]
                py = py_legal(st, mv)
                ok &= report(js is want and py is want and got["applied"] in ("ok", "throw"),
                             name + " / %s → %s" % (label, "置ける" if want else "置けない"),
                             "JS=%r PY=%r apply=%s" % (js, py, got["applied"]))
            if "expect_top4" in sc:
                e = sc["expect_top4"]
                got4 = rec["tops"][4]
                ok &= report(got4 == [e["owner"], e["size"]] and rec["board"][4] == [[e["owner"], e["size"]]],
                             name + " / 下の駒が現れた", "マス4=%s 積み=%s" % (got4, rec["board"][4]))
            if "expect_winner" in sc:
                ok &= report(rec["winner"] == sc["expect_winner"],
                             name + " / 勝者は %s" % sc["expect_winner"], "実測=%s" % rec["winner"])
                ok &= report(py_judge(st, sc["setup"][-1]["player"]) == sc["expect_winner"],
                             name + " / Python の判定も %s" % sc["expect_winner"])
            if sc.get("expect_winners_both"):
                ok &= report(sorted(rec["winners"]) == ["bottom", "top"] and
                             sorted(py_winners(st)) == ["bottom", "top"],
                             name + " / 3並びは両者に成立している", "JS=%s" % rec["winners"])
            ok &= report(rec["immutable"], name + " / applyMove は元の状態を変えない")


def check_games(data, field, label, expect_finish):
    print("\n[%s] %s" % ("2" if field == "games" else "3", label))
    games = data[field]
    bad_move = bad_state = bad_count = bad_winner = bad_line = 0
    zero_legal = stopped = 0
    min_legal = 10 ** 9
    min_legal_handempty = 10 ** 9
    handempty_plies = 0
    plies = 0
    winners = {"top": 0, "bottom": 0, None: 0}
    first_bad = None

    for gi, g in enumerate(games):
        st = py_initial()
        stopped += g["stopped"]
        zero_legal += g["zero"]
        for mi, m in enumerate(g["moves"]):
            player, frm, size, to = m[0], m[1], m[2], m[3]
            mv = {"player": player, "from": ("hand" if frm == -1 else frm),
                  "size": size, "to": to}
            # 手番どおりか
            if player != st["turn"]:
                bad_move += 1
                first_bad = first_bad or ("手番違い", gi, mi, m)
                break
            legal = py_legal_moves(st, player)
            n = len(legal)
            plies += 1
            if n < min_legal:
                min_legal = n
            if not st["hands"][player]:
                handempty_plies += 1
                if n < min_legal_handempty:
                    min_legal_handempty = n
            if n != g["counts"][mi]:
                bad_count += 1
                first_bad = first_bad or ("合法手の数の食い違い JS=%d PY=%d" % (g["counts"][mi], n), gi, mi, m)
            if not py_legal(st, mv) or key(mv) not in [key(x) for x in legal]:
                bad_move += 1
                first_bad = first_bad or ("反則の手が選ばれた", gi, mi, m)
                break
            st = py_apply(st, mv)
            reason = integrity(st)
            if reason:
                bad_state += 1
                first_bad = first_bad or ("状態が壊れた: " + reason, gi, mi, m)
                break
            if st["winner"] and mi != len(g["moves"]) - 1:
                bad_winner += 1
                first_bad = first_bad or ("決着後に手が続いた", gi, mi, m)
                break
        else:
            py_board = [[[p["owner"], p["size"]] for p in stk] for stk in st["board"]]
            if py_board != g["board"] or st["winner"] != g["winner"]:
                bad_winner += 1
                first_bad = first_bad or ("最終局面が食い違う JS勝者=%s PY勝者=%s" % (g["winner"], st["winner"]), gi, -1, None)
            winners[st["winner"]] = winners.get(st["winner"], 0) + 1
            if st["winner"]:
                ws = py_winners(st)
                if st["winner"] not in ws:
                    bad_line += 1
                    first_bad = first_bad or ("勝ちなのに3並びが無い", gi, -1, None)

    n = len(games)
    report(bad_move == 0, "%d局 反則の手が合法と判定されない" % n, "違反=%d" % bad_move)
    report(bad_count == 0, "%d局 合法手の数が Python と一致" % n, "食い違い=%d" % bad_count)
    report(bad_state == 0, "%d局 状態が壊れない（駒の数・積みの大小順）" % n, "破損=%d" % bad_state)
    report(bad_winner == 0, "%d局 最終局面と勝者が Python と一致" % n, "食い違い=%d" % bad_winner)
    report(bad_line == 0, "%d局 決着局面で本当に3並びが成立" % n, "不成立=%d" % bad_line)
    report(zero_legal == 0, "%d局 合法手がゼロになる局面が出ない" % n, "発生=%d" % zero_legal)
    if expect_finish:
        report(stopped == 0, "%d局 打ち切りに達しない" % n, "打ち切り=%d" % stopped)
    print("      手数=%d  合法手の最小=%d  勝ち上=%d 下=%d 未決=%d  打ち切り=%d"
          % (plies, min_legal, winners.get("top", 0), winners.get("bottom", 0),
             winners.get(None, 0), stopped))
    if handempty_plies:
        report(min_legal_handempty > 0, "持ち駒が尽きた側でも合法手がある",
               "該当手数=%d 合法手の最小=%d" % (handempty_plies, min_legal_handempty))
    else:
        print("      （持ち駒が尽きた局面はこの試行では出なかった）")
    if first_bad:
        print("      最初の不一致: %s  game=%s ply=%s move=%s" % first_bad)
    return handempty_plies


def check_no_zero(data):
    """合法手がゼロになる局面は存在しうるか。
    大(3)は何にもかぶせられない＝必ず見えている。盤の一番上が大のマスは最大4つ
    （大は全部で4個）。よって「大を置ける／動かせるマス」は常に5つ以上ある。
    どの局面でも各自 大2個を持ち駒か盤に持っているので、指す手が無くなることは無い。
    ここでは全局面でその前提（一番上が大のマス ≤ 4）が崩れないかを機械で確かめる。"""
    print("\n[4] 合法手がゼロになる局面")
    worst = 0
    n = 0
    for field in ("games", "longGames"):
        for g in data[field]:
            st = py_initial()
            for m in g["moves"]:
                mv = {"player": m[0], "from": ("hand" if m[1] == -1 else m[1]),
                      "size": m[2], "to": m[3]}
                if not py_legal(st, mv):
                    break
                st = py_apply(st, mv)
                n += 1
                big = sum(1 for c in range(9) if (py_top(st, c) or {"size": 0})["size"] == 3)
                if big > worst:
                    worst = big
                # 各自、大を必ず1個以上「使える形」で持っている
                for side in ("top", "bottom"):
                    have_big = (3 in st["hands"][side]) or any(
                        (py_top(st, c) or {}).get("owner") == side and py_top(st, c)["size"] == 3
                        for c in range(9))
                    if not have_big:
                        report(False, "大を1個も使えない側が現れた", "side=%s" % side)
                        return
    report(worst <= 4, "一番上が大のマスは常に4つ以下（＝大を置けるマスが5つ以上残る）",
           "最大=%d / %d局面" % (worst, n))
    report(True, "合法手ゼロの局面は理論上も存在しない",
           "大(3)は覆えず必ず見え、各自2個持つ。置き先は常に5マス以上")


def main():
    print("かぶせっこ 規則の機械検査")
    data = run_node()
    check_scenarios(data)
    he1 = check_games(data, "games", "でたらめ対局 1000局（合法手から一様に選ぶ）", True)
    he2 = check_games(data, "longGames", "長引かせた対局 100局（勝ちを避けて持ち駒を使い切らせる）", False)
    check_no_zero(data)
    if not he1 and not he2:
        report(False, "持ち駒が尽きた局面に一度も到達しなかった", "試験が届いていない")
    print("\n" + ("すべて通過" if not _fail else "NG %d件: %s" % (len(_fail), _fail[:6])))
    sys.exit(0 if not _fail else 1)


if __name__ == "__main__":
    main()
