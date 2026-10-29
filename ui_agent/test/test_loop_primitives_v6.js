'use strict';
// NEW controls, source only at delivery. Claude owns the first functional execution.
const fs=require('fs'),path=require('path'),assert=require('assert'),vm=require('vm');
function load(name,names){return new Function(fs.readFileSync(path.join(__dirname,'../qml',name),'utf8').replace(/^\.pragma library\s*$/m,'')+'\nreturn {'+names.join(',')+'};')();}
const Loop=load('GcpAgentLoop.js',['create','goalTemplate']),Verifier=load('GcpAgentVerifier.js',['verify']),Snapshot=load('GcpAgentSnapshot.js',['capture']);
const clone=x=>JSON.parse(JSON.stringify(x));let cases=0;
function test(name,fn){fn();cases++;console.log('PASS '+name);}
function nav(id,page,extra={}){return {id,action:{kind:'nav',page,section:-1},expected:{page},...extra};}
function harness(options={}){
    let world={page:0,section:-1,viewport:{x:0,y:0,w:200,h:200},modules:{}},undo=[{label:'old'}],redo=[{label:'redo'}];
    let commits=0,rollbacks=0,restores=0,begins=0,executions=0,finished=0;
    const reports=[],requests=[],callbacks=[],proposalCallbacks=[];
    const spec=options.spec||{goal:'fake goal',label:'goal group',steps:['A'],catalog:[nav('A',1),nav('R',1,{repairFor:['A'],failureCodes:['PAGE_NOT_REACHED']})],expected:{page:1}};
    const ports={
        begin(){begins++;return {world:clone(world),undo:clone(undo),redo:clone(redo)};},
        commit(cp,label){if(options.commitError)throw Error('commit');undo=cp.undo.concat([{label,world:cp.world}]);redo=[];commits++;},
        rollback(cp){rollbacks++;if(options.rollbackError)throw Error('restore unavailable');world=clone(cp.world);undo=clone(cp.undo);redo=clone(cp.redo);},
        snapshot(){return clone(world);},checkpoint(){return clone(world);},restore(cp){restores++;world=clone(cp);},
        execute(action,done){executions++;callbacks.push(done);if(options.apply)options.apply(action,world,executions);else world.page=action.page;
            if(!options.asyncExecute)done(options.executeError?'denied':null);},
        verify(s,e){return options.verify?options.verify(s,e):Verifier.verify(s,e);},
        propose(request,done){requests.push(clone(request));proposalCallbacks.push(done);if(options.propose)options.propose(request,done);else done({steps:[{choice_id:request.candidates[request.candidates.length-1].id}],reason_zh:'fake model chose bounded repair'});},
        report(event){reports.push(event);if(options.report)options.report(event);},finished(){finished++;}
    };
    if(options.noPropose)delete ports.propose;
    const controller=Loop.create(spec,ports);
    return {controller,spec,ports,reports,requests,callbacks,proposalCallbacks,world:()=>clone(world),
        counts:()=>({commits,rollbacks,restores,begins,executions,finished}),history:()=>({undo:clone(undo),redo:clone(redo)})};
}
test('no execution before explicit host Yes',()=>{const h=harness();assert.throws(()=>h.controller.start(false),/confirmation/);assert.equal(h.counts().begins,0);assert.equal(h.controller.state().phase,'ready');});
test('first step fail, fake model sees reason, bounded repair passes',()=>{const h=harness({apply(a,w,n){if(n>1)w.page=a.page;}});h.controller.start(true);assert.equal(h.controller.state().phase,'complete');assert.equal(h.requests.length,1);assert.equal(h.requests[0].failures[0].code,'PAGE_NOT_REACHED');assert(h.requests[0].failures[0].detail.includes('Expected page'));assert.equal(h.counts().commits,1);assert.equal(h.counts().executions,2);});
test('perpetual failure hits five rounds and restores original plus redo',()=>{const h=harness({apply(){}}),old=h.history();h.controller.start(true);assert.equal(h.controller.state().phase,'failed');assert.equal(h.controller.state().round,5);assert.equal(h.requests.length,4);assert.equal(h.world().page,0);assert.deepStrictEqual(h.history(),old);assert.equal(h.counts().rollbacks,1);});
test('five initial steps execute and commit once',()=>{const cat=[1,2,3,4,5].map(n=>nav('N'+n,n));const h=harness({spec:{steps:cat.map(c=>c.id),catalog:cat,expected:{page:5}}});h.controller.start(true);assert.equal(h.controller.state().phase,'complete');assert.equal(h.counts().executions,5);assert.equal(h.history().undo.length,2);assert.equal(h.history().redo.length,0);});
test('six initial steps rejected before begin',()=>{const h=harness();const s=clone(h.spec);s.steps=Array(6).fill('A');assert.throws(()=>Loop.create(s,h.ports),/five/);assert.equal(h.counts().begins,0);});
test('six repair steps rejected and whole group restored',()=>{const h=harness({apply(){},propose(r,done){done({steps:Array(6).fill({choice_id:'R'})});}});h.controller.start(true);assert.equal(h.controller.state().phase,'failed');assert.equal(h.counts().executions,1);assert.equal(h.world().page,0);});
test('unknown repair id cannot execute',()=>{const h=harness({apply(){},propose(r,done){done({steps:[{choice_id:'ARM'}]});}});h.controller.start(true);assert.equal(h.counts().executions,1);assert.equal(h.controller.state().phase,'failed');});
test('extra model action payload cannot cross id gate',()=>{const h=harness({apply(){},propose(r,done){done({steps:[{choice_id:'R',page:10}]});}});h.controller.start(true);assert.equal(h.counts().executions,1);assert.equal(h.controller.state().phase,'failed');});
test('repair id for another failure code is excluded',()=>{const h=harness({apply(){},propose(r,done){assert.deepStrictEqual(r.candidates.map(c=>c.id),['A']);done({steps:[{choice_id:'R'}]});}});h.spec.catalog[1].failureCodes=['OVERLAP'];const x=Loop.create(h.spec,h.ports);x.start(true);assert.equal(x.state().phase,'failed');});
test('two failures of second slot restore pre-previous checkpoint',()=>{let b=0;const h=harness({spec:{steps:['A','B'],catalog:[nav('A',1),nav('B',2)],expected:{page:2}},apply(a,w){if(a.page===2&&++b<=2)return;w.page=a.page;}});h.controller.start(true);assert.equal(h.controller.state().phase,'complete');assert(h.reports.some(e=>e.phase==='backtrack'&&e.from===1&&e.to===0));assert.equal(h.counts().restores,1);assert(h.counts().executions>=5);});
test('duplicate execution callback is ignored',()=>{const h=harness({asyncExecute:true});h.controller.start(true);h.callbacks[0](null);h.callbacks[0](null);assert.equal(h.counts().commits,1);assert.equal(h.counts().finished,1);});
test('cancel ignores late execute callback and restores',()=>{const h=harness({asyncExecute:true});h.controller.start(true);h.controller.cancel();h.callbacks[0](null);assert.equal(h.controller.state().phase,'failed');assert.equal(h.world().page,0);assert.equal(h.counts().commits,0);assert.equal(h.counts().rollbacks,1);});
test('cancel ignores late fake model response',()=>{const h=harness({apply(){},propose(){}});h.controller.start(true);assert(h.controller.state().repairPending);h.controller.cancel();h.proposalCallbacks[0]({steps:[{choice_id:'R'}]});assert.equal(h.counts().executions,1);assert.equal(h.counts().rollbacks,1);});
test('duplicate fake model response cannot dispatch twice',()=>{const h=harness({apply(a,w,n){if(n>1)w.page=a.page;},propose(r,done){done({steps:[{choice_id:'R'}]});done({steps:[{choice_id:'R'}]});}});h.controller.start(true);assert.equal(h.counts().executions,2);assert.equal(h.counts().commits,1);});
test('explicit execution error restores and reports failure',()=>{const h=harness({executeError:true});h.controller.start(true);assert.equal(h.world().page,0);assert.equal(h.controller.state().phase,'failed');assert.equal(h.counts().commits,0);});
test('missing repair port restores instead of inventing action',()=>{const h=harness({apply(){},noPropose:true});h.controller.start(true);assert.equal(h.controller.state().phase,'failed');assert(h.controller.state().trace.some(e=>e.reason==='REPAIR_UNAVAILABLE'));});
test('verifier exception restores whole group',()=>{const h=harness({verify(){throw Error('snapshot drift');}});h.controller.start(true);assert.equal(h.counts().rollbacks,1);assert.equal(h.world().page,0);});
test('inconsistent verifier success rejected',()=>{const h=harness({verify(){return {ok:true,failures:[{code:'OVERLAP',detail:'bad'}]};}});h.controller.start(true);assert.equal(h.controller.state().phase,'failed');});
test('final invariant remains independent of repaired step',()=>{const h=harness();h.spec.expected={page:2};const x=Loop.create(h.spec,h.ports);x.start(true);assert.equal(x.state().phase,'failed');assert.equal(h.world().page,0);});
test('commit error attempts rollback',()=>{const h=harness({commitError:true});h.controller.start(true);assert.equal(h.counts().rollbacks,1);assert.equal(h.world().page,0);});
test('rollback failure never claims restored state',()=>{const h=harness({executeError:true,rollbackError:true});h.controller.start(true);assert.equal(h.controller.state().phase,'rollback_failed');assert(h.controller.state().trace.some(e=>String(e.reason).includes('ROLLBACK_FAILED')));});
test('spec detached from mutable host catalog',()=>{const h=harness();h.spec.catalog[0].action.page=10;h.controller.start(true);assert.equal(h.world().page,1);});
test('returned state detached from controller trace',()=>{const h=harness({asyncExecute:true});const s=h.controller.start(true);s.trace.length=0;assert(h.controller.state().trace.length>0);h.controller.cancel();});
test('flight and parameter actions rejected before ports',()=>{for(const kind of ['flight','parameter']){const h=harness();h.spec.catalog[0].action.kind=kind;assert.throws(()=>Loop.create(h.spec,h.ports),/unsupported/);assert.equal(h.counts().begins,0);}});
test('empty final and step expectations rejected',()=>{const h=harness();h.spec.expected={};assert.throws(()=>Loop.create(h.spec,h.ports),/final expectation/);h.spec.expected={page:1};h.spec.catalog[0].expected={};assert.throws(()=>Loop.create(h.spec,h.ports),/step expectation/);});
test('restart after completion rejected',()=>{const h=harness();h.controller.start(true);assert.throws(()=>h.controller.start(true),/already started/);assert.equal(h.counts().commits,1);});
test('report callback cancellation cannot continue checking or commit',()=>{for(const phase of ['step_check','logical_check','final_check']){let controller;const h=harness({report(e){if(e.phase===phase)controller.cancel();}});controller=h.controller;controller.start(true);assert.equal(controller.state().phase,'failed');assert.equal(h.counts().commits,0);assert.equal(h.counts().rollbacks,1);assert.equal(h.world().page,0);}});
test('small-map goal is confirmation-only template',()=>{const t=Loop.goalTemplate('小地圖看清楚一點',{page:1,modules:{miniView:{registered:true,visible:true}}});assert.equal(t.decision,'SELECT');assert.equal(t.candidates[0].op,'scale');assert(t.confirmation_required);});
test('generic map goal asks which map',()=>{assert.equal(Loop.goalTemplate('地圖看清楚一點',{page:1}).decision,'CLARIFY');});
test('missing or hidden small map asks rather than executing',()=>{assert.equal(Loop.goalTemplate('小地圖看清楚一點',{page:0}).decision,'CLARIFY');assert.equal(Loop.goalTemplate('小地圖看清楚一點',{page:1,modules:{miniView:{registered:true,visible:false}}}).decision,'CLARIFY');});
test('unrecognized text not silently treated as goal',()=>{assert.equal(Loop.goalTemplate('解鎖並起飛',{}),null);});

