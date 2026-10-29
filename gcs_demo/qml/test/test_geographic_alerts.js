// NEW synthetic contracts. Claude owns the first functional execution.
"use strict";
const assert=require("assert"),fs=require("fs"),path=require("path"),c=require("./load_core")();
const load=id=>c.loadAirframe(JSON.parse(fs.readFileSync(path.join(__dirname,"../../airframes",id+".json"),"utf8")));
const clone=x=>JSON.parse(JSON.stringify(x)),v=load("fw_example"),entry={lat:23,lon:120,alt:80,air_heading_deg:0},metres=Math.PI*6371000/180;
const straight=(north=100,p=entry)=>({kind:"straight",lat:p.lat+north/metres,lon:p.lon,alt:p.alt,ground_mps:16});
const arc=()=>({kind:"arc",v_air:16,angle_deg:90,clockwise:true,radius_m:40});
const candidate=(id="C1",north=100,extra={})=>Object.assign({id,entry:clone(entry),events:[straight(north)]},extra);
const bounds=(events=[straight()],w=c.wind(0,0),vehicle=v,pct=100,mode=undefined,p=entry)=>c.geographicWindRouteBounds(vehicle,p,events,w,pct,mode);
const run=(items=[candidate()],w=c.wind(0,0),vehicle=v,pct=100)=>c.evaluateGeographicAlertCandidates(vehicle,items,w,pct);
const near=(a,b)=>assert(Math.abs(a-b)<=1e-8*Math.max(1,Math.abs(a),Math.abs(b)),a+" != "+b);
let groups=0;
function test(name,f){f();groups++;console.log("PASS "+name)}
test("nominal and 13 full corner scenarios",()=>{
    const r=bounds(undefined,c.wind(3,0));assert(r.available);assert.equal(r.scenarios.length,13);
    assert.deepEqual(r.nominal.wind,{speed_mps:3,from_deg:0});
    assert(r.scenarios.every(s=>JSON.stringify(s.base_estimate.projection.origin)===JSON.stringify({lat:23,lon:120,alt:80})));
});
test("zero uncertainty deduplicates to one",()=>{
    const x=clone(v);x.airframe_profile.uncertainty={power_pct:0,capacity_pct:0,wind_mps:0};
    const r=bounds(undefined,undefined,x);assert.equal(r.scenarios.length,1);assert.equal(r.low_pct,r.high_pct);
});
test("calm wind clamps and deduplicates corners",()=>{
    const r=bounds();assert.equal(r.scenarios.length,9);assert.deepEqual([...new Set(r.scenarios.map(s=>s.wind.speed_mps))],[0,2]);
    assert.equal(new Set(r.scenarios.map(s=>JSON.stringify([s.wind.speed_mps,s.power_multiplier,s.capacity_multiplier]))).size,9);
});
test("energy capacity scaling and extrema",()=>{
    const r=bounds(undefined,undefined,undefined,73);
    r.scenarios.forEach(s=>{near(s.energy_wh,s.base_energy_wh*s.power_multiplier);near(s.end_pct,73-s.energy_wh/s.capacity_wh*100)});
    assert.equal(r.low_pct,Math.min(...r.scenarios.map(s=>s.end_pct)));assert.equal(r.high_pct,Math.max(...r.scenarios.map(s=>s.end_pct)));
});
test("calibration applied once",()=>{
    const a=bounds(),b=bounds(undefined,undefined,Object.assign({},v,{calib:1.3}));
    a.scenarios.forEach((x,i)=>near(b.scenarios[i].energy_wh,x.energy_wh*1.3));
});
test("negative percentages and no flight authority",()=>{
    const r=bounds(undefined,undefined,undefined,0);assert(r.high_pct<0);
    ["feasible","executable","return_inferred","landing_modeled","common_endpoint_enforced","wind_direction_varied"].forEach(k=>assert.strictEqual(r[k],false));
});
test("all scenarios keep both whole-route legs",()=>{
    const r=bounds([straight(100),straight(200)]);assert(r.available);assert(r.scenarios.every(s=>s.base_estimate.legs.length===2));
});
test("unsupported perturbation invalidates both extrema",()=>{
    const r=bounds(undefined,c.wind(0,270));assert.equal(r.nominal.status,"ok");assert(!r.available);assert.strictEqual(r.low_pct,null);assert.strictEqual(r.high_pct,null);
    assert(r.scenarios.some(s=>s.status==="unsupported"&&/tangent/.test(s.reason)));
});
test("nominal failure still replays perturbed scenarios",()=>{
    const e=straight();e.lon+=12.5/(metres*Math.cos(entry.lat*Math.PI/180));e.ground_mps=Math.hypot(2,16);
    const r=bounds([e],c.wind(0,270));assert.equal(r.nominal.status,"unsupported");assert(r.scenarios.some(s=>s.status==="ok"));assert.strictEqual(r.low_pct,null);
});
test("curves drift to different scenario endpoints",()=>{
    const r=bounds([arc()],c.wind(3,270));assert(r.available);
    const ends=r.scenarios.map(s=>s.base_estimate.exit_geographic.lon);assert(Math.max(...ends)>Math.min(...ends));assert(!r.common_endpoint_enforced);
});
test("path budget rechecked under perturbed wind",()=>{
    const r=bounds([{kind:"loiter",v_air:16,duration_s:550,clockwise:true,radius_m:40}],c.wind(1,270));
    assert.equal(r.nominal.status,"ok");assert(!r.available);assert(r.scenarios.some(s=>s.status==="unsupported"&&/10 km/.test(s.reason)));
});
test("input and nominal evidence detached",()=>{
    const items=[candidate()],w=c.wind(0,0),before=JSON.stringify([v,items,w]),r=run(items,w),b=r.candidates[0].bounds;
    b.nominal.base_estimate.legs[0].exit_geographic.lat=0;assert.notEqual(b.scenarios[0].base_estimate.legs[0].exit_geographic.lat,0);
    assert.equal(JSON.stringify([v,items,w]),before);
});
test("hybrid explicit FW required",()=>{
    const h=load("vtol_example");assert.throws(()=>bounds(undefined,undefined,h));assert.throws(()=>bounds(undefined,undefined,h,100,"mc"));assert(bounds(undefined,undefined,h,100,"fw").available);
});
test("MC and missing profile rejected",()=>{
    assert.throws(()=>bounds(undefined,undefined,load("x500")));assert.throws(()=>bounds(undefined,undefined,Object.assign({},v,{airframe_profile:null})));
});
test("invalid global values rejected",()=>{
    assert.throws(()=>bounds(undefined,{speed_mps:-1,from_deg:0}));assert.throws(()=>bounds(undefined,{speed_mps:NaN,from_deg:0}));
    assert.throws(()=>bounds(undefined,undefined,undefined,true));assert.throws(()=>bounds(undefined,undefined,undefined,101));
    const x=clone(v);x.airframe_profile.uncertainty.capacity_pct=100;assert.throws(()=>bounds(undefined,undefined,x));
});
test("geographic restrictions remain visible",()=>{
    [[],[Object.assign(straight(),{alt:81})],[Object.assign(straight(),{extra:true})],[straight(11000)]].forEach(ev=>{
        const r=bounds(ev);assert(!r.available);assert(r.scenarios.every(s=>s.status==="unsupported"));
    });
});
test("rank eligible alternatives with stable ties",()=>{
    const r=run([candidate("long",200),candidate("first"),candidate("tie")]);assert.equal(r.best_energy_id,"first");
    assert(!r.feasible&&!r.executable&&r.candidates.every(x=>!x.feasible));
});
test("unsupported rows and energy deficit excluded",()=>{
    const r=run([candidate("bad",100,{events:[]}),candidate("ok")]);assert.deepEqual(r.candidates.map(x=>x.status),["unsupported","ok"]);
    assert.equal(r.best_energy_id,"ok");assert.strictEqual(run(undefined,undefined,undefined,0).best_energy_id,null);
});
test("batch schema IDs and limits",()=>{
    [[],[candidate(),candidate()],[candidate("")],[candidate("x".repeat(129))],[candidate("x",100,{action:"RTL"})],Array(17).fill(candidate()),[{id:"x",points:[],ground_mps:16}]].forEach(items=>assert.throws(()=>run(items)));
    assert.equal(run([candidate("😀".repeat(128))]).candidates[0].status,"ok");
});
test("nonfinite cycles undefined and sparse data rejected",()=>{
    const a=candidate();a.entry.lat=NaN;const b=candidate();b.events.push(b);const d=candidate();d.events.push(undefined);
    const s=candidate();s.events.length=2;[a,b,d,s].forEach(x=>assert.throws(()=>run([x])));
});
function summary(r){return {best_energy_id:r.best_energy_id,feasible:r.feasible,executable:r.executable,candidates:r.candidates.map(x=>({
    id:x.id,status:x.status,sampled_energy_feasible:x.sampled_energy_feasible,low_pct:x.bounds?x.bounds.low_pct:null,high_pct:x.bounds?x.bounds.high_pct:null,
    scenarios:x.bounds?x.bounds.scenarios.map(s=>({status:s.status,wind:s.wind,end_pct:s.end_pct===undefined?null:s.end_pct,exit_geographic:s.base_estimate?s.base_estimate.exit_geographic:null})):[]
}))}}
if(process.argv[2]) {
    const rows=JSON.parse(fs.readFileSync(process.argv[2],"utf8").replace(/^\uFEFF/,""));assert.equal(rows.length,4);
    function compare(a,b){if(typeof a==="number")near(a,b);else if(a&&typeof a==="object"){assert.deepEqual(Object.keys(a).sort(),Object.keys(b).sort());Object.keys(a).forEach(k=>compare(a[k],b[k]))}else assert.strictEqual(a,b)}
    rows.forEach(row=>compare(summary(run(row.candidates,row.wind,load(row.profile),row.start_pct)),row.result));console.log("PASS 4 Python/JS scenario and endpoint parity summaries");
}
console.log("NEW geographic alert groups: "+groups);
