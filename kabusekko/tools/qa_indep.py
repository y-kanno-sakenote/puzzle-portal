#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""かぶせっこ 独立検証（qa係）

実装者が書いた tools/qa_check.py は読んだが中身は流用していない（同じ思い込みを
引き継がないため）。ここでの Python 実装は docs/spec.md と docs/decision_log.md
だけを根拠に自分で組み直したもの。index.html のロジックのコードは読んで手法は
把握したが、判定式そのものは書き写していない。

    python3 tools/qa_indep.py

標準ライブラリのみ。node が要る。
"""

import json
import os
import random
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, "index.html")

LINES = [(0, 1, 2), (3, 4, 5), (6, 7, 8),
         (0, 3, 6), (1, 4, 7), (2, 5, 8),
         (0, 4, 8), (2, 4, 6)]
HAND = (3, 3, 2, 2, 1, 1)  # 各自 大2・中2・小2

_fail = []


def report(ok, label, detail=""):
    print(("  OK  " if ok else "  NG  ") + label + ((" " + detail) if detail else ""))
    if not ok:
        _fail.append(label)
    return ok


# =====================================================================
# 独立実装（spec.md / decision_log.md のみを根拠に組む）
# =====================================================================

def other(p):
    return 'bottom' if p == 'top' else 'top'


def init_state():
    return {
        'board': [[] for _ in range(9)],
        'hands': {'top': list(HAND), 'bottom': list(HAND)},
        'turn': 'bottom',   # 決定ログ 2026-09-13: 先手は下（青）
        'winner': None,
    }


def clone(s):
    return {
        'board': [[dict(p) for p in st] for st in s['board']],
        'hands': {k: list(v) for k, v in s['hands'].items()},
        'turn': s['turn'],
        'winner': s['winner'],
    }


def is_cell(c):
    return isinstance(c, int) and not isinstance(c, bool) and 0 <= c <= 8


def is_size(v):
    return (not isinstance(v, bool)) and v in (1, 2, 3)


def is_player(p):
    return p in ('top', 'bottom')


def top_of(s, cell):
    if not is_cell(cell):
        return None
    st = s['board'][cell]
    return st[-1] if st else None


def can_cover(under, size):
    return under is None or under['size'] < size


def is_legal(s, mv):
    if not isinstance(mv, dict):
        return False
    if s.get('winner'):
        return False
    player = mv['player'] if 'player' in mv and mv['player'] is not None else s['turn']
    if not is_player(player):
        return False
    if player != s['turn']:
        return False  # 手番でない側は指せない
    to = mv.get('to')
    if not is_cell(to):
        return False
    frm = mv.get('from')
    if frm == 'hand':
        size = mv.get('size')
        if not is_size(size):
            return False
        if size not in s['hands'][player]:
            return False
    else:
        if not is_cell(frm) or frm == to:
            return False
        p = top_of(s, frm)
        if p is None or p['owner'] != player:
            return False
        size = p['size']
    return can_cover(top_of(s, to), size)


def legal_moves(s, player):
    out = []
    if not is_player(player) or s.get('winner') or player != s['turn']:
        return out
    for size in sorted(set(s['hands'][player])):
        for c in range(9):
            if can_cover(top_of(s, c), size):
                out.append({'player': player, 'from': 'hand', 'size': size, 'to': c})
    for c in range(9):
        p = top_of(s, c)
        if not p or p['owner'] != player:
            continue
        for d in range(9):
            if d == c:
                continue
            if can_cover(top_of(s, d), p['size']):
                out.append({'player': player, 'from': c, 'size': p['size'], 'to': d})
    return out


def winners_of(s):
    out = []
    for (a, b, c) in LINES:
        pa, pb, pc = top_of(s, a), top_of(s, b), top_of(s, c)
        if pa and pb and pc and pa['owner'] == pb['owner'] == pc['owner']:
            if pa['owner'] not in out:
                out.append(pa['owner'])
    return out


def judge_after(s, mover):
    w = winners_of(s)
    if mover in w:
        return mover
    return w[0] if w else None


def apply_move(s, mv):
    if not is_legal(s, mv):
        raise ValueError('反則の手')
    player = mv['player'] if mv.get('player') is not None else s['turn']
    ns = clone(s)
    if mv['from'] == 'hand':
        size = mv['size']
        ns['hands'][player].remove(size)
    else:
        size = ns['board'][mv['from']].pop()['size']
    ns['board'][mv['to']].append({'owner': player, 'size': size})
    ns['winner'] = judge_after(ns, player)
    ns['turn'] = player if ns['winner'] else other(player)
    return ns


def move_key(mv):
    if mv['from'] == 'hand':
        return 'H%d>%d' % (mv['size'], mv['to'])
    return '%d>%d' % (mv['from'], mv['to'])


def parse_key(key, player):
    if key.startswith('H'):
        size_s, to_s = key[1:].split('>')
        return {'player': player, 'from': 'hand', 'size': int(size_s), 'to': int(to_s)}
    frm_s, to_s = key.split('>')
    return {'player': player, 'from': int(frm_s), 'to': int(to_s)}


def board_dump(s):
    return [[[p['owner'], p['size']] for p in st] for st in s['board']]


# =====================================================================
# index.html から window.Kabusekko の <script> を取り出す
# =====================================================================

def read_scripts():
    src = open(INDEX, encoding='utf-8').read()
    out, idx = [], 0
    while True:
        b = src.find('<script>', idx)
        if b < 0:
            break
        e = src.find('</script>', b)
        out.append(src[b + len('<script>'):e])
        idx = e + len('</script>')
    return out


def extract_logic(scripts):
    for sc in scripts:
        if 'window.Kabusekko' in sc:
            return sc
    print('  NG  window.Kabusekko を含む <script> が無い')
    sys.exit(1)


def run_node(js_src, timeout=180):
    tmp = os.path.join(tempfile.gettempdir(), 'kabusekko_qa_indep_%d.js' % os.getpid())
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(js_src)
    r = subprocess.run(['node', tmp], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        print('  NG  node 実行 exit=%d\n%s' % (r.returncode, r.stderr[:3000]))
        sys.exit(1)
    return r.stdout


# =====================================================================
# [1] でたらめ対局 2000 局 + 手番偏り局 300 局（実装者の1000局より多い）
# =====================================================================

RANDOM_GAMES_JS = r"""
__LOGIC__
function mulberry32(a){return function(){a|=0;a=a+0x6D2B79F5|0;var t=Math.imul(a^a>>>15,1|a);
  t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296;};}
