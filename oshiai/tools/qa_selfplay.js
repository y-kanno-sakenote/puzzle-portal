// 自前エンジンで自動対局 v0.4（本戦＋延長戦）：node tools/qa_selfplay.js <方針A> <方針B> <局数> <盤.json> [seed]
// 盤.json は配列（本戦の盤だけ・延長戦は指さない）か {main:[盤…], ext:[{cells,hand}…]}（延長戦込み）。どちらも window.Oshiai が配った盤（newGame / extend）を書き出したもの
// 1局 = 本戦（先手は局ごとに交代）→ 同点の打ち切りなら延長戦（先手は本戦の後手）→ まだ同点ならもう1回（先手交代）→ 引き分け。延長戦の盤は ext プールから局ごと・回ごとに別の盤
// 先手の1手目は、方針が「動かせるつもりで」選んだ押し込みだけを使い、動かす指しは捨てる（v0.2 の方針定義をそのまま流用）
// 盤は window.Oshiai.newGame が配ったものを JSON で渡す（配りの検査は別。ここでは規則は自前エンジンだけで進める）
require('./qa_engine.js'); const Q=globalThis.QA; const fs=require('fs');
const [a,b,n,bp,sd]=[process.argv[2],process.argv[3],+process.argv[4],process.argv[5],+process.argv[6]||12345];
const BJ=JSON.parse(fs.readFileSync(bp,'utf8')); const boards=Array.isArray(BJ)?BJ:BJ.main, extBoards=Array.isArray(BJ)?null:BJ.ext;
let seed=sd; const R=()=>{seed^=seed<<13;seed>>>=0;seed^=seed>>>17;seed^=seed<<5;seed>>>=0;return seed/4294967296;};
const pick=a=>a[Math.floor(R()*a.length)];
const man=(a,b)=>Math.abs((a/5|0)-(b/5|0))+Math.abs(a%5-b%5);
function pushes(s){const out=[];for(const op of Q.legalOps(s))for(const m of Q.variants(s.hand)){const t=Q.pushRaw(s,op,m);if(t){t._op=op;t._m=m;out.push(t);}}return out;}
function cells(t){const r=Q.reachable(t,t.turn);return [...Array(25).keys()].filter(i=>r[i]);}
function canPick(t,p){const x=Q.target(t,p);return x>=0&&Q.reach(t.cells,t.piece[p])[x];}
// 1手の評価：拾えるなら最優先、だめなら次に狙うマスに一番近いマス（自分の宝が手持ちなら距離は据え置き4）
function bestMoveFor(t){const p=t.turn,x=Q.target(t,p),r=Q.reachable(t,p);let best=1e9,bc=[];
  for(const c of cells(t)){const d=x>=0?(c===x&&r[x]?-100:man(c,x)):4;if(d<best){best=d;bc=[c];}else if(d===best)bc.push(c);}return [best,pick(bc)];}
const POL={
 random(s){const t=pick(pushes(s));return [t,pick(cells(t))];},
 // 貪欲：拾えるなら拾う。だめなら次に狙うマスに一番近づく
 greedy(s){let best=1e9,b=[];for(const t of pushes(s)){const [d,c]=bestMoveFor(t);if(d<best){best=d;b=[[t,c]];}else if(d===best)b.push([t,c]);}return pick(b);},
 // 見える範囲だけ邪魔：拾えるなら拾う。だめなら「押した直後の盤で相手が次に狙うマスへ道がつながらない」押し込みを優先し、その中で貪欲
 blocker1(s){const me=s.turn,op=me^1;const ps=pushes(s);const pk=ps.filter(t=>canPick(t,me));if(pk.length){const t=pick(pk);return [t,Q.target(t,me)];}
   let best=[9,1e9],b=[];for(const t of ps){const k=[canPick(t,op)?1:0,bestMoveFor(t)[0]];if(k[0]<best[0]||(k[0]===best[0]&&k[1]<best[1])){best=k;b=[t];}else if(k[0]===best[0]&&k[1]===best[1])b.push(t);}
   const t=pick(b);return [t,bestMoveFor(t)[1]];},
 // 守り手：拾えるなら拾う。だめなら「相手の次の一押しで相手が拾える押し方（口×向き）の数」が最少の押し込み、その中で貪欲
 blocker(s){const me=s.turn,op=me^1;const ps=pushes(s);const pk=ps.filter(t=>canPick(t,me));if(pk.length){const t=pick(pk);return [t,Q.target(t,me)];}
   let best=[1e9,1e9],b=[];
   for(const t of ps){const u=Q.clone(t);u.phase='push';u.turn=op; // 自分の駒の置き場所は相手の届く範囲に効かない
     let threat=0;for(const v of pushes(u))if(canPick(v,op))threat++;
     const [d,c]=bestMoveFor(t);const k=[threat,d];
     if(k[0]<best[0]||(k[0]===best[0]&&k[1]<best[1])){best=k;b=[[t,c]];}else if(k[0]===best[0]&&k[1]===best[1])b.push([t,c]);}
   return pick(b);},
};
// QA_FIRST=still：先手の1手目を「動かせない前提」で選ぶ（駒は現在地のまま。次に狙うマスまでの距離＝駒の今の位置から。手持ちが狙いなら4）。未指定は「動かせるつもり」
function stillKey(t,me,name){const x=Q.target(t,me),d=x>=0?man(t.piece[me],x):4;
  if(name==='greedy')return [0,d];
  if(name==='blocker1')return [canPick(t,me^1)?1:0,d];
  if(name==='blocker'){const u=Q.clone(t);u.phase='push';u.turn=me^1;let th=0;for(const v of pushes(u))if(canPick(v,me^1))th++;return [th,d];}
  return [0,0];}
