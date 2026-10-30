"use strict";
// NEW authored controls; Claude owns first execution using the QML loader.
const assert=require("assert"),fs=require("fs"),path=require("path"),c=require("./load_core")();
const CFG={min_samples:3,min_distance_span_m:100,window_s:10,max_gap_s:5,horizon_s:30,max_extrapolation_m:250};
const FAST={min_samples:2,min_distance_span_m:1,window_s:1,max_gap_s:1};
function vehicle(key="fw_example"){return c.loadAirframe(JSON.parse(fs.readFileSync(path.join(__dirname,"../../airframes",key+".json"),"utf8")))}
const samples=(qs=[80,70,60],ds=[0,100,200],ts=[0,1,2])=>qs.map((link_pct,i)=>({t_s:ts[i],distance_m:ds[i],link_pct}));
const probes=(distance_m=450,eta_s=10)=>[{id:"A",distance_m,eta_s}];
const snap=(rows=samples(),targets=probes(),cfg=CFG)=>c.typedLinkDistanceSnapshot(vehicle(),"home.v1",rows,targets,cfg);
const feed=(cfg=FAST,r=2,k=2)=>c.createTypedLinkDistancePredictor(vehicle(),"home.v1",cfg,r,k);
const tick=(f,i,q,distance=(i%2)*100,version="v1",time=i,targets=probes(100))=>f.tick(i,{t_s:time,distance_m:distance,link_pct:q},targets,version);
const types=r=>r.events.map(e=>e.type);
let groups=0;
function test(name,f){f();groups++;console.log("PASS "+name)}
test("hand calculated slope and exact quality threshold",()=>{const r=snap();assert.equal(r.status,"ok");assert.strictEqual(r.risk,true);assert.equal(r.slope_pct_per_m,-0.1);assert.equal(r.r2,1);assert.equal(r.probes[0].predicted_link_pct,35);assert.equal(r.first_probe_id,"A");assert.equal(r.lead_s,10)});
test("observed low is immediate; warmup and stationary unknown",()=>{assert.equal(snap(samples([35],[0],[0])).lead_s,0);assert.strictEqual(snap(samples([80],[0],[0])).risk,null);assert.equal(snap(samples([80,70,60],[100,100,100])).reason,"insufficient_distance_span")});
test("flat positive and poor fits have distinct states",()=>{assert.strictEqual(snap(samples([80,80,80])).risk,false);assert.equal(snap(samples([60,70,80])).reason,"distance_fit_increasing");assert.equal(snap(samples([80,70,80])).reason,"distance_fit_unreliable")});
test("no default extrapolation; boundary and raw negative prediction",()=>{assert.strictEqual(snap(samples(),probes(),{...CFG,max_extrapolation_m:0}).risk,null);assert.strictEqual(snap(samples(),probes(),{...CFG,max_extrapolation_m:249}).risk,null);assert.equal(snap(samples(),probes(1000),{...CFG,max_extrapolation_m:800}).probes[0].predicted_link_pct,-20)});
test("horizon and all-probe support",()=>{assert(snap(samples(),probes(450,30)).risk);assert.strictEqual(snap(samples(),probes(450,31)).risk,null);const r=snap(samples(),[{id:"A",distance_m:450,eta_s:10},{id:"B",distance_m:451,eta_s:11}]);assert.strictEqual(r.risk,null);assert.strictEqual(r.first_probe_id,null)});
test("first temporal crossing is reported",()=>{const r=snap(samples(),[{id:"B",distance_m:200,eta_s:1},{id:"C",distance_m:450,eta_s:2}]);assert.equal(r.first_probe_id,"C");assert.equal(r.lead_s,2)});
test("window and contiguous suffix",()=>{assert.equal(snap(samples([80,70,60],[0,100,200],[0,8,9])).sample_count,2);assert.equal(snap(samples(),probes(),{...CFG,window_s:1,max_gap_s:1}).sample_count,2)});
test("measurement schema finite numbers ordering and count",()=>{
    [[],[{t_s:0}],samples([80,70,60],[0,100,200],[0,0,1]),samples([80,true,60]),samples([80,70,60],[0,-1,200]),samples([80,70,60],[0,10001,200]),Array.from({length:602},(_,i)=>({t_s:i,distance_m:0,link_pct:80}))].forEach(rows=>assert.throws(()=>snap(rows)));
    ["t_s","distance_m","link_pct"].forEach(k=>[true,NaN,Infinity].forEach(v=>assert.throws(()=>snap([{...samples()[0],[k]:v}]))));
});
test("explicit probe schema IDs and order",()=>{
    [[],probes().concat(probes()),Array(1001).fill(probes()[0]),[{id:"X",distance_m:0}],[{...probes()[0],action:"RTL"}],probes(-1),probes(0,-1),[{id:"X",distance_m:0,eta_s:2},{id:"Y",distance_m:0,eta_s:1}]].forEach(p=>assert.throws(()=>snap(samples(),p)));
});
test("options scope and identities",()=>{
    [{typo:1},{min_samples:true},{min_samples:1},{max_gap_s:181},{min_distance_span_m:0},{min_r2:2},{link_min_pct:101},{max_extrapolation_m:-1}].forEach(cfg=>assert.throws(()=>feed(cfg)));
    assert.throws(()=>c.typedLinkDistanceSnapshot(vehicle("x500"),"home",samples(),probes(),CFG));
    ["","a\n","非ASCII","a".repeat(129)].forEach(id=>assert.throws(()=>c.createTypedLinkDistancePredictor(vehicle(),id)));
    assert(c.typedLinkDistanceSnapshot(vehicle("vtol_example"),"home",samples(),probes(),CFG).risk);
});
test("raise and clear streaks",()=>{const f=feed(),r=[30,30,80,80,80].map((q,i)=>tick(f,i,q));assert.deepEqual(r.map(types),[["known"],["raise"],[],[],["resolve"]]);assert.deepEqual(r.map(x=>x.active),[false,true,true,true,false])});
test("unknown breaks latch without resolve",()=>{const f=feed(FAST,1,1);tick(f,0,30,100);const r=tick(f,1,80,100);assert.deepEqual(types(r),["unknown"]);assert.strictEqual(r.active,null);assert.deepEqual(types(tick(f,2,80,0)),["known"])});
test("version gap reset is neutral",()=>{const f=feed(FAST,1,1);tick(f,0,30);[tick(f,1,80,100,"v2"),tick(f,2,80,0,"v2",10)].forEach(r=>{assert.deepEqual(types(r),["reset","unknown"]);assert.strictEqual(r.events[0].active,null);assert.deepEqual(r.events[0].evidence,[]);assert.equal(r.sample_count,1)})});
test("failed tick commits nothing",()=>{const f=feed(FAST,1,1);tick(f,0,30);[[1,80,100,"bad version",1,[]],[0,30,0,"v1",1,probes()],[1,80,100,"v1",0,probes()],[1,80,100,"v2",1,[]]].forEach(a=>assert.throws(()=>tick(f,...a)));assert.deepEqual(types(tick(f,1,30)),[])});
test("sequences versions and streak validation",()=>{[true,-1,0.5,9007199254740992].forEach(i=>assert.throws(()=>tick(feed(),i,80)));[true,0,0.5,10001].forEach(n=>assert.throws(()=>feed(FAST,n)));[null,"","v1\n"].forEach(v=>assert.throws(()=>tick(feed(),0,80,0,v)))});
test("detached inputs and outputs and no authority",()=>{const cfg={...CFG},v=vehicle(),f=c.createTypedLinkDistancePredictor(v,"home",cfg,1,1);cfg.link_min_pct=0;const rec={t_s:0,distance_m:0,link_pct:35},targets=probes(0),before=JSON.stringify([rec,targets]),r=f.tick(0,rec,targets,"v1");assert(r.risk);assert.equal(JSON.stringify([rec,targets]),before);r.finding.active=false;assert(tick(f,1,30).active);assert.deepEqual(r.finding.candidates,[]);assert.strictEqual(r.finding.rule_choice,null);[r,snap()].forEach(x=>["executable","feasible","geometry_evaluated","eta_verified","distance_reference_verified"].forEach(k=>assert.strictEqual(x[k],false)))});
test("history bounded to 601",()=>{const f=feed({window_s:1000},1,1);let r;for(let i=0;i<605;i++)r=tick(f,i,80);assert.equal(r.sample_count,601)});

