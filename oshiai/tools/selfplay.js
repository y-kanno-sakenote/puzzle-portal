#!/usr/bin/env node
/* おしあい 自動対局（index.html の window.Oshiai をそのまま読み込んで指す）
   使い方: node oshiai/tools/selfplay.js [局数=2000] [種=20261015]
   OSHIAI_HTML=ファイル  別の版の index.html を読む（前の版との比べ用。旧版には target が無いので下で補う）
   OSHIAI_RULE=案        先手の有利を縮める案を、読み込んだ規則の上にかぶせて比べる（2026-10-15。既定は読み込んだ規則のまま）
                          B=先手の最初の手番は押すだけ（v0.3 で index.html に採用済み）  M=先手の最初の手番は動かすだけ（押さない）
                          B2=先手の最初の2手番は押すだけ  BF=Bに加えて、後手の最初の押し込みは押し戻しの禁止なし
                          ※ かぶせる案は旧版の上で比べる：OSHIAI_HTML=<d5f2bfd の index.html> OSHIAI_RULE=M …（案A＝旧版そのまま）
   OSHIAI_POL=名,名…     指し手役（既定 random,greedy,blocker1,blocker,defender）。各役の同士対局を、先手を交互にして指す
     random   押し込み口・向き・行き先を一様に
     greedy   次の宝に止まれるならそれ。無ければ届くマスのうち次の宝に一番近いマス（手持ちに乗っていれば距離8）
     blocker1 見える範囲だけ邪魔：拾えるなら拾う。だめなら「押した直後に相手が次の宝へつながらない」押し込みを優先し、その中で貪欲
     blocker  守り寄りで拾えるなら拾う：拾えるなら拾う。だめなら相手の次の一押し（口×向き）で相手が拾える数が最小、その中で貪欲
     defender 守り手：勝てる手 → 相手の次の一押しで拾える数が最小 → 自分が拾える → 近づく（前からの役）
   決着までの手数の分布・上限到達と引き分けの率・先手の勝率を出し、配った盤が180度対称か・押し込みが毎回7通り以上あるかを確かめる */
'use strict';
var fs = require('fs'), path = require('path'), vm = require('vm');

var html = fs.readFileSync(process.env.OSHIAI_HTML || path.join(__dirname, '..', 'index.html'), 'utf8');
var src = html.match(/<script>([\s\S]*?)<\/script>/)[1];   /* 1つ目の script＝純粋ロジック */
var ctx = { globalThis: {} };
vm.createContext(ctx);
vm.runInContext(src, ctx);
var O = ctx.globalThis.Oshiai;

var GAMES = +(process.argv[2] || 2000), SEED = +(process.argv[3] || 20261015);
var RULE = process.env.OSHIAI_RULE || '';
var POLS = (process.env.OSHIAI_POL || 'random,greedy,blocker1,blocker,defender').split(',');
if (process.env.NO_DEFENDER) POLS = POLS.filter(function (p) { return p !== 'defender' && p !== 'blocker'; });

