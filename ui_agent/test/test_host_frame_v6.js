'use strict';
// New adapter controls, using real Snapshot/Catalog/Core/Loop/Verifier and fake Qt mappings.
// Does not execute any previously successful suite, backend, API or device.
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const root=path.resolve(process.argv[2] || path.join(__dirname,'..'));
const load=p=>{const c={};vm.createContext(c);vm.runInContext(fs.readFileSync(p,'utf8').replace(/^\.pragma[^\n]*\n/,''),c,{filename:p});return c;};
const Core=load(path.join(root,'qml/GcpAgentCore.js')), Snapshot=load(path.join(root,'qml/GcpAgentSnapshot.js'));
const Catalog=load(path.join(root,'qml/GcpAgentCatalog.js')), Loop=load(path.join(root,'qml/GcpAgentLoop.js'));
const Verifier=load(path.join(root,'qml/GcpAgentVerifier.js'));
const Host=load(path.join(__dirname,'../qml/GcpAgentHost.js'));
const clone=x=>JSON.parse(JSON.stringify(x)); let tests=0;
function test(name,fn){fn();tests++;console.log('PASS '+name);}
function fixture(){
 const viewport={width:800,height:600,z:0,visible:true,opacity:1,children:[],parent:null};
 const container={x:10,y:15,width:760,height:560,z:0,visible:true,opacity:1,children:[],parent:viewport,
   mapToItem(to,x,y){assert.strictEqual(to,viewport);return {x:this.x+x,y:this.y+y};}};
 const ov={dx:20,dy:10,scale:1,hidden:false};
 const item={x:100,y:100,width:200,height:120,z:0,visible:true,opacity:1,children:[],parent:container,
   mapToItem(to,x,y){const p={x:this.x+ov.dx+x*ov.scale,y:this.y+ov.dy+y*ov.scale};
     if(to===container)return p;assert.strictEqual(to,viewport);return {x:container.x+p.x,y:container.y+p.y};}};
 viewport.children=[container];container.children=[item];
 const registry={miniView:{item,container}};
 const goal={kind:'readable',minWidth:160,minHeight:80,allowMove:true,allowShrink:false,allowNavigate:false};
 const candidates=clone(Loop.goalTemplate('讓小地圖看得清楚一點',{page:1,modules:{miniView:{registered:true,visible:true}}}).candidates);
 return {viewport,container,item,registry,ov,goal,candidates,revision:4,location:{page:1,section:-1},
  capture(){return Host.captureReadable(this.viewport,this.registry,Core.MODULES,this.location,()=>clone(this.ov),this.revision,this.goal,this.candidates,Snapshot);}};
}
function reject(name,mutate,reason){test(name,()=>{const f=fixture();mutate(f);assert.throws(()=>Host.prepareReadable(f.capture(),Core,Catalog),reason);});}
test('real Snapshot maps translated/resized override into Catalog',()=>{
 const f=fixture();f.ov.scale=1.25;const h=f.capture(),p=Host.prepareReadable(h,Core,Catalog);
 assert.deepEqual(clone(h.frame.origin),{x:10,y:15});assert.equal(h.snapshot.modules.miniView.rect.w,250);
 assert.equal(h.frame.override.dx,20);assert.equal(p.spec.guard.revision,4);
 assert(p.summary.includes('寬 160 × 高 80'));assert(p.summary.includes('移動允許'));assert(p.summary.includes('降尺寸不允許'));
});
test('all permissions are disclosed without inferring minimums',()=>{
 const f=fixture();f.goal.allowMove=false;f.goal.allowShrink=true;f.goal.allowNavigate=true;
 const p=Host.prepareReadable(f.capture(),Core,Catalog);assert(p.summary.includes('移動不允許'));assert(p.summary.includes('降尺寸允許'));assert(p.summary.includes('回所在畫面允許'));
});
test('prepared input is detached from mutable host objects',()=>{const f=fixture(),h=f.capture(),p=Host.prepareReadable(h,Core,Catalog);
 h.goal.minWidth=900;f.ov.dx=60;assert.equal(p.basis.goal.minWidth,160);assert.equal(p.basis.frame.override.dx,20);});
