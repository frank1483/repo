"use strict";
// NEW authored controls; do not execute before Claude's first-execution handoff.
const assert=require("assert"),fs=require("fs"),path=require("path"),c=require("./load_core")();
const clone=x=>JSON.parse(JSON.stringify(x)),ENTRY={lat:23,lon:120,alt:80,air_heading_deg:0},TARGET={lat:23,lon:120,alt:80,tolerance_m:0.001};
function vehicle(name="fw_example"){const v=c.loadAirframe(JSON.parse(fs.readFileSync(path.join(__dirname,"../../airframes",name+".json"),"utf8")));v.airframe_profile.uncertainty={power_pct:0,capacity_pct:0,wind_mps:0};return v}
const arc=()=>({kind:"arc",v_air:16,angle_deg:180,clockwise:true,radius_m:40});
function request(version="v1"){return {mission_version:version,recovery_reference_id:"site:home",
    p1:{current_id:"current",candidates:[{id:"current",entry:clone(ENTRY),events:Array.from({length:4},arc),mode:"fw"}]},
    p2:{target:clone(TARGET),probes:[{id:"A",outbound_events:[arc()],return_events:[arc()]}],mode:"fw"}}}
const rec=(t=1,pct=100)=>({...ENTRY,t_s:t,battery_pct:pct,wind_mps:0,wind_from:0,mode:"fw"});
const kinds=(o,code)=>o.events.filter(e=>e.predictor===code).map(e=>e.type);
function summary(output){const o=clone(output);delete o.predictors.P1.snapshot.comparison;o.predictors.P2.snapshot.probes.forEach(p=>{delete p.bounds;p.scenarios.forEach(s=>delete s.reason)});return o}
function vectors(){
    const traces=[];
    for(const name of ["latch","version","gap","p2_unknown","p1_unknown","version_and_gap","hybrid","different_reference"]){
        const f=c.createTypedMissionSampleFeed(vehicle(name==="hybrid"?"vtol_example":"fw_example"),2,2,5),rows=[f.tick(1,rec(1,0),request())];
        if(name==="latch"||name==="hybrid"){[0,100,100].forEach((pct,j)=>rows.push(f.tick(j+2,rec(j+2,pct),request())))}
        else if(name==="version")rows.push(f.tick(2,rec(2,0),request("v2")));
        else if(name==="gap")rows.push(f.tick(2,rec(7,0),request()));
        else if(name==="version_and_gap")rows.push(f.tick(2,rec(7,0),request("v2")));
        else if(name==="different_reference"){const r=request("v2");r.recovery_reference_id="site:alternate";rows.push(f.tick(2,rec(2),r))}
        else{
            rows.push(f.tick(2,rec(2,0),request()));const r=request();
            if(name==="p2_unknown")r.p2.probes[0].return_events=[{kind:"landing"}];else r.p1.candidates[0].events[3]={kind:"landing"};
            rows.push(f.tick(3,rec(3,0),r));rows.push(f.tick(4,rec(4,0),request()));
        }
        traces.push({name,outputs:rows.map(summary)});
    }
    return {contract:"mission_sample_feed_v1",traces};
}
let groups=0;
function test(name,fn){fn();groups++;console.log("PASS "+name)}
test("safe initial means samples only",()=>{const o=c.createTypedMissionSampleFeed(vehicle()).tick(1,rec(),request());assert.equal(o.status,"ok");for(const code of ["P1","P2"]){assert.strictEqual(o.predictors[code].active,false);assert.deepEqual(kinds(o,code),["known"])}assert.deepEqual(o.unassessed_predictors,["P3","P4","P5"])});
test("independent raise and clear hysteresis",()=>{const rows=vectors().traces[0].outputs;for(const code of ["P1","P2"]){assert.deepEqual(rows.map(r=>r.predictors[code].active),[false,true,true,false]);assert.deepEqual(kinds(rows[1],code),["raise"]);assert.deepEqual(kinds(rows[2],code),[]);assert.deepEqual(kinds(rows[3],code),["resolve"]);assert.equal(rows[2].predictors[code].finding.value,"sampled_risk_latched_pending_clear")}});
test("P2 unknown never resolves or clears P1",()=>{const rows=vectors().traces[3].outputs;assert.strictEqual(rows[2].predictors.P2.active,null);assert.deepEqual(kinds(rows[2],"P2"),["unknown"]);assert.strictEqual(rows[2].predictors.P1.active,true);assert.strictEqual(rows[3].predictors.P2.active,false);assert.equal(rows[3].predictors.P2.raise_streak,1);assert.deepEqual(kinds(rows[3],"P2"),["known"])});
test("P1 unknown does not hide P2",()=>{const o=vectors().traces[4].outputs[2];assert.equal(o.status,"unknown");assert.strictEqual(o.predictors.P1.active,null);assert.deepEqual(kinds(o,"P1"),["unknown"]);assert.strictEqual(o.predictors.P2.active,true)});
test("version and telemetry gap reset",()=>{const ts=vectors().traces;for(const [i,reasons]of [[1,["mission_version_changed"]],[2,["telemetry_gap"]],[5,["mission_version_changed","telemetry_gap"]]]){const o=ts[i].outputs[1];assert.deepEqual(o.reset_reasons,reasons);for(const code of ["P1","P2"]){assert.deepEqual(kinds(o,code),["reset","known"]);assert.equal(o.predictors[code].raise_streak,1);const e=o.events.find(e=>e.predictor===code&&e.type==="reset");assert.strictEqual(e.active,null);assert.deepEqual(e.evidence,[])}}});
test("gap equality retains streak",()=>{const f=c.createTypedMissionSampleFeed(vehicle(),2,2,5);f.tick(1,rec(1,0),request());const o=f.tick(2,rec(6,0),request());assert.deepEqual(o.reset_reasons,[]);assert.strictEqual(o.predictors.P2.active,true)});
test("P2 schema error rolls back both latches",()=>{const f=c.createTypedMissionSampleFeed(vehicle(),3,2);f.tick(1,rec(1,0),request());const r=request();delete r.p2.target.tolerance_m;assert.throws(()=>f.tick(2,rec(2,0),r));const o=f.tick(2,rec(2,0),request());for(const code of ["P1","P2"]){assert.equal(o.predictors[code].raise_streak,2);assert.strictEqual(o.predictors[code].active,false)}});
test("reject unrelated outbound",()=>{const r=request();r.p2.probes[0].outbound_events[0].radius_m=41;assert.throws(()=>c.createTypedMissionSampleFeed(vehicle()).tick(1,rec(),r))});
test("pose alignment includes all alternatives",()=>{for(const [k,v]of [["lat",24],["air_heading_deg",1],["alt",81],["lat",true]]){const r=request(),other=clone(r.p1.candidates[0]);other.id="other";other.entry[k]=v;r.p1.candidates.push(other);assert.throws(()=>c.createTypedMissionSampleFeed(vehicle()).tick(1,rec(),r))}});
test("identity and target changes need a version",()=>{for(const variant of ["current","reference","target"]){const f=c.createTypedMissionSampleFeed(vehicle());f.tick(1,rec(),request());const r=request();if(variant==="current")r.p1.current_id=r.p1.candidates[0].id="other";else if(variant==="reference")r.recovery_reference_id="site:other";else r.p2.target.tolerance_m=20;assert.throws(()=>f.tick(2,rec(2),r));r.mission_version="v2";assert.deepEqual(f.tick(2,rec(2),r).reset_reasons,["mission_version_changed"])}});
test("measured FW mode is explicit for FW and hybrid",()=>{assert.equal(vectors().traces[6].outputs[0].status,"ok");for(const variant of ["missing","mc","p1","p2"]){const tm=rec(),r=request();if(variant==="missing")delete tm.mode;else if(variant==="mc")tm.mode="mc";else if(variant==="p1")delete r.p1.candidates[0].mode;else r.p2.mode="mc";assert.throws(()=>c.createTypedMissionSampleFeed(vehicle()).tick(1,tm,r))}});
test("sequence and time errors do not consume",()=>{const f=c.createTypedMissionSampleFeed(vehicle());f.tick(1,rec(),request());for(const [s,t]of [[1,rec(2)],[true,rec(2)],[2,rec(1)],[2,rec(0)]])assert.throws(()=>f.tick(s,t,request()));assert.equal(f.tick(2,rec(2),request()).sequence,2)});
test("finite measured values and required fields",()=>{for(const [k,v]of [["battery_pct",true],["wind_mps",-1],["lat",76],["t_s",Infinity],["alt",null]]){const tm=rec();tm[k]=v;assert.throws(()=>c.createTypedMissionSampleFeed(vehicle()).tick(1,tm,request()))}const tm=rec();delete tm.wind_from;assert.throws(()=>c.createTypedMissionSampleFeed(vehicle()).tick(1,tm,request()))});
test("constructor limits",()=>{for(const opts of [[true,10,30],[3,0,30],[3,10,0],[3,10,NaN]])assert.throws(()=>c.createTypedMissionSampleFeed(vehicle(),...opts));const v=c.loadAirframe(JSON.parse(fs.readFileSync(path.join(__dirname,"../../airframes/x500.json"),"utf8")));assert.throws(()=>c.createTypedMissionSampleFeed(v))});
test("detached vehicle request result",()=>{const v=vehicle(),r=request(),tm=rec(1,0),f=c.createTypedMissionSampleFeed(v,2,2),before=JSON.stringify([r,tm]),o=f.tick(1,tm,r);assert.equal(JSON.stringify([r,tm]),before);r.p2.target.tolerance_m=50;o.predictors.P2.raise_streak=999;v.airframe_profile.uncertainty.wind_mps=8;assert.strictEqual(f.tick(2,rec(2,0),request()).predictors.P2.active,true)});
test("repeat unknown then recover",()=>{const f=c.createTypedMissionSampleFeed(vehicle(),2,2),r=request();r.p2.probes[0].return_events=[{kind:"landing"}];assert.deepEqual(kinds(f.tick(1,rec(),r),"P2"),["unknown"]);const o=f.tick(2,rec(2),r);assert.deepEqual(kinds(o,"P2"),[]);assert.strictEqual(o.predictors.P2.active,null);assert.deepEqual(kinds(f.tick(3,rec(3),request()),"P2"),["known"])});
test("future P2 deficit is not an immediate emergency",()=>{const o=c.createTypedMissionSampleFeed(vehicle(),1,1).tick(1,rec(1,0),request());assert.equal(o.predictors.P1.finding.severity,2);assert.equal(o.predictors.P2.finding.severity,4);assert.strictEqual(o.predictors.P2.finding.lead_s,null)});
test("no continuous boundary or action",()=>{for(const o of [c.createTypedMissionSampleFeed(vehicle()).tick(1,rec(),request()),c.createTypedMissionSampleFeed(vehicle(),1,1).tick(1,rec(1,0),request())]){for(const k of ["continuous_boundary_known","return_now_evaluated","recovery_reference_verified","telemetry_freshness_verified","landing_modeled","feasible","executable"])assert.strictEqual(o[k],false);assert.strictEqual(o.latest_return_deadline_s,null);assert.strictEqual(o.rule_choice,null);assert.deepEqual(o.candidates,[]);for(const e of o.events){assert.strictEqual(e.lead_s,null);assert.strictEqual(e.latest_return_deadline_s,null);assert.strictEqual(e.continuous_boundary_known,false);assert.strictEqual(e.executable,false)}}});
test("request schema and identity",()=>{for(const k of ["mission_version","recovery_reference_id","p1","p2"]){const r=request();delete r[k];assert.throws(()=>c.createTypedMissionSampleFeed(vehicle()).tick(1,rec(),r))}for(const v of ["","bad space","x\n",true]){const r=request();r.mission_version=v;assert.throws(()=>c.createTypedMissionSampleFeed(vehicle()).tick(1,rec(),r))}});
test("changed recovery reference remains unverified",()=>{const o=vectors().traces[7].outputs[1];assert.equal(o.recovery_reference_id,"site:alternate");assert.strictEqual(o.recovery_reference_verified,false)});
assert.equal(process.argv.length,3,"usage: node test_typed_mission_feed.js <Python --vectors JSON>");
const expected=JSON.parse(fs.readFileSync(process.argv[2],"utf8").replace(/^\uFEFF/,""));
function parity(a,b,where){
    if(typeof a==="number"&&typeof b==="number"){assert(Math.abs(a-b)<=1e-8*Math.max(1,Math.abs(a),Math.abs(b)),where);return}
    if(Array.isArray(a)||Array.isArray(b)){assert(Array.isArray(a)&&Array.isArray(b),where);assert.equal(a.length,b.length,where);a.forEach((v,i)=>parity(v,b[i],where+"["+i+"]"));return}
    if(a&&b&&typeof a==="object"&&typeof b==="object"){assert.deepEqual(Object.keys(a).sort(),Object.keys(b).sort(),where);for(const k of Object.keys(a))parity(a[k],b[k],where+"."+k);return}
    assert.strictEqual(a,b,where);
}
const actual=vectors();assert.equal(expected.contract,"mission_sample_feed_v1");assert.equal(expected.traces.length,8);parity(actual,expected,"feed");
console.log(JSON.stringify({groups,parity_traces:actual.traces.length,parity_ticks:actual.traces.reduce((n,t)=>n+t.outputs.length,0)}));