function mulberry32(a) {
  return function () {
    a |= 0; a = a + 0x6D2B79F5 | 0;
    var t = Math.imul(a ^ a >>> 15, 1 | a);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}
/* 人 w が次に狙うマス（-1=手持ちに乗っている／-2=拾い終えた） */
function target(s, w) {
  if (O.target) return O.target(s, w);
  return s.next[w] < O.GOAL ? s.tre[w][s.next[w]] : -2;
}
function pick(a, rng) { return a[Math.floor(rng() * a.length)]; }
function dist(a, b) { return Math.abs((a / 5 | 0) - (b / 5 | 0)) + Math.abs(a % 5 - b % 5); }

var problems = [];
function check(c, msg) { if (!c) problems.push(msg); }

/* ---- 案のかぶせ（turns は手番の終わりに増えるので、押した後の状態でも「今の手番が何手目か」を表す） ---- */
function pushOnly(s) {                  /* この手番は押すだけ（駒は動かせない＝とどまる） */
  if (RULE === 'B' || RULE === 'BF') return s.turns === 0;
  if (RULE === 'B2') return s.turns === 0 || s.turns === 2;
  return false;
}
function moveOnly(s) { return RULE === 'M' && s.turns === 0; }   /* この手番は押さない（動かすだけ） */

/* 押し込みの段の選択肢（押した後の状態の一覧）。「押さない」手番は今の状態をそのまま動かす段へ */
function pushes(s) {
  if (moveOnly(s)) { var u = O.clone(s); u.phase = 'move'; return [u]; }
  var out = [], ops = O.legalOps(s), vs = O.variants(s.hand);
  for (var a = 0; a < ops.length; a++) for (var b = 0; b < vs.length; b++) {
    var t = O.push(s, ops[a], vs[b]);
    if (RULE === 'BF' && s.turns === 0) t.ban = -1;
    out.push(t);
  }
  return out;
}
/* 押した後、人 me が行けるマス（規則が押すだけの手番を自前で終えていれば、とどまったマスだけ） */
function dests(t, me) {
  if (t.phase !== 'move') return [t.piece[me]];
  if (pushOnly(t)) return [t.piece[me]];
  var r = O.reachable(t, me), out = [];
  for (var i = 0; i < 25; i++) if (r[i]) out.push(i);
  return out;
}
function finish(t, cell) { return t.phase !== 'move' ? t : O.moveTo(t, cell); }
/* 押した後の状態 t で、人 me が次の宝に止まれるか */
function canPick(t, me) {
  var g = target(t, me);
  return g >= 0 && dests(t, me).indexOf(g) >= 0;
}
/* 押した後の状態 t から見た、相手 opp の次の手番の状態（押す段） */
function oppTurn(t, opp) {
  if (t.phase !== 'move') return t;
  var u = O.clone(t);
  u.phase = 'push'; u.turn = opp; u.turns = t.turns + 1;
  return u;
}
/* 相手の次の一押し（口×向き）で、相手が次の宝に止まれる数（自分の駒の置き場所は相手の届く範囲に効かない） */
function threats(t, opp) {
  var ps = pushes(oppTurn(t, opp)), cnt = 0;
  for (var i = 0; i < ps.length; i++) if (canPick(ps[i], opp)) cnt++;
  return cnt;
}
/* 押した後の t で、次の宝に一番近いマスとその距離（拾えるなら -1） */
function nearest(t, me, far) {
  var g = target(t, me), ds = dests(t, me);
  if (g >= 0 && ds.indexOf(g) >= 0) return { d: -1, dest: [g] };
  if (g < 0) return { d: far, dest: ds };
  var d = 99, dest = [];
  for (var i = 0; i < ds.length; i++) {
    var e = dist(ds[i], g);
    if (e < d) { d = e; dest = [ds[i]]; } else if (e === d) dest.push(ds[i]);
  }
  return { d: d, dest: dest };
}
/* 点の小さい手を集めて1つ選ぶ */
function choose(s, rng, score) {
  var ps = pushes(s), best = [], bs = 1e18;
  for (var i = 0; i < ps.length; i++) {
    var r = score(ps[i]);
    if (r.sc < bs) { bs = r.sc; best = []; }
    if (r.sc === bs) best.push({ t: ps[i], dest: r.dest });
  }
  var c = pick(best, rng);
  return finish(c.t, pick(c.dest, rng));
}

var POLICY = {
  random: function (s, rng) {
    var t = pick(pushes(s), rng);
    return finish(t, pick(dests(t, t.turn), rng));
  },
  greedy: function (s, rng) {
    var me = s.turn;
    return choose(s, rng, function (t) { var n = nearest(t, me, 8); return { sc: n.d, dest: n.dest }; });
  },
  blocker1: function (s, rng) {
    var me = s.turn, opp = 1 - me;
    return choose(s, rng, function (t) {
      var n = nearest(t, me, 8);
      if (n.d < 0) return { sc: -1, dest: n.dest };
      return { sc: (canPick(oppTurnView(t), opp) ? 1000 : 0) + n.d, dest: n.dest };
    });
  },
  blocker: function (s, rng) {
    var me = s.turn, opp = 1 - me;
    return choose(s, rng, function (t) {
      var n = nearest(t, me, 8);
      if (n.d < 0) return { sc: -1, dest: n.dest };
      return { sc: threats(t, opp) * 1000 + n.d, dest: n.dest };
    });
  },
  defender: function (s, rng) {
    var me = s.turn, opp = 1 - me;
    return choose(s, rng, function (t) {
      var n = nearest(t, me, 8), can = n.d < 0;
      if (can && t.next[me] === O.GOAL - 1) return { sc: 0, dest: n.dest };
      return { sc: 1e6 + threats(t, opp) * 1000 + (can ? 0 : 100) + Math.max(n.d, 0), dest: n.dest };
    });
  }
};
/* 押した直後の盤で、相手の駒から相手の次の宝へ道がつながっているか（見える範囲の邪魔） */
function oppTurnView(t) { var u = O.clone(t); u.phase = 'move'; u.turns = -1; return u; }

function run(name, turnFn, rng) {
  var hist = {}, cap = 0, draw = 0, firstWin = 0, secondWin = 0, total = 0, lens = [], minOps = 99;
  for (var g = 0; g < GAMES; g++) {
    var s = O.newGame({ rng: rng, first: g % 2 });
    check(O.isSymmetric(s), name + ' 局' + g + ': 盤が180度対称でない');
    check(!O.reachable(s, 0)[s.tre[0][0]] && !O.reachable(s, 1)[s.tre[1][0]], name + ' 局' + g + ': はじめから最初の宝につながっている');
    while (!s.over) {
      if (!moveOnly(s)) {
        var n = O.legalOps(s).length;
        if (n < minOps) minOps = n;
        check(n >= 7, name + ' 局' + g + ': 押し込みが' + n + '通り');
      }
      s = turnFn(s, rng);
      check(!!s, name + ' 局' + g + ': 打てない手');
      if (!s) break;
    }
    if (!s) continue;
    total++;
    lens.push(s.turns);
    var bucket = s.turns >= O.MAX_TURNS ? O.MAX_TURNS : Math.floor(s.turns / 10) * 10;
    hist[bucket] = (hist[bucket] || 0) + 1;
    var reached = s.next[0] < O.GOAL && s.next[1] < O.GOAL;
    if (reached) cap++;
    if (s.winner < 0) draw++;
    else if (s.winner === s.first) firstWin++;
    else secondWin++;
  }
  lens.sort(function (a, b) { return a - b; });
  function q(p) { return lens[Math.min(lens.length - 1, Math.floor(p * lens.length))]; }
  var dec = firstWin + secondWin;
  console.log('== ' + name + '（' + total + '局' + (RULE ? '・案 ' + RULE : '') + '）');
  console.log('  手数（二人の合計）: 中央値 ' + q(0.5) + ' / 四分位 ' + q(0.25) + '〜' + q(0.75) + ' / 最小 ' + lens[0] + ' 最大 ' + lens[lens.length - 1]);
  console.log('  分布(10手ごと): ' + Object.keys(hist).sort(function (a, b) { return a - b; }).map(function (k) {
    return (+k === O.MAX_TURNS ? O.MAX_TURNS + '(上限)' : k + '-' + (+k + 9)) + ':' + hist[k]; }).join('  '));
  console.log('  上限到達 ' + (100 * cap / total).toFixed(1) + '%（うち引き分け ' + (100 * draw / total).toFixed(1) + '%）');
  console.log('  先手の勝ち ' + firstWin + ' / 後手の勝ち ' + secondWin + ' → 決着した局での先手の勝率 ' + (100 * firstWin / dec).toFixed(1) + '%');
  console.log('  押し込みの選択肢の最小 ' + minOps);
}

POLS.forEach(function (p, i) { run(p + ' 同士', POLICY[p], mulberry32(SEED + i)); });
console.log(problems.length ? '問題 ' + problems.length + ' 件: ' + problems.slice(0, 5).join(' / ') : '盤の対称・押し込みの有無・はじめの宝の不通: すべて OK');
