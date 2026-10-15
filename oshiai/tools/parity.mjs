// 並走：node tools/parity.mjs <局数> [URL]   （自前エンジン QA と window.Oshiai を同じ手で進め、毎手すべての押し込み・移動を突き合わせる）
import {open} from './cdp.mjs'; import fs from 'fs';
const url=process.argv[3]||'http://127.0.0.1:8762/oshiai/';
const p=await open(url);
await p.ev(fs.readFileSync(new URL('./qa_engine.js',import.meta.url),'utf8'));
await p.ev(fs.readFileSync(new URL('./parity_page.js',import.meta.url),'utf8'));
const NG=+process.argv[2]||100, CH=500; const tot={games:0,steps:0,pushCalls:0,moveCalls:0,ownPicks:0,wins:0,cut:0,draws:0,minLegal:99,maxLegal:0,endMin:99,endMax:0,ev:{},mism:{},ex:{}};
const t0=Date.now();
for(let b=0;b*CH<NG;b++){const r=await p.ev(`JSON.stringify(QAPAR(${b+1},${Math.min(CH,NG-b*CH)}))`);const s=JSON.parse(r);
  for(const k of ['games','steps','pushCalls','moveCalls','ownPicks','wins','cut','draws'])tot[k]+=s[k];
  for(const k in s.ev)tot.ev[k]=(tot.ev[k]||0)+s.ev[k];
  tot.minLegal=Math.min(tot.minLegal,s.minLegal);tot.maxLegal=Math.max(tot.maxLegal,s.maxLegal);tot.endMin=Math.min(tot.endMin,s.endMin);tot.endMax=Math.max(tot.endMax,s.endMax);
  for(const k in s.mism){tot.mism[k]=(tot.mism[k]||0)+s.mism[k];if(!tot.ex[k])tot.ex[k]=s.ex[k];}}
tot.sec=(Date.now()-t0)/1000; tot.consoleErrors=p.logs;
const {ex,...rest}=tot; console.log(JSON.stringify(rest,null,0)); for(const k in ex)console.log(k,JSON.stringify(ex[k]).slice(0,900));
await p.close(); process.exit(0);
