// ページ内で実行：Oshiai と QA を並走
window.QAPAR=function(seed0,ngames){
  const O=window.Oshiai,Q=window.QA;
  const mk=seed=>{let s=seed>>>0||1;return()=>{s^=s<<13;s>>>=0;s^=s>>>17;s^=s<<5;s>>>=0;return s/4294967296;};};
  const J=JSON.stringify, KEYS=['cells','hand','piece','tre','next','turn','phase','ban','turns','first','over','winner'];
  const eq=(a,b)=>{if(a===null||b===null)return a===b;for(const k of KEYS)if(J(a[k])!==J(b[k]))return k;return true;};
  const st={games:0,steps:0,pushCalls:0,moveCalls:0,picks:0,wins:0,cut:0,draws:0,minLegal:99,maxLegal:0,mism:{},ex:{},endTurns:[]};
  const bad=(cat,info)=>{st.mism[cat]=(st.mism[cat]||0)+1;if(!st.ex[cat])st.ex[cat]=info;};
  for(let g=0;g<ngames;g++){
    const R=mk(seed0*100003+g*7919+1);
    const first=R()<0.5?0:1;
    let s=O.newGame({rng:mk(seed0*7+g*31+5),first});
    const mode=[0,0.5,0.9][g%3];
    st.games++;
    for(let step=0;step<200&&!s.over;step++){
      st.steps++;
      // 押す段
      const lo=O.legalOps(s),lq=Q.legalOps(s);
      if(J(lo)!==J(lq))bad('legalOps',{s:J(s),O:lo,Q:lq});
      st.minLegal=Math.min(st.minLegal,lq.length);st.maxLegal=Math.max(st.maxLegal,lq.length);
      const full=(st.steps%10===0);
      const masks=full?[...Array(16).keys()]:Q.variants(s.hand);
      const ops=full?[0,1,2,3,4,5,6,7]:[0,1,2,3,4,5,6,7];
      const cand=[];
      for(const op of ops)for(const m of masks){
        st.pushCalls++;
        let a;try{a=O.push(s,op,m);}catch(e){a='EXC '+e.message;}
        const b=Q.push(s,op,m);
        const r=typeof a==='string'?a:eq(a,b);
        if(r!==true)bad('push:'+(a===null?'O=null':b===null?'Q=null':r),{s:J(s),op,m,O:J(a),Q:J(b)});
        if(b)cand.push(b);
      }
      // 押す手を選ぶ
      let t=null;
      if(R()<mode){const good=cand.filter(c=>Q.reachable(c,c.turn)[c.tre[c.turn][c.next[c.turn]]]);if(good.length)t=good[Math.floor(R()*good.length)];}
      if(!t)t=cand[Math.floor(R()*cand.length)];
      s=t;
      // 動かす段
      for(const p of [0,1]){const a=J(O.reachable(s,p)),b=J(Q.reachable(s,p));if(a!==b)bad('reachable',{s:J(s),p,O:a,Q:b});}
      // 段の取り違え
      if(O.push(s,0,s.hand)!==null&&s.ban!==0)bad('pushInMovePhase',{s:J(s)});
      const nexts=[];
      for(let c=0;c<25;c++){st.moveCalls++;let a;try{a=O.moveTo(s,c);}catch(e){a='EXC '+e.message;}const b=Q.moveTo(s,c);
        const r=typeof a==='string'?a:eq(a,b);
        if(r!==true)bad('moveTo:'+(a===null?'O=null':b===null?'Q=null':r),{s:J(s),c,O:J(a),Q:J(b)});
        if(b)nexts.push(b);}
      // pathBetween：届くマスへは隣接・接続の道
      const me=s.turn,from=s.piece[me];
      let u=null;
      if(R()<mode){u=nexts.find(n=>n.next[me]>s.next[me])||null;}
      if(!u)u=nexts[Math.floor(R()*nexts.length)];
      const to=u.piece[me];
      const path=O.pathBetween(s,from,to);
      if(Array.isArray(path)){const d=Q.dist(s.cells,from);
        let ok=path[0]===from&&path[path.length-1]===to&&path.length-1===d[to];
        for(let k=1;k<path.length&&ok;k++)if(!Q.nbrs(s.cells,path[k-1]).includes(path[k]))ok=false;
        if(!ok)bad('pathBetween',{s:J(s),from,to,path:J(path),d:d[to]});} else bad('pathBetween:notArray',{path:J(path)});
      if(u.next[me]>s.next[me])st.picks++;
      s=u;
    }
    if(!s.over)bad('notOver',{s:J(s)});
    if(s.over){ if(Math.max(...s.next)>=3)st.wins++; else {st.cut++; if(s.winner===-1)st.draws++;}
      st.endTurns.push(s.turns);
      // 終局後
      if(O.legalOps(s).length)bad('legalAfterOver',{s:J(s),O:O.legalOps(s)});
      let pp=null;for(let op=0;op<8&&!pp;op++)pp=O.push(s,op,s.hand)||null; if(pp)bad('pushAfterOver',{s:J(s)});
    }
  }
  const et=st.endTurns;st.endMax=Math.max(...et);st.endMin=Math.min(...et);delete st.endTurns;
  return st;
};
