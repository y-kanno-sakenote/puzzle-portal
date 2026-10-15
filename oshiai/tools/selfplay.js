#!/usr/bin/env node
/* おしあい 自動対局（index.html の window.Oshiai をそのまま読み込んで指す）
   使い方: node oshiai/tools/selfplay.js [局数=2000] [種=20261015]
   （OSHIAI_HTML=ファイル で別の版の index.html を読める。前の版との比べ用。旧版には target が無いので下で補う）
   (a) ランダム同士 (b) 「次の宝に一番近づく」貪欲同士 (c) 守り手同士（相手の次の一押しで拾える手を最小にする）を、先手を交互にして指し、
   決着までの手数の分布・上限到達と引き分けの率・先手の勝率を出す。
   あわせて、配った盤が180度対称か・押し込みが毎回7通り以上あるかを確かめる */
'use strict';
var fs = require('fs'), path = require('path'), vm = require('vm');

var html = fs.readFileSync(process.env.OSHIAI_HTML || path.join(__dirname, '..', 'index.html'), 'utf8');
var src = html.match(/<script>([\s\S]*?)<\/script>/)[1];   /* 1つ目の script＝純粋ロジック */
var ctx = { globalThis: {} };
vm.createContext(ctx);
vm.runInContext(src, ctx);
var O = ctx.globalThis.Oshiai;

var GAMES = +(process.argv[2] || 2000), SEED = +(process.argv[3] || 20261015);

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

/* ランダム：押し込み口・向き・行き先を一様に */
function randomTurn(s, rng) {
  var ops = O.legalOps(s);
  var t = O.push(s, pick(ops, rng), pick(O.variants(s.hand), rng));
  var r = O.reachable(t, t.turn), cells = [];
  for (var i = 0; i < 25; i++) if (r[i]) cells.push(i);
  return O.moveTo(t, pick(cells, rng));
}

/* 貪欲：押し込み口×向きを全部試し、次の宝に止まれるならそれ。無ければ「届くマスのうち次の宝に一番近いマス」の距離が最小の手。
   次の宝が手持ちに乗った（押し出した）なら距離8とみなす。同点はランダム */
function greedyTurn(s, rng) {
  var me = s.turn, best = [], bestScore = 1e9, ops = O.legalOps(s), vs = O.variants(s.hand);
  for (var a = 0; a < ops.length; a++) for (var b = 0; b < vs.length; b++) {
    var t = O.push(s, ops[a], vs[b]), r = O.reachable(t, me), goal = target(t, me);
    var sc, dest = [];
    if (goal >= 0 && r[goal]) { sc = -1; dest = [goal]; }
    else if (goal < 0) { sc = 8; for (var i = 0; i < 25; i++) if (r[i]) dest.push(i); }
    else {
      sc = 99;
      for (i = 0; i < 25; i++) if (r[i]) {
        var d = dist(i, goal);
        if (d < sc) { sc = d; dest = [i]; } else if (d === sc) dest.push(i);
      }
    }
    if (sc < bestScore) { bestScore = sc; best = []; }
    if (sc === bestScore) best.push({ t: t, dest: dest });
  }
  var c = pick(best, rng);
  return O.moveTo(c.t, pick(c.dest, rng));
}

/* 守り手：押し込み口×向きを全部試し、(1) 勝てる（最後の宝に止まれる）手 (2) 相手の次の一押し（口×向き）のうち
   相手が次の宝に止まれるものの数が最小 (3) 自分が宝を拾える (4) 次の宝に一番近づく、の順で選ぶ。同点はランダム。
   相手の届く範囲は自分の駒の位置に左右されないので、押し込みだけで数えられる */
function threats(t, opp) {
  var u = O.clone(t), cnt = 0;
  u.phase = 'push'; u.turn = opp;
  var ops = O.legalOps(u), vs = O.variants(u.hand);
  for (var a = 0; a < ops.length; a++) for (var b = 0; b < vs.length; b++) {
    var v = O.push(u, ops[a], vs[b]), g = target(v, opp);
    if (g >= 0 && O.reachable(v, opp)[g]) cnt++;
  }
  return cnt;
}
function defenderTurn(s, rng) {
  var me = s.turn, opp = 1 - me, best = [], bestScore = 1e18, ops = O.legalOps(s), vs = O.variants(s.hand);
  for (var a = 0; a < ops.length; a++) for (var b = 0; b < vs.length; b++) {
    var t = O.push(s, ops[a], vs[b]), r = O.reachable(t, me), goal = target(t, me), dest = [], i;
    var can = goal >= 0 && r[goal], win = can && t.next[me] === O.GOAL - 1, d = 99;
    if (can) { d = 0; dest = [goal]; }
    else if (goal < 0) { d = 8; for (i = 0; i < 25; i++) if (r[i]) dest.push(i); }
    else for (i = 0; i < 25; i++) if (r[i]) {
      var e = dist(i, goal);
      if (e < d) { d = e; dest = [i]; } else if (e === d) dest.push(i);
    }
    var sc = win ? 0 : 1e6 + threats(t, opp) * 1000 + (can ? 0 : 100) + d;
    if (sc < bestScore) { bestScore = sc; best = []; }
    if (sc === bestScore) best.push({ t: t, dest: dest });
  }
  var c = pick(best, rng);
  return O.moveTo(c.t, pick(c.dest, rng));
}

function run(name, turnFn, rng) {
  var hist = {}, cap = 0, draw = 0, firstWin = 0, secondWin = 0, total = 0, lens = [], minOps = 99;
  for (var g = 0; g < GAMES; g++) {
    var s = O.newGame({ rng: rng, first: g % 2 });
    check(O.isSymmetric(s), name + ' 局' + g + ': 盤が180度対称でない');
    check(!O.reachable(s, 0)[s.tre[0][0]] && !O.reachable(s, 1)[s.tre[1][0]], name + ' 局' + g + ': はじめから最初の宝につながっている');
    while (!s.over) {
      var n = O.legalOps(s).length;
      if (n < minOps) minOps = n;
      check(n >= 7, name + ' 局' + g + ': 押し込みが' + n + '通り');
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
  console.log('== ' + name + '（' + total + '局）');
  console.log('  手数（二人の合計）: 中央値 ' + q(0.5) + ' / 四分位 ' + q(0.25) + '〜' + q(0.75) + ' / 最小 ' + lens[0] + ' 最大 ' + lens[lens.length - 1]);
  console.log('  分布(10手ごと): ' + Object.keys(hist).sort(function (a, b) { return a - b; }).map(function (k) {
    return (+k === O.MAX_TURNS ? O.MAX_TURNS + '(上限)' : k + '-' + (+k + 9)) + ':' + hist[k]; }).join('  '));
  console.log('  上限到達 ' + (100 * cap / total).toFixed(1) + '%（うち引き分け ' + (100 * draw / total).toFixed(1) + '%）');
  console.log('  先手の勝ち ' + firstWin + ' / 後手の勝ち ' + secondWin + ' → 決着した局での先手の勝率 ' + (100 * firstWin / dec).toFixed(1) + '%');
  console.log('  押し込みの選択肢の最小 ' + minOps);
}

run('(a) ランダム同士', randomTurn, mulberry32(SEED));
run('(b) 貪欲同士', greedyTurn, mulberry32(SEED + 1));
if (!process.env.NO_DEFENDER) run('(c) 守り手同士', defenderTurn, mulberry32(SEED + 2));
console.log(problems.length ? '問題 ' + problems.length + ' 件: ' + problems.slice(0, 5).join(' / ') : '盤の対称・押し込みの有無・はじめの宝の不通: すべて OK');
