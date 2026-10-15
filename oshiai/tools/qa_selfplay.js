// 自前エンジンで自動対局 v0.2：node tools/qa_selfplay.js <方針A> <方針B> <局数> <盤.json> [seed]
// 盤は window.Oshiai.newGame が配ったものを JSON で渡す（配りの検査は別。ここでは規則は自前エンジンだけで進める）
require('./qa_engine.js'); const Q=globalThis.QA; const fs=require('fs');
const [a,b,n,bp,sd]=[process.argv[2],process.argv[3],+process.argv[4],process.argv[5],+process.argv[6]||12345];
const boards=JSON.parse(fs.readFileSync(bp,'utf8'));
let seed=sd; const R=()=>{seed^=seed<<13;seed>>>=0;seed^=seed>>>17;seed^=seed<<5;seed>>>=0;return seed/4294967296;};
const pick=a=>a[Math.floor(R()*a.length)];
const man=(a,b)=>Math.abs((a/5|0)-(b/5|0))+Math.abs(a%5-b%5);
function pushes(s){const out=[];for(const op of Q.legalOps(s))for(const m of Q.variants(s.hand)){const t=Q.push(s,op,m);if(t)out.push(t);}return out;}
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
function play(board,first,P){let s=Q.clone(board);s.turn=first;s.first=first;
  while(!s.over){const [t,c]=P[s.turn](s);s=Q.moveTo(t,c);if(!s)throw new Error('illegal');}return s;}
function q(a,p){const b=a.slice().sort((x,y)=>x-y);return b[Math.floor(p*(b.length-1))];}
const res={games:0,turns:[],cut:0,draw:0,firstWin:0,decided:0,firstWinCommon:0,common:0,aWin:0};
for(let g=0;g<n;g++){const board=boards[g%boards.length];const first=g%2;
  const seatA=(g>>1)%2; const P=[];P[seatA]=POL[a];P[seatA^1]=POL[b];
  const s=play(board,first,P);res.games++;res.turns.push(s.turns);
  const full=Math.max(...s.next)>=2; if(!full)res.cut++; else{res.common++;if(s.winner===first)res.firstWinCommon++;}
  if(s.winner===-1)res.draw++; else{res.decided++;if(s.winner===first)res.firstWin++;if(s.winner===seatA)res.aWin++;}}
const T=res.turns,pc=x=>(x*100).toFixed(1)+'%';
console.log(JSON.stringify({match:a+' vs '+b,games:res.games,median:q(T,.5),q1:q(T,.25),q3:q(T,.75),min:Math.min(...T),max:Math.max(...T),cut40:pc(res.cut/res.games),draw:pc(res.draw/res.games),
  firstWinOfDecided:pc(res.firstWin/res.decided),decided:res.decided,firstWinOfCommonWins:pc(res.firstWinCommon/res.common),aWinOfDecided:pc(res.aWin/res.decided)}));
