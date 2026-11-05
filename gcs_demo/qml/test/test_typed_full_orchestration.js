"use strict";
// New controls + real Python-vector parity. No old test entrypoint is loaded.
const assert=require("assert"),fs=require("fs"),path=require("path"),c=require("./load_core")();
const copy=x=>JSON.parse(JSON.stringify(x));
function vehicle(name="fw_example"){const v=c.loadAirframe(JSON.parse(fs.readFileSync(path.join(__dirname,"../../airframes",name+".json"),"utf8")));v.battery_wh=100;v.airframe_profile.uncertainty={power_pct:0,capacity_pct:0,wind_mps:0};return v;}
const options=()=>({cell_r_ohm:0.004,cell_empty_v:3.55,min_samples:3});
const linkOptions=()=>({min_samples:3,min_distance_span_m:100}),windOptions=()=>({min_samples:3,min_span_s:2});
function request(version="v1",session="session:one"){
    const pose={lat:23,lon:120,alt:80,air_heading_deg:0},arc={kind:"arc",v_air:16,angle_deg:180,clockwise:true,radius_m:40};
    return {capacity_session_id:session,mission:{mission_version:version,recovery_reference_id:"site:home",
        p1:{current_id:"current",candidates:[{id:"current",entry:pose,events:Array.from({length:4},()=>copy(arc)),mode:"fw"}]},
        p2:{target:{lat:23,lon:120,alt:80,tolerance_m:0.001},probes:[{id:"A",outbound_events:[copy(arc)],return_events:[copy(arc)]}],mode:"fw"}},
        link:{reference_id:"radio:home",probes:[{id:"probe:A",distance_m:200,eta_s:10}]}};
}
function measurement(i){const used=5*i;return {mission:{t_s:i,lat:23,lon:120,alt:80,air_heading_deg:0,battery_pct:90,wind_mps:i,wind_from:0,mode:"fw"},capacity:{t_s:i,battery_id:"battery:one",used_wh:used,voltage:(4.2-0.65/80*used-5*0.004)*4,current_a:5,cell_count:4,battery_pct:90},link:{t_s:i,distance_m:i*100,link_pct:90-i*10},wind:{t_s:i,wind_mps:i}};}
const feed=(name="fw_example")=>c.createTypedFullMissionOrchestrator(vehicle(name),options(),"radio:home",linkOptions(),windOptions(),2,2,30,3);
function compare(a,b,label="output"){
    assert.equal(typeof a,typeof b,label);
    if(typeof a==="number"){assert(Number.isFinite(a)&&Number.isFinite(b)&&Math.abs(a-b)<=1e-8*Math.max(1,Math.abs(a),Math.abs(b)),label+": "+a+" / "+b);return;}
    if(a===null||b===null||typeof a!=="object"){assert.strictEqual(a,b,label);return;}
    assert.equal(Array.isArray(a),Array.isArray(b),label);assert.deepEqual(Object.keys(a).sort(),Object.keys(b).sort(),label);
    for(const k of Object.keys(a))compare(a[k],b[k],label+"."+k);
}
function summary(out){const o=copy(out);delete o.predictors.P1.snapshot.comparison;for(const p of o.predictors.P2.snapshot.probes){delete p.bounds;for(const s of p.scenarios)delete s.reason;}return o;}
let groups=0;
function test(name,fn){fn();groups++;console.log("ok "+name);}
function pair(){const f=feed(),clean=feed();for(let i=0;i<3;i++){f.tick(i,measurement(i),request());clean.tick(i,measurement(i),request());}return [f,clean];}
function retry(mutator){const [f,clean]=pair(),m=measurement(3),r=request();mutator(m,r);assert.throws(()=>f.tick(3,m,r));compare(f.tick(3,measurement(3),request()),clean.tick(3,measurement(3),request()));}
test("full caller exactly matches five standalone predictors",()=>{
    const f=feed(),a=c.createTypedMissionOrchestrator(vehicle(),options(),2,2,30,3),b=c.createTypedLinkDistancePredictor(vehicle(),"radio:home",linkOptions(),2,2),d=c.createTypedWindTrendPredictor(vehicle(),windOptions(),2,2);
    for(let i=0;i<6;i++){const m=measurement(i),r=request(),o=f.tick(i,m,r),old=a.tick(i,{mission:m.mission,capacity:m.capacity},{mission:r.mission,capacity_session_id:r.capacity_session_id});compare(o.predictors,{...old.predictors,P4:b.tick(i,m.link,r.link.probes,"v1"),P5:d.tick(i,m.wind,"v1")});}
});
test("late P4 rejection rolls back every child",()=>retry(m=>m.link.link_pct=101));
test("late P5 exception rolls back every child",()=>{
    const vm=require("vm"),src=fs.readFileSync(path.join(__dirname,"../GcpMissionCore.js"),"utf8").replace(/^\.pragma library/,""),context={module:{exports:{}},Math,JSON,String,Number,Array};vm.createContext(context);vm.runInContext(src,context);
    const make=()=>context.module.exports.createTypedFullMissionOrchestrator(vehicle(),options(),"radio:home",linkOptions(),windOptions(),2,2,30,3),f=make(),clean=make();
    for(let i=0;i<3;i++){f.tick(i,measurement(i),request());clean.tick(i,measurement(i),request());}
    const original=context.typedWindTrendSnapshot;context.typedWindTrendSnapshot=()=>{throw Error("injected late P5");};
    assert.throws(()=>f.tick(3,measurement(3),request()),/injected late P5/);context.typedWindTrendSnapshot=original;
    compare(f.tick(3,measurement(3),request()),clean.tick(3,measurement(3),request()));
});
test("late final snapshot exception rolls back every child",()=>{
    // Inject at the actual VM global, after all child ticks.
    const vm=require("vm"),src=fs.readFileSync(path.join(__dirname,"../GcpMissionCore.js"),"utf8").replace(/^\.pragma library/,""),context={module:{exports:{}},Math,JSON,String,Number,Array};vm.createContext(context);vm.runInContext(src,context);
    const make=()=>context.module.exports.createTypedFullMissionOrchestrator(vehicle(),options(),"radio:home",linkOptions(),windOptions(),2,2,30,3),f=make(),clean=make();
    for(let i=0;i<3;i++){f.tick(i,measurement(i),request());clean.tick(i,measurement(i),request());}
    const snapshot=context.geographicAlertSnapshot;context.geographicAlertSnapshot=x=>{if(x&&x.caller_scope==="atomic_measured_P1_P2_P3_P4_P5_only")throw Error("injected final snapshot");return snapshot(x);};
    assert.throws(()=>f.tick(3,measurement(3),request()),/injected final snapshot/);context.geographicAlertSnapshot=snapshot;
    compare(f.tick(3,measurement(3),request()),clean.tick(3,measurement(3),request()));
});
test("common time rejection is atomic",()=>retry(m=>m.wind.t_s=4));
test("common wind rejection is atomic",()=>retry(m=>m.wind.wind_mps=4));
test("reference identity fixed per instance",()=>retry((m,r)=>r.link.reference_id="radio:other"));
test("battery session requires new mission version",()=>retry((m,r)=>r.capacity_session_id="session:two"));
test("version resets P4 P5 with provenance",()=>{const [f]=pair(),o=f.tick(3,measurement(3),request("v2"));for(const k of ["P4","P5"]){assert.deepEqual(o.reset_reasons_by_predictor[k],["mission_version_changed"]);assert.strictEqual(o.predictors[k].active,null);}for(const e of o.events){assert.equal(e.mission_version,"v2");assert.equal(e.session_id,o.session_id);assert.equal(e.battery_id,o.battery_id);if(e.predictor_id==="P4")assert.equal(e.reference_id,"radio:home");}});
test("gap resets all five without false resolve",()=>{const [f]=pair(),m=measurement(3);for(const x of Object.values(m))x.t_s=34;const o=f.tick(3,m,request());for(const k of o.evaluated_predictors)assert.deepEqual(o.reset_reasons_by_predictor[k],["telemetry_gap"]);assert(!o.events.some(e=>e.type==="resolve"));});
test("unsupported P4 probe stays unknown",()=>{const [f]=pair(),r=request();r.link.probes[0].distance_m=9999;const o=f.tick(3,measurement(3),r);assert.equal(o.predictors.P4.status,"unknown");assert.strictEqual(o.predictors.P4.active,null);assert(!o.predictors.P4.events.some(e=>e.type==="resolve"));assert.strictEqual(o.executable,false);});
test("detached inputs outputs",()=>{const f=feed(),clean=feed(),m=measurement(0),r=request(),before=JSON.stringify([m,r]),out=f.tick(0,m,r);clean.tick(0,measurement(0),request());assert.equal(JSON.stringify([m,r]),before);out.predictors.P4.events.length=0;m.link.distance_m=999;r.link.probes.length=0;compare(f.tick(1,measurement(1),request()),clean.tick(1,measurement(1),request()));});
test("fork isolation at all three child layers",()=>{const m=measurement(0),r=request(),items=[{f:c.createTypedMissionOrchestrator(vehicle(),options(),2,2,30,3),args:[{mission:m.mission,capacity:m.capacity},{mission:r.mission,capacity_session_id:r.capacity_session_id}],next:[{mission:measurement(1).mission,capacity:measurement(1).capacity},{mission:r.mission,capacity_session_id:r.capacity_session_id}]},{f:c.createTypedLinkDistancePredictor(vehicle(),"radio:home",linkOptions(),2,2),args:[m.link,r.link.probes,"v1"],next:[measurement(1).link,r.link.probes,"v1"]},{f:c.createTypedWindTrendPredictor(vehicle(),windOptions(),2,2),args:[m.wind,"v1"],next:[measurement(1).wind,"v1"]}];for(const x of items){x.f.tick(0,...x.args);const branch=x.f.fork(),control=x.f.fork();branch.tick(1,...x.next);compare(x.f.tick(1,...x.next),control.tick(1,...x.next));}});
test("exact envelopes and safe flags",()=>{retry(m=>m.extra=1);retry((m,r)=>r.link.extra=1);const o=feed("vtol_example").tick(0,measurement(0),request());assert.deepEqual(o.evaluated_predictors,["P1","P2","P3","P4","P5"]);assert.deepEqual(o.unassessed_predictors,[]);for(const k of ["continuous_boundary_known","return_now_evaluated","recovery_reference_verified","telemetry_freshness_verified","measured_capacity","sensor_validated","independent_window_evidence","energy_correction_applied","landing_modeled","feasible","executable"])assert.strictEqual(o[k],false);assert.strictEqual(o.latest_return_deadline_s,null);assert.strictEqual(o.rule_choice,null);assert.deepEqual(o.candidates,[]);for(const k of ["P3","P4","P5"])assert.equal(o.predictors[k].status,"unknown");});
if(process.argv[2]==="--controls-only")console.log(JSON.stringify({groups,python_parity:"NOT_RUN"}));
else {
    assert.equal(process.argv.length,3,"real Python vector file required or --controls-only");
    const vectors=JSON.parse(fs.readFileSync(process.argv[2],"utf8").replace(/^\uFEFF/,""));assert.equal(vectors.contract,"typed_full_orchestration_P1_P5_v1");assert.equal(vectors.cases.length,13);
    let steps=0,rejections=0;
    for(const item of vectors.cases){const f=feed(item.airframe);assert.equal(item.steps.length,item.outputs.length);for(let i=0;i<item.steps.length;i++){const s=item.steps[i];let actual;try{actual={output:summary(f.tick(s.sequence,s.measurement,s.request))};}catch(e){if(!s.expect_error)throw e;actual={error:true};rejections++;}assert.equal(!!actual.error,s.expect_error);compare(actual,item.outputs[i],item.name+"["+i+"]");steps++;}}
    assert.equal(steps,71);assert.equal(rejections,6);console.log(JSON.stringify({groups,parity_cases:13,steps,rejections}));
}
