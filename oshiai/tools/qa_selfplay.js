// 自前エンジンで自動対局（盤は Oshiai.newGame が配った boards30k.json）
require('./qa_engine.js'); const Q=globalThis.QA; const fs=require('fs');
const boards=JSON.parse(fs.readFileSync(__dirname+'/boards30k.json','utf8'));
let seed=12345; const R=()=>{seed^=seed<<13;seed>>>=0;seed^=seed>>>17;seed^=seed<<5;seed>>>=0;return seed/4294967296;};
const pick=a=>a[Math.floor(R()*a.length)];
const man=(a,b)=>Math.abs((a/5|0)-(b/5|0))+Math.abs(a%5-b%5);
function pushes(s){const out=[];for(const op of Q.legalOps(s))for(const m of Q.variants(s.hand)){const t=Q.push(s,op,m);if(t)out.push(t);}return out;}
function cells(t){const r=Q.reachable(t,t.turn);return [...Array(25).keys()].filter(i=>r[i]);}
function canPick(t,p){const x=t.tre[p][t.next[p]];return x>=0&&Q.reach(t.cells,t.piece[p])[x];}
// 1手の評価：拾えるなら最優先、だめなら次の宝に一番近いマス（宝が手持ちなら距離は据え置き4）
function bestMoveFor(t){const p=t.turn,x=t.tre[p][t.next[p]];let best=1e9,bc=[];
  for(const c of cells(t)){const d=x>=0?(c===x&&Q.reachable(t,p)[x]?-100:man(c,x)):4;if(d<best){best=d;bc=[c];}else if(d===best)bc.push(c);}return [best,pick(bc)];}
const POL={
 random(s){const t=pick(pushes(s));return [t,pick(cells(t))];},
 greedy(s){let best=1e9,b=[];for(const t of pushes(s)){const [d,c]=bestMoveFor(t);if(d<best){best=d;b=[[t,c]];}else if(d===best)b.push([t,c]);}return pick(b);},
 // 貪欲＋邪魔：拾えるなら拾う。拾えないなら「相手の次の一押しで相手が拾える押し方の数」が最少の押し込みを優先し、その中で貪欲
 blocker(s){const me=s.turn,op=me^1;const ps=pushes(s);let pickers=[];
   for(const t of ps){if(canPick(t,me))pickers.push([t,t.tre[me][t.next[me]]]);}
   if(pickers.length)return pick(pickers);
   let best=[1e9,1e9],b=[];
   for(const t of ps){const u=Q.clone(t);u.phase='push';u.turn=op; // 自分の駒の位置は相手の届く範囲に効かない
     let threat=0;for(const v of pushes(u))if(canPick(v,op))threat++;
     const [d,c]=bestMoveFor(t);const k=[threat,d];
     if(k[0]<best[0]||(k[0]===best[0]&&k[1]<best[1])){best=k;b=[[t,c]];}else if(k[0]===best[0]&&k[1]===best[1])b.push([t,c]);}
   return pick(b);},
 // 見える範囲だけ邪魔：拾えるなら拾う。だめなら「押した直後の盤で相手の駒から相手の次の宝へ道がつながらない」押し込みを優先し、その中で貪欲
 blocker1(s){const me=s.turn,op=me^1;const ps=pushes(s);const pk=ps.filter(t=>canPick(t,me));if(pk.length){const t=pick(pk);return [t,t.tre[me][t.next[me]]];}
   let best=[9,1e9],b=[];for(const t of ps){const k=[canPick(t,op)?1:0,bestMoveFor(t)[0]];if(k[0]<best[0]||(k[0]===best[0]&&k[1]<best[1])){best=k;b=[t];}else if(k[0]===best[0]&&k[1]===best[1])b.push(t);}
   const t=pick(b);return [t,bestMoveFor(t)[1]];},
};
function play(board,first,P){let s=Q.clone(board);s.turn=first;s.first=first;
  while(!s.over){const [t,c]=P[s.turn](s);s=Q.moveTo(t,c);if(!s)throw new Error('illegal');}return s;}
function q(a,p){const b=a.slice().sort((x,y)=>x-y);return b[Math.floor(p*(b.length-1))];}
const [a,b,n]=[process.argv[2],process.argv[3],+process.argv[4]];
const res={games:0,turns:[],cut:0,draw:0,firstWin:0,decided:0,aWin:0,bWin:0};
for(let g=0;g<n;g++){const board=boards[g%boards.length];const first=g%2;
  // a は 偶数局で青、奇数局で赤（席と先手を両方入れ替える）
  const seatA=(g>>1)%2; const P=[];P[seatA]=POL[a];P[seatA^1]=POL[b];
  const s=play(board,first,P);res.games++;res.turns.push(s.turns);
  const full=Math.max(...s.next)>=3; if(!full)res.cut++; if(s.winner===-1)res.draw++; else{res.decided++;if(s.winner===first)res.firstWin++;if(s.winner===seatA)res.aWin++;else res.bWin++;}}
const T=res.turns;
console.log(JSON.stringify({match:a+' vs '+b,games:res.games,median:q(T,.5),q1:q(T,.25),q3:q(T,.75),min:Math.min(...T),max:Math.max(...T),cut60:(res.cut/res.games*100).toFixed(1)+'%',draw:(res.draw/res.games*100).toFixed(1)+'%',firstWinOfDecided:(res.firstWin/res.decided*100).toFixed(1)+'%',decided:res.decided,aWinOfDecided:(res.aWin/res.decided*100).toFixed(1)+'%'}));