assert.equal(process.argv.length,3,"usage: node test_typed_link.js <Python --vectors JSON>");
const expected=JSON.parse(fs.readFileSync(process.argv[2],"utf8").replace(/^\uFEFF/,""));
const snapshots=[snap(),snap(samples(),probes(),{...CFG,max_extrapolation_m:249}),snap(samples(),probes(200)),snap(samples(),probes(450,31)),snap(samples([80,80,80])),snap(samples([60,70,80])),snap(samples([80,70,80])),snap(samples([35],[0],[0])),snap(samples([80],[0],[0]))];
const f=feed(),stream=[tick(f,0,30),tick(f,1,30),tick(f,2,80),tick(f,3,80),tick(f,4,80),tick(f,5,30,100,"v2"),tick(f,6,30,0,"v2"),tick(f,7,80,100,"v2",20),tick(f,8,80,0,"v2",21)];
function parity(a,b,where){
    if(typeof a==="number"&&typeof b==="number"){assert(Math.abs(a-b)<=1e-9*Math.max(1,Math.abs(a),Math.abs(b)),where);return}
    if(a&&b&&typeof a==="object"&&typeof b==="object"){assert.deepEqual(Object.keys(a).sort(),Object.keys(b).sort(),where+" keys");Object.keys(a).forEach(k=>parity(a[k],b[k],where+"."+k));return}
    assert.strictEqual(a,b,where)
}
parity({snapshots,stream},expected,"vectors");
console.log(JSON.stringify({groups,parity_rows:snapshots.length+stream.length,scope:"new_synthetic_P4_distance_probe_controls_only"}));
