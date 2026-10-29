'use strict';
// First functional run belongs to Claude. Production QML functions; dispatch is a spy.
// No HTTP, model, Qt, Settings, flight commands, or preserved research scripts.
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const Core=require('./load_core');
const source=fs.readFileSync(path.join(__dirname,'../qml/GcpAgentOverlay.qml'),'utf8');
function extract(name){const a=source.indexOf('    function '+name+'(');assert(a>=0,name);const line=source.indexOf('\n',a);const end=source.slice(a,line).trimEnd().endsWith('}')?line:source.indexOf('\n    }',line)+6;assert(end>a);return source.slice(a,end).trim();}
const plain=x=>JSON.parse(JSON.stringify(x));
const nav=()=>({id:'NAV_1',kind:'nav',page:1,section:-1,label_zh:'切到即時飛行',score:1});
const layout=()=>({id:'LAYOUT_WIND',kind:'layout',module:'wind',region:'top_left',label_zh:'風速計移到左上角',score:1});
function setup(){
    const calls=[],events=[],loc={page:0,section:-1};let focus=0;
    const O={Core,GcpAgentState:{revision:0},JSON,Date,Array,console:{log(){}},
        qsTr:s=>s,busy:false,_transaction:null,_confirmation:null,_pending:null,_choiceGuard:null,
        pendingText:'',choices:[],messageText:'',statusText:'',_modelGeneration:0,_cancelModel:null,
        backend:'none',modelName:'',modelEnabled:false,modelAlways:false,_t0:Date.now(),
        input:{forceActiveFocus(){focus++;}},context:()=>({...loc}),
        executeSteps:(steps,from)=>calls.push({steps:plain(steps),from}),decisionLogged:e=>events.push(plain(e))};
    O.root=O;vm.createContext(O);
    vm.runInContext(['sameContext','clearConfirmation','requestExecution','confirmationSummary','confirmIntent',
        'rejectIntent','cancelWaiting','submit','choose','finish'].map(extract).join('\n'),O);
    vm.runInContext('String.prototype.arg=function(v){return String(this).replace(/%[1-9]/,String(v));}',O);
    return {O,calls,events,loc,focus:()=>focus};
}
function result(c=layout()){return {intent:'把風速計移到左上角',candidates:[c],rule:{decision:'SELECT',choice_id:c.id,reason_zh:'明確'}};}
const model=c=>({ok:true,decision:'SELECT',choice_id:c.id,reason_zh:'fake selection'});
let count=0;
function test(name,run){run();count++;console.log('PASS '+name);}
test('one rule navigation dispatches directly',()=>{const {O,calls}=setup();O.requestExecution([nav()],'rule',{});assert.equal(calls.length,1);assert.equal(O._confirmation,null);});
test('model navigation waits for Yes',()=>{const {O,calls}=setup();O.requestExecution([nav()],'model',{modelSelected:true});assert.equal(calls.length,0);assert(O._confirmation);O.confirmIntent();assert.equal(calls.length,1);});
test('unique confident rule layout dispatches directly',()=>{const {O,calls}=setup();O.finish(result(),null);assert.equal(calls.length,1);assert.equal(O._confirmation,null);});
test('two strong layout alternatives require a card',()=>{const {O,calls}=setup(),r=result();r.candidates.push({...layout(),id:'OTHER',score:.8});O.finish(r,null);assert.equal(calls.length,0);assert(O._confirmation);});
test('weak alternative does not invalidate one confident choice',()=>{const {O,calls}=setup(),r=result();r.candidates.push({...layout(),id:'OTHER',score:.2});O.finish(r,null);assert.equal(calls.length,1);});
test('unique text-scale rule remains direct',()=>{const {O,calls}=setup();O.finish(result({id:'TEXT_SCALE',kind:'text_scale',value:1.15,label_zh:'放大文字',score:1}),null);assert.equal(calls.length,1);});
test('model layout waits without changing the screen',()=>{const {O,calls,loc}=setup();O.finish(result(),model(layout()));assert.equal(calls.length,0);assert.equal(loc.page,0);assert(O._confirmation);});
test('two rule steps wait including navigation-only plans',()=>{const {O,calls}=setup(),a=nav(),b={...nav(),id:'NAV_2',page:2};O.finish({intent:'去即時飛行再去設備',compound:true,candidates:[a,b],rule:{decision:'SELECT',steps:[{choice_id:a.id},{choice_id:b.id}]}},null);assert.equal(calls.length,0);O.confirmIntent();assert.equal(calls[0].steps.length,2);});
test('model multi-step plan waits then keeps order',()=>{const {O,calls}=setup(),a=nav(),b=layout(),r=result();r.candidates=[a,b];O.finish(r,{ok:true,decision:'SELECT',steps:[{choice_id:a.id},{choice_id:b.id}]});assert.equal(calls.length,0);O.confirmIntent();assert.deepEqual(calls[0].steps.map(c=>c.id),[a.id,b.id]);});
test('goal marker requires confirmation even for navigation',()=>{const {O,calls}=setup();const r=result(nav());r.goal_intent=true;O.finish(r,null);assert.equal(calls.length,0);assert(O._confirmation);});
test('goal marker requires confirmation for unique layout',()=>{const {O,calls}=setup();const r=result();r.goal_intent=true;O.finish(r,null);assert.equal(calls.length,0);});
test('explicit human clarification choice remains direct',()=>{const {O,calls}=setup();O._choiceGuard={revision:0,page:0,section:-1};O._pending=result();O.choose(layout());assert.equal(calls.length,1);});
test('human goal choice still requires the goal confirmation',()=>{const {O,calls}=setup();O._choiceGuard={revision:0,page:0,section:-1};O._pending={...result(),goal_intent:true};O.choose(layout());assert.equal(calls.length,0);assert(O._confirmation);});
test('stale revision blocks Yes and consumes the pending card',()=>{const {O,calls}=setup();O.requestExecution([layout()],'model',{modelSelected:true});O.GcpAgentState.revision++;O.confirmIntent();assert.equal(calls.length,0);assert.equal(O._confirmation,null);assert(O.messageText.includes('畫面已改變'));});
test('manual page change blocks Yes',()=>{const {O,calls,loc}=setup();O.requestExecution([nav()],'model',{modelSelected:true});loc.page=2;O.confirmIntent();assert.equal(calls.length,0);});
test('manual section change blocks Yes',()=>{const {O,calls,loc}=setup();O.requestExecution([nav()],'model',{modelSelected:true});loc.section=2;O.confirmIntent();assert.equal(calls.length,0);});
test('double Yes dispatches once',()=>{const {O,calls}=setup();O.requestExecution([layout()],'model',{modelSelected:true});O.confirmIntent();O.confirmIntent();assert.equal(calls.length,1);});
test('No clears all continuation state and focuses correction input',()=>{const {O,calls,focus}=setup();O.requestExecution([layout()],'model',{modelSelected:true});O.pendingText='old';O._pending=result();O.rejectIntent();assert.equal(calls.length,0);assert.equal(O._confirmation,null);assert.equal(O._pending,null);assert.equal(O.pendingText,'');assert.equal(focus(),1);});
test('card plan is detached from mutable candidates',()=>{const {O,calls}=setup(),c=layout();O.requestExecution([c],'model',{modelSelected:true});c.module='different';c.label_zh='changed';O.confirmIntent();assert.equal(calls[0].steps[0].module,'wind');assert.notEqual(calls[0].steps[0].label_zh,'changed');});
test('cancel clears card and cannot later dispatch',()=>{const {O,calls}=setup();let aborted=0;O.requestExecution([layout()],'model',{modelSelected:true});O._cancelModel=()=>{aborted++;};O.cancelWaiting();O.confirmIntent();assert.equal(calls.length,0);assert.equal(aborted,1);assert.equal(O._confirmation,null);});
test('unsupported flight action is rejected before card or dispatch',()=>{const {O,calls}=setup();O.requestExecution([{id:'ARM',kind:'flight',label_zh:'解鎖'}],'model',{modelSelected:true});assert.equal(calls.length,0);assert.equal(O._confirmation,null);});
test('missing action is rejected',()=>{const {O,calls}=setup();O.requestExecution([null],'model',{modelSelected:true});assert.equal(calls.length,0);assert.equal(O._confirmation,null);});
test('current executor three-step bound is preserved',()=>{const {O,calls}=setup();O.requestExecution([nav(),nav(),nav(),nav()],'model',{modelSelected:true});assert.equal(calls.length,0);assert.equal(O._confirmation,null);});
test('Yes cannot dispatch while already busy',()=>{const {O,calls}=setup();O.requestExecution([nav()],'model',{modelSelected:true});O.busy=true;O.confirmIntent();assert.equal(calls.length,0);assert(O._confirmation);});
test('request cannot replace an active transaction',()=>{const {O,calls}=setup();O._transaction={};O.requestExecution([nav()],'model',{modelSelected:true});assert.equal(calls.length,0);assert.equal(O._confirmation,null);});
test('summary is numbered in execution order',()=>{const {O}=setup();O.requestExecution([nav(),layout()],'rule',{});assert(O.confirmationSummary().includes('① 切到即時飛行\n② 風速計移到左上角'));});
test('failed model uses direct confident rule fallback',()=>{const {O,calls}=setup();O.finish(result(),{ok:false,error:'timeout'});assert.equal(calls.length,1);assert.equal(O._confirmation,null);});
test('generic settings stay clarification even with valid fake model',()=>{const {O,calls}=setup(),r=result(nav());r.generic_settings=true;r.rule={decision:'CLARIFY',reason_zh:'設定目標待確認'};O.finish(r,model(nav()));assert.equal(calls.length,0);assert.equal(O._confirmation,null);assert.equal(O.choices.length,1);});
test('unknown model candidate never reaches execution or card',()=>{const {O,calls}=setup();O.finish(result(),{ok:true,decision:'SELECT',choice_id:'UNKNOWN'});assert.equal(calls.length,0);assert.equal(O._confirmation,null);});
test('fresh utterance discards old card before analysis',()=>{const {O,calls}=setup();O.requestExecution([layout()],'model',{modelSelected:true});let observed=false;O.finish=()=>{observed=true;assert.equal(O._confirmation,null);};O.submit('去告警中心');assert(observed);assert.equal(calls.length,0);});
test('events distinguish pending confirmation from accepted execution',()=>{const {O,events,calls}=setup();O.requestExecution([nav()],'model',{modelSelected:true,intent:'看畫面'});assert.equal(events[0].phase,'confirmation_required');assert.equal(events[0].executed,false);assert.equal(calls.length,0);O.confirmIntent();assert.equal(events[1].phase,'confirmation_accepted');assert.equal(calls.length,1);});
console.log('confirmation v6: '+count+' cases PASS');
