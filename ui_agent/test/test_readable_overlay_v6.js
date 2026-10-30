'use strict';
// New controls only. Claude owns first functional execution. No API/model/device.
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const R=path.resolve(__dirname,'..'),clone=x=>JSON.parse(JSON.stringify(x));
function load(name){const c={};vm.createContext(c);vm.runInContext(fs.readFileSync(path.join(R,'qml',name),'utf8').replace(/^\.pragma[^\n]*\n/,''),c);return c;}
const Core=load('GcpAgentCore.js'),Host=load('GcpAgentHost.js'),Catalog=load('GcpAgentCatalog.js'),Loop=load('GcpAgentLoop.js');
const Snapshot=load('GcpAgentSnapshot.js'),Verifier=load('GcpAgentVerifier.js'),Session=load('GcpAgentReadableSession.js');
const source=fs.readFileSync(path.join(R,'qml/GcpAgentOverlay.qml'),'utf8');
function extract(name){const a=source.indexOf('    function '+name+'(');assert(a>=0,name);const first=source.indexOf('\n',a);const b=source.slice(a,first).trimEnd().endsWith('}')?first:source.indexOf('\n    }',first)+6;assert(b>a);return source.slice(a,b).trim();}
function fixture(){
 const viewport={width:800,height:600,z:0,visible:true,opacity:1,children:[],parent:null};
 const container={x:10,y:15,width:760,height:560,z:0,visible:true,opacity:1,children:[],parent:viewport,
  mapToItem(to,x,y){assert.strictEqual(to,viewport);return {x:this.x+x,y:this.y+y};}};
 const ov={dx:20,dy:10,scale:1,hidden:false};
 const mini={x:100,y:100,width:200,height:120,z:0,visible:true,opacity:1,children:[],parent:container,
  mapToItem(to,x,y){const p={x:this.x+ov.dx+x*ov.scale,y:this.y+ov.dy+y*ov.scale};if(to===container)return p;assert.strictEqual(to,viewport);return {x:container.x+p.x,y:container.y+p.y};}};
 const other={x:500,y:350,width:200,height:200,z:1,visible:true,opacity:1,children:[],parent:viewport};
 const wind={x:5,y:5,width:40,height:40,z:1,visible:true,opacity:1,children:[],parent:other,
  mapToItem(to,x,y){assert.strictEqual(to,viewport);return {x:other.x+this.x+x,y:other.y+this.y+y};}};
 viewport.children=[container,other];container.children=[mini];other.children=[wind];
 const registry={miniView:{item:mini,container},windGauge:{item:wind,container:other}},loc={page:1,section:-1};
 let clock=0,queue=[],backendCalls=0;const events=[],stats={begin:0,commit:0,rollback:0,apply:0,capture:0},finished=[];
 const State={revision:4,_groupActive:false,_activeGroupCheckpoint:null,
  readableHostInput(v,g,c){stats.capture++;return Host.captureReadable(v,registry,Core.MODULES,loc,id=>id==='miniView'?clone(ov):{dx:0,dy:0,scale:1,hidden:false},this.revision,g,c,Snapshot);},
  snapshot(){return {ov:clone(ov),loc:clone(loc)};},
  beginGroup(){if(this._groupActive)throw Error('nested');stats.begin++;const token={snap:this.snapshot()};this._groupActive=true;this._activeGroupCheckpoint=token;return token;},
  commitGroup(t){assert.strictEqual(t,this._activeGroupCheckpoint);if(stats.commitThrows)throw Error('commit injected');stats.commit++;this._groupActive=false;this._activeGroupCheckpoint=null;this.revision++;},
  rollbackGroup(t){assert.strictEqual(t,this._activeGroupCheckpoint);if(stats.rollbackThrows)throw Error('rollback injected');stats.rollback++;this._restore(t.snap);this._groupActive=false;this._activeGroupCheckpoint=null;},
  _restore(s){Object.assign(ov,s.ov);Object.assign(loc,s.loc);this.revision++;},
  setOverride(id,next){assert.equal(id,'miniView');assert(this._groupActive);stats.apply++;Object.assign(ov,next);this.revision++;}};
 const tick={onFire:null,interval:0,restart(){queue=[{fn:this.onFire,delay:this.interval}];},stop(){queue=[];}};
 const O={Core,ReadableHost:Host,ReadableCatalog:Catalog,ReadableLoop:Loop,ReadableVerifier:Verifier,ReadableSession:Session,
  GcpAgentState:State,JSON,Array,Date:{now:()=>clock},qsTr:s=>s,readableTick:tick,
  readableViewport:viewport,readableGoalPolicy:{kind:'readable',minWidth:160,minHeight:80,allowMove:true,allowShrink:false,allowNavigate:false},
  busy:false,_transaction:null,_readableSession:null,_destroying:false,_confirmation:null,_pending:null,_choiceGuard:null,
  pendingText:'',choices:[],messageText:'',statusText:'',modelNotice:'',_cancelModel:null,_modelGeneration:0,
  context:()=>({...loc,modules:{miniView:{registered:true,visible:true}}}),
  executeSteps(){throw Error('legacy execution forbidden');},finish(){throw Error('goal escaped to ordinary model path');},
  decisionLogged:e=>events.push(clone(e)),done(){finished.push('complete');O.open=false;},input:{forceActiveFocus(){}},
  callModel(){backendCalls++;throw Error('backend forbidden');}};
 O.root=O;vm.createContext(O);
 vm.runInContext(['captureReadable','requestReadableConfirmation','requestExecution','startReadable','clearConfirmation','sameContext','confirmationSummary',
  'confirmIntent','submit','cancelWaiting','rejectIntent'].map(extract).join('\n'),O);
 vm.runInContext('String.prototype.arg=function(v){return String(this).replace(/%[1-9]/,String(v));}',O);
 function step(){assert(queue.length,'no pending poll');const q=queue.shift();clock+=q.delay;tick.onFire=null;q.fn();}
 function drain(){let i=0;while(queue.length){assert(++i<200,'poll budget');step();}}
 return {O,State,ov,viewport,container,mini,other,loc,stats,events,finished,step,drain,advance(ms){clock+=ms;},
  queued:()=>queue.length,backend:()=>backendCalls,card(){O.submit('讓小地圖看得清楚一點');}};
}
let count=0;function test(name,work){work();count++;console.log('PASS '+name);}
test('actual confirmation binding contains host minimum and every permission',()=>{const f=fixture();f.card();assert(f.O._confirmation.readable);const s=f.O.confirmationSummary();for(const t of ['160','80','移動允許','降尺寸不允許','回所在畫面不允許','尚未接模型修補'])assert(s.includes(t),t);assert(source.includes('text: root.confirmationSummary()'));assert.equal(f.stats.apply,0);assert.equal(f.backend(),0);});
test('submit intercepts goal before model analysis',()=>{const f=fixture();f.card();assert.equal(f.backend(),0);assert.equal(f.stats.begin,0);});
test('reserved goal candidate cannot bypass the specialized confirmation gate',()=>{const f=fixture();const candidates=clone(Loop.goalTemplate('讓小地圖看得清楚一點',f.O.context()).candidates);f.O.requestExecution(candidates,'model',{goal:true,intent:'readable'});assert(f.O._confirmation.readable);assert.equal(f.stats.begin,0);f.O.requestExecution(candidates.concat(candidates),'model',{});assert.equal(f.O._confirmation,null);assert.equal(f.stats.apply,0);});
test('main map ambiguity asks clarification without host action',()=>{const f=fixture();f.O.submit('讓地圖看得清楚一點');assert.equal(f.O._confirmation,null);assert(f.O.messageText.includes('主地圖'));assert.equal(f.stats.capture,0);});
test('missing trusted policy refuses without fallback',()=>{const f=fixture();f.O.readableGoalPolicy=null;f.card();assert.equal(f.O._confirmation,null);assert.equal(f.stats.begin,0);assert.equal(f.backend(),0);});
test('missing viewport refuses without a card',()=>{const f=fixture();f.O.readableViewport=null;f.card();assert.equal(f.O._confirmation,null);});
test('missing permission has no default',()=>{const f=fixture();delete f.O.readableGoalPolicy.allowMove;f.card();assert.equal(f.O._confirmation,null);});
test('No consumes card without a transaction',()=>{const f=fixture();f.card();f.O.rejectIntent();f.O.confirmIntent();assert.equal(f.stats.begin,0);});
for(const [name,mutate] of [['revision',f=>f.State.revision++],['policy',f=>f.O.readableGoalPolicy.allowShrink=true],
 ['target size',f=>f.mini.width++],['container translation',f=>f.container.x++],['cross-container obstacle',f=>f.other.x++],
 ['viewport size',f=>f.viewport.width++]])test('Yes rejects stale '+name,()=>{const f=fixture();f.card();mutate(f);f.O.confirmIntent();assert.equal(f.O._confirmation,null);assert.equal(f.stats.begin,0);assert.equal(f.stats.apply,0);});