test('current guard rebuilds detached spec; object ordering irrelevant',()=>{const f=fixture(),p=Host.prepareReadable(f.capture(),Core,Catalog),fresh=f.capture();
 fresh.goal=Object.fromEntries(Object.entries(fresh.goal).reverse());const s=Host.assertReadableCurrent(p,fresh,Core,Catalog);s.guard.revision=99;assert.equal(p.spec.guard.revision,4);});
for(const [name,mutate] of [
 ['revision',f=>f.revision++],['section',f=>f.location.section=0],['viewport resize',f=>f.viewport.width++],
 ['container shift without revision',f=>f.container.x++],['container resize',f=>f.container.width++],
 ['target geometry',f=>f.item.width++],['override',f=>f.ov.dx++],['opacity',f=>f.item.opacity=0.8],
 ['readable minimum',f=>f.goal.minWidth++],['repair permission',f=>f.goal.allowShrink=true]]) {
 test('stale '+name+' rejected',()=>{const f=fixture(),p=Host.prepareReadable(f.capture(),Core,Catalog);mutate(f);
   assert.throws(()=>Host.assertReadableCurrent(p,f.capture(),Core,Catalog),/stale/);});
}
test('tampered spec rejected',()=>{const f=fixture(),p=Host.prepareReadable(f.capture(),Core,Catalog);p.spec.expected.modules[0].minWidth=1;
 assert.throws(()=>Host.assertReadableCurrent(p,f.capture(),Core,Catalog),/payload/);});
test('tampered summary rejected',()=>{const f=fixture(),p=Host.prepareReadable(f.capture(),Core,Catalog);p.summary='批准所有修補';
 assert.throws(()=>Host.assertReadableCurrent(p,f.capture(),Core,Catalog),/payload/);});
reject('nested target cannot use direct-child executor geometry',f=>f.item.parent={},/direct child/);
reject('scaled container mapping rejected',f=>f.container.mapToItem=(to,x,y)=>({x:10+x*2,y:15+y}),/translation-only/);
reject('rotated container mapping rejected',f=>f.container.mapToItem=(to,x,y)=>({x:10-y,y:15+x}),/translation-only/);
reject('oversized area rejected before freeSpot scan',f=>f.container.width=32769,/bounds/);
reject('invalid origin rejected',f=>f.container.x=NaN,/origin/);
reject('target transform outside executor override rejected',f=>{const map=f.item.mapToItem;f.item.mapToItem=function(to,x,y){const p=map.call(this,to,x,y);p.x+=2;return p;};},/target transform/);
reject('hidden target rejected',f=>f.item.visible=false,/visible/);
reject('hidden override rejected',f=>f.ov.hidden=true,/override/);
reject('clipped ancestor rejected by real Snapshot',f=>f.container.clip=true,/clipping/);
reject('layered scene rejected by real Snapshot',f=>f.container.layer={enabled:true},/layered/);
reject('off-page target rejected by real Catalog',f=>f.location.page=0,/current/);
reject('missing minimum never defaults',f=>delete f.goal.minWidth,/minimums/);
reject('missing permission never defaults',f=>delete f.goal.allowMove,/permissions/);
reject('candidate expected injection rejected',f=>f.candidates[0].expected={page:0},/expectations/);
reject('unbounded registry rejected',f=>{for(let i=0;i<128;i++)f.registry['extra'+i]={};},/bounded registry/);
function obstacle(f,id='windGauge') {
 const item={width:80,height:80,z:1,visible:true,opacity:1,children:[],parent:f.viewport,
   mapToItem(to,x,y){assert.strictEqual(to,f.viewport);return {x:310+x,y:115+y};}};
 f.viewport.children.push(item);f.registry[id]={item,container:f.viewport};return item;
}
test('obstacle in another container uses measured viewport rectangle',()=>{const f=fixture();obstacle(f);
 const h=f.capture();assert.deepEqual(clone(h.frame.others),[{x:300,y:100,w:80,h:80}]);});