function item(parent,props={}){const o={parent,children:[],width:20,height:20,x:0,y:0,z:0,visible:true,opacity:1,...props};if(parent)parent.children.push(o);
    o.mapToItem=function(root,x,y){let cur=this;while(cur!==root){x=x*(cur.factor||1)+cur.x;y=y*(cur.factor||1)+cur.y;cur=cur.parent;if(!cur)throw Error('outside');}return {x,y};};return o;}
function scene(){const root=item(null,{width:200,height:200}),a=item(root,{x:10,y:20}),b=item(root,{x:60,y:20,z:2});return {root,a,b,registry:{a:{item:a},b:{item:b}},policies:[{id:'a',page:1,locked:true},{id:'b',page:1}]};}
function capture(s){return Snapshot.capture(s.root,s.registry,s.policies,{page:1,section:-1},()=>({scale:1}));}
test('adapter measures transformed four corners',()=>{const s=scene();s.a.factor=2;const snap=capture(s);assert.deepStrictEqual(snap.modules.a.rect,{x:10,y:20,w:40,h:40});assert(snap.modules.a.locked);});
test('adapter orders nested branches across parents by paint traversal',()=>{const s=scene(),p=item(s.root,{z:-1}),inner=item(p,{z:1000});s.registry.a.item=inner;assert(capture(s).modules.a.paintOrder<capture(s).modules.b.paintOrder);});
test('adapter respects negative-z child before parent',()=>{const s=scene(),child=item(s.a,{z:-1});s.registry.b.item=child;const out=capture(s);assert(out.modules.b.paintOrder<out.modules.a.paintOrder);});
test('adapter multiplies ancestor opacity',()=>{const s=scene();s.root.opacity=0.5;s.a.opacity=0.4;assert.equal(capture(s).modules.a.opacity,0.2);});
test('adapter hidden ancestor makes item invisible',()=>{const s=scene();s.root.visible=false;assert.equal(capture(s).modules.a.visible,false);});
test('adapter rejects clipped ancestor instead of false pass',()=>{const s=scene();s.root.clip=true;assert.throws(()=>capture(s),/clipp/);});
test('adapter rejects layers and outside-root modules',()=>{const s=scene();s.a.layer={enabled:true};assert.throws(()=>capture(s),/layer/);s.a.layer=null;s.registry.a.item=item(null);assert.throws(()=>capture(s),/outside/);});
test('adapter bounds malformed parent-chain traversal',()=>{const s=scene();s.a.mapToItem=()=>({x:10,y:10});s.a.parent=s.a;assert.throws(()=>capture(s),/parent chain/);});
test('adapter snapshot feeds actual overlap and occlusion verifier',()=>{const s=scene();s.b.x=10;const snap=capture(s),r=Verifier.verify(snap,{modules:[{id:'a'}]});assert(r.failures.some(f=>f.code==='OVERLAP'));assert(r.failures.some(f=>f.code==='OCCLUDED'));});

