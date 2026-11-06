'use strict';
// NEW controls, prepared for Claude first execution. Fake XHR/clock only.
// Does not execute the existing suites while importing their fixture definitions.
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const qml=fs.readFileSync(path.join(__dirname,'../qml/GcpAgentOverlay.qml'),'utf8');
const clone=x=>JSON.parse(JSON.stringify(x)); let count=0;
function test(name,fn){fn();++count;console.log('PASS '+name);}
function extract(name){const start=qml.indexOf('    function '+name+'(');assert(start>=0,name);const end=qml.indexOf('\n    function ',start+1);return qml.slice(start,end<0?qml.length:end).split('\n    Timer {')[0];}
// sm-v2: ordinary requests come from the state machine; a one-step fake session stands in for it.
function fakeMachine(){let done=null;const call={state:'S4_PICK',repair:false,messages:[{role:'system',content:'fake'},{role:'user',content:''}],schema:{type:'object'},codes:['X']};
 return {next(){return done?{type:'done',decision:done,trace:[],model_calls:1}:{type:'ask',call};},
  answer(raw){done={decision:'SELECT',choice_id:'X',steps:[{choice_id:'X'}],source:'state_machine',raw};},
  fail(reason){done={decision:'HOLD',choice_id:'',source:'rule_fallback',model_errors:[reason]};}};}
