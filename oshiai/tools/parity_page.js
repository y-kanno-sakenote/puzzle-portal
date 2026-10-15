// ページ内で実行：Oshiai と QA（自前エンジン）を並走。v0.4（本戦＋延長戦）
// 1局 = 本戦(ext0)→同点打ち切りなら O.extend で延長戦の盤→(ext1)→同点なら延長戦もう1回(ext2)→それでも同点なら引き分け
// 延長戦の盤の配りは乱数なので、QA.checkExt（仕様から書いた検査）で「配られた盤が仕様どおりか」を見て、その盤から並走を続ける
window.QAPAR=function(seed0,ngames){
  const O=window.Oshiai,Q=window.QA;
  const mk=seed=>{let s=seed>>>0||1;return()=>{s^=s<<13;s>>>=0;s^=s>>>17;s^=s<<5;s>>>=0;return s/4294967296;};};
  const J=JSON.stringify, KEYS=['cells','hand','piece','tre','next','turn','phase','ban','turns','first','over','winner','ext','extend'];
  const eq=(a,b)=>{if(a===null||b===null)return a===b;for(const k of KEYS)if(J(a[k])!==J(b[k]))return k;return true;};
  const st={games:0,steps:0,pushCalls:0,moveCalls:0,wins:0,mism:{},ex:{},minLegal:99,maxLegal:0,
    ev:{main_decided_by_count:0,main_win_common:0,main_tie_00:0,main_tie_11:0,ext1_started:0,ext1_win_first:0,ext1_win_second:0,ext1_cut:0,ext2_started:0,ext2_win_first:0,ext2_win_second:0,ext2_cut_draw:0,
        ext_pushOnly:0,ext_first_is_main_second:0,ext2_first_is_main_first:0,ext_boards_identical_to_prev:0,ext_board_checked:0,ext_sym_ok:0,ext_cross_ok:0,ext_move_after_pushonly_null:0,
        ext_pick_stay:0,ext_cut_turns20:0,main_cut_turns40:0,ext_extend_not_null_when_not_allowed:0,ext_extend_pure:0,ext_extend_deterministic:0,ext_second_turn_normal:0,
        types_main_s:0,types_main_c:0,types_main_t:0,types_ext_s:0,types_ext_c:0,types_ext_t:0,types_ext_boards:0,types_main_boards:0}};
  const bad=(cat,info)=>{st.mism[cat]=(st.mism[cat]||0)+1;if(!st.ex[cat])st.ex[cat]=info;};
  if(J([O.GOAL,O.OWN,O.MAX_TURNS,O.COMMON,O.EXT_TURNS,O.EXT_MAX])!==J([2,1,40,12,20,2]))bad('consts',[O.GOAL,O.OWN,O.MAX_TURNS,O.COMMON,O.EXT_TURNS,O.EXT_MAX]);
  const typeOf=m=>{const n=(m&1)+((m>>1)&1)+((m>>2)&1)+((m>>3)&1);return n===2?((m===5||m===10)?'s':'c'):n===3?'t':'x';};
  const countTypes=(s,tag)=>{for(let i=0;i<25;i++){if(i===12)continue;const t=typeOf(s.cells[i]);if(t!=='x')st.ev['types_'+tag+'_'+t]++;}const t=typeOf(s.hand);if(t!=='x')st.ev['types_'+tag+'_'+t]++;st.ev['types_'+tag+'_boards']++;};
  // 方針：自分の宝を拾う確率 pOwn・共通の宝を拾う確率 pCom（段ごとに決める）。0 なら拾える手でも避ける（避けられなければ拾う）
  function stagePol(R,ext){
    const pOwn=[0,0.5,1][Math.floor(R()*3)];
    const pCom=ext===0?[0,0.3,1][Math.floor(R()*3)]:[0,0,0.15,0.5,1][Math.floor(R()*5)];
    return {pOwn,pCom,lure:[0.6,0.3,0.1][Math.floor(R()*3)]};
  }
  for(let g=0;g<ngames;g++){
    const R=mk(seed0*100003+g*7919+1);
    const mainFirst=R()<0.5?0:1;
    let s=O.newGame({rng:mk(seed0*7+g*31+5),first:mainFirst});
    countTypes(s,'main');
    st.games++;
    let stageIdx=0, prevBoardJ=null;
    for(;;){
      const ext=s.ext||0;
      const pol=[stagePol(R,ext),stagePol(R,ext)]; // 手番側ごと
      for(let step=0;step<200&&!s.over;step++){
        st.steps++;
        for(const p of [0,1])if(O.target(s,p)!==Q.target(s,p))bad('target',{s:J(s),p,O:O.target(s,p),Q:Q.target(s,p)});
        if(O.pushOnly(s)!==Q.pushOnly(s))bad('pushOnly',{s:J(s),O:O.pushOnly(s),Q:Q.pushOnly(s)});
        if(O.limit(s)!==Q.limit(s))bad('limit',{s:J(s),O:O.limit(s),Q:Q.limit(s)});
        if(s.phase==='push'&&s.turns===1&&ext>0)st.ev.ext_second_turn_normal++;
        const lo=O.legalOps(s),lq=Q.legalOps(s);
        if(J(lo)!==J(lq))bad('legalOps',{s:J(s),O:lo,Q:lq});
        st.minLegal=Math.min(st.minLegal,lq.length);st.maxLegal=Math.max(st.maxLegal,lq.length);
        const masks=(st.steps%10===0)?[...Array(16).keys()]:Q.variants(s.hand);
        const cand=[];
        for(let op=-1;op<9;op++)for(const m of masks){
          st.pushCalls++;
          let a;try{a=O.push(s,op,m);}catch(e){a='EXC '+e.message;}
          const b=Q.push(s,op,m);
          const r=typeof a==='string'?a:eq(a,b);
          if(r!==true)bad('push:'+(a===null?'O=null':b===null?'Q=null':r),{s:J(s),op,m,O:J(a),Q:J(b)});
          if(b)cand.push(b);
        }
        const me0=s.turn, P0=pol[me0];
        const pk=(c)=>{const x=Q.target(c,c.turn);return x>=0&&Q.reachable(c,c.turn)[x];};
        const wantPick=s.next[me0]===0?P0.pOwn:P0.pCom;
        let t=null;
        if(R()<wantPick){const good=cand.filter(pk);if(good.length)t=good[Math.floor(R()*good.length)];}
        if(!t)t=cand[Math.floor(R()*cand.length)];
        if(Q.pushOnly(s)){ // 押すだけの手番：独立の不変条件
          if(ext>0)st.ev.ext_pushOnly++;
          if(t.phase!=='push'||t.turn!==(s.turn^1)||t.turns!==1||J(t.next)!==J(s.next)||t.over)bad('pushOnly:state',{s:J(s),t:J(t)});
          let anyMove=false;for(let c=-1;c<26;c++){let a;try{a=O.moveTo(t,c);}catch(e){a='EXC';}if(a!==null)anyMove=true;}
          if(anyMove)bad('pushOnly:moveAllowedAfter',{t:J(t)}); else st.ev.ext_move_after_pushonly_null++;
          s=t;continue;}
        s=t;
        for(const p of [0,1]){const a=J(O.reachable(s,p)),b=J(Q.reachable(s,p));if(a!==b)bad('reachable',{s:J(s),p,O:a,Q:b});}
        if(O.push(s,s.ban===0?1:0,s.hand)!==null)bad('pushInMovePhase',{s:J(s)});
        const nexts=[];
        for(let c=-1;c<26;c++){st.moveCalls++;let a;try{a=O.moveTo(s,c);}catch(e){a='EXC '+e.message;}const b=(c<0||c>24)?null:Q.moveTo(s,c);
          const r=typeof a==='string'?a:eq(a,b);
          if(r!==true)bad('moveTo:'+(a===null?'O=null':b===null?'Q=null':r),{s:J(s),c,O:J(a),Q:J(b)});
          if(b)nexts.push(b);}
        const me=s.turn,from=s.piece[me], P=pol[me];
        const picks=nexts.filter(n=>n.next[me]>s.next[me]), nopick=nexts.filter(n=>n.next[me]===s.next[me]);
        const pPick=s.next[me]===0?P.pOwn:P.pCom;
        let u=null;
        if(picks.length&&R()<pPick)u=picks[Math.floor(R()*picks.length)];
        if(!u&&nopick.length){ if(R()<P.lure)u=nopick.find(n=>n.piece[me]===12)||null; if(!u)u=nopick[Math.floor(R()*nopick.length)]; }
        if(!u)u=nexts[Math.floor(R()*nexts.length)];
        const to=u.piece[me];
        const path=O.pathBetween(s,from,to);
        if(Array.isArray(path)){const d=Q.dist(s.cells,from);
          let ok=path[0]===from&&path[path.length-1]===to&&path.length-1===d[to];
          for(let k=1;k<path.length&&ok;k++)if(!Q.nbrs(s.cells,path[k-1]).includes(path[k]))ok=false;
          if(!ok)bad('pathBetween',{s:J(s),from,to,path:J(path),d:d[to]});} else bad('pathBetween:notArray',{path:J(path)});
        if(ext>0&&to===from&&u.next[me]>s.next[me])st.ev.ext_pick_stay++;
        s=u;
      }
      if(!s.over){bad('notOver',{s:J(s)});break;}
      // --- 段の終わり ---
      const lim=Q.limit({ext}), picked=Math.max(...s.next)>=2;
      if(O.legalOps(s).length)bad('legalAfterOver',{s:J(s),O:O.legalOps(s)});
      let pp=null;for(let op=0;op<8&&!pp;op++)pp=O.push(s,op,s.hand)||null; if(pp)bad('pushAfterOver',{s:J(s)});
      let mm=null;for(let c=0;c<25&&!mm;c++)mm=O.moveTo(s,c)||null; if(mm)bad('moveAfterOver',{s:J(s)});
      // 終わり方の独立判定
      if(picked){ // 共通の宝を拾った：勝者はその人、延長戦にならない
        if(s.winner!==s.next.indexOf(2)||s.extend)bad('end:pick',{s:J(s)});
        if(ext===0)st.ev.main_win_common++;
        else if(ext===1){ if(s.winner===s.first)st.ev.ext1_win_first++;else st.ev.ext1_win_second++;}
        else { if(s.winner===s.first)st.ev.ext2_win_first++;else st.ev.ext2_win_second++;}
        st.wins++;break;}
      // 打ち切り
      if(s.turns!==lim)bad('end:cut-turns',{s:J(s),lim});
      if(ext===0)st.ev.main_cut_turns40++; else if(s.turns===20)st.ev.ext_cut_turns20++;
      const n0=s.next[0],n1=s.next[1];
      if(n0!==n1){ // 拾った数が違う（本戦だけで起きる）：多い方の勝ち・延長戦にならない
        if(ext!==0)bad('end:ext-uneven',{s:J(s)});
        if(s.winner!==(n0>n1?0:1)||s.extend)bad('end:uneven',{s:J(s)});
        st.ev.main_decided_by_count++;break;}
      // 同点の打ち切り
      if(s.winner!==-1||!s.over)bad('end:tie-winner',{s:J(s)});
      if(ext===0){ if(n0===0)st.ev.main_tie_00++; else st.ev.main_tie_11++; }
      if(ext<2){
        if(!s.extend){bad('end:tie-not-extend',{s:J(s)});break;}
        // 延長戦の盤
        const before=J(s);
        let e,e2;
        try{e=O.extend(s,{rng:mk(seed0*13+g*17+stageIdx)});e2=O.extend(s,{rng:mk(seed0*13+g*17+stageIdx)});}catch(x){bad('extend:exception',{msg:x.message,s:J(s)});break;}
        if(J(s)===before)st.ev.ext_extend_pure++; else bad('extend:mutates-input',{before,after:J(s)});
        if(J(e)===J(e2))st.ev.ext_extend_deterministic++; else bad('extend:rng-not-deterministic',{});
        const viol=Q.checkExt(s,e);
        st.ev.ext_board_checked++;
        if(viol.length)for(const v of viol)bad('extBoard:'+v.split(/[@:]/)[0],{v,s:J(s),e:J(e)});
        else { st.ev.ext_sym_ok++;st.ev.ext_cross_ok++; }
        if(e){
          if(e.first===(mainFirst^1)&&e.ext===1)st.ev.ext_first_is_main_second++;
          if(e.ext===2&&e.first===mainFirst)st.ev.ext2_first_is_main_first++;
          if(J(e.cells)===J(s.cells))st.ev.ext_boards_identical_to_prev++;
          countTypes(e,'ext');
          if(e.ext===1)st.ev.ext1_started++; else st.ev.ext2_started++;
          if(ext===1&&prevBoardJ&&J(e.cells)===prevBoardJ)bad('ext2-board-same-as-ext1',{});
          prevBoardJ=J(e.cells);
          s=JSON.parse(J(e)); stageIdx++; continue;}
        break;}
      // ext=2 の同点：引き分け（延長戦なし）
      if(s.extend)bad('end:ext2-tie-extend-true',{s:J(s)});
      st.ev.ext2_cut_draw++;
      // 延長戦に入れない状態で extend を呼ぶと？（観察：null なら良。盤が返るなら記録）
      let x=null;try{x=O.extend(s,{rng:mk(1)});}catch(err){x=null;}
      if(x)st.ev.ext_extend_not_null_when_not_allowed++;
      break;
    }
    if(!s.over)bad('notOver2',{s:J(s)});
  }
  return st;
};
