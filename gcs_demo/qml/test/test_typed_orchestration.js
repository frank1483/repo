"use strict";
// NEW controls; Claude owns first functional execution. Requires real Python vectors.
const assert=require("assert"),fs=require("fs"),path=require("path"),c=require("./load_core")();
function vehicle(name="fw_example"){const v=c.loadAirframe(JSON.parse(fs.readFileSync(path.join(__dirname,"../../airframes",name+".json"),"utf8")));v.battery_wh=100;v.airframe_profile.uncertainty={power_pct:0,capacity_pct:0,wind_mps:0};return v;}
const options=()=>({cell_r_ohm:0.004,cell_empty_v:3.55,min_samples:3}),copy=x=>JSON.parse(JSON.stringify(x));
function request(version="v1",session="session:one"){
    const pose={lat:23,lon:120,alt:80,air_heading_deg:0},arc={kind:"arc",v_air:16,angle_deg:180,clockwise:true,radius_m:40};
    return {capacity_session_id:session,mission:{mission_version:version,recovery_reference_id:"site:home",
        p1:{current_id:"current",candidates:[{id:"current",entry:pose,events:Array.from({length:4},()=>copy(arc)),mode:"fw"}]},
        p2:{target:{lat:23,lon:120,alt:80,tolerance_m:0.001},probes:[{id:"A",outbound_events:[copy(arc)],return_events:[copy(arc)]}],mode:"fw"}}};
}
function measurement(i,pct=90,t=i){const used=5*i;return {mission:{t_s:t,lat:23,lon:120,alt:80,air_heading_deg:0,battery_pct:pct,wind_mps:0,wind_from:0,mode:"fw"},capacity:{t_s:t,battery_id:"battery:one",used_wh:used,voltage:(4.2-0.65/80*used-5*0.004)*4,current_a:5,cell_count:4,battery_pct:pct}};}
const feed=(name="fw_example")=>c.createTypedMissionOrchestrator(vehicle(name),options(),2,2,30,3);
let groups=0;function test(name,fn){fn();groups++;console.log("ok "+name);}
function compare(a,b,label="output"){
    assert.equal(typeof a,typeof b,label);
    if(typeof a==="number"){assert(Number.isFinite(a)&&Number.isFinite(b)&&Math.abs(a-b)<=1e-8*Math.max(1,Math.abs(a),Math.abs(b)),label);return;}
    if(a===null||b===null||typeof a!=="object"){assert.strictEqual(a,b,label);return;}
    assert.equal(Array.isArray(a),Array.isArray(b),label);assert.deepEqual(Object.keys(a).sort(),Object.keys(b).sort(),label);
    for(const k of Object.keys(a))compare(a[k],b[k],label+"."+k);
}
function summary(out){const o=copy(out);delete o.predictors.P1.snapshot.comparison;for(const p of o.predictors.P2.snapshot.probes){delete p.bounds;for(const s of p.scenarios)delete s.reason;}return o;}
test("initial unknown remains visible",()=>{const o=feed().tick(0,measurement(0),request());assert.equal(o.status,"unknown");assert.equal(o.predictors.P1.status,"ok");assert.equal(o.predictors.P2.status,"ok");assert.strictEqual(o.predictors.P3.active,null);assert.deepEqual(o.unassessed_predictors,["P4","P5"]);});
test("exact standalone outputs",()=>{const f=feed(),a=c.createTypedMissionSampleFeed(vehicle(),2,2,30),b=c.createTypedCapacityFeed(vehicle(),options(),2,2,3);for(let i=0;i<6;i++){const m=measurement(i,i<4?90:0),r=request(),o=f.tick(i,m,r),ma=a.tick(i,m.mission,r.mission),ca=b.tick(i,m.capacity,r.capacity_session_id);compare(o.predictors,{P1:ma.predictors.P1,P2:ma.predictors.P2,P3:ca});assert.deepEqual(o.events.map(e=>e.predictor),ma.events.concat(ca.events).map(e=>e.predictor));}});
test("late P3 reject rolls back P1/P2",()=>{const f=feed(),clean=feed();for(let i=0;i<4;i++){f.tick(i,measurement(i),request());clean.tick(i,measurement(i),request());}const bad=measurement(4,0);bad.capacity.current_a=-1;assert.throws(()=>f.tick(4,bad,request()));compare(f.tick(4,measurement(4,0),request()),clean.tick(4,measurement(4,0),request()));});
test("P2 reject does not consume P3",()=>{const f=feed(),r=request();r.mission.p2.probes[0].outbound_events=[];assert.throws(()=>f.tick(0,measurement(0),r));compare(f.tick(0,measurement(0),request()),feed().tick(0,measurement(0),request()));});
test("common time and SOC",()=>{for(const k of ["t_s","battery_pct"]){const f=feed(),m=measurement(0);m.capacity[k]++;assert.throws(()=>f.tick(0,m,request()));assert.equal(f.tick(0,measurement(0),request()).sequence,0);}});
test("session change needs version",()=>{const f=feed();f.tick(0,measurement(0),request());assert.throws(()=>f.tick(1,measurement(1),request("v1","session:two")));const o=f.tick(1,measurement(1),request("v2","session:two"));assert.deepEqual(o.reset_reasons_by_predictor,{P1:["mission_version_changed"],P2:["mission_version_changed"],P3:["session_changed"]});assert(!o.events.some(e=>e.type==="resolve"));});
test("version preserves capacity",()=>{const f=feed();f.tick(0,measurement(0),request());const o=f.tick(1,measurement(1),request("v2"));assert.equal(o.predictors.P3.window_sample_count,2);assert.deepEqual(o.reset_reasons_by_predictor.P3,[]);});
test("battery retry",()=>{const f=feed(),m=measurement(1);f.tick(0,measurement(0),request());m.capacity.battery_id="battery:two";assert.throws(()=>f.tick(1,m,request("v2")));const o=f.tick(1,m,request("v2","session:two"));assert.equal(o.battery_id,"battery:two");assert.equal(o.predictors.P3.window_sample_count,1);});
test("gap resets all",()=>{const f=feed();for(let i=0;i<4;i++)f.tick(i,measurement(i),request());const o=f.tick(4,measurement(4,90,34),request());for(const x of Object.values(o.reset_reasons_by_predictor))assert.deepEqual(x,["telemetry_gap"]);assert.equal(o.predictors.P3.window_sample_count,1);assert(!o.events.some(e=>e.type==="resolve"));});
test("gap equality",()=>{const f=feed();f.tick(0,measurement(0),request());const o=f.tick(1,measurement(1,90,30),request());for(const x of Object.values(o.reset_reasons_by_predictor))assert.deepEqual(x,[]);});
test("unsupported P2 independent",()=>{const f=feed();for(let i=0;i<3;i++)f.tick(i,measurement(i),request());const r=request();r.mission.p2.probes[0].return_events=[{kind:"landing"}];const o=f.tick(3,measurement(3),r);assert.equal(o.predictors.P2.status,"unknown");assert.equal(o.predictors.P1.status,"ok");assert.equal(o.predictors.P3.status,"ok");assert(!o.events.some(e=>e.type==="resolve"&&e.predictor==="P2"));});
test("copy isolation",()=>{const v=vehicle(),cfg=options(),f=c.createTypedMissionOrchestrator(v,cfg,2,2,30,3);cfg.min_samples=601;v.airframe_profile.uncertainty.power_pct=100;const m=measurement(0),r=request(),before=JSON.stringify([m,r]),o=f.tick(0,m,r);assert.equal(JSON.stringify([m,r]),before);o.predictors.P3.snapshot.assumptions.min_samples=601;r.mission.p2.target.lat=24;f.tick(1,measurement(1),request());assert.equal(f.tick(2,measurement(2),request()).predictors.P3.status,"ok");});
test("exact envelopes sequence and flags",()=>{for(const [m,r] of [[{...measurement(0),extra:1},request()],[measurement(0),{...request(),extra:1}],[{mission:measurement(0).mission},request()]])assert.throws(()=>feed().tick(0,m,r));const f=feed("vtol_example"),o=f.tick(0,measurement(0),request());assert.throws(()=>f.tick(0,measurement(1),request()));assert.equal(f.tick(1,measurement(1),request()).sequence,1);for(const e of o.events)for(const k of ["sequence","mission_version","recovery_reference_id","session_id","battery_id"])assert.equal(e[k],o[k]);for(const k of ["continuous_boundary_known","return_now_evaluated","recovery_reference_verified","telemetry_freshness_verified","measured_capacity","sensor_validated","independent_window_evidence","energy_correction_applied","landing_modeled","feasible","executable"])assert.strictEqual(o[k],false);assert.strictEqual(o.latest_return_deadline_s,null);assert.strictEqual(o.rule_choice,null);assert.deepEqual(o.candidates,[]);});
test("fork branches independently",()=>{
    const m=measurement(0),r=request(),a=c.createTypedMissionSampleFeed(vehicle(),2,2,30),b=c.createTypedCapacityFeed(vehicle(),options(),2,2,3);
    a.tick(0,m.mission,r.mission);b.tick(0,m.capacity,r.capacity_session_id);
    const aa=a.fork(),bb=b.fork(),a2=a.fork(),b2=b.fork(),n=measurement(1),rr=request();
    const ao=aa.tick(1,n.mission,rr.mission),bo=bb.tick(1,n.capacity,rr.capacity_session_id);
    ao.predictors.P1.snapshot.current_id="mutated";bo.snapshot.assumptions.min_samples=601;
    compare(a.tick(1,n.mission,rr.mission),a2.tick(1,n.mission,rr.mission));
    compare(b.tick(1,n.capacity,rr.capacity_session_id),b2.tick(1,n.capacity,rr.capacity_session_id));
});
assert.equal(process.argv.length,3,"real first Python vectors path required");
const vectors=JSON.parse(fs.readFileSync(process.argv[2],"utf8").replace(/^\uFEFF/,""));
assert.equal(vectors.contract,"typed_orchestration_P1_P2_P3_v1");assert.equal(vectors.cases.length,9);
let steps=0,rejections=0;
for(const item of vectors.cases){const f=feed(item.airframe);assert.equal(item.steps.length,item.outputs.length);for(let i=0;i<item.steps.length;i++){const s=item.steps[i];let actual;try{actual={output:summary(f.tick(s.sequence,s.measurement,s.request))};}catch(e){actual={error:true};rejections++;}compare(actual,item.outputs[i],item.name+"["+i+"]");steps++;}}
console.log(JSON.stringify({groups,parity_cases:vectors.cases.length,steps,rejections}));