function keyOf(m){return m.from==='hand' ? ('H'+m.size+'>'+m.to) : (m.from+'>'+m.to);}
function dumpBoard(s){return s.board.map(function(st){return st.map(function(p){return [p.owner,p.size];});});}
function playGame(rnd, maxPlies, biasHand){
  var st = Kabusekko.initialState();
  var plies = [];
  var zero = false;
  for(var i=0;i<maxPlies;i++){
    if(st.winner) break;
    var player = st.turn;
    var moves = Kabusekko.legalMoves(st, player);
    if(!moves.length){ zero = true; break; }
    var pick;
    if(biasHand && rnd() < 0.6){
      var hm = moves.filter(function(m){return m.from==='hand';});
      pick = hm.length ? hm[Math.floor(rnd()*hm.length)] : moves[Math.floor(rnd()*moves.length)];
    } else {
      pick = moves[Math.floor(rnd()*moves.length)];
    }
    var legalKeys = moves.map(keyOf).sort().join(',');
    var chosen = keyOf(pick);
    st = Kabusekko.applyMove(st, pick);
    plies.push({p: player, legal: legalKeys, chosen: chosen, board: dumpBoard(st),
                hTop: st.hands.top.slice().sort(), hBot: st.hands.bottom.slice().sort(),
                turn: st.turn, winner: st.winner});
  }
  var stopped = (!st.winner && !zero && plies.length>=maxPlies) ? 1 : 0;
  return {plies: plies, winner: st.winner, zero: zero?1:0, stopped: stopped};
}
var rnd = mulberry32(__SEED__);
var games = [];
for (var g=0; g<__NGAMES__; g++) games.push(playGame(rnd, __MAXPLIES__, false));
var biasGames = [];
for (var g=0; g<__NBIAS__; g++) biasGames.push(playGame(rnd, __MAXPLIES__, true));
var init0 = Kabusekko.initialState();
var initMoves = Kabusekko.legalMoves(init0, 'bottom').map(keyOf).sort();
console.log(JSON.stringify({games: games, biasGames: biasGames, initMoves: initMoves}));
"""


def check_random_games(logic):
    print('\n[1] でたらめ対局（Node で Kabusekko 自身に指させ、Python 独立実装で突き合わせ）')
    js = (RANDOM_GAMES_JS.replace('__LOGIC__', logic)
          .replace('__SEED__', '20260913')
          .replace('__NGAMES__', '2000')
          .replace('__NBIAS__', '300')
          .replace('__MAXPLIES__', '80'))
    data = json.loads(run_node(js))

    init_moves_py = sorted(move_key(m) for m in legal_moves(init_state(), 'bottom'))
    report(init_moves_py == data['initMoves'], '初期局面の合法手集合が一致',
           '件数 JS=%d PY=%d' % (len(data['initMoves']), len(init_moves_py)))

    for label, games in (('通常', data['games']), ('持ち駒優先バイアス', data['biasGames'])):
        bad_legal = bad_apply = bad_state = bad_winline = 0
        zero_seen = stopped_seen = 0
        min_legal = 10 ** 9
        handempty_plies = 0
        min_legal_handempty = 10 ** 9
        total_plies = 0
        winners_count = {'top': 0, 'bottom': 0, None: 0}
        first_bad = None
        for gi, g in enumerate(games):
            zero_seen += g['zero']
            stopped_seen += g['stopped']
            st = init_state()
            for mi, ply in enumerate(g['plies']):
                player = ply['p']
                mine = sorted(move_key(m) for m in legal_moves(st, player))
                theirs = ply['legal'].split(',') if ply['legal'] else []
                total_plies += 1
                if len(mine) < min_legal:
                    min_legal = len(mine)
                if not st['hands'][player]:
                    handempty_plies += 1
                    if len(mine) < min_legal_handempty:
                        min_legal_handempty = len(mine)
                if mine != theirs:
                    bad_legal += 1
                    if first_bad is None:
                        first_bad = ('合法手集合の食い違い', label, gi, mi,
                                      'PYのみ=%s JSのみ=%s' % (
                                          [k for k in mine if k not in theirs][:4],
                                          [k for k in theirs if k not in mine][:4]))
                    break
                mv = parse_key(ply['chosen'], player)
                if not is_legal(st, mv):
                    bad_apply += 1
                    if first_bad is None:
                        first_bad = ('JSが選んだ手をPYが反則と判定', label, gi, mi, mv)
                    break
                st = apply_move(st, mv)
                if board_dump(st) != ply['board'] or sorted(st['hands']['top']) != ply['hTop'] \
                        or sorted(st['hands']['bottom']) != ply['hBot'] or st['turn'] != ply['turn'] \
                        or st['winner'] != ply['winner']:
                    bad_state += 1
                    if first_bad is None:
                        first_bad = ('適用後の状態が食い違う', label, gi, mi,
                                      'JS.winner=%s PY.winner=%s' % (ply['winner'], st['winner']))
                    break
                if st['winner']:
                    if st['winner'] not in winners_of(st):
                        bad_winline += 1
                        if first_bad is None:
                            first_bad = ('勝ちなのに3並びが無い', label, gi, mi, None)
            else:
                winners_count[st['winner']] = winners_count.get(st['winner'], 0) + 1

        n = len(games)
        report(bad_legal == 0, '%s %d局: 合法手の集合が全手一致' % (label, n), '不一致=%d' % bad_legal)
        report(bad_apply == 0, '%s %d局: JSが選んだ手はPYでも常に合法' % (label, n), '違反=%d' % bad_apply)
        report(bad_state == 0, '%s %d局: 適用後の盤/持ち駒/手番/勝者が一致' % (label, n), '不一致=%d' % bad_state)
        report(bad_winline == 0, '%s %d局: 決着局面は必ず3並びが実在' % (label, n), '不成立=%d' % bad_winline)
        report(zero_seen == 0, '%s %d局: 合法手ゼロで打ち切られた対局は無い' % (label, n), '件数=%d' % zero_seen)
        print('      手数計=%d 合法手最小=%d 勝ち top=%d bottom=%d 未決=%d 上限打ち切り=%d'
              % (total_plies, min_legal, winners_count.get('top', 0), winners_count.get('bottom', 0),
                 winners_count.get(None, 0), stopped_seen))
        if handempty_plies:
            report(min_legal_handempty > 0, '      持ち駒が尽きた側にも常に合法手がある',
                   '該当手数=%d 最小=%d' % (handempty_plies, min_legal_handempty))
        if first_bad:
            print('      最初の不一致:', first_bad)


# =====================================================================
# [2] 仕様の細かい所を狙った単発プローブ（自作状態で is_legal を直撃）
# =====================================================================

SCENARIO_JS = r"""
__LOGIC__
function run(cmds){
  var out = [];
  cmds.forEach(function(c){
    try {
      if (c.op === 'legal') out.push({ok:true, v: Kabusekko.isLegal(c.state, c.move)});
      else if (c.op === 'apply') {
        try { var ns = Kabusekko.applyMove(c.state, c.move); out.push({ok:true, v:'applied', state: ns}); }
        catch(e){ out.push({ok:true, v:'threw', msg: e.message}); }
      } else if (c.op === 'winners') out.push({ok:true, v: Kabusekko.winnerOf(c.state)});
    } catch(e){ out.push({ok:false, err: e.message}); }
  });
  return out;
}
console.log(JSON.stringify(run(__CMDS__)));
"""


def mk_state(board_pairs, hands, turn, winner=None):
    """board_pairs: {cell: [[owner,size], ...stack bottom→top]}"""
    board = [[] for _ in range(9)]
    for cell, stack in board_pairs.items():
        board[cell] = [{'owner': o, 'size': sz} for (o, sz) in stack]
    return {'board': board, 'hands': {k: list(v) for k, v in hands.items()}, 'turn': turn, 'winner': winner}


def check_rule_probes(logic):
    print('\n[2] 仕様の細かい所（自作局面で is_legal / applyMove を直撃）')

    cmds = []
    probes = []  # (label, expect_bool) を cmds と対応させる

    def add_legal(label, state, move, expect):
        cmds.append({'op': 'legal', 'state': state, 'move': move})
        probes.append((label, expect, state, move))

    # 同じ大きさの上に置けない（持ち駒 中2 を、盤の中2の上へ）
    s1 = mk_state({0: [('bottom', 2)]}, {'top': [3, 3, 2, 1, 1], 'bottom': [3, 3, 2, 1, 1]}, 'top')
    add_legal('同じ大きさの上に置けない(中→中)', s1, {'player': 'top', 'from': 'hand', 'size': 2, 'to': 0}, False)

    # より大きい駒の上に置けない（盤の大3の上に、持ち駒の小1を置く）
    s2 = mk_state({0: [('bottom', 3)]}, {'top': [3, 2, 2, 1, 1], 'bottom': [3, 2, 2, 1, 1]}, 'top')
    add_legal('より大きい駒の上に置けない(小→大)', s2, {'player': 'top', 'from': 'hand', 'size': 1, 'to': 0}, False)
    # ただし小さい駒の上には置ける（大3を、盤の小1の上へ）
    add_legal('自分より大きい駒はより小さい駒の上に置ける(大→小)',
              mk_state({1: [('top', 1)]}, {'top': [3, 3, 2, 2, 1], 'bottom': [3, 3, 2, 2, 1, 1]}, 'top'),
              {'player': 'top', 'from': 'hand', 'size': 3, 'to': 1}, True)

    # 相手の駒は動かせない
    s3 = mk_state({4: [('top', 2)]}, {'top': [3, 3, 1, 1], 'bottom': [3, 3, 2, 2, 1, 1]}, 'bottom')
    add_legal('相手の駒は動かせない', s3, {'player': 'bottom', 'from': 4, 'to': 0}, False)

    # 埋まっている自分の駒は動かせない（bottom小1がtop中2に覆われている。from=そのマスは常にtopが解決する）
    s4 = mk_state({2: [('bottom', 1), ('top', 2)]}, {'top': [3, 3, 2, 1, 1], 'bottom': [3, 3, 2, 2, 1]}, 'bottom')
    add_legal('埋まっている自分の駒は動かせない(topがかぶせ中)', s4, {'player': 'bottom', 'from': 2, 'to': 0}, False)
    s4b = mk_state({2: [('bottom', 1), ('top', 2)]}, {'top': [3, 3, 2, 1, 1], 'bottom': [3, 3, 2, 2, 1]}, 'top')
    add_legal('かぶせている側(top)は同じマスの駒を動かせる', s4b, {'player': 'top', 'from': 2, 'to': 0}, True)

    # 手番でない側は指せない
    s5 = init_state()
    add_legal('手番でない側(top)は打てない(turn=bottom)', s5, {'player': 'top', 'from': 'hand', 'size': 3, 'to': 0}, False)

    # 現れ直し: topが2で覆っていたbottom1の上から退けると、bottom1がまた見える
    s6 = mk_state({0: [('bottom', 1), ('top', 2)]}, {'top': [3, 3, 2, 1, 1], 'bottom': [3, 3, 2, 2, 1]}, 'top')
    cmds.append({'op': 'apply', 'state': s6, 'move': {'player': 'top', 'from': 0, 'to': 5}})
    reveal_idx = len(cmds) - 1

    print('  --- 単発プローブ ---')
    results = json.loads(run_node(
        SCENARIO_JS.replace('__LOGIC__', logic).replace('__CMDS__', json.dumps(cmds))))

    for (label, expect, state, move), got in zip(probes, results[:len(probes)]):
        js_ok = got.get('ok') and got.get('v') is expect
        py_ok = is_legal(state, move) is expect
        report(js_ok and py_ok, label + (' → 可' if expect else ' → 不可'),
               'JS=%r PY=%r' % (got.get('v'), is_legal(state, move)))

    rv = results[reveal_idx]
    py_after = apply_move(s6, {'player': 'top', 'from': 0, 'to': 5})
    report(rv['v'] == 'applied' and rv['state']['board'][0] == [{'owner': 'bottom', 'size': 1}],
           '退けたら下の駒がまた現れる(JS)', 'JS盤0=%s' % rv.get('state', {}).get('board', [None])[0])
    report(py_after['board'][0] == [{'owner': 'bottom', 'size': 1}],
           '退けたら下の駒がまた現れる(PY)', 'PY盤0=%s' % py_after['board'][0])


# =====================================================================
# [3] 勝ち判定の3通り（本人の列／相手の列が現れる／両方同時は本人）
#     手順は自分で組んだ move 列。合法性は毎手 Python で確認しながら進める。
# =====================================================================

def play_sequence(seq):
    st = init_state()
    for mv in seq:
        assert is_legal(st, mv), 'PY: 手順中に反則: %r' % (mv,)
        st = apply_move(st, mv)
    return st


WIN_SCENARIOS = {
    '本人の列(横一列を自分で作る)': (
        [
            {'player': 'bottom', 'from': 'hand', 'size': 1, 'to': 0},
            {'player': 'top', 'from': 'hand', 'size': 1, 'to': 3},
            {'player': 'bottom', 'from': 'hand', 'size': 1, 'to': 1},
            {'player': 'top', 'from': 'hand', 'size': 1, 'to': 4},
            {'player': 'bottom', 'from': 'hand', 'size': 2, 'to': 2},
        ], 'bottom'),
    '相手の列が現れて相手の勝ち(自分は移動しただけ)': (
        [
            {'player': 'bottom', 'from': 'hand', 'size': 1, 'to': 6},
            {'player': 'top', 'from': 'hand', 'size': 1, 'to': 0},
            {'player': 'bottom', 'from': 'hand', 'size': 2, 'to': 0},   # bottomがtopの小をかぶせる
            {'player': 'top', 'from': 'hand', 'size': 1, 'to': 1},
            {'player': 'bottom', 'from': 'hand', 'size': 1, 'to': 7},
            {'player': 'top', 'from': 'hand', 'size': 2, 'to': 2},
            {'player': 'bottom', 'from': 0, 'to': 4},                  # 退けるとtopの行0が現れる。bottom自身は列なし
        ], 'top'),
    '両方同時に成立したら本人の勝ち': (
        [
            {'player': 'bottom', 'from': 'hand', 'size': 1, 'to': 3},
            {'player': 'top', 'from': 'hand', 'size': 1, 'to': 6},
            {'player': 'bottom', 'from': 'hand', 'size': 1, 'to': 4},
            {'player': 'top', 'from': 'hand', 'size': 1, 'to': 7},
            {'player': 'bottom', 'from': 'hand', 'size': 2, 'to': 6},  # bottomがtopの小をかぶせる(隠す)
            {'player': 'top', 'from': 'hand', 'size': 2, 'to': 8},
            {'player': 'bottom', 'from': 6, 'to': 5},  # 退けて自分の行1完成、同時に相手の行2も出現
        ], 'bottom'),
}


APPLY_SEQ_JS = r"""
__LOGIC__
var seq = __SEQ__;
var st = Kabusekko.initialState();
var log = [];
for (var i=0;i<seq.length;i++){
  var legal = Kabusekko.isLegal(st, seq[i]);
  if (!legal) { log.push({i:i, legal:false}); break; }
  st = Kabusekko.applyMove(st, seq[i]);
  log.push({i:i, legal:true, winner: st.winner});
}
console.log(JSON.stringify({log: log, winner: st.winner, winners: Kabusekko.winnerOf(st)}));
"""


def check_win_scenarios(logic):
    print('\n[3] 勝ち判定の3通り（自作手順をPYで検証し、同じ手順をJSにも通す）')
    for name, (seq, expect) in WIN_SCENARIOS.items():
        try:
            st = play_sequence(seq)
            py_ok = st['winner'] == expect
        except AssertionError as e:
            py_ok = False
            st = None
        js = json.loads(run_node(APPLY_SEQ_JS.replace('__LOGIC__', logic).replace('__SEQ__', json.dumps(seq))))
        js_ok = js['winner'] == expect and all(x['legal'] for x in js['log'])
        report(py_ok and js_ok, name,
               'PY勝者=%s JS勝者=%s 期待=%s' % (st['winner'] if st else 'PY手順が反則', js['winner'], expect))


# =====================================================================
# [4] 壊れた入力
# =====================================================================

MALFORMED_JS = r"""
__LOGIC__
var st = Kabusekko.initialState();
function t(mv){
  try { return {ok:true, v: Kabusekko.isLegal(st, mv)}; }
  catch(e){ return {ok:false, err: e.message}; }
}
function ta(mv){
  try { Kabusekko.applyMove(st, mv); return {threw:false}; }
  catch(e){ return {threw:true, msg: e.message}; }
}
var cases = __CASES__;
var out = cases.map(function(c){ return c.apply ? ta(c.move) : t(c.move); });
console.log(JSON.stringify(out));
"""


def check_malformed(logic):
    print('\n[4] 壊れた入力（盤外・無い大きさ・空きマスから・null・手番でない側）')
    cases = [
        ('to=9(盤外)', {'from': 'hand', 'size': 3, 'to': 9}, False, False),
        ('to=-1', {'from': 'hand', 'size': 3, 'to': -1}, False, False),
        ('to=3.5(整数でない)', {'from': 'hand', 'size': 3, 'to': 3.5}, False, False),
        ('size=0(存在しない)', {'from': 'hand', 'size': 0, 'to': 0}, False, False),
        ('size=4(存在しない)', {'from': 'hand', 'size': 4, 'to': 0}, False, False),
        ('from=空きマス5', {'from': 5, 'to': 0}, False, False),
        ('move=null', None, False, False),
        ('move={}', {}, False, False),
        ('手番でない側(top)が打つ', {'player': 'top', 'from': 'hand', 'size': 3, 'to': 0}, False, False),
        ('apply(空きマスから)は例外', {'from': 5, 'to': 0}, None, True),
        ('apply(null)は例外', None, None, True),
    ]
    js_cases = [{'move': mv, 'apply': is_apply} for (_, mv, _, is_apply) in cases]
    results = json.loads(run_node(MALFORMED_JS.replace('__LOGIC__', logic).replace('__CASES__', json.dumps(js_cases))))

    st = init_state()
    for (label, mv, expect, is_apply), got in zip(cases, results):
        if is_apply:
            report(got.get('threw') is True, label, 'JS threw=%s' % got.get('threw'))
        else:
            js_v = got.get('v')
            py_v = is_legal(st, mv) if not isinstance(mv, list) else False
            report(js_v is expect and py_v is expect, label, 'JS=%r PY=%r' % (js_v, py_v))


# =====================================================================
# [5] localStorage 壊れ値で起動が落ちないか（vm + 最小 document スタブ）
# =====================================================================

STORAGE_HARNESS = r"""
const vm = require('vm');
class El {
  constructor(tag){ this.tag=tag; this.children=[]; this.dataset={}; this._class=''; }
  get className(){return this._class;} set className(v){this._class=v;}
  get childNodes(){return this.children;}
  get firstChild(){return this.children[0]||null;}
  appendChild(c){ this.children.push(c); return c; }
  removeChild(c){ const i=this.children.indexOf(c); if(i>=0) this.children.splice(i,1); }
  addEventListener(){}
  setPointerCapture(){}
  classList = { toggle(){}, add(){}, remove(){} };
  closest(){ return null; }
  getBoundingClientRect(){ return {left:0,right:10,top:0,bottom:10}; }
  querySelectorAll(){ return []; }
}
function makeDocument(){
  const ids = {};
  ['board','handTop','handBottom','sideTop','sideBottom','noteTop','noteBottom',
   'over','resTop','resBottom','app','againOver'].forEach(id=>{ ids[id]=new El('div'); });
  return {
    getElementById(id){ return ids[id] || null; },
    createElement(tag){ return new El(tag); },
    querySelectorAll(){ return []; },
    body: new El('body'),
  };
}
const cases = __CASES__;
const logic = __LOGIC_JSON__;
const screen = __SCREEN_JSON__;
const out = cases.map(function(c){
  const ctx = { console: console, Number: Number, JSON: JSON, Array: Array, Math: Math, Object: Object };
  ctx.document = makeDocument();
  ctx.localStorage = {
    getItem(k){ if (c.getThrow) throw new Error('getItem boom'); return c.raw; },
    setItem(k,v){ if (c.setThrow) throw new Error('setItem boom'); },
  };
  ctx.window = ctx; ctx.globalThis = ctx;
  vm.createContext(ctx);
  try {
    vm.runInContext(logic, ctx);
    vm.runInContext(screen, ctx);
    return {ok: true};
  } catch (e) {
    return {ok: false, msg: e.message};
  }
});
console.log(JSON.stringify(out));
"""


def check_local_storage(scripts):
    print('\n[5] localStorage 壊れ値（getItem/setItem を差し替えて起動を実走）')
    logic = extract_logic(scripts)
    screen = None
    for sc in scripts:
        if 'localStorage' in sc and 'kabusekko' in sc:
            screen = sc
    if screen is None:
        report(False, '画面側 <script>（localStorage を使う方）が見つからない')
        return

    cases = [
        {'label': '非JSON文字列', 'raw': 'not json'},
        {'label': 'raw=null(未保存相当)', 'raw': None},
        {'label': '配列JSON', 'raw': '[1,2,3]'},
        {'label': 'wins無し', 'raw': '{}'},
        {'label': 'wins型不正(文字列)', 'raw': json.dumps({'wins': 'x'})},
        {'label': 'wins.top文字列型', 'raw': json.dumps({'wins': {'top': '3', 'bottom': 0}})},
        {'label': 'wins.top負数', 'raw': json.dumps({'wins': {'top': -5, 'bottom': 0}})},
        {'label': 'wins.top小数', 'raw': json.dumps({'wins': {'top': 1.5, 'bottom': 0}})},
        {'label': 'wins=null', 'raw': json.dumps({'wins': None})},
        {'label': 'getItemがthrow', 'raw': None, 'getThrow': True},
        {'label': 'setItemがthrow', 'raw': None, 'setThrow': True},
    ]
    js = (STORAGE_HARNESS.replace('__CASES__', json.dumps(cases))
          .replace('__LOGIC_JSON__', json.dumps(logic))
          .replace('__SCREEN_JSON__', json.dumps(screen)))
    results = json.loads(run_node(js))
    for c, r in zip(cases, results):
        report(r['ok'], 'localStorage: %s → 起動が落ちない' % c['label'], r.get('msg', ''))


# =====================================================================
# [6] 合法手がゼロになる局面は本当に無いか（独立実装でBFS/DFS探索）
# =====================================================================

def canon(s):
    board = tuple(tuple((p['owner'], p['size']) for p in st) for st in s['board'])
    hands = (tuple(sorted(s['hands']['top'])), tuple(sorted(s['hands']['bottom'])))
    return (board, hands, s['turn'])


def search_no_zero_legal(state_budget=400000, time_budget_sec=60):
    print('\n[6] 合法手がゼロになる局面の探索（独立実装のみで到達可能な局面をしらみつぶし）')
    t0 = time.time()
    start = init_state()
    seen = {canon(start)}
    stack = [start]
    visited_nonterminal = 0
    max_big_visible = 0
    zero_states = []
    exhausted = True
    while stack:
        if len(seen) >= state_budget or (time.time() - t0) > time_budget_sec:
            exhausted = False
            break
        s = stack.pop()
        if s['winner']:
            continue
        visited_nonterminal += 1
        big = sum(1 for c in range(9) if (top_of(s, c) or {}).get('size') == 3)
        if big > max_big_visible:
            max_big_visible = big
        moves = legal_moves(s, s['turn'])
        if not moves:
            zero_states.append(s)
            continue
        for mv in moves:
            ns = apply_move(s, mv)
            k = canon(ns)
            if k not in seen:
                seen.add(k)
                stack.append(ns)
    report(len(zero_states) == 0, '探索した局面(%d件, 非終端%d件)に合法手ゼロは無い'
           % (len(seen), visited_nonterminal), '発見=%d' % len(zero_states))
    report(max_big_visible <= 4, '一番上が「大」のマスは常に4つ以下(大は全部で4個しか無い)',
           '実測最大=%d' % max_big_visible)
    print('      探索を使い切った(全数): %s  経過=%.1fs  visited=%d' % (exhausted, time.time() - t0, len(seen)))
    if not exhausted:
        print('      【要確認】状態数が予算を超えたため打ち切り。全数証明ではなく大規模サンプルでの確認')


# =====================================================================
# [7] 足さないものが入っていないか（spec.md の禁止リストをテキスト走査）
# =====================================================================

def check_not_added():
    print('\n[7] spec.md「足さないもの」がindex.htmlに紛れ込んでいないか')
    src = open(INDEX, encoding='utf-8').read()
    banned = ['制限時間', 'タイマー', 'undo', 'Undo', 'コンピュータ', 'AI対戦',
              'setInterval', '覗く', '手数:', '手数表示']
    hit = [b for b in banned if b in src]
    report(len(hit) == 0, 'index.html に禁止語が出てこない', '検出=%s' % hit)
    # 「待った」は「待ったは無し」という否定コメントで出現しうるので機能有無で見る
    if '待った' in src and ('待ったは無し' not in src and '待ったが出来る' not in src):
        report(False, '「待った」に触れる記述があるが文脈不明', 'grepで目視要')
    # setTimeout はゴーストのドラッグ演出等に無関係な用途で使われうるので個別に見る
    if 'setInterval' in src:
        report(False, 'setInterval が使われている(制限時間演出の疑い)')


# =====================================================================
def main():
    scripts = read_scripts()
    logic = extract_logic(scripts)
    check_random_games(logic)
    check_rule_probes(logic)
    check_win_scenarios(logic)
    check_malformed(logic)
    check_local_storage(scripts)
    search_no_zero_legal()
    check_not_added()

    print('\n==== まとめ ====')
    if _fail:
        print('NG項目 %d件:' % len(_fail))
        for f in _fail:
            print('  - ' + f)
        sys.exit(1)
    else:
        print('全項目 OK')


if __name__ == '__main__':
    main()