function firstPick(s,name){const ps=pushes(s);if(name==='random')return pick(ps);let best=null,b=[];
  for(const t of ps){const k=stillKey(t,s.turn,name);if(!best||k[0]<best[0]||(k[0]===best[0]&&k[1]<best[1])){best=k;b=[t];}else if(k[0]===best[0]&&k[1]===best[1])b.push(t);}
  return pick(b);}
function run(s,P){while(!s.over){let t,c;if(process.env.QA_FIRST==='still'&&Q.pushOnly(s)){t=firstPick(s,P[s.turn].nm);c=0;}else [t,c]=P[s.turn](s);s=Q.pushOnly(s)?Q.push(s,t._op,t._m):Q.moveTo(t,c);if(!s)throw new Error('illegal');}return s;}
// 1局：段ごとの結果 [{ext, first, winner, turns, picked}] と 最終の勝者(-1=引き分け)
function play(board,first,P,g){let s=Q.clone(board);s.turn=first;s.first=first;const stages=[];
  for(;;){s=run(s,P);stages.push({ext:s.ext,first:s.first,winner:s.winner,turns:s.turns,picked:Math.max(...s.next)>=2});
    if(!(s.extend&&extBoards))break;
    const eb=extBoards[(g*2+s.ext)%extBoards.length];s=Q.startExt(s,eb);}
  return {stages,winner:s.winner};}
const A=a, pc=x=>(x*100).toFixed(1)+'%', R_={games:0,mainTie:0,mainTurns:[],mainCut:0,
  ext:[{n:0,dec:0,firstWin:0,turns:[],decTurns:[]},{n:0,dec:0,firstWin:0,turns:[],decTurns:[]}],draw:0,decided:0,firstWin:0,aWin:0};
for(let g=0;g<n;g++){const board=boards[g%boards.length];const first=g%2;
  const seatA=(g>>1)%2; const P=[];P[seatA]=POL[a];P[seatA^1]=POL[b];P[seatA].nm=a;P[seatA^1].nm=b;
  const r=play(board,first,P,g);R_.games++;
  const m=r.stages[0];R_.mainTurns.push(m.turns);if(!m.picked)R_.mainCut++;
  if(m.winner===-1)R_.mainTie++;   // 本戦だけなら引き分け（＝延長戦に入る）
  for(const st of r.stages.slice(1)){const e=R_.ext[st.ext-1];e.n++;e.turns.push(st.turns);if(st.winner!==-1){e.dec++;e.decTurns.push(st.turns);if(st.winner===st.first)e.firstWin++;}}
  if(r.winner===-1)R_.draw++; else{R_.decided++;if(r.winner===first)R_.firstWin++;if(r.winner===seatA)R_.aWin++;}}
function q(a,p){if(!a.length)return null;const b=a.slice().sort((x,y)=>x-y);return b[Math.floor(p*(b.length-1))];}
const ex=R_.ext, ea=ex[0].turns.concat(ex[1].turns), ed=ex[0].decTurns.concat(ex[1].decTurns);
console.log(JSON.stringify({match:a+' vs '+b,first:process.env.QA_FIRST||'can-move',games:R_.games,extBoards:!!extBoards,
  mainTurnsMedian:q(R_.mainTurns,.5),mainCut40:pc(R_.mainCut/R_.games),
  drawMainOnly:pc(R_.mainTie/R_.games),drawWithExt:pc(R_.draw/R_.games),
  ext1:{started:ex[0].n,decidedRate:ex[0].n?pc(ex[0].dec/ex[0].n):null,firstWinOfDecided:ex[0].dec?pc(ex[0].firstWin/ex[0].dec):null,turnsMedianAll:q(ex[0].turns,.5),turnsMedianDecided:q(ex[0].decTurns,.5)},
  ext2:{started:ex[1].n,decidedRate:ex[1].n?pc(ex[1].dec/ex[1].n):null,firstWinOfDecided:ex[1].dec?pc(ex[1].firstWin/ex[1].dec):null},
  extPooled:{started:ex[0].n+ex[1].n,decidedRate:(ex[0].n+ex[1].n)?pc((ex[0].dec+ex[1].dec)/(ex[0].n+ex[1].n)):null,firstWinOfDecided:(ex[0].dec+ex[1].dec)?pc((ex[0].firstWin+ex[1].firstWin)/(ex[0].dec+ex[1].dec)):null,turnsMedianAll:q(ea,.5),turnsMedianDecided:q(ed,.5)},
  mainFirstWinOfDecided_wholeGame:pc(R_.firstWin/R_.decided),decidedGames:R_.decided,aWinOfDecided:pc(R_.aWin/R_.decided)}));
