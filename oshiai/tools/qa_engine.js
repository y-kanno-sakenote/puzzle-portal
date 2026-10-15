// おしあい 独立規則エンジン（docs/spec.md v0.2 だけから書いた。index.html のロジック・tools/selfplay.js は読んでいない）
// v0.2：宝は1人2つ（自分の色の宝 tre[p][0] → 真ん中12の共通の宝）。共通を先に拾った方の勝ち。打ち切りは合わせて40手
(function(root){
  const N=5, GOAL=2, OWN=1, COMMON=12, MAX_TURNS=40;
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
    turn:s.turn,phase:s.phase,ban:s.ban,turns:s.turns,first:s.first,over:s.over,winner:s.winner});
  // 次に狙うマス：自分の宝の位置（-1=手持ち）→ 共通12 → -2（拾い終えた）
  function target(s,p){return s.next[p]===0?s.tre[p][0]:s.next[p]===1?COMMON:-2;}
  function legalOps(s){if(s.over||s.phase!=='push')return[];const o=[];for(let op=0;op<8;op++)if(op!==s.ban)o.push(op);return o;}
  function push(s,op,mask){
    if(s.over||s.phase!=='push'||op===s.ban||!(op>=0&&op<8)||!variants(s.hand).includes(mask))return null;
    const t=clone(s),L=LINES[op];
    for(let k=4;k>0;k--)t.cells[L[k]]=s.cells[L[k-1]];
    t.cells[L[0]]=mask;t.hand=s.cells[L[4]];
    const mv=x=>{const k=L.indexOf(x);if(x===-1)return L[0];if(x<0||k<0)return x;return k===4?-1:L[k+1];};
    t.tre=s.tre.map(a=>a.map(mv));   // 共通の宝は12（動かないマス）なので tre に持たない
    t.piece=s.piece.map(x=>{const k=L.indexOf(x);if(k<0)return x;return k===4?L[0]:L[k+1];});
    t.ban=op^1;t.phase='move';return t;}
  function reachable(s,p){return reach(s.cells,s.piece[p]);}
  function moveTo(s,cell){
    if(s.over||s.phase!=='move')return null;const p=s.turn;
    if(!(cell>=0&&cell<25)||!reachable(s,p)[cell])return null;
    const t=clone(s);t.piece[p]=cell;
    if(t.next[p]===0&&t.tre[p][0]===cell){t.tre[p][0]=-2;t.next[p]=1;}
    else if(t.next[p]===1&&cell===COMMON){t.next[p]=2;}
    t.turns++;
    if(t.next[p]>=GOAL){t.over=true;t.winner=p;}
    else if(t.turns>=MAX_TURNS){t.over=true;t.winner=t.next[0]>t.next[1]?0:t.next[1]>t.next[0]?1:-1;}
    if(!t.over){t.turn^=1;t.phase='push';}return t;} // 終局時は手番・段を据え置く（v0.1 で合わせた表記の約束。規則ではない）
  root.QA={N,GOAL,OWN,COMMON,MAX_TURNS,rot,rot180,variants,isFixed,LINES,reach,dist,nbrs,clone,target,legalOps,push,reachable,moveTo};
})(typeof window!=='undefined'?window:globalThis);
