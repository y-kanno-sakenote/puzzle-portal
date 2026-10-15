// ページ内で実行：Oshiai と QA（自前エンジン）を並走。v0.3（自分の宝→共通12・40手・先手の最初の手番は押すだけ）
window.QAPAR=function(seed0,ngames){
  const O=window.Oshiai,Q=window.QA;
  const mk=seed=>{let s=seed>>>0||1;return()=>{s^=s<<13;s>>>=0;s^=s>>>17;s^=s<<5;s>>>=0;return s/4294967296;};};
  const J=JSON.stringify, KEYS=['cells','hand','piece','tre','next','turn','phase','ban','turns','first','over','winner'];
  const eq=(a,b)=>{if(a===null||b===null)return a===b;for(const k of KEYS)if(J(a[k])!==J(b[k]))return k;return true;};
  const st={games:0,steps:0,pushCalls:0,moveCalls:0,ownPicks:0,wins:0,cut:0,draws:0,minLegal:99,maxLegal:0,mism:{},ex:{},endTurns:[],
    ev:{pushOnly_turns:0,pushOnly_first0:0,pushOnly_first1:0,pushOnly_synth:0,pushOnly_synth_samecell:0,pushOnly_stay_on_target:0,pushOnly_move_null_ok:0,second_turn_normal:0,stop12_before_own:0,win_while_opp_next0:0,win_while_opp_next1:0,stop_on_opp_tre:0,stay_pick:0,center_changed:0,cut_at40:0,cut_win:0}};
  const bad=(cat,info)=>{st.mism[cat]=(st.mism[cat]||0)+1;if(!st.ex[cat])st.ex[cat]=info;};
  if(J([O.GOAL,O.OWN,O.MAX_TURNS,O.COMMON])!==J([2,1,40,12]))bad('consts',[O.GOAL,O.OWN,O.MAX_TURNS,O.COMMON]);
  for(let g=0;g<ngames;g++){
    const R=mk(seed0*100003+g*7919+1);
    const first=R()<0.5?0:1;
    let s=O.newGame({rng:mk(seed0*7+g*31+5),first});
    const c12=s.cells[12];
    const mode=[0,0.5,0.9][g%3];          // 0=ランダム 0.5/0.9=拾える手を優先する割合
    const lure=[0.6,0.3,0.1][g%3];        // 真ん中12に届くなら止まる割合（自分の宝の前でも）
    st.games++;
    for(let step=0;step<200&&!s.over;step++){
      st.steps++;
      for(const p of [0,1])if(O.target(s,p)!==Q.target(s,p))bad('target',{s:J(s),p,O:O.target(s,p),Q:Q.target(s,p)});
      if(O.pushOnly(s)!==Q.pushOnly(s))bad('pushOnly',{s:J(s),O:O.pushOnly(s),Q:Q.pushOnly(s)});
      if(s.phase==='push'&&s.turns===1)st.ev.second_turn_normal++;
      const lo=O.legalOps(s),lq=Q.legalOps(s);
      if(J(lo)!==J(lq))bad('legalOps',{s:J(s),O:lo,Q:lq});
      st.minLegal=Math.min(st.minLegal,lq.length);st.maxLegal=Math.max(st.maxLegal,lq.length);
      const masks=(st.steps%10===0)?[...Array(16).keys()]:Q.variants(s.hand);
      if(s.turns===0&&s.phase==='push'){
        for(const kind of [0,1,2]){const d=Q.clone(s);const p=s.turn;
          if(kind===0){d.piece[p]=d.tre[p][0];d.piece[p^1]=d.tre[p^1][0];}
          else if(kind===1){d.next[p]=1;d.tre[p][0]=-2;d.piece[p]=12;}
          else{d.next[p]=1;d.tre[p][0]=-2;d.next[p^1]=1;d.tre[p^1][0]=-2;d.piece=[12,12];}
          for(let op=0;op<8;op++)for(const m of Q.variants(d.hand)){
            const a=O.push(d,op,m),b=Q.push(d,op,m);st.ev.pushOnly_synth++;
            const r=eq(a,b);if(r!==true)bad('synthPush:'+(a===null?'O=null':b===null?'Q=null':r),{s:J(d),op,m,O:J(a),Q:J(b)});
            if(a){ if(J(a.next)!==J(d.next)||a.over)bad('synthPush:picked',{s:J(d),op,m,O:J(a)});
              for(const q of [0,1])if(a.piece[q]===Q.target(a,q)&&Q.target(a,q)>=0)st.ev.pushOnly_synth_samecell++; }}}
      }
      const cand=[];
      for(let op=-1;op<9;op++)for(const m of masks){
        st.pushCalls++;
        let a;try{a=O.push(s,op,m);}catch(e){a='EXC '+e.message;}
        const b=Q.push(s,op,m);
        const r=typeof a==='string'?a:eq(a,b);
        if(r!==true)bad('push:'+(a===null?'O=null':b===null?'Q=null':r),{s:J(s),op,m,O:J(a),Q:J(b)});
        if(b)cand.push(b);
      }
      let t=null;
      if(R()<mode){const good=cand.filter(c=>{const x=Q.target(c,c.turn);return x>=0&&Q.reachable(c,c.turn)[x];});if(good.length)t=good[Math.floor(R()*good.length)];}
      if(!t)t=cand[Math.floor(R()*cand.length)];
      if(Q.pushOnly(s)){ // いま押したのは押すだけの手番：独立の不変条件
        st.ev.pushOnly_turns++; if(s.first===0)st.ev.pushOnly_first0++; else st.ev.pushOnly_first1++;
        if(t.phase!=='push'||t.turn!==(s.turn^1)||t.turns!==1||J(t.next)!==J(s.next)||t.over||t.hand===undefined)bad('pushOnly:state',{s:J(s),t:J(t)});
        for(const q of [0,1])if(t.piece[q]===Q.target(t,q)&&Q.target(t,q)>=0)st.ev.pushOnly_stay_on_target++;
        let anyMove=false;for(let c=-1;c<26;c++){let a;try{a=O.moveTo(t,c);}catch(e){a='EXC';}if(a!==null)anyMove=true;}
        if(anyMove)bad('pushOnly:moveAllowedAfter',{t:J(t)}); else st.ev.pushOnly_move_null_ok++;
        if(O.pushOnly(t))bad('pushOnly:stillPushOnly',{t:J(t)});
        s=t;continue;}
      s=t;
      for(const p of [0,1]){const a=J(O.reachable(s,p)),b=J(Q.reachable(s,p));if(a!==b)bad('reachable',{s:J(s),p,O:a,Q:b});}
      for(const p of [0,1])if(O.target(s,p)!==Q.target(s,p))bad('target',{s:J(s),p,O:O.target(s,p),Q:Q.target(s,p)});
      if(O.push(s,s.ban===0?1:0,s.hand)!==null)bad('pushInMovePhase',{s:J(s)});
      const nexts=[];
      for(let c=-1;c<26;c++){st.moveCalls++;let a;try{a=O.moveTo(s,c);}catch(e){a='EXC '+e.message;}const b=(c<0||c>24)?null:Q.moveTo(s,c);
        const r=typeof a==='string'?a:eq(a,b);
        if(r!==true)bad('moveTo:'+(a===null?'O=null':b===null?'Q=null':r),{s:J(s),c,O:J(a),Q:J(b)});
        if(b)nexts.push(b);}
      const me=s.turn,from=s.piece[me];
      let u=null;
      if(R()<mode)u=nexts.find(n=>n.next[me]>s.next[me])||null;
      if(!u&&R()<lure)u=nexts.find(n=>n.piece[me]===12)||null;
      if(!u)u=nexts[Math.floor(R()*nexts.length)];
      const to=u.piece[me];
      const path=O.pathBetween(s,from,to);
      if(Array.isArray(path)){const d=Q.dist(s.cells,from);
        let ok=path[0]===from&&path[path.length-1]===to&&path.length-1===d[to];
        for(let k=1;k<path.length&&ok;k++)if(!Q.nbrs(s.cells,path[k-1]).includes(path[k]))ok=false;
        if(!ok)bad('pathBetween',{s:J(s),from,to,path:J(path),d:d[to]});} else bad('pathBetween:notArray',{path:J(path)});
      // 数えたい場面
      if(to===12&&s.next[me]===0)st.ev.stop12_before_own++;
      if(s.next[me]===0&&to===s.tre[me^1][0])st.ev.stop_on_opp_tre++;
      if(to===from&&u.next[me]>s.next[me])st.ev.stay_pick++;
      if(u.next[me]===1&&s.next[me]===0)st.ownPicks++;
      if(u.over&&u.next[me]===2){if(u.next[me^1]===0)st.ev.win_while_opp_next0++;else st.ev.win_while_opp_next1++;}
      if(u.cells[12]!==c12)st.ev.center_changed++;
      s=u;
    }
    if(!s.over)bad('notOver',{s:J(s)});
    if(s.over){ if(Math.max(...s.next)>=2)st.wins++; else {st.cut++; if(s.turns===40)st.ev.cut_at40++; if(s.winner===-1)st.draws++; else st.ev.cut_win++;}
      st.endTurns.push(s.turns);
      if(O.legalOps(s).length)bad('legalAfterOver',{s:J(s),O:O.legalOps(s)});
      let pp=null;for(let op=0;op<8&&!pp;op++)pp=O.push(s,op,s.hand)||null; if(pp)bad('pushAfterOver',{s:J(s)});
      let mm=null;for(let c=0;c<25&&!mm;c++)mm=O.moveTo(s,c)||null; if(mm)bad('moveAfterOver',{s:J(s)});
    }
  }
  const et=st.endTurns;st.endMax=Math.max(...et);st.endMin=Math.min(...et);delete st.endTurns;
  return st;
};
