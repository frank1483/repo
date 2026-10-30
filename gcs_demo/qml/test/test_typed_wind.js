"use strict";
// NEW first-execution controls; product runtime is loaded only on Claude host.
const assert=require("assert"),fs=require("fs"),path=require("path"),c=require("./load_core")();
const CFG={min_samples:3,min_span_s:2,window_s:10,max_gap_s:3,horizon_s:20},FAST={min_samples:2,min_span_s:1,window_s:1,max_gap_s:1};
function vehicle(key="fw_example"){return c.loadAirframe(JSON.parse(fs.readFileSync(path.join(__dirname,"../../airframes",key+".json"),"utf8")))}
const samples=(vs,start=0,step=1)=>vs.map((wind_mps,i)=>({t_s:start+i*step,wind_mps}));
const snap=(vs,options=CFG)=>c.typedWindTrendSnapshot(vehicle(),samples(vs),options);
const feed=(options=FAST,r=2,k=2)=>c.createTypedWindTrendPredictor(vehicle(),options,r,k);
const tick=(f,i,v,version="v1",time=i)=>f.tick(i,{t_s:time,wind_mps:v},version);
const types=r=>r.events.map(e=>e.type);
let groups=0;
function test(name,f){f();groups++;console.log("PASS "+name)}
test("limit equality needs no fit",()=>{const r=c.typedWindTrendSnapshot(vehicle(),samples([12]));assert.equal(r.status,"ok");assert.strictEqual(r.risk,true);assert.equal(r.lead_s,0)});
test("warmup and insufficient span stay unknown",()=>{assert.strictEqual(snap([1,2]).risk,null);assert.equal(c.typedWindTrendSnapshot(vehicle(),samples([1,2,3],0,0.1),CFG).reason,"insufficient_span")});
test("hand calculated linear crossing and horizon",()=>{const r=snap([1,2,3]);assert.equal(r.trend_mps_per_s,1);assert.equal(r.r2,1);assert.equal(r.lead_s,9);assert(snap([1,2,3],{...CFG,horizon_s:9}).risk);assert(!snap([1,2,3],{...CFG,horizon_s:8.5}).risk)});
test("constant falling low-fit and slope policy",()=>{assert.equal(snap([2,2,2]).reason,"constant_wind");assert.strictEqual(snap([3,2,1]).risk,false);assert.equal(snap([2,4,2]).reason,"trend_fit_unreliable");assert.strictEqual(snap([2,4,2]).risk,null);assert.equal(snap([1,2,3],{...CFG,min_slope_mps2:1}).reason,"trend_not_rising")});
test("default units and stable large timestamps",()=>{const vs=Array.from({length:60},(_,i)=>1+i/10),a=c.typedWindTrendSnapshot(vehicle(),samples(vs)),b=c.typedWindTrendSnapshot(vehicle(),samples(vs,1e12));assert(Math.abs(a.lead_s-51)<1e-9);assert.equal(a.lead_s,b.lead_s)});
test("window and contiguous suffix",()=>{assert.equal(snap(Array(11).fill(1),{...CFG,window_s:4}).sample_count,5);const r=c.typedWindTrendSnapshot(vehicle(),[0,1,10,11,12].map(t_s=>({t_s,wind_mps:1})),{...CFG,window_s:20});assert.equal(r.sample_count,3);assert.equal(r.span_s,2)});
test("measurements and ordering required",()=>{
    [[],samples(Array(602).fill(1)),samples([1,2],0,0),[{t_s:0}],samples([true]),samples([-1])].forEach(rows=>assert.throws(()=>c.typedWindTrendSnapshot(vehicle(),rows)));
    ["t_s","wind_mps"].forEach(k=>[true,NaN,Infinity].forEach(v=>assert.throws(()=>c.typedWindTrendSnapshot(vehicle(),[{t_s:0,wind_mps:0,[k]:v}]))));
});
test("policy and profile scope",()=>{
    [{typo:1},{min_samples:true},{min_samples:1},{min_samples:602},{min_span_s:181},{max_gap_s:0},{min_r2:1.1},{horizon_s:-1}].forEach(cfg=>assert.throws(()=>feed(cfg)));
    assert.throws(()=>c.createTypedWindTrendPredictor(vehicle("x500")));assert(c.typedWindTrendSnapshot(vehicle("vtol_example"),samples([100])).risk);
});
test("raise and clear require their own streak",()=>{const f=feed(),r=[13,13,1,1].map((v,i)=>tick(f,i,v));assert.deepEqual(r.map(types),[["known"],["raise"],[],["resolve"]]);assert.deepEqual(r.map(x=>x.active),[false,true,true,false])});
test("unknown breaks latch without resolve",()=>{const f=feed(CFG,1,1);assert(tick(f,0,13).active);const r=tick(f,1,1);assert.deepEqual(types(r),["unknown"]);assert.strictEqual(r.active,null);assert(tick(f,2,13).active)});
test("version and telemetry gap reset",()=>{const f=feed();tick(f,0,13);tick(f,1,13);const r=tick(f,2,13,"v2");assert.deepEqual(types(r),["reset","known"]);assert.strictEqual(r.active,false);assert.equal(r.raise_streak,1);assert.equal(r.reset_reason,"mission_version_changed");const g=tick(f,3,1,"v2",10);assert.deepEqual(types(g),["reset","unknown"]);assert.equal(g.sample_count,1);assert.equal(g.reset_reason,"telemetry_gap")});
test("failed tick cannot alter prior version or streak",()=>{const f=feed();tick(f,0,13);assert.throws(()=>tick(f,1,13,"v2",0));assert.throws(()=>f.tick(1,{t_s:1},"v2"));assert.throws(()=>tick(f,1,13,"版本"));assert(tick(f,1,13).active);assert.throws(()=>tick(f,1,13,"v2",2))});
test("strict versions sequences thresholds",()=>{[true,-1,0.5,9007199254740992].forEach(s=>assert.throws(()=>tick(feed(),s,1)));[null,"","a".repeat(129),"v1\n"].forEach(v=>assert.throws(()=>tick(feed(),0,1,v)));[true,0,0.5,10001].forEach(n=>assert.throws(()=>feed(FAST,n)))});
test("snapshotted inputs detached output and no authority",()=>{const v=vehicle(),cfg={...CFG},f=c.createTypedWindTrendPredictor(v,cfg,1,1);v.airframe_profile.limits.wind_limit_mps=0;cfg.min_samples=2;const rec={t_s:0,wind_mps:1,battery_pct:0},before=JSON.stringify(rec),r=f.tick(0,rec,"v1");r.finding.value="edited";assert.equal(JSON.stringify(rec),before);assert.equal(r.limit_mps,12);assert.strictEqual(tick(f,1,1).active,null);assert.deepEqual(r.finding.candidates,[]);assert.strictEqual(r.finding.rule_choice,null);["feasible","executable","sensor_validated","direction_predicted","probability_interval"].forEach(k=>assert.strictEqual(r[k],false))});
test("history count is bounded",()=>{const f=feed({window_s:1000},1,1);let r;for(let i=0;i<605;i++)r=tick(f,i,1);assert.equal(r.sample_count,601)});

