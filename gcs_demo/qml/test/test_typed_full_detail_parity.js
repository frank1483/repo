"use strict";
// New entrypoint only. Does not load any previously passed test entrypoint.
const assert=require("assert"),fs=require("fs"),path=require("path");
const c=require("./load_core")(),copy=x=>JSON.parse(JSON.stringify(x));
const CONTRACT="typed_full_orchestration_detail_P1_comparison_P2_bounds_v1";
const NAMES=["safe_detail","risk_alternative","uncertain_multi","p1_unsupported","p2_unsupported","hybrid_detail","version_detail","endpoint_unknown"];
function vehicle(name,uncertain){const v=c.loadAirframe(JSON.parse(fs.readFileSync(path.join(__dirname,"../../airframes",name+".json"),"utf8")));v.battery_wh=100;v.airframe_profile.uncertainty={power_pct:uncertain?10:0,capacity_pct:uncertain?5:0,wind_mps:uncertain?1:0};return v;}
function feed(name="fw_example",uncertain=false){return c.createTypedFullMissionOrchestrator(vehicle(name,uncertain),{cell_r_ohm:0.004,cell_empty_v:3.55,min_samples:3},"radio:home",{min_samples:3,min_distance_span_m:100},{min_samples:3,min_span_s:2},2,2,30,3);}
function step(i,name){
    const pose={lat:23,lon:120,alt:80,air_heading_deg:0},arc={kind:"arc",v_air:16,angle_deg:180,clockwise:true,radius_m:40};
    const candidate={id:"current",entry:pose,events:Array.from({length:4},()=>copy(arc)),mode:"fw"},probe={id:"A",outbound_events:[copy(arc)],return_events:[copy(arc)]};
    const pct=name==="risk_alternative"?20.5:90,used=5*i;
    const m={mission:{t_s:i,...pose,battery_pct:pct,wind_mps:0,wind_from:0,mode:"fw"},capacity:{t_s:i,battery_id:"battery:one",used_wh:used,voltage:(4.2-0.65/80*used-5*0.004)*4,current_a:5,cell_count:4,battery_pct:pct},link:{t_s:i,distance_m:i*100,link_pct:90-i*10},wind:{t_s:i,wind_mps:0}};
    const r={capacity_session_id:"session:one",mission:{mission_version:name==="version_detail"&&i===3?"v2":"v1",recovery_reference_id:"site:home",p1:{current_id:"current",candidates:[candidate]},p2:{target:{lat:23,lon:120,alt:80,tolerance_m:0.001},probes:[probe],mode:"fw"}},link:{reference_id:"radio:home",probes:[{id:"probe:A",distance_m:200,eta_s:10}]}};
    if(["risk_alternative","uncertain_multi"].includes(name))r.mission.p1.candidates.push({...copy(candidate),id:"alternative",events:[copy(arc)]});
    if(name==="uncertain_multi")r.mission.p2.probes.push({id:"B",outbound_events:Array.from({length:3},()=>copy(arc)),return_events:[copy(arc)]});
    if(name==="p1_unsupported")candidate.events=[copy(arc),{kind:"landing"}];
    if(name==="p2_unsupported")probe.return_events=[{kind:"landing"}];
    if(name==="endpoint_unknown")r.mission.p2.target.lat+=0.001;
    return {sequence:i,measurement:m,request:r};
}
// Backend exception prose is not a stable code. Retain its key/type/presence;
// normalize ONLY unsupported-row reason leaves inside the two detail trees
// and P2 scenario rows. All raw Python outputs remain in the evidence file.
function normalize(out){
    const o=copy(out);
    function diagnostic(x){if(!x||typeof x!=="object")return;if(x.status==="unsupported"&&Object.hasOwn(x,"reason")){assert.equal(typeof x.reason,"string");assert(x.reason.length>0);x.reason="<backend diagnostic>";}for(const v of Object.values(x))diagnostic(v);}
    diagnostic(o.predictors.P1.snapshot.comparison);
    for(const p of o.predictors.P2.snapshot.probes){diagnostic(p.bounds);for(const s of p.scenarios)diagnostic(s);}
    return o;
}
// Output-only equivalence: exactly 360 degrees is north (0 degrees).
// Do not modulo arbitrary numbers or change the saved runtime/vector evidence.
const HEADING_LEAVES=new Set(["exit_air_heading_deg","exit_ground_heading_deg"]);
function canonicalHeading(n){assert(Number.isFinite(n)&&n>=0&&n<=360,"heading outside [0,360]");return n===360?0:n;}
function compare(a,b,label="output",headingEquivalence=false,leaf=""){
    assert.equal(typeof a,typeof b,label);
    if(typeof a==="number"){
        const av=headingEquivalence&&HEADING_LEAVES.has(leaf)?canonicalHeading(a):a;
        const bv=headingEquivalence&&HEADING_LEAVES.has(leaf)?canonicalHeading(b):b;
        assert(Number.isFinite(av)&&Number.isFinite(bv)&&Math.abs(av-bv)<=1e-8*Math.max(1,Math.abs(av),Math.abs(bv)),label+": "+a+" / "+b);return;
    }
    if(a===null||b===null||typeof a!=="object"){assert.strictEqual(a,b,label);return;}
    assert.equal(Array.isArray(a),Array.isArray(b),label);assert.deepEqual(Object.keys(a).sort(),Object.keys(b).sort(),label);
    for(const k of Object.keys(a))compare(a[k],b[k],label+"."+k,headingEquivalence,k);
}
function details(o){
    const p1=o.predictors.P1.snapshot.comparison,p2=o.predictors.P2.snapshot.probes;
    assert(p1&&p1.candidates.length>0);assert(p2.length>0);
    for(const p of p2){assert(Object.hasOwn(p,"bounds"));assert(p.bounds.scenarios.length>0);assert(Object.hasOwn(p.bounds,"nominal"));assert(Object.hasOwn(p.bounds,"conservative"));assert(Object.hasOwn(p.bounds,"optimistic"));}
    for(const k of ["feasible","executable","landing_modeled","continuous_boundary_known"])assert.strictEqual(o[k],false);
    return {p1,p2};
}
function localCases(){return NAMES.map(name=>{const airframe=name==="hybrid_detail"?"vtol_example":"fw_example",uncertain=name==="uncertain_multi",f=feed(airframe,uncertain),steps=Array.from({length:4},(_,i)=>step(i,name));return {name,airframe,uncertain,steps,outputs:steps.map(s=>f.tick(s.sequence,s.measurement,s.request))};});}
function controls(cases){
    let groups=0;const test=(name,fn)=>{fn();groups++;console.log("ok "+name);},get=n=>cases.find(x=>x.name===n).outputs.at(-1);
    test("all detail trees and safety flags present",()=>{for(const x of cases)for(const o of x.outputs)details(o);});
    test("safe detailed bounds have numeric extrema and nested replay",()=>{const {p1,p2}=details(get("safe_detail"));assert.equal(p1.candidates[0].status,"ok");assert(p1.candidates[0].bounds.nominal.base_estimate.legs.length);assert(Number.isFinite(p2[0].bounds.low_pct));assert(p2[0].bounds.nominal.base_estimate.legs.length);});
    test("alternative ordering and sampled ranking retained",()=>{const {p1}=details(get("risk_alternative"));assert.deepEqual(p1.candidates.map(x=>x.id),["current","alternative"]);assert.equal(p1.best_energy_id,"alternative");});
    test("nonzero uncertainty and multiple probe details retained",()=>{const {p1,p2}=details(get("uncertain_multi"));assert.equal(p1.candidates.length,2);assert.equal(p2.length,2);assert(p1.candidates[0].bounds.scenarios.length>1);assert(p2.every(x=>x.bounds.scenarios.length>1));});
    test("unsupported P1 comparison preserves evidence",()=>{const {p1}=details(get("p1_unsupported"));assert.equal(p1.candidates[0].status,"unsupported");assert.equal(typeof p1.candidates[0].reason,"string");assert.strictEqual(get("p1_unsupported").predictors.P1.active,null);});
    test("unsupported P2 bounds preserve nulls and diagnostic shape",()=>{const out=get("p2_unsupported"),{p2}=details(out);assert.strictEqual(p2[0].bounds.available,false);assert.strictEqual(p2[0].bounds.low_pct,null);assert.strictEqual(p2[0].bounds.conservative,null);assert.equal(normalize(out).predictors.P2.snapshot.probes[0].bounds.nominal.reason,"<backend diagnostic>");});
    test("endpoint unknown retains supported bounds without clearance",()=>{const o=get("endpoint_unknown"),{p2}=details(o);assert.equal(o.predictors.P2.status,"unknown");assert.strictEqual(p2[0].bounds.available,true);assert.strictEqual(p2[0].scenarios[0].endpoint_supported,false);});
    test("numeric nested detail and missing-field mutations are detected",()=>{
        const original=normalize(get("safe_detail"));
        for(const edit of [x=>x.predictors.P1.snapshot.comparison.candidates[0].bounds.nominal.base_estimate.legs[0].time_s+=1,x=>x.predictors.P2.snapshot.probes[0].bounds.scenarios[0].end_pct+=1,x=>{delete x.predictors.P1.snapshot.comparison.best_energy_id;},x=>{delete x.predictors.P2.snapshot.probes[0].bounds;}]){const altered=copy(original);edit(altered);assert.throws(()=>compare(original,altered));}
        const altered=copy(original);altered.predictors.P1.snapshot.reason="changed stable reason";assert.throws(()=>compare(original,altered));
    });
    test("version reset and hybrid details remain explicit",()=>{const o=get("version_detail");assert.equal(o.mission_version,"v2");assert.deepEqual(o.reset_reasons_by_predictor.P1,["mission_version_changed"]);assert.equal(get("hybrid_detail").predictors.P1.snapshot.mode,"fw");});
    return groups;
}
function angleControls(){
    let groups=0;const test=(name,fn)=>{fn();groups++;console.log("ok "+name);};
    test("both documented heading leaves accept exact 0/360 in either direction",()=>{
        for(const k of HEADING_LEAVES){compare({[k]:0},{[k]:360},"output",true);compare({[k]:360},{[k]:0},"output",true);}
    });
    test("ordinary numeric fields and input headings keep original comparison",()=>{
        for(const k of ["time_s","angle_deg","air_heading_deg","wind_from","battery_pct"])
            assert.throws(()=>compare({[k]:0},{[k]:360},"output",true));
        for(const k of HEADING_LEAVES)assert.throws(()=>compare({[k]:0},{[k]:360},"input"));
    });
    test("non-equivalent and out-of-domain headings are rejected",()=>{
        for(const n of [1,359.999,720,-360,-1,NaN,Infinity])
            assert.throws(()=>compare({exit_ground_heading_deg:0},{exit_ground_heading_deg:n},"output",true));
    });
    test("existing tolerance and exact key/null/type/order checks remain",()=>{
        compare({exit_ground_heading_deg:123},{exit_ground_heading_deg:123+1e-9},"output",true);
        const a={exit_ground_heading_deg:0,x:[1,2],n:null};
        for(const b of [{exit_ground_heading_deg:360,x:[2,1],n:null},{exit_ground_heading_deg:360,x:[1,2]},
            {exit_ground_heading_deg:"360",x:[1,2],n:null},{exit_ground_heading_deg:360,x:[1,2],n:0}])
            assert.throws(()=>compare(a,b,"output",true));
    });
    test("normalization preserves raw heading values and unlisted reason leaves",()=>{
        const a={predictors:{P1:{snapshot:{comparison:{exit_ground_heading_deg:360}}},P2:{snapshot:{probes:[]}}}};
        const before=JSON.stringify(a),n=normalize(a);compare(n,normalize(a),"output",true);
        assert.equal(JSON.stringify(a),before);assert.equal(n.predictors.P1.snapshot.comparison.exit_ground_heading_deg,360);
        assert.throws(()=>compare({reason:"stable A"},{reason:"stable B"},"output",true));
    });
    return groups;
}
if(require.main===module){
    assert.equal(process.argv.length,3,"usage: raw Python vector path or --angle-controls-only or --controls-only");
    if(process.argv[2]==="--controls-only")console.log(JSON.stringify({groups:controls(localCases()),python_parity:"NOT_RUN"}));
    else if(process.argv[2]==="--angle-controls-only")console.log(JSON.stringify({angle_groups:angleControls(),python_parity:"NOT_RUN"}));
    else {
        const groups=angleControls();
        const v=JSON.parse(fs.readFileSync(process.argv[2],"utf8").replace(/^\uFEFF/,""));assert.equal(v.contract,CONTRACT);assert.deepEqual(v.cases.map(x=>x.name),NAMES);
        let ticks=0;for(const item of v.cases){assert.equal(item.airframe,item.name==="hybrid_detail"?"vtol_example":"fw_example");assert.strictEqual(item.uncertain,item.name==="uncertain_multi");assert.equal(item.steps.length,4);assert.equal(item.outputs.length,4);const f=feed(item.airframe,item.uncertain);for(let i=0;i<4;i++){const s=item.steps[i];compare(s,step(i,item.name),item.name+".input["+i+"]");const actual=f.tick(s.sequence,s.measurement,s.request);details(actual);details(item.outputs[i]);compare(normalize(actual),normalize(item.outputs[i]),item.name+"["+i+"]",true);ticks++;}}
        assert.equal(ticks,32);console.log(JSON.stringify({groups,parity_cases:v.cases.length,ticks,detail_fields_omitted:0,exception_reason_text:"normalized_only_in_documented_detail_subtrees",heading_equivalence:"exact_360_to_0_output_exit_headings_only_v1"}));
    }
}
module.exports={step,normalize,compare,localCases,controls,angleControls};