test('unknown registry fails; hidden registered obstacle is excluded',()=>{
 const f=fixture();obstacle(f).visible=false;obstacle(f,'settingsPane');
 // settingsPane has no Core policy; unknown inventory must fail rather than disappear.
 assert.throws(()=>f.capture(),/unrecognized/);
 delete f.registry.settingsPane;const h=f.capture();assert.equal(h.frame.others.length,0);
});
test('obstacle opacity change invalidates confirmation without revision',()=>{const f=fixture(),o=obstacle(f),p=Host.prepareReadable(f.capture(),Core,Catalog);
 o.opacity=0.6;assert.throws(()=>Host.assertReadableCurrent(p,f.capture(),Core,Catalog),/stale/);});
test('prepared current host spec executes real Loop and Verifier once',()=>{
 const f=fixture();f.goal.allowMove=false;const p=Host.prepareReadable(f.capture(),Core,Catalog),s=Host.assertReadableCurrent(p,f.capture(),Core,Catalog);
 const baseline=clone(f.ov);let begins=0,commits=0,rollbacks=0;
 const loop=Loop.create(s,{begin(){begins++;return 'g';},commit(){commits++;},rollback(){rollbacks++;Object.assign(f.ov,baseline);},
 snapshot(){return f.capture().snapshot;},checkpoint(){return clone(f.ov);},restore(o){Object.assign(f.ov,o);},verify:Verifier.verify,
 execute(a,done){const h=f.capture(),policy=Core.MODULES.find(m=>m.id==='miniView');
   Object.assign(f.ov,Core.layoutTarget(a.op,h.frame.base,h.frame.area,h.frame.override,a.factor,h.frame.others,policy));done();}});
 assert.throws(()=>loop.start(),/explicit host confirmation/);assert.equal(begins,0);
 loop.start(true);assert.equal(loop.state().phase,'complete');assert.equal(begins,1);assert.equal(commits,1);assert.equal(rollbacks,0);
});
function stateMethod(f,adapter=Host){
 const text=fs.readFileSync(path.join(__dirname,'../qml/GcpAgentState.qml'),'utf8');
 const start=text.indexOf('    function readableHostInput('),end=text.indexOf('\n    // 模組在容器',start);
 assert(start>=0&&end>start);const c={revision:f.revision,shell:{agentLocation:()=>clone(f.location)},
  AgentHost:adapter,AgentSnapshot:Snapshot,Core,_modules:f.registry,overrideOf:()=>clone(f.ov)};
 vm.createContext(c);vm.runInContext(text.slice(start,end),c);return c;
}
test('actual State method captures fresh host input without writes',()=>{const f=fixture(),c=stateMethod(f),before=clone(f.ov);
 const h=c.readableHostInput(f.viewport,f.goal,f.candidates);assert.equal(h.revision,4);assert.deepEqual(f.ov,before);});
test('actual State method rejects revision change during capture',()=>{const f=fixture();let c;
 c=stateMethod(f,{captureReadable(...args){const h=Host.captureReadable(...args);c.revision++;return h;}});
 assert.throws(()=>c.readableHostInput(f.viewport,f.goal,f.candidates),/host changed/);});
test('actual State method rejects page change during capture',()=>{const f=fixture();
 const c=stateMethod(f,{captureReadable(...args){const h=Host.captureReadable(...args);f.location.page=8;return h;}});
 assert.throws(()=>c.readableHostInput(f.viewport,f.goal,f.candidates),/host changed/);});
console.log(JSON.stringify({tests,backend_calls:0,qt_runtime:false,old_suites_executed:0}));