test('Yes starts once; conditions, step/logical/final checks precede one commit',()=>{const f=fixture();f.card();f.O.confirmIntent();f.O.confirmIntent();assert.equal(f.stats.begin,1);assert.equal(f.stats.apply,1);assert.equal(f.stats.commit,0);f.step();assert.equal(f.stats.commit,0);f.drain();assert.equal(f.stats.commit,1);assert.equal(f.stats.rollback,0);assert.equal(f.O.busy,false);const phases=f.events.filter(e=>e.phase==='readability_loop').map(e=>e.event.phase);for(const p of ['step_check','logical_check','final_check','complete'])assert(phases.includes(p));assert.equal(f.backend(),0);});
test('every settled poll recaptures measured host input',()=>{const f=fixture();f.card();f.O.confirmIntent();const n=f.stats.capture;f.step();assert(f.stats.capture>n);f.O.cancelWaiting();});
test('fresh full obstacle list fails verification and rolls back without model repair',()=>{const f=fixture();f.card();f.O.confirmIntent();f.other.x=180;f.other.y=140;f.drain();assert.equal(f.stats.commit,0);assert.equal(f.stats.rollback,1);assert.equal(f.ov.scale,1);assert.equal(f.backend(),0);assert(f.events.some(e=>e.event&&e.event.reason==='REPAIR_UNAVAILABLE'));});
test('cancel pending poll restores only owned group and late callback is inert',()=>{const f=fixture();f.card();f.O.confirmIntent();const late=f.O.readableTick.onFire;f.O.cancelWaiting();assert.equal(f.stats.rollback,1);assert.equal(f.queued(),0);late();assert.equal(f.stats.commit,0);assert.equal(f.stats.apply,1);});
test('settle timeout rolls back with retained failure',()=>{const f=fixture();f.card();f.O.confirmIntent();f.advance(2600);f.step();assert.equal(f.stats.rollback,1);assert(f.events.some(e=>e.event&&String(e.event.reason).includes('TIMEOUT')));});
test('external State revision aborts then restores owned group',()=>{const f=fixture();f.card();f.O.confirmIntent();f.State.revision++;f.drain();assert.equal(f.stats.rollback,1);assert.equal(f.stats.commit,0);});
test('foreign preexisting group survives rejected begin',()=>{const f=fixture();const foreign=f.State.beginGroup();f.card();f.O.confirmIntent();assert.strictEqual(f.State._activeGroupCheckpoint,foreign);assert.equal(f.stats.rollback,0);assert.equal(f.stats.apply,0);});
test('lost ownership never rolls back a foreign token',()=>{const f=fixture();f.card();f.O.confirmIntent();const foreign={foreign:true};f.State._activeGroupCheckpoint=foreign;f.drain();assert.strictEqual(f.State._activeGroupCheckpoint,foreign);assert.equal(f.stats.rollback,0);assert(f.events.some(e=>e.event&&e.event.phase==='rollback_failed'));});
test('commit error falls back to owned rollback',()=>{const f=fixture();f.stats.commitThrows=true;f.card();f.O.confirmIntent();f.drain();assert.equal(f.stats.commit,0);assert.equal(f.stats.rollback,1);});
test('rollback failure remains visible when cancelled',()=>{const f=fixture();f.stats.rollbackThrows=true;f.card();f.O.confirmIntent();f.O.cancelWaiting();assert(f.O.messageText.includes('復原未完成'));assert(f.State._groupActive);});
test('replacing viewport during polling aborts owned group',()=>{const f=fixture();f.card();f.O.confirmIntent();f.O.readableViewport={};f.drain();assert.equal(f.stats.rollback,1);});
test('cancel button is available throughout an active readability session',()=>{assert(source.includes('visible: root._cancelModel !== null || root.pendingText !== "" || root._readableSession !== null'));});
test('close/destruction hooks explicitly cancel and stop scheduler',()=>{assert(/onOpenChanged:[\s\S]*?if \(_readableSession\) _readableSession.cancel\(\)/.test(source));assert(/Component.onDestruction:[\s\S]*?_destroying = true[\s\S]*?_readableSession.cancel\(\)[\s\S]*?readableTick.stop\(\)/.test(source));});
console.log(JSON.stringify({new_controls:count,backend_calls:0,Qt_runtime:false,old_suites_executed:0}));
