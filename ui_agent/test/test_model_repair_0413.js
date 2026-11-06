'use strict';
// New engineering controls only. Real Core/Loop/Catalog/Snapshot/Verifier,
// deterministic host clock and fake propose/XHR. No network or model APIs.
const fs=require('fs'), path=require('path'), vm=require('vm'), assert=require('assert');
const old=fs.readFileSync(path.join(__dirname,'test_readable_overlay_v6.js'),'utf8');
const fixtureVM={require,__dirname,console}; vm.createContext(fixtureVM);
vm.runInContext(old.slice(0,old.indexOf('let count=0;'))+'\nthis.makeFixture=fixture;',fixtureVM);
const clone=x=>JSON.parse(JSON.stringify(x)); let count=0;
function test(name,fn){fn();++count;console.log('PASS '+name);}
function fixture(options={}) {
 const f=fixtureVM.makeFixture(), calls=[], callbacks=[];
 let aborts=0;
 f.State.undoStack=[];
 const commit=f.State.commitGroup;
 f.State.commitGroup=function(...a){commit.apply(this,a);this.undoStack.push('readability');};
 f.O.callReadableRepair=(r,done)=>{calls.push(clone(r));callbacks.push(done);
  if(options.throws) throw Error('injected transport exception');
  if(options.sync) done({ok:true,response:{steps:[{choice_id:r.candidates[0].id}],reason_zh:'sync'},raw:'sync'});
  return ()=>{++aborts;};};
 // Initially just outside the miniView, overlapping only after its 1.25x scale.
 f.other.x=335;f.other.y=130;
 if(options.noOverlap) {f.other.x=500;f.other.y=350;}
 if(options.shrink) {f.O.readableGoalPolicy.allowMove=false;f.O.readableGoalPolicy.allowShrink=true;}
 if(options.noCandidates) {f.O.readableGoalPolicy.allowMove=false;f.O.readableGoalPolicy.allowShrink=false;}
 f.card();assert(f.O._confirmation.readable);f.O.confirmIntent();
 const session=f.O._readableSession;
 function toRequest(){let n=0;while(!calls.length && f.O._readableSession){assert(++n<10);f.step();}}
 function reply(response,raw){callbacks[0]({ok:true,response,raw:raw===undefined?JSON.stringify(response):raw});}
 return Object.assign(f,{calls,callbacks,session,toRequest,reply,aborts:()=>aborts,
  good(){return {steps:[{choice_id:calls[0].candidates[0].id}],reason_zh:'選擇已確認空位'};},
  reason(){return session.state().trace.at(-1).reason;},
  failed(reason){assert.equal(session.state().phase,'failed');assert.equal(this.reason(),reason);assert.equal(f.stats.rollback,1);assert.equal(f.State.undoStack.length,0);assert.equal(f.stats.commit,0);assert.equal(f.ov.scale,1);}
 });
}
test('one allowed repair uses real verifier and commits exactly one undo',()=>{
 const f=fixture();f.toRequest();assert.equal(f.calls.length,1);const req=f.calls[0];
 assert(req.candidates.every(c=>c.id.startsWith('REPAIR_MINIVIEW_')));
 assert.equal(req.max_steps,1);assert.equal(req.json_schema.properties.steps.minItems,1);assert.equal(req.json_schema.properties.steps.maxItems,1);
 assert.deepEqual(req.json_schema.properties.steps.items.properties.choice_id.enum,req.candidates.map(c=>c.id));
 f.reply(f.good());f.drain();assert.equal(f.reason(),'VERIFIED');assert.equal(f.stats.apply,2);
 assert.equal(f.stats.rollback,0);assert.equal(f.State.undoStack.length,1);assert.equal(f.stats.commit,1);assert.equal(f.aborts(),1);
 assert.equal(f.session.state().repair.repair_source,'model');assert(f.session.state().repair.raw.includes('choice_id'));
 const gateStages=f.session.state().trace.filter(e=>e.gate).map(e=>e.stage);assert(gateStages.includes('loop_repair'));assert(gateStages.filter(s=>s==='loop_step').length===2);
});
for(const [name,bad] of [
 ['unknown id',()=>({steps:[{choice_id:'UNLISTED'}],reason_zh:'x'})],
 ['empty steps',()=>({steps:[],reason_zh:'x'})],
 ['two ids',f=>({steps:[f.good().steps[0],f.good().steps[0]],reason_zh:'x'})],
 ['step action injection',f=>({steps:[{...f.good().steps[0],action:{kind:'nav',page:0}}],reason_zh:'x'})],
 ['top-level action injection',f=>({...f.good(),command:'takeoff'})],
 ['missing choice_id',()=>({steps:[{id:'x'}],reason_zh:'x'})],
 ['missing reason',f=>({steps:f.good().steps})],
 ['initial id is not a repair',()=>({steps:[{choice_id:'GOAL_MINIVIEW_READABLE'}],reason_zh:'x'})]
]) test(name+' rolls back once and creates zero undo',()=>{const f=fixture();f.toRequest();f.reply(bad(f));f.failed('REPAIR_INVALID');f.session.cancel();f.session.cancel();assert.equal(f.stats.rollback,1);assert.equal(f.stats.apply,1);});
test('repair verification failure is REPAIR_LIMIT without a second propose',()=>{
 const f=fixture();f.toRequest();const verifier=f.O.ReadableVerifier, before=verifier.verify;
 verifier.verify=(s,e)=>f.stats.apply>=2?{ok:false,failures:[{code:'OVERLAP',detail:'injected after repair'}]}:before(s,e);
 try {f.reply(f.good());f.drain();f.failed('REPAIR_LIMIT');assert.equal(f.calls.length,1);assert.equal(f.stats.apply,2);}
 finally {verifier.verify=before;}
});
test('model timeout aborts and late/duplicate replies cannot mutate State or trace',()=>{
 const f=fixture();f.toRequest();const good=f.good();f.step();f.failed('REPAIR_TIMEOUT');assert.equal(f.aborts(),1);
 const state=JSON.stringify(f.session.state()),snap=JSON.stringify(f.State.snapshot()),apply=f.stats.apply;
 f.reply(good);f.reply(good);f.session.cancel();assert.equal(JSON.stringify(f.session.state()),state);assert.equal(JSON.stringify(f.State.snapshot()),snap);assert.equal(f.stats.apply,apply);assert.equal(f.stats.rollback,1);
});
test('late response rejected by clock even if timeout event has not run',()=>{
 const f=fixture();f.toRequest();f.advance(20001);f.reply(f.good());f.failed('REPAIR_TIMEOUT');assert.equal(f.stats.apply,1);assert.equal(f.aborts(),1);
});
test('19-second model wait does not consume operation budget',()=>{
 const f=fixture();f.toRequest();f.advance(19000);f.reply(f.good());f.drain();assert.equal(f.reason(),'VERIFIED');assert.equal(f.session.state().repair.latency_ms,19000);assert.equal(f.State.undoStack.length,1);
});
test('cancel during repair aborts once and discards response',()=>{
 const f=fixture();f.toRequest();const response=f.good();f.session.cancel();f.failed('CANCELLED');f.reply(response);assert.equal(f.stats.apply,1);assert.equal(f.aborts(),1);
});
test('transport error fails with no rule fallback',()=>{const f=fixture();f.toRequest();f.callbacks[0]({ok:false,error_code:'REPAIR_INVALID',raw:'HTTP failure'});f.failed('REPAIR_INVALID');assert.equal(f.calls.length,1);assert.equal(f.session.state().repair.raw,'HTTP failure');});
test('transport timeout keeps timeout reason',()=>{const f=fixture();f.toRequest();f.callbacks[0]({ok:false,error_code:'REPAIR_TIMEOUT',raw:'gateway 504'});f.failed('REPAIR_TIMEOUT');});
test('repair post-selection gate remains enforced',()=>{
 const f=fixture();f.toRequest();const core=f.O.Core, before=core.gateSelection;
 core.gateSelection=(d,c,s)=>d.steps.some(x=>x.choice_id.startsWith('REPAIR_'))?{ok:false,failures:[{code:'LOCKED_MODULE',detail:'injected',step:1}],checks:[]}:before(d,c,s);
 try {f.reply(f.good());assert.equal(f.stats.apply,1);assert.equal(f.stats.rollback,1);assert.equal(f.State.undoStack.length,0);assert(f.session.state().trace.some(e=>e.stage==='loop_repair'&&!e.ok));}
 finally {core.gateSelection=before;}
});
test('success without repair uses source none and never calls propose',()=>{const f=fixture({noOverlap:true});f.drain();assert.equal(f.calls.length,0);assert.equal(f.reason(),'VERIFIED');assert.equal(f.session.state().repair.repair_source,'none');assert.equal(f.State.undoStack.length,1);});
test('confirmed shrink candidate executes with real verifier',()=>{const f=fixture({shrink:true});f.toRequest();assert(f.calls[0].candidates.every(c=>c.id==='REPAIR_MINIVIEW_SHRINK'));f.reply(f.good());f.drain();assert.equal(f.reason(),'VERIFIED');assert.equal(f.ov.scale,1);assert.equal(f.State.undoStack.length,1);});
test('no repair candidates fails without a model call',()=>{const f=fixture({noCandidates:true});f.drain();f.failed('REPAIR_INVALID');assert.equal(f.calls.length,0);assert.equal(f.session.state().repair.repair_source,'none');});
test('synchronous transport reply commits once and cleans returned cancel handle',()=>{const f=fixture({sync:true});f.drain();assert.equal(f.reason(),'VERIFIED');assert.equal(f.stats.commit,1);assert.equal(f.aborts(),1);});
test('transport exception rolls back once',()=>{const f=fixture({throws:true});f.toRequest();f.failed('REPAIR_INVALID');assert.equal(f.calls.length,1);});
test('delayed layout after reply respects absolute operation/session cap',()=>{const f=fixture();f.toRequest();f.advance(19000);f.reply(f.good());f.advance(13000);f.step();assert.equal(f.session.state().phase,'failed');assert(f.reason().includes('TIMEOUT'));assert.equal(f.stats.rollback,1);assert.equal(f.State.undoStack.length,0);});
test('changed confirmation policy during model wait prevents repair dispatch',()=>{const f=fixture();f.toRequest();f.O.readableGoalPolicy.allowMove=false;f.reply(f.good());assert.equal(f.stats.apply,1);assert.equal(f.stats.rollback,1);assert.equal(f.State.undoStack.length,0);});
function transport(backend='openai') {
 const sent=[], replies=[], xs=[];
 class XHR {constructor(){this.aborts=0;this.headers={};xs.push(this);} open(method,url){this.method=method;this.url=url;}setRequestHeader(k,v){this.headers[k]=v;}send(body){sent.push(JSON.parse(body));}abort(){this.aborts++;}}
 XHR.DONE=4;
 const qml=fs.readFileSync(path.join(__dirname,'../qml/GcpAgentOverlay.qml'),'utf8');
 const start=qml.indexOf('    function callReadableRepair('),end=qml.indexOf('\n    function callModel(',start);
 const context={backend,modelUrl:'http://127.0.0.1:8090/f/ui/v1',modelName:'fake',envValue:(_n,v)=>v,XMLHttpRequest:XHR};vm.createContext(context);vm.runInContext(qml.slice(start,end),context);
 const request={deadline_ms:32000,timeout_ms:20000,goal:'小地圖',failures:[],snapshot:{},expected:{},candidates:[{id:'REPAIR_MINIVIEW_MOVE_TL'}],json_schema:{type:'object'}};
 const cancel=context.callReadableRepair(request,r=>replies.push(clone(r)));
 return {sent,replies,xs,cancel,respond(status,raw){const x=xs[0];x.status=status;x.responseText=raw;x.readyState=4;x.onreadystatechange();}};
}
test('gateway transport sends strict schema in one request, never schema-retries',()=>{
 const t=transport();assert.equal(t.xs[0].url,'http://127.0.0.1:8090/f/ui/v1/chat/completions');assert.equal(t.sent[0].response_format.type,'json_schema');assert.equal(t.sent[0].response_format.json_schema.strict,true);
 t.respond(400,'bad schema');assert.equal(t.sent.length,1);assert.equal(t.replies[0].error_code,'REPAIR_INVALID');
});
test('gateway valid content preserves entire raw reply',()=>{const t=transport();const raw=JSON.stringify({steps:[{choice_id:'REPAIR_MINIVIEW_MOVE_TL'}],reason_zh:'x'.repeat(800)});t.respond(200,JSON.stringify({choices:[{message:{content:raw}}]}));assert.equal(t.replies[0].raw,raw);assert.equal(t.replies[0].response.reason_zh.length,800);});
test('gateway malformed JSON is invalid',()=>{const t=transport();t.respond(200,JSON.stringify({choices:[{message:{content:'not json'}}]}));assert.equal(t.replies[0].error_code,'REPAIR_INVALID');});
test('gateway 504 is a timeout',()=>{const t=transport();t.respond(504,'timeout');assert.equal(t.replies[0].error_code,'REPAIR_TIMEOUT');});
test('XHR cancel aborts once and stale handler does not call done',()=>{const t=transport(),x=t.xs[0],handler=x.onreadystatechange;t.cancel();t.cancel();x.readyState=4;x.status=200;x.responseText='{}';handler();assert.equal(x.aborts,1);assert.equal(t.replies.length,0);});
test('native backend is refused for repair without network',()=>{const t=transport('ollama');assert.equal(t.sent.length,0);assert.equal(t.replies[0].error_code,'REPAIR_INVALID');});
console.log(JSON.stringify({new_controls:count,external_model_calls:0,Qt_runtime:false}));