const stateSource=fs.readFileSync(path.join(__dirname,'../qml/GcpAgentState.qml'),'utf8');
function functionText(name){const start=stateSource.indexOf('    function '+name+'(');assert(start>=0);const headEnd=stateSource.indexOf('\n',start);if(stateSource.slice(start,headEnd).trimEnd().endsWith('}'))return stateSource.slice(start,headEnd);const end=stateSource.indexOf('\n    }',headEnd);assert(end>start);return stateSource.slice(start,end+6);}
function stateHarness(){let world={page:0};const s={_groupActive:false,_activeGroupCheckpoint:null,undoStack:[],redoStack:[{label:'old redo'}],revision:0,
    snapshot(){return clone(world);},_restore(cp){world=clone(cp);},setPage(page){world.page=page;},getPage(){return world.page;}};
    vm.createContext(s);vm.runInContext(['beginGroup','commitGroup','rollbackGroup','undo','redo'].map(functionText).join('\n'),s);return s;}
test('opt-in State atomic group creates one undo then one redo for entire chain',()=>{const s=stateHarness(),cp=s.beginGroup();s.setPage(1);s.undoStack.push({label:'intermediate',snap:{page:0}});s.setPage(2);s.commitGroup(cp,'all steps','layout');assert.equal(s.undoStack.length,1);s.undo(1);assert.equal(s.getPage(),0);s.redo();assert.equal(s.getPage(),2);});
test('State failure restores pre-group redo and undo',()=>{const s=stateHarness(),old=clone(s.redoStack),cp=s.beginGroup();s.setPage(3);s.undoStack.push({label:'bad'});s.redoStack=[];s.rollbackGroup(cp);assert.equal(s.getPage(),0);assert.deepStrictEqual(clone(s.redoStack),old);assert.equal(s.undoStack.length,0);});
test('State rejects forged token and nested begin',()=>{const s=stateHarness(),cp=s.beginGroup();assert.throws(()=>s.beginGroup(),/nested/);assert.throws(()=>s.commitGroup(clone(cp),'bad'),/invalid/);assert.throws(()=>s.rollbackGroup(clone(cp)),/invalid/);s.rollbackGroup(cp);assert.throws(()=>s.rollbackGroup(cp),/invalid/);});
test('State legacy no-arg commit retains individual undo entries',()=>{const s=stateHarness();s.beginGroup();s.undoStack.push({label:'one'},{label:'two'});s.commitGroup();assert.equal(s.undoStack.length,2);assert.equal(s._groupActive,false);});
console.log('loop primitives v6: '+cases+' cases PASS (mock ports, not Qt or model execution)');
