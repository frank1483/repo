'use strict';
// New controls only. Claude owns first execution. QML methods are evaluated with
// explicit in-memory ports; this is not real Qt, rendered-card, model or board evidence.
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const Core=require('./load_core');
const source=fs.readFileSync(path.join(__dirname,'../qml/GcpAgentOverlay.qml'),'utf8');
function extract(name){const a=source.indexOf('    function '+name+'(');assert(a>=0,name);const line=source.indexOf('\n',a);const end=source.slice(a,line).trimEnd().endsWith('}')?line:source.indexOf('\n    }',line)+6;assert(end>a,name);return source.slice(a,end).trim();}
const plain=x=>JSON.parse(JSON.stringify(x));
const nav=i=>({id:'NAV_'+i,kind:'nav',page:i,section:-1,label_zh:'Page '+i,score:1});
const plan=n=>Array.from({length:n},(_,i)=>nav(i+1));
const result=()=>({intent:'five pages',candidates:plan(6),evidence:[],rule:{decision:'SELECT'}});
const decision=n=>({decision:'SELECT',steps:plan(n).map(c=>({choice_id:c.id})),reason_zh:'ordered',evidence_ids:[]});
function setup(realExecutor=false){
 const calls=[],events=[],queue=[],loc={page:0,section:-1};
 const stats={begin:0,commit:0,rollback:0,navigation:[],failPage:-1};
 const State={revision:0,layoutFingerprint:()=> 'unchanged',snapshot:()=>({...loc}),
  beginGroup(){stats.begin++;return {snap:{...loc}};},commitGroup(){stats.commit++;},
  rollbackGroup(token){stats.rollback++;Object.assign(loc,token.snap);},beginChange(){}};
 const O={Core,JSON,Date,Array,console:{log(){}},qsTr:s=>s,GcpAgentState:State,
  busy:false,_transaction:null,_confirmation:null,_pending:null,_layoutJob:null,
  choices:[],pendingText:'',messageText:'',statusText:'',context:()=>({...loc}),
  Qt:{callLater(fn){queue.push(fn);}},layoutRetry:{stop(){}},decisionLogged:e=>events.push(plain(e)),
  done:(...args)=>calls.push({done:true,args:plain(args)}),
  shell:{agentGoTo(page,section){stats.navigation.push(page);if(page===stats.failPage)return false;loc.page=page;loc.section=section;return true;}},
  executeSteps:(steps,from)=>calls.push({steps:plain(steps),from})};
 O.root=O;vm.createContext(O);
 const names=['sameContext','clearConfirmation','requestExecution','confirmationSummary','confirmIntent'];
 if(realExecutor)names.push('executeSteps','failSteps','navigateStep','beginLayoutStep','advanceSteps');
 vm.runInContext(names.map(extract).join('\n'),O);
 vm.runInContext('String.prototype.arg=function(v){return String(this).replace(/%[1-9]/,String(v));}',O);
 function drain(){let n=0;while(queue.length){assert(++n<=30,'scheduler budget');queue.shift()();}}
 return {O,calls,events,loc,stats,drain};
}
let count=0;function test(name,fn){fn();count++;console.log('PASS '+name);}
test('five candidate IDs validate in order',()=>{const v=Core.validateModelDecision(decision(5),result());assert(v.ok);assert.deepEqual(v.steps.map(s=>s.choice_id),plan(5).map(c=>c.id));});
test('four steps validate',()=>assert(Core.validateModelDecision(decision(4),result()).ok));
test('six model steps reject whole response',()=>assert(!Core.validateModelDecision(decision(6),result()).ok));
test('unknown fifth ID rejects whole response',()=>{const d=decision(5);d.steps[4].choice_id='NOT_CATALOGUED';assert(!Core.validateModelDecision(d,result()).ok);});
test('mixed choice_id and steps reject',()=>{const d=decision(5);d.choice_id='NAV_1';assert(!Core.validateModelDecision(d,result()).ok);});
test('model cannot attach expectation to fifth step',()=>{const d=decision(5);d.steps[4].expected={page:5};assert(!Core.validateModelDecision(d,result()).ok);});
test('history cannot enter five-step model plan',()=>{const r=result(),d=decision(5);r.candidates[4]={id:'UNDO',kind:'undo'};d.steps[4]={choice_id:'UNDO'};assert(!Core.validateModelDecision(d,r).ok);});
test('single history choice remains available',()=>{const r=result();r.candidates=[{id:'UNDO',kind:'undo'}];assert(Core.validateModelDecision({decision:'SELECT',choice_id:'UNDO',reason_zh:'',evidence_ids:[]},r).ok);});
test('schema advertises five ordered steps',()=>{const s=Core.decisionSchema(result());assert.equal(s.properties.steps.maxItems,5);assert.equal(s.properties.steps.items.additionalProperties,false);});
test('five explicit rule clauses retain all actions',()=>{const r=Core.analyze('切到首頁總覽，切到即時飛行，切到任務規劃，切到告警中心，切到設備管理',{page:13,section:-1});assert.equal(r.rule.decision,'SELECT');assert.equal(r.rule.steps.length,5);});
test('six explicit clauses hold before partial dispatch',()=>{const r=Core.analyze('切到首頁總覽，切到即時飛行，切到任務規劃，切到告警中心，切到設備管理，切到飛行日誌',{page:13,section:-1});assert.equal(r.rule.decision,'HOLD');assert.equal(r.candidates.length,0);});
test('five-row card stays pending and ordered',()=>{const {O,calls}=setup();O.requestExecution(plan(5),'model',{modelSelected:true});assert.equal(calls.length,0);assert.equal(O._confirmation.steps.length,5);const s=O.confirmationSummary();assert(s.includes('④ Page 4\n⑤ Page 5'));assert(!s.includes('undefined'));});
test('four-row card is accepted',()=>{const {O}=setup();O.requestExecution(plan(4),'rule',{});assert.equal(O._confirmation.steps.length,4);});
test('six-row request creates no card',()=>{const {O,calls}=setup();O.requestExecution(plan(6),'model',{modelSelected:true});assert.equal(O._confirmation,null);assert.equal(calls.length,0);});
test('five-step card detaches from mutable proposal',()=>{const {O}=setup(),p=plan(5);O.requestExecution(p,'model',{modelSelected:true});p[4].page=13;p[4].label_zh='mutated';assert.equal(O._confirmation.steps[4].page,5);assert(O.confirmationSummary().includes('⑤ Page 5'));});
test('confirmation dispatches all five once',()=>{const {O,calls}=setup();O.requestExecution(plan(5),'model',{modelSelected:true});O.confirmIntent();O.confirmIntent();assert.equal(calls.length,1);assert.deepEqual(calls[0].steps.map(c=>c.page),[1,2,3,4,5]);});
test('stale five-step card dispatches nothing',()=>{const {O,calls}=setup();O.requestExecution(plan(5),'model',{modelSelected:true});O.GcpAgentState.revision++;O.confirmIntent();assert.equal(calls.length,0);assert.equal(O._confirmation,null);});
test('multi-step saved-layout request rejects before card',()=>{const {O,calls}=setup(),p=plan(5);p[4]={id:'LOAD',kind:'layout_load',name:'saved'};O.requestExecution(p,'model',{modelSelected:true});assert.equal(O._confirmation,null);assert.equal(calls.length,0);});
test('direct six-step dispatch never opens transaction',()=>{const {O,stats}=setup(true);O.executeSteps(plan(6),'bypass');assert.equal(stats.begin,0);});
test('direct mixed saved-layout plan never opens transaction',()=>{const {O,stats}=setup(true),p=plan(5);p[4]={id:'LOAD',kind:'layout_load',name:'saved'};O.executeSteps(p,'bypass');assert.equal(stats.begin,0);});
test('confirmed five-navigation plan commits one transaction',()=>{const {O,stats,loc,drain}=setup(true);O.requestExecution(plan(5),'model',{modelSelected:true});assert.equal(stats.begin,0);O.confirmIntent();drain();assert.deepEqual(stats.navigation,[1,2,3,4,5]);assert.equal(stats.begin,1);assert.equal(stats.commit,1);assert.equal(stats.rollback,0);assert.equal(loc.page,5);assert.equal(O.busy,false);});
test('failed fifth navigation restores all earlier pages',()=>{const {O,stats,loc,drain}=setup(true);stats.failPage=5;O.requestExecution(plan(5),'model',{modelSelected:true});O.confirmIntent();drain();assert.deepEqual(stats.navigation,[1,2,3,4,5]);assert.equal(stats.commit,0);assert.equal(stats.rollback,1);assert.equal(loc.page,0);assert.equal(O._transaction,null);assert.equal(O.busy,false);});
console.log('five-step v6: '+count+' cases PASS');
