'use strict';
// First functional execution belongs to Claude. Actual QML functions, fake XHR/manual timer.
// No network, model, Qt or previously passed research runner.
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const Core=require('./load_core'),SM=require('./load_sm');
const source=fs.readFileSync(path.join(__dirname,'../qml/GcpAgentOverlay.qml'),'utf8');
function extract(name){const a=source.indexOf('    function '+name+'(');assert(a>=0,name);const line=source.indexOf('\n',a);const end=source.slice(a,line).trimEnd().endsWith('}')?line:source.indexOf('\n    }',line)+6;assert(end>a);return source.slice(a,end).trim();}
const plain=x=>JSON.parse(JSON.stringify(x));
const nav={id:'NAV_1',kind:'nav',page:1,section:-1,label_zh:'切到即時飛行',score:1};
function result(decision='SELECT'){return {intent:'去即時飛行',evidence:[],candidates:[{...nav}],rule:{decision,choice_id:decision==='SELECT'?nav.id:'',reason_zh:'rule'}};}
function setup(options={}){
    const env={...options.env},requests=[],done=[],events=[],dispatch=[];
    let timerStarts=0;
    const timer={interval:0,onFire:null,restart(){timerStarts++;},stop(){}};
    class FakeXHR{
        constructor(){this.readyState=0;this.status=0;this.responseText='';this.headers={};this.aborted=0;requests.push(this);}
        open(method,url){this.method=method;this.url=url;this.readyState=1;if(options.throwOpen)throw Error('fake open');}
        setRequestHeader(k,v){this.headers[k]=v;}
        send(body){this.body=JSON.parse(body);if(options.throwSend)throw Error('fake send');}
        respond(status,body){this.status=status;this.responseText=typeof body==='string'?body:JSON.stringify(body);this.readyState=4;if(this.onreadystatechange)this.onreadystatechange();}
        abort(){this.aborted++;this.respond(0,'');}
    }
    FakeXHR.DONE=4;
    const O={Core,Machine:SM,JSON,Date,Array,console:{log(){}},qsTr:s=>s,XMLHttpRequest:FakeXHR,
        agentSettings:{llmTimeoutMs:options.saved||0},envValue:(k,d)=>Object.hasOwn(env,k)?env[k]:d,
        timeoutTimer:timer,_cancelModel:null,backend:options.backend||'ollama',modelUrl:'http://fake.invalid:11434/',
        modelName:'qwen2.5:3b',busy:false,modelNotice:'',messageText:'',pendingText:'',_t0:Date.now(),
        _transaction:null,_confirmation:null,_modelGeneration:0,choices:[],GcpAgentState:{revision:0},
        context:()=>({page:0,section:-1}),
        requestExecution:(steps,from,policy)=>dispatch.push({steps:plain(steps),from,policy:plain(policy)}),
        decisionLogged:e=>events.push(plain(e)),failSteps(){throw Error('unexpected transaction');}};
    O.root=O;vm.createContext(O);
    O._candidateScope=[]; O.recordChange=function(){};
    vm.runInContext(['recordGate','checkSelection','checkSteps','resolvedModelTimeoutMs','setModelTimeout','callMachine','machineModel','finish','clearConfirmation','cancelWaiting'].map(extract).join('\n'),O);
    vm.runInContext('String.prototype.arg=function(v){return String(this).replace(/%[1-9]/,String(v));}',O);
    Object.defineProperty(O,'modelTimeoutMs',{get:()=>O.resolvedModelTimeoutMs()});
    // sm-v2: ordinary requests come from a real state-machine session (this sentence reaches S2_CLASSIFY).
    function start(){const m=SM.create(Core).start('幫我講個笑話',{page:0,section:-1},'');O.callMachine(m,m.next(),v=>done.push(plain(v)));return requests[requests.length-1];}
    function reply(req,value){req.respond(200,O.backend==='ollama'?{message:{content:JSON.stringify(value)}}:{choices:[{message:{content:JSON.stringify(value)}}]});}
    function select(v='OUT_OF_SCOPE'){return {value:v};}
    return {O,env,requests,done,events,dispatch,timer,start,reply,select,timerStarts:()=>timerStarts};
}
let count=0;
function test(name,fn){fn();count++;console.log('PASS '+name);}
test('unconfigured timeout is32seconds',()=>{const {O}=setup();assert.equal(O.modelTimeoutMs,32000);});
test('environment timeout is inherited below limit',()=>{const {O}=setup({env:{GCS_LLM_TIMEOUT_MS:'19000'}});assert.equal(O.modelTimeoutMs,19000);});
test('panel timeout overrides environment',()=>{const {O}=setup({saved:25000,env:{GCS_LLM_TIMEOUT_MS:'31000'}});assert.equal(O.modelTimeoutMs,25000);});
test('invalid environment values use default',()=>{for(const value of ['','abc','0','-1','Infinity','NaN']){const {O}=setup({env:{GCS_LLM_TIMEOUT_MS:value}});assert.equal(O.modelTimeoutMs,32000,value);}});
test('environment bounds clamp and truncate',()=>{for(const [value,expected] of [['0.4',1],['31999.9',31999],['32000',32000],['60000.9',32000],['999999',32000]]){const {O}=setup({env:{GCS_LLM_TIMEOUT_MS:value}});assert.equal(O.modelTimeoutMs,expected);}});
test('invalid persisted timeout inherits environment',()=>{const {O}=setup({saved:-1,env:{GCS_LLM_TIMEOUT_MS:'70000'}});assert.equal(O.modelTimeoutMs,32000);});
test('panel whole milliseconds persist',()=>{const {O}=setup();assert(O.setModelTimeout(' 27500 '));assert.equal(O.agentSettings.llmTimeoutMs,27500);assert.equal(O.modelTimeoutMs,27500);});
test('empty panel restores environment inheritance',()=>{const {O}=setup({saved:25000,env:{GCS_LLM_TIMEOUT_MS:'80000'}});assert(O.setModelTimeout('  '));assert.equal(O.agentSettings.llmTimeoutMs,0);assert.equal(O.modelTimeoutMs,32000);});
test('invalid panel edits preserve prior setting',()=>{for(const value of ['0','-1','32001','120000','120001','abc','NaN','Infinity','1.2','1e3']){const {O}=setup({saved:25000});assert.equal(O.setModelTimeout(value),false,value);assert.equal(O.agentSettings.llmTimeoutMs,25000);}});
test('panel boundary values accepted',()=>{const {O}=setup();assert(O.setModelTimeout('1'));assert.equal(O.modelTimeoutMs,1);assert(O.setModelTimeout('32000'));assert.equal(O.modelTimeoutMs,32000);});
test('busy panel cannot change or clear timeout',()=>{const {O}=setup({saved:25000});O.busy=true;assert.equal(O.setModelTimeout('30000'),false);assert.equal(O.setModelTimeout(''),false);assert.equal(O.agentSettings.llmTimeoutMs,25000);});
test('Ollama sends one-slot enum schema and existing model',()=>{const h=setup(),req=h.start();assert.equal(req.method,'POST');assert.equal(req.url,'http://fake.invalid:11434/api/chat');assert.equal(req.body.model,'qwen2.5:3b');assert.deepEqual(req.body.format.required,['value']);assert.deepEqual(req.body.format.properties.value.enum,SM.KINDS.map(k=>k.code));assert.equal(req.body.stream,false);assert.equal(req.body.options.temperature,0);assert.equal(h.timer.interval,32000);});
test('Ollama ignores OpenAI schema-off switch',()=>{const h=setup({env:{GCS_LLM_SCHEMA:'0'}}),req=h.start();assert.equal(typeof req.body.format,'object');assert(req.body.format.properties.value.enum.includes('NAV'));});
test('Ollama HTTP400 has no schema retry, one repair then rule',()=>{const h=setup(),req=h.start();req.respond(400,'bad schema');assert.equal(h.requests.length,2);assert.equal(h.requests[1].body.messages[1].content.includes('上次錯誤：模型未回覆：HTTP 400'),true);h.requests[1].respond(400,'bad');assert.equal(h.requests.length,2);assert.equal(h.done.length,1);assert.equal(h.done[0].decision.source,'rule_fallback');assert.deepEqual(h.done[0].decision.model_errors,['模型未回覆：HTTP 400','模型未回覆：HTTP 400']);});
test('fake Ollama slot passes actual validator',()=>{const h=setup(),req=h.start();h.reply(req,h.select());assert.equal(h.done.length,1);assert.equal(h.done[0].decision.source,'state_machine');assert.equal(h.done[0].decision.decision,'HOLD');assert.equal(h.done[0].request_model,'qwen2.5:3b');assert.equal(h.done[0].timeout_ms,32000);assert.equal(h.O._cancelModel,null);assert.equal(h.timer.onFire,null);});
test('fake hallucinated code rejected, repaired once',()=>{const h=setup(),req=h.start();h.reply(req,h.select('FLY_NOW'));assert.equal(h.done.length,0);assert.equal(h.requests.length,2);h.reply(h.requests[1],h.select('FLY_NOW'));assert.equal(h.done[0].decision.source,'rule_fallback');assert.equal(h.requests.length,2);});
test('fake extra field rejected',()=>{const h=setup(),req=h.start(),v=h.select();v.evidence_ids=['invented'];h.reply(req,v);assert.equal(h.done.length,0);assert(h.requests[1].body.messages[1].content.includes('只能有 value 一個欄位'));});
test('malformed envelope counts as one failed answer',()=>{const h=setup(),req=h.start();req.respond(200,{});assert.equal(h.done.length,0);h.requests[1].respond(200,{});assert.equal(h.done.length,1);assert.equal(h.done[0].decision.source,'rule_fallback');});
test('timeout completes once aborts and ignores late success',()=>{const h=setup(),req=h.start(),fire=h.timer.onFire;fire();fire();h.reply(req,h.select());assert.equal(h.done.length,1);assert.equal(h.done[0].error_code,'TIMEOUT');assert(h.done[0].error.includes('32'));assert.equal(req.aborted,1);assert.equal(h.O._cancelModel,null);assert.equal(h.timer.onFire,null);});
test('configured deadline frozen in flight',()=>{const h=setup({saved:25000}),req=h.start();h.O.agentSettings.llmTimeoutMs=1000;assert.equal(h.timer.interval,25000);h.timer.onFire();assert.equal(h.done[0].timeout_ms,25000);assert(h.done[0].error.includes('25'));assert.equal(req.aborted,1);});
test('cancel produces no dispatch or done',()=>{const h=setup(),req=h.start(),cancel=h.O._cancelModel;cancel();cancel();h.reply(req,h.select());assert.equal(h.done.length,0);assert.equal(h.dispatch.length,0);assert.equal(req.aborted,1);assert.equal(h.timer.onFire,null);});
test('OpenAI retries once inside same deadline',()=>{const h=setup({backend:'openai'}),req=h.start();assert.equal(req.body.response_format.type,'json_schema');req.respond(400,'unsupported');assert.equal(h.requests.length,2);assert.equal(h.requests[1].body.response_format.type,'json_object');assert.equal(h.timerStarts(),1);h.requests[1].respond(400,'bad');assert.equal(h.requests.length,3);assert.equal(h.requests[2].body.response_format.type,'json_object');h.requests[2].respond(400,'bad');assert.equal(h.done.length,1);assert.equal(h.requests.length,3);});
test('OpenAI retry freezes endpoint model and key',()=>{const h=setup({backend:'openai',env:{GCS_LLM_API_KEY:'fake-key'}}),req=h.start();h.O.modelUrl='http://changed.invalid';h.O.modelName='other';h.env.GCS_LLM_API_KEY='changed';req.respond(400,'unsupported');const retry=h.requests[1];assert.equal(retry.url,'http://fake.invalid:11434/chat/completions');assert.equal(retry.body.model,'qwen2.5:3b');assert.equal(retry.headers.Authorization,'Bearer fake-key');});
test('OpenAI stale first attempt ignored',()=>{const h=setup({backend:'openai'}),req=h.start();req.respond(400,'unsupported');h.reply(req,h.select());assert.equal(h.done.length,0);h.reply(h.requests[1],h.select());assert.equal(h.done.length,1);assert.equal(h.done[0].schema_fallback,true);assert.equal(h.done[0].calls.length,1);});
test('OpenAI retry timeout aborts current attempt',()=>{const h=setup({backend:'openai'}),req=h.start();req.respond(400,'unsupported');h.timer.onFire();assert.equal(h.requests[1].aborted,1);assert.equal(h.done[0].error_code,'TIMEOUT');assert.equal(h.timerStarts(),1);});
test('OpenAI schema-off stays json_object without schema retry',()=>{const h=setup({backend:'openai',env:{GCS_LLM_SCHEMA:'0'}}),req=h.start();assert.equal(req.body.response_format.type,'json_object');req.respond(400,'bad');assert.equal(h.requests.length,2);assert.equal(h.requests[1].body.response_format.type,'json_object');h.requests[1].respond(400,'bad');assert.equal(h.done.length,1);});
test('transport open failure ends and aborts',()=>{const h=setup({throwOpen:true}),req=h.start();assert.equal(h.done.length,1);assert.equal(h.done[0].decision.source,'rule_fallback');assert.equal(h.requests.length,2);assert.equal(h.requests[0].aborted,1);assert.equal(req.aborted,1);assert.equal(h.timer.onFire,null);});
test('transport send failure ends and aborts',()=>{const h=setup({throwSend:true}),req=h.start();assert.equal(h.done.length,1);assert.equal(h.done[0].decision.source,'rule_fallback');assert.equal(req.aborted,1);});
test('rule SELECT retains separate fallback explanation',()=>{const h=setup();h.O.finish(result(),{ok:false,error:'等待超過60秒'});assert.equal(h.dispatch.length,1);assert(h.O.modelNotice.includes('已改用規則'));h.O.messageText='action replaced this';assert(h.O.modelNotice.includes('60'));assert.equal(h.dispatch[0].policy.modelSelected,false);});
test('generic settings fallback remains clarification',()=>{const h=setup(),r=result('CLARIFY');r.generic_settings=true;h.O.finish(r,{ok:false,error:'timeout'});assert.equal(h.dispatch.length,0);assert.equal(h.O.choices.length,1);assert(h.O.modelNotice.includes('已改用規則'));});
test('HOLD fallback cannot execute',()=>{const h=setup();h.O.finish(result('HOLD'),{ok:false,error:'timeout'});assert.equal(h.dispatch.length,0);assert(h.O.modelNotice.includes('已改用規則'));});
test('model success clears previous fallback notice',()=>{const h=setup();h.O.modelNotice='old';h.O.finish(result(),h.O.machineModel(result(),{decision:{decision:'SELECT',choice_id:nav.id,steps:[{choice_id:nav.id}],reason_zh:'fake',candidates:[{...nav}],source:'state_machine'},model_calls:1}));assert.equal(h.O.modelNotice,'');assert.equal(h.dispatch[0].policy.modelSelected,true);});
test('method-built candidate joins scope and passes both gates',()=>{const h=setup(),r=result('HOLD');r.candidates=[];const c={id:'NAV_2',kind:'nav',page:2,section:-1,label_zh:'切到任務規劃',score:0};h.O.finish(r,h.O.machineModel(r,{decision:{decision:'SELECT',choice_id:'NAV_2',steps:[{choice_id:'NAV_2'}],candidates:[c],source:'state_machine'},model_calls:2}));assert.equal(h.dispatch.length,1);assert.equal(h.dispatch[0].steps[0].id,'NAV_2');assert.equal(h.dispatch[0].policy.modelSelected,true);});
test('rule fallback from machine keeps rule path and notice',()=>{const h=setup();h.O.finish(result(),h.O.machineModel(result(),{decision:{decision:'SELECT',choice_id:nav.id,source:'rule_fallback',model_errors:['回覆不是 JSON 物件']},model_calls:2}));assert.equal(h.dispatch.length,1);assert.equal(h.dispatch[0].policy.modelSelected,false);assert(h.O.modelNotice.includes('回覆不是 JSON 物件'));});
test('machine timeout never dispatches',()=>{const h=setup();h.O.finish(result(),h.O.machineModel(result(),{ok:false,error_code:'TIMEOUT',error:'deadline'}));assert.equal(h.dispatch.length,0);assert(h.O.modelNotice.includes('逾時'));});
test('cancel clears fallback notice',()=>{const h=setup();h.O.modelNotice='old';h.O.cancelWaiting();assert.equal(h.O.modelNotice,'');});
test('old persisted settings clamp without rewriting storage',()=>{for(const saved of [45000,120000,999999]){const {O}=setup({saved});assert.equal(O.modelTimeoutMs,32000);assert.equal(O.agentSettings.llmTimeoutMs,saved);}});
test('environment above limit clamps to32seconds',()=>{const {O}=setup({env:{GCS_LLM_TIMEOUT_MS:'91000'}});assert.equal(O.modelTimeoutMs,32000);});
console.log('model settings v6 (sm-v2 transport): '+count+' cases PASS (fake transport only)');
