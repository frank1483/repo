"use strict";
// New controls for Claude FIRST execution; no legacy suites invoked.
const assert=require("assert"),fs=require("fs"),path=require("path"),c=require("./load_core")();
function vehicle(name="fw_example"){const v=c.loadAirframe(JSON.parse(fs.readFileSync(path.join(__dirname,"../../airframes",name+".json"),"utf8")));v.battery_wh=100;return v;}
const options=()=>({cell_r_ohm:0.004,cell_empty_v:3.55});
const samples=(total=80,n=100,span=20)=>Array.from({length:n},(_,i)=>({t_s:i,battery_id:"battery:one",used_wh:span*i/(n-1),voltage:(4.2-(4.2-3.55)/total*(span*i/(n-1))-5*0.004)*4,current_a:5,cell_count:4,battery_pct:90}));
const snap=(r=samples(),o=options(),v=vehicle())=>c.typedBatteryCapacitySnapshot(v,r,o),near=(a,b)=>assert(Math.abs(a-b)<=1e-8*Math.max(1,Math.abs(a),Math.abs(b)));
let groups=0;function test(name,f){f();groups++;console.log("ok "+name);}
test("capacity and compensation",()=>{const o=snap();assert.equal(o.status,"ok");assert.strictEqual(o.risk,true);near(o.estimated_total_wh,80);near(o.estimated_remaining_wh,60);near(o.soc_overestimate_pct,30);});
test("healthy and low SOC",()=>{assert.strictEqual(snap(samples(120)).risk,false);const r=samples();r.forEach(x=>x.battery_pct=10);const o=snap(r);assert.strictEqual(o.risk,false);assert.equal(o.conservative_remaining_wh,10);});
test("warmup and span boundary",()=>{assert.equal(snap(samples(80,89)).reason,"insufficient_samples");assert.equal(snap(samples(80,100,7.9)).reason,"insufficient_energy_span");assert.equal(snap(samples(80,100,8)).status,"ok");});
test("gap and flat",()=>{let r=samples();r.slice(50).forEach(x=>x.t_s+=31);assert.equal(snap(r).reason,"telemetry_gap");r=samples();r.forEach(x=>x.voltage=16);assert.equal(snap(r).reason,"degenerate_fit");});
test("rising noisy exhausted",()=>{let r=samples();r.forEach((x,i)=>x.voltage=15+i*0.001);assert.equal(snap(r).reason,"capacity_fit_unreliable");r=samples();r.forEach((x,i)=>x.voltage+=(i%2?-1:1)*0.5);assert.equal(snap(r).reason,"capacity_fit_unreliable");assert.equal(snap(samples(),{...options(),cell_empty_v:4.5}).reason,"extrapolated_empty_reached");});
test("strict risk thresholds",()=>{const o=snap();for(const [k,v]of [["capacity_ratio_limit",o.capacity_ratio],["soc_gap_limit_pct",o.soc_overestimate_pct]])assert.strictEqual(snap(samples(),{...options(),[k]:v}).risk,false);});
test("counter origin preserved",()=>{const r=samples();r.forEach(x=>x.used_wh+=10);const o=snap(r);near(o.estimated_total_wh,90);near(o.estimated_remaining_wh,60);});
test("session and charging rejected",()=>{for(const [k,v]of [["battery_id","battery:two"],["cell_count",5],["current_a",-1],["used_wh",-1],["t_s",0]]){const r=samples();r[r.length-1][k]=v;assert.throws(()=>snap(r));}});
test("schema finite and bounded",()=>{for(const [k,v]of [["cell_count",true],["battery_pct",true],["used_wh",NaN],["voltage",Infinity],["battery_id","bad id"],["battery_id","battery:one\n"]]){const r=samples();r[0][k]=v;assert.throws(()=>snap(r));}for(const r of [[],samples(80,602),[{}]])assert.throws(()=>snap(r));const r=samples();r[0].extra=1;assert.throws(()=>snap(r));});
test("options profile hybrid",()=>{for(const o of [null,{}, {...options(),extra:1},{...options(),min_samples:true},{...options(),cell_empty_v:null},{...options(),min_r2:2}])assert.throws(()=>snap(samples(),o));assert.throws(()=>snap(samples(),options(),vehicle("x500")));assert.equal(snap(samples(),options(),vehicle("vtol_example")).status,"ok");});
test("immutable inputs and no action claim",()=>{const r=samples(),cfg=options(),before=JSON.stringify([r,cfg]),o=snap(r,cfg);assert.equal(JSON.stringify([r,cfg]),before);o.assumptions.cell_r_ohm=1;assert.deepEqual(cfg,options());for(const k of ["measured_capacity","sensor_validated","probability_interval","energy_correction_applied","feasible","executable"])assert.strictEqual(o[k],false);assert.deepEqual(o.candidates,[]);assert.strictEqual(o.rule_choice,null);});
test("gap equality and plateau",()=>{let r=samples();r.slice(50).forEach(x=>x.t_s+=29);assert.equal(snap(r).status,"ok");r=samples();r[1].used_wh=r[0].used_wh;r[1].voltage=r[0].voltage;assert.equal(snap(r).status,"ok");});
function compare(a,b,label){if(typeof a==="number"&&typeof b==="number"){near(a,b);return;}assert.equal(typeof a,typeof b,label);if(a===null||b===null||typeof a!=="object"){assert.strictEqual(a,b,label);return;}assert.equal(Array.isArray(a),Array.isArray(b),label);assert.deepEqual(Object.keys(a).sort(),Object.keys(b).sort(),label);for(const k of Object.keys(a))compare(a[k],b[k],label+"."+k);}
assert.equal(process.argv.length,3,"Python vector JSON path required");
const vectors=JSON.parse(fs.readFileSync(process.argv[2],"utf8").replace(/^\uFEFF/,""));assert.equal(vectors.contract,"typed_capacity_snapshot_v1");assert.equal(vectors.cases.length,13);
for(const item of vectors.cases)compare(snap(item.samples,item.options,vehicle(item.airframe)),item.output,item.name);
console.log(JSON.stringify({groups,parity_cases:vectors.cases.length}));
