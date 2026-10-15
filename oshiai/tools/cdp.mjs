// CDP直結の最小ヘルパ
export async function open(url,{w=360,h=740,mobile=true,port=9341,pre=null}={}){
  const t=await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`,{method:'PUT'})).json();
  const ws=new WebSocket(t.webSocketDebuggerUrl); await new Promise(r=>ws.onopen=r);
  let id=0; const pend=new Map(); const logs=[]; const evh=[];
  ws.onmessage=m=>{const d=JSON.parse(m.data); if(d.id&&pend.has(d.id)){const p=pend.get(d.id);pend.delete(d.id);d.error?p.j(new Error(JSON.stringify(d.error))):p.r(d.result);} else if(d.method){
    if(d.method==='Runtime.consoleAPICalled'&&(d.params.type==='error'||d.params.type==='warning'))logs.push(d.params.type+': '+d.params.args.map(a=>a.value??a.description).join(' '));
    if(d.method==='Runtime.exceptionThrown')logs.push('EXC: '+(d.params.exceptionDetails.exception?.description||d.params.exceptionDetails.text));
    if(d.method==='Log.entryAdded'&&d.params.entry.level==='error')logs.push('LOG: '+d.params.entry.text+' '+(d.params.entry.url||''));
    evh.forEach(f=>f(d));}};
  const send=(method,params={})=>new Promise((r,j)=>{const i=++id;pend.set(i,{r,j});ws.send(JSON.stringify({id:i,method,params}));});
  await send('Runtime.enable'); await send('Log.enable'); await send('Page.enable');
  await send('Emulation.setDeviceMetricsOverride',{width:w,height:h,deviceScaleFactor:2,mobile});
  await send('Emulation.setTouchEmulationEnabled',{enabled:mobile,maxTouchPoints:5});
  if(pre) await send('Page.addScriptToEvaluateOnNewDocument',{source:pre});
  const load=new Promise(r=>evh.push(d=>{if(d.method==='Page.loadEventFired')r();}));
  await send('Page.navigate',{url}); await load;
  const ev=async(expr)=>{const r=await send('Runtime.evaluate',{expression:expr,awaitPromise:true,returnByValue:true}); if(r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text); return r.result.value;};
  const tap=async(x,y)=>{await send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y}]});await send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});};
  const shot=async(path)=>{const r=await send('Page.captureScreenshot',{format:'png'}); (await import('fs')).writeFileSync(path,Buffer.from(r.data,'base64'));};
  const close=async()=>{try{await fetch(`http://127.0.0.1:${port}/json/close/${t.id}`);}catch(e){} ws.close();};
  return {send,ev,tap,shot,close,logs,sleep:ms=>new Promise(r=>setTimeout(r,ms))};
}
