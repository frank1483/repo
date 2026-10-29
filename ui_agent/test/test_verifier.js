// First functional execution belongs to Claude; keep stdout/stderr and exit code.
const fs = require('fs'), path = require('path'), assert = require('assert');
const src=fs.readFileSync(path.join(__dirname,'../qml/GcpAgentVerifier.js'),'utf8').replace(/^\.pragma library\r?\n/,'');
const V=new Function(src+'\nreturn {verify};')();
const base=()=>({page:1,section:-1,viewport:{x:0,y:0,w:800,h:600},modules:{a:{page:1,visible:true,rect:{x:10,y:10,w:100,h:60},paintOrder:1}}});
const expected=()=>({page:1,section:-1,modules:[{id:'a',minWidth:80,minHeight:40}]});
function codes(s,e){return V.verify(s,e).failures.map(f=>f.code);}
let count=0;
function pair(code,change){const s=base(),e=expected();assert(!codes(s,e).includes(code),code+' negative');change(s,e);assert(codes(s,e).includes(code),code+' positive');count+=2;}
pair('PAGE_NOT_REACHED',s=>s.page=2);
pair('MODULE_NOT_VISIBLE',s=>s.modules.a.visible=false);
pair('OVERLAP',s=>s.modules.b={visible:true,page:1,rect:{x:20,y:20,w:50,h:30}});
pair('OUT_OF_BOUNDS',s=>s.modules.a.rect.x=750);
pair('OCCLUDED',s=>s.modules.b={visible:true,page:1,rect:{x:20,y:20,w:50,h:30},paintOrder:2,occludes:true,collisionGroup:'overlay'});
pair('TEXT_TRUNCATED',s=>s.modules.a.rect.w=70);
pair('LOCKED_VIOLATION',(s,e)=>{s.modules.a.locked=true;e.before=structuredClone(s);s.modules.a.rect.x+=1;});
const s=base(),e=expected();s.modules.a.locked=true;e.before=structuredClone(s);assert(V.verify(s,e).ok);count++;
const before=JSON.stringify(s);V.verify(s,e);assert.equal(JSON.stringify(s),before);count++;
s.modules.a.rect.x+=1e-8;assert(!codes(s,e).includes('LOCKED_VIOLATION'));count++;
s.modules.a.rect.w=NaN;assert(codes(s,e).includes('OUT_OF_BOUNDS'));count++;
const t=base();t.modules.a.textTruncated=true;assert(codes(t,expected()).includes('TEXT_TRUNCATED'));count++;
const bg=base();bg.modules.map={visible:true,background:true,rect:{x:0,y:0,w:800,h:600}};assert(V.verify(bg,expected()).ok);count++;
const edge=base();edge.modules.b={visible:true,rect:{x:110,y:10,w:20,h:20}};assert(!codes(edge,expected()).includes('OVERLAP'));count++;
const hidden=base();hidden.modules.a.visible=false;assert(V.verify(hidden,{modules:[{id:'a',visible:false}]}).ok);count++;
const ext={extraChecks:['data_source'],modules:[]};assert(V.verify(base(),ext).failures.some(f=>f.code==='CHECK_UNAVAILABLE'));count++;
assert(V.verify(base(),ext,{data_source:()=>[]}).ok);count++;
const out=V.verify(base(),ext,{data_source:()=>[{code:'WRONG_DATA_SOURCE',module:'a',detail:'fixture'}]});assert.equal(out.failures[0].code,'WRONG_DATA_SOURCE');count++;
console.log(JSON.stringify({scope:'pure verifier; simulated snapshots only',assertion_cases:count,ok:true}));