assert.equal(process.argv.length,3,"usage: node test_typed_wind.js <Python --vectors JSON>");
const expected=JSON.parse(fs.readFileSync(process.argv[2],"utf8").replace(/^\uFEFF/,""));
const snapshots=[snap([1]),snap([12]),snap([2,2,2]),snap([1,2,3]),snap([3,2,1]),snap([2,4,2]),snap([1,2,3],{...CFG,horizon_s:9}),snap([1,2,3],{...CFG,horizon_s:8.5})];
const f=feed(),stream=[tick(f,0,13),tick(f,1,13),tick(f,2,1),tick(f,3,1),tick(f,4,13),tick(f,5,13),tick(f,6,13,"v2"),tick(f,7,13,"v2"),tick(f,8,1,"v2",20),tick(f,9,1,"v2",21)];
function parity(a,b,where){
    if(typeof a==="number"&&typeof b==="number"){assert(Math.abs(a-b)<=1e-9*Math.max(1,Math.abs(a),Math.abs(b)),where);return}
    if(a&&b&&typeof a==="object"&&typeof b==="object"){assert.deepEqual(Object.keys(a).sort(),Object.keys(b).sort(),where+" keys");Object.keys(a).forEach(k=>parity(a[k],b[k],where+"."+k));return}
    assert.strictEqual(a,b,where);
}
parity({snapshots,stream},expected,"vectors");
console.log(JSON.stringify({groups,parity_rows:snapshots.length+stream.length,scope:"new_synthetic_P5_controls_only"}));
