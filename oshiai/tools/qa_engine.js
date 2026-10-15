// おしあい 独立規則エンジン（docs/spec.md だけから書いた。index.html のロジック・tools/selfplay.js は読んでいない）
// v0.4：延長戦。本戦(ext=0)が40手の打ち切りで拾った数が同じ → 延長戦(ext=1,2)。延長戦は自分の宝なし・真ん中の共通の宝だけ・20手・1手目は押すだけ・先手は前の段の相手
//   同点の打ち切りは over・winner=-1 のまま extend=true（ext<2 のとき）。ext=2 の同点は extend=false の引き分け。盤の配りは乱数なので自前では作らず、checkExt が「配られた盤が仕様どおりか」を独立に検査する
// v0.3：先手の最初の手番（turns=0 の押す段）は押すだけ。押したら駒はその場（押し込みで列ごと動くのみ）、拾わず、turns+1 で手番が相手の押す段へ移る
// v0.2：宝は1人2つ（自分の色の宝 tre[p][0] → 真ん中12の共通の宝）。共通を先に拾った方の勝ち。打ち切りは合わせて40手
(function(root){
  const N=5, GOAL=2, OWN=1, COMMON=12, MAX_TURNS=40, EXT_TURNS=20, EXT_MAX=2;
  const limit=s=>s.ext>0?EXT_TURNS:MAX_TURNS;
  const DIRS=[[1,-1,0,4],[2,0,1,8],[4,1,0,1],[8,0,-1,2]]; // [自分の腕, dr, dc, 相手の腕]  N:上 E:右 S:下 W:左
  const rot=m=>((m<<1)|(m>>3))&15;               // 時計回り90度
  const rot180=m=>rot(rot(m));
  function variants(m){const v=[];let x=m;for(let i=0;i<4;i++){if(!v.includes(x))v.push(x);x=rot(x);}return v;}
  const isFixed=i=>(Math.floor(i/N)%2===0)&&(i%N%2===0);
  // 押し込み口：0=行1左 1=行1右 2=行3左 3=行3右 4=列1上 5=列1下 6=列3上 7=列3下。並びは入口→出口
  const LINES=[];
  for(const r of [1,3]){const L=[0,1,2,3,4].map(c=>r*N+c);LINES.push(L,L.slice().reverse());}
  for(const c of [1,3]){const L=[0,1,2,3,4].map(r=>r*N+c);LINES.push(L,L.slice().reverse());}
  function nbrs(cells,i){const r=Math.floor(i/N),c=i%N,out=[];
    for(const [b,dr,dc,ob] of DIRS){const rr=r+dr,cc=c+dc;if(rr<0||rr>=N||cc<0||cc>=N)continue;const j=rr*N+cc;
      if((cells[i]&b)&&(cells[j]&ob))out.push(j);}return out;}
  function reach(cells,from){const seen=new Array(N*N).fill(false);seen[from]=true;const q=[from];
    while(q.length){const i=q.shift();for(const j of nbrs(cells,i))if(!seen[j]){seen[j]=true;q.push(j);}}return seen;}
  function dist(cells,from){const d=new Array(N*N).fill(-1);d[from]=0;const q=[from];
    while(q.length){const i=q.shift();for(const j of nbrs(cells,i))if(d[j]<0){d[j]=d[i]+1;q.push(j);}}return d;}
  const clone=s=>({cells:s.cells.slice(),hand:s.hand,piece:s.piece.slice(),tre:s.tre.map(a=>a.slice()),next:s.next.slice(),
    turn:s.turn,phase:s.phase,ban:s.ban,turns:s.turns,first:s.first,over:s.over,winner:s.winner,ext:s.ext||0,extend:!!s.extend});
  // 次に狙うマス：自分の宝の位置（-1=手持ち）→ 共通12 → -2（拾い終えた）
  function target(s,p){return s.next[p]===0?s.tre[p][0]:s.next[p]===1?COMMON:-2;}
  function legalOps(s){if(s.over||s.phase!=='push')return[];const o=[];for(let op=0;op<8;op++)if(op!==s.ban)o.push(op);return o;}
  // pushRaw：押し込みの機械的な部分（列ずらし・宝/駒の移動・ban）。押した後は move 段。方針が「動かせたら」を仮に評価するのにも使う
  function pushRaw(s,op,mask){
    if(s.over||s.phase!=='push'||op===s.ban||!(op>=0&&op<8)||!variants(s.hand).includes(mask))return null;
    const t=clone(s),L=LINES[op];
    for(let k=4;k>0;k--)t.cells[L[k]]=s.cells[L[k-1]];
    t.cells[L[0]]=mask;t.hand=s.cells[L[4]];
    const mv=x=>{const k=L.indexOf(x);if(x===-1)return L[0];if(x<0||k<0)return x;return k===4?-1:L[k+1];};
    t.tre=s.tre.map(a=>a.map(mv));   // 共通の宝は12（動かないマス）なので tre に持たない
    t.piece=s.piece.map(x=>{const k=L.indexOf(x);if(k<0)return x;return k===4?L[0]:L[k+1];});
    t.ban=op^1;t.phase='move';return t;}
  // v0.3：この手番は押すだけか（一局の最初の手番＝押す段で turns=0）
  const pushOnly=s=>!s.over&&s.phase==='push'&&s.turns===0;
  function push(s,op,mask){
    const t=pushRaw(s,op,mask);if(!t||!pushOnly(s))return t;
    t.turns++;t.turn^=1;t.phase='push';return t;}   // 動かす段なし・拾わない・手番は相手の押す段へ
  function reachable(s,p){return reach(s.cells,s.piece[p]);}
  function moveTo(s,cell){
    if(s.over||s.phase!=='move')return null;const p=s.turn;
    if(!(cell>=0&&cell<25)||!reachable(s,p)[cell])return null;
    const t=clone(s);t.piece[p]=cell;
    if(t.next[p]===0&&t.tre[p][0]===cell){t.tre[p][0]=-2;t.next[p]=1;}
    else if(t.next[p]===1&&cell===COMMON){t.next[p]=2;}
    t.turns++;
    if(t.next[p]>=GOAL){t.over=true;t.winner=p;}
    else if(t.turns>=limit(t)){t.over=true;t.winner=t.next[0]>t.next[1]?0:t.next[1]>t.next[0]?1:-1;
      if(t.winner===-1&&t.ext<EXT_MAX)t.extend=true;}   // 同点の打ち切り→延長戦（2回まで）。ext=2 の同点は extend=false の引き分け
    if(!t.over){t.turn^=1;t.phase='push';}return t;} // 終局時は手番・段を据え置く（v0.1 で合わせた表記の約束。規則ではない）
  const CORNER={0:6,4:12,20:3,24:9};  // 四隅は内向きのかど（S+E / S+W / N+E / N+W）
  const TILE_OK=new Set([5,10,3,6,9,12,7,11,13,14]);  // 直線・かど・三叉（十字15は真ん中だけ）
  // 配られた延長戦の盤 e が、直前の（同点で終わった）状態 prev から見て仕様どおりか。違反の文字列の配列を返す（空=OK）
  function checkExt(prev,e){const v=[];
    if(!e){v.push('null');return v;}
    if(!(prev.over&&prev.winner===-1&&prev.extend&&(prev.ext||0)<EXT_MAX))v.push('prev-not-extendable');
    for(let i=0;i<25;i++)if(e.cells[i]!==rot180(e.cells[24-i]))v.push('asym@'+i);
    if(e.cells[12]!==15)v.push('center-not-cross:'+e.cells[12]);
    for(const k in CORNER)if(e.cells[k]!==CORNER[k])v.push('corner@'+k+':'+e.cells[k]);
    for(let i=0;i<25;i++)if(i!==12&&!(i in CORNER)&&!TILE_OK.has(e.cells[i]))v.push('badtile@'+i+':'+e.cells[i]);
    if(!TILE_OK.has(e.hand))v.push('badhand:'+e.hand);
    if(JSON.stringify(e.piece)!=='[20,4]')v.push('piece:'+JSON.stringify(e.piece));
    if(JSON.stringify(e.tre)!=='[[-2],[-2]]')v.push('own-treasure-left:'+JSON.stringify(e.tre));
    if(JSON.stringify(e.next)!=='[1,1]')v.push('next:'+JSON.stringify(e.next));
    if(e.ext!==(prev.ext||0)+1)v.push('ext:'+e.ext);
    if(e.first!==(prev.first^1))v.push('first:'+e.first+' prev='+prev.first);
    if(e.turn!==e.first)v.push('turn!=first');
    if(e.turns!==0||e.phase!=='push'||e.ban!==-1||e.over||e.winner!==-1||e.extend)v.push('start-fields:'+JSON.stringify([e.turns,e.phase,e.ban,e.over,e.winner,e.extend]));
    if(!pushOnly(e))v.push('first-not-pushOnly');
    if(limit(e)!==EXT_TURNS)v.push('limit:'+limit(e));
    const r0=reach(e.cells,20),r1=reach(e.cells,4);
    if(r0[12]||r1[12])v.push('center-connected-at-start');
    return v;}
  // 自前の延長戦の開始状態（盤の cells/hand だけ借りる。selfplay 用）
  function startExt(prev,b){return {cells:b.cells.slice(),hand:b.hand,piece:[20,4],tre:[[-2],[-2]],next:[1,1],turn:prev.first^1,phase:'push',ban:-1,turns:0,first:prev.first^1,over:false,winner:-1,ext:(prev.ext||0)+1,extend:false};}
  root.QA={N,GOAL,OWN,COMMON,MAX_TURNS,EXT_TURNS,EXT_MAX,limit,checkExt,startExt,rot,rot180,variants,isFixed,LINES,reach,dist,nbrs,clone,target,legalOps,pushRaw,pushOnly,push,reachable,moveTo};
})(typeof window!=='undefined'?window:globalThis);