function transport(kind='ordinary',opts={}) {
 let clock=1000;const xs=[],sent=[],results=[],errors=[];
 class XHR {constructor(){this.headers={};this.aborts=0;xs.push(this);}open(m,u){this.method=m;this.url=u;}setRequestHeader(k,v){this.headers[k]=v;}send(b){sent.push(JSON.parse(b));}abort(){++this.aborts;}}
 XHR.DONE=4;
 const timer={onFire:null,interval:0,restart(){},stop(){}};
 const c={XMLHttpRequest:XHR,Date:class extends Date{static now(){return clock;}},
  backend:opts.backend||'openai',modelUrl:'http://127.0.0.1:8090/f/ui/v1',modelName:'fake',modelTimeoutMs:opts.timeout||60000,
  envValue:(_n,d)=>d,timeoutTimer:timer,themeTimeoutTimer:timer,_themeModelGeneration:0,
  open:true,modelEnabled:true,themeEditor:{visible:true,_request:{id:1},receiveModelError:(...a)=>errors.push(a)},
  cancelThemeModel(){},receiveThemeModelValue:a=>results.push(a),
  Core:{decisionSchema:()=>({type:'object'}),SYSTEM_PROMPT:'fake',buildUserMessage:()=>'',extractJson:JSON.parse,
        validateModelDecision:d=>({ok:true,...d})},qsTr:s=>s};
 c.root=c;vm.createContext(c);vm.runInContext('String.prototype.arg=function(x){return this.replace(/%[1-9]/,String(x));}',c);
 const name=kind==='repair'?'callReadableRepair':kind==='theme'?'requestThemeModel':'callMachine';
 vm.runInContext(extract(name),c);
 const request={goal:'map',candidates:[{id:'X'}],json_schema:{type:'object'},timeout_ms:20000,deadline_ms:opts.remaining===undefined?31000:opts.remaining};
 let cancel;
 if(kind==='repair') cancel=c.callReadableRepair(request,r=>results.push(clone(r)));
 else if(kind==='theme') c.requestThemeModel({id:1,group:'background',text:'blue'});
 else { const m=fakeMachine(); c.callMachine(m,m.next(),r=>results.push(clone(r))); }
 return {c,xs,sent,results,errors,timer,cancel,advance:ms=>clock+=ms,
  header(i=0){return Number(xs[i].headers['X-GCS-Deadline-Ms']);},
  respond(status,body,i=xs.length-1){const x=xs[i];x.status=status;x.responseText=typeof body==='string'?body:JSON.stringify(body);x.readyState=4;const fn=x.onreadystatechange;if(fn)fn();},
  success(i){this.respond(200,{choices:[{message:{content:JSON.stringify({steps:[{choice_id:'X'}],reason_zh:'ok'})}}]},i);}};
}
test('ordinary header caps configured 60s at remaining 32s',()=>{const t=transport();assert.equal(t.header(),32000);assert.equal(t.timer.interval,32000);});
test('ordinary caller can shorten the deadline',()=>{const t=transport('ordinary',{timeout:7500});assert.equal(t.header(),7500);assert.equal(t.timer.interval,7500);});
test('second schema call carries remaining time without resetting the clock',()=>{const t=transport();t.advance(4500);t.respond(400,'unsupported schema');assert.equal(t.sent.length,2);assert.equal(t.header(1),27500);assert.equal(t.timer.interval,32000);});
test('expired schema error never starts second call',()=>{const t=transport();t.advance(32000);t.respond(400,'schema');assert.equal(t.sent.length,1);assert.equal(t.results[0].error_code,'TIMEOUT');});
test('ordinary 504 deadline becomes timeout and cannot schema-retry',()=>{const t=transport();t.respond(504,{error:{type:'deadline',message:'expired'}});assert.equal(t.results[0].error_code,'TIMEOUT');assert.equal(t.sent.length,1);});
test('ordinary timer aborts once, late callback cannot deliver',()=>{const t=transport(),x=t.xs[0],late=x.onreadystatechange;t.timer.onFire();assert.equal(x.aborts,1);x.status=200;x.readyState=4;x.responseText='{}';late();assert.equal(t.results.length,1);assert.equal(t.results[0].error_code,'TIMEOUT');});
test('ordinary late success rejected even before local timeout event',()=>{const t=transport();t.advance(32001);t.success();assert.equal(t.results[0].error_code,'TIMEOUT');});
test('ordinary cancellation aborts once and discards old result',()=>{const t=transport(),x=t.xs[0],late=x.onreadystatechange;t.c._cancelModel();assert.equal(x.aborts,1);x.readyState=4;x.status=504;late();assert.equal(t.results.length,0);});
test('ordinary stale first XHR is ignored after retry',()=>{const t=transport(),old=t.xs[0],late=old.onreadystatechange;t.respond(400,'schema');old.status=504;late();assert.equal(t.results.length,0);t.success(1);assert.equal(t.results.length,1);});
test('native ordinary path also sends bounded header',()=>{const t=transport('ordinary',{backend:'ollama'});assert.equal(t.header(),32000);assert(t.xs[0].url.endsWith('/api/chat'));});
test('repair header is remaining session total, separately bounded 20s wait',()=>{const t=transport('repair');assert.equal(t.header(),31000);t.advance(20000);t.success();assert.equal(t.results[0].error_code,'REPAIR_TIMEOUT');});
test('repair near total cap sends actual remaining milliseconds',()=>{const t=transport('repair',{remaining:450});assert.equal(t.header(),450);t.advance(450);t.success();assert.equal(t.results[0].error_code,'REPAIR_TIMEOUT');});
test('expired repair deadline refuses network',()=>{const t=transport('repair',{remaining:0});assert.equal(t.xs.length,0);assert.equal(t.results[0].error_code,'REPAIR_TIMEOUT');});
test('repair 504 deadline is REPAIR_TIMEOUT',()=>{const t=transport('repair');t.respond(504,{error:{type:'deadline'}});assert.equal(t.results[0].error_code,'REPAIR_TIMEOUT');});
test('repair cancellation discards gateway deadline callback',()=>{const t=transport('repair'),x=t.xs[0],late=x.onreadystatechange;t.cancel();t.cancel();x.readyState=4;x.status=504;late();assert.equal(x.aborts,1);assert.equal(t.results.length,0);});
test('repair nondeadline HTTP errors remain invalid',()=>{const t=transport('repair');t.respond(400,{error:{type:'schema'}});assert.equal(t.results[0].error_code,'REPAIR_INVALID');});
test('theme first and second call share deadline header',()=>{const t=transport('theme');assert.equal(t.header(),32000);t.advance(6000);t.respond(400,'schema');assert.equal(t.header(1),26000);});
test('theme 504 leaves color unmodified',()=>{const t=transport('theme');t.respond(504,{error:{type:'deadline'}});assert.equal(t.results.length,0);assert.equal(t.errors.length,1);});
// Only the fixture prefix is evaluated: no old test() invocation executes.
const previous=fs.readFileSync(path.join(__dirname,'test_model_repair_0413.js'),'utf8');
const fixtureVM={require,__dirname,console};vm.createContext(fixtureVM);
vm.runInContext(previous.slice(0,previous.indexOf("test('one allowed repair"))+'\nthis.makeFixture=fixture;',fixtureVM);
test('Session passes finite remaining total and model budgets',()=>{const f=fixtureVM.makeFixture();f.toRequest();assert(f.calls[0].deadline_ms>0&&f.calls[0].deadline_ms<=32000);assert(f.calls[0].timeout_ms>0&&f.calls[0].timeout_ms<=20000);});
test('gateway deadline rolls back once, zero undo, late success inert',()=>{const f=fixtureVM.makeFixture();f.toRequest();const good=f.good();f.callbacks[0]({ok:false,error_code:'REPAIR_TIMEOUT',raw:'{"error":{"type":"deadline"}}'});f.failed('REPAIR_TIMEOUT');const before=JSON.stringify(f.State.snapshot()),s=JSON.stringify(f.session.state());f.reply(good);f.session.cancel();assert.equal(f.stats.rollback,1);assert.equal(f.stats.apply,1);assert.equal(JSON.stringify(f.State.snapshot()),before);assert.equal(JSON.stringify(f.session.state()),s);});
test('ordinary timeout finish never dispatches rule candidate or changes State',()=>{
 let dispatched=0;const c={clearConfirmation(){c._confirmation=null;},decisionLogged(){},qsTr:s=>s,requestExecution(){++dispatched;},
  _confirmation:{old:true},_pending:{},_candidateScope:['X'],choices:['X'],pendingText:'old',messageText:'',modelNotice:''};
 vm.createContext(c);vm.runInContext(extract('finish'),c);
 c.finish({intent:'x',rule:{decision:'SELECT',choice_id:'X'}},{ok:false,error_code:'TIMEOUT'});
 assert.equal(dispatched,0);assert.equal(c._confirmation,null);assert.equal(c._pending,null);assert.equal(c.choices.length,0);
});
console.log(JSON.stringify({new_controls:count,model_calls:0,Qt_runtime:false}));
