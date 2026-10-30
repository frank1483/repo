"use strict";
// NEW authored controls. First execution: Python vectors, then this file once.
const assert=require("assert"),fs=require("fs"),path=require("path"),c=require("./load_core")();
const ENTRY={lat:23,lon:120,alt:80,air_heading_deg:0};
const TARGET={lat:23,lon:120,alt:80,tolerance_m:0.001};
const clone=x=>JSON.parse(JSON.stringify(x));
function rawVehicle(name="fw_example"){return c.loadAirframe(JSON.parse(fs.readFileSync(path.join(__dirname,"../../airframes",name+".json"),"utf8")))}
function vehicle(name="fw_example"){const v=rawVehicle(name);v.airframe_profile.uncertainty={power_pct:0,capacity_pct:0,wind_mps:0};return v}
const arc=()=>({kind:"arc",v_air:16,angle_deg:180,clockwise:true,radius_m:40});
const probe=(id="A",n=1,ret=n)=>({id,outbound_events:Array.from({length:n},arc),return_events:Array.from({length:ret},arc)});
const snap=(items=[probe()],v=vehicle(),pct=100,w=c.wind(0,0),target=TARGET,entry=ENTRY,mode)=>c.typedReturnProbeSnapshot(v,entry,target,items,w,pct,mode);
function summary(r){r=clone(r);r.probes.forEach(p=>{delete p.bounds;p.scenarios.forEach(s=>delete s.reason)});return r}
function vectors(){
    const one=snap(),two=snap([probe(),probe("B",2)]),used1=100-one.probes[0].low_pct,used2=100-two.probes[1].low_pct;
    const middle=vehicle().reserve_pct+(used1+used2)/2,s=one.probes[0].bounds.scenarios[0],v=vehicle();v.reserve_pct=0;
    return [one,two,snap([probe(),probe("B",2)],vehicle(),middle),snap([probe()],v,s.energy_wh/s.capacity_wh*100),snap([probe()],vehicle(),0),
        snap([probe()],vehicle(),100,c.wind(1,270)),snap([probe()],rawVehicle(),100,c.wind(0,0),{...TARGET,tolerance_m:100}),
        snap([probe()],vehicle("vtol_example"),100,c.wind(0,0),TARGET,ENTRY,"fw"),
        snap([probe()],vehicle(),100,c.wind(0,0),{...TARGET,lon:-179.9999,tolerance_m:100},{...ENTRY,lon:179.9999})].map(summary)
}
let groups=0;
function test(name,f){f();groups++;console.log("PASS "+name)}
test("full circle and calculated outbound time",()=>{const r=snap(),s=r.probes[0].scenarios[0];assert.equal(r.status,"ok");assert.strictEqual(r.sampled_energy_risk,false);assert(Math.abs(s.eta_s-Math.PI*40/16)<1e-9);assert(s.endpoint_supported);assert(Math.abs(s.exit_geographic.lat-ENTRY.lat)<1e-9)});
test("first discrete crossing and preceding feasible prefix",()=>{const r=vectors()[2];assert.strictEqual(r.sampled_energy_risk,true);assert.equal(r.first_sampled_infeasible_id,"B");assert.equal(r.last_sampled_feasible_prefix_id,"A");assert(Math.abs(r.first_sampled_infeasible_nominal_eta_s-2*Math.PI*40/16)<1e-9)});
test("exact reserve equality is supported",()=>{const r=vectors()[3];assert.strictEqual(r.sampled_energy_risk,false);assert.equal(r.probes[0].low_pct,0);assert.equal(r.last_sampled_feasible_prefix_id,"A")});
test("first sample risky preserves negative energy and no preceding prefix",()=>{const r=snap([probe()],vehicle(),0);assert(r.sampled_energy_risk);assert.equal(r.first_sampled_infeasible_id,"A");assert.strictEqual(r.last_sampled_feasible_prefix_id,null);assert(r.probes[0].low_pct<0)});
test("wind drift invalidates endpoint while energy remains available",()=>{const r=snap([probe()],vehicle(),100,c.wind(1,270));assert.equal(r.status,"unknown");assert(r.probes[0].bounds.available);assert.strictEqual(r.probes[0].scenarios[0].endpoint_supported,false);assert.strictEqual(r.sampled_energy_risk,null)});
test("every scenario must reach recovery target",()=>{const r=snap([probe()],rawVehicle());assert(r.probes[0].scenarios[0].endpoint_supported);assert(r.probes[0].scenarios.some(s=>!s.endpoint_supported));assert.equal(r.status,"unknown")});
test("explicit endpoint tolerance",()=>{const r=snap([probe()],vehicle(),100,c.wind(1,270),{...TARGET,tolerance_m:20});assert.equal(r.status,"ok");assert(r.probes[0].scenarios[0].endpoint_error_m>10)});
test("unsupported one poisons aggregate without hiding good row",()=>{const b=probe("B",2);b.return_events=[{kind:"landing"}];const r=snap([probe(),b]);assert.equal(r.probes[0].status,"ok");assert.equal(r.probes[1].status,"unknown");["sampled_energy_risk","first_sampled_infeasible_id","last_sampled_feasible_prefix_id"].forEach(k=>assert.strictEqual(r[k],null))});
test("feasibility reentry is diagnostic not a last safe boundary",()=>{const items=[probe("A",1,7),probe("B",2,2)],full=snap(items),used=full.probes.map(p=>100-p.low_pct),r=snap(items,vehicle(),vehicle().reserve_pct+(used[0]+used[1])/2);assert(r.sampled_feasibility_reentry);assert.equal(r.first_sampled_infeasible_id,"A");assert.strictEqual(r.last_sampled_feasible_prefix_id,null)});
test("outbound strict prefix ordering",()=>{[[probe("A",2),probe("B")],[probe(),probe("B")]].forEach(items=>assert.throws(()=>snap(items)));const b=probe("B",2);b.outbound_events[0].radius_m=41;assert.throws(()=>snap([probe(),b]))});
test("object field order irrelevant",()=>{const b=probe("B",2);b.outbound_events[0]=Object.fromEntries(Object.entries(arc()).reverse());assert.equal(snap([probe(),b]).status,"ok")});
test("malformed batch rejected",()=>{[[],Array(17).fill(probe()),[probe(),probe()],[{...probe(),action:"RTL"}],[{...probe(),return_events:[]}],[{...probe(),outbound_events:[0]}]].forEach(items=>assert.throws(()=>snap(items)))});
test("total replay budget",()=>assert.throws(()=>snap([probe("A",501)])));
test("target and entry contracts",()=>{const missing={...TARGET};delete missing.tolerance_m;[missing,{...TARGET,tolerance_m:-1},{...TARGET,tolerance_m:101},{...TARGET,tolerance_m:true},{...TARGET,alt:0}].forEach(t=>assert.throws(()=>snap([probe()],vehicle(),100,c.wind(0,0),t)));assert.throws(()=>snap([probe()],vehicle(),100,c.wind(0,0),TARGET,{...ENTRY,lat:76}))});
test("FW profile via airframeType and explicit hybrid mode",()=>{assert.equal(snap([probe()],vehicle("vtol_example"),100,c.wind(0,0),TARGET,ENTRY,"fw").status,"ok");[[vehicle("vtol_example"),undefined],[vehicle("vtol_example"),"mc"],[rawVehicle("x500"),undefined],[{...vehicle(),airframe_profile:null},undefined]].forEach(([v,m])=>assert.throws(()=>snap([probe()],v,100,c.wind(0,0),TARGET,ENTRY,m)))});
test("finite JSON and start percentage",()=>{[true,-1,101,NaN].forEach(p=>assert.throws(()=>snap([probe()],vehicle(),p)));const p=probe();p.return_events[0].radius_m=Infinity;assert.throws(()=>snap([p]))});
test("detached input and output",()=>{const items=[probe()],e=clone(ENTRY),t=clone(TARGET),before=JSON.stringify([items,e,t]),r=snap(items,vehicle(),100,c.wind(0,0),t,e);assert.equal(JSON.stringify([items,e,t]),before);r.probes[0].scenarios[0].exit_geographic.lat=0;assert.equal(JSON.stringify([items,e,t]),before);assert.equal(snap().status,"ok")});
test("no action or continuous boundary authority",()=>{const r=snap();["continuous_boundary_known","return_inferred","recovery_reference_verified","landing_modeled","wind_direction_varied","feasible","executable"].forEach(k=>assert.strictEqual(r[k],false));assert.deepEqual(r.candidates,[]);assert.strictEqual(r.rule_choice,null)});
test("date line endpoint is measured in wrapped adapter plane",()=>{const r=vectors()[8];assert.equal(r.status,"ok");assert(r.probes[0].scenarios[0].endpoint_error_m<30)});
assert.equal(process.argv.length,3,"usage: node test_typed_return.js <Python --vectors JSON>");
const expected=JSON.parse(fs.readFileSync(process.argv[2],"utf8").replace(/^\uFEFF/,""));
function parity(a,b,where){
    if(typeof a==="number"&&typeof b==="number"){assert(Math.abs(a-b)<=1e-8*Math.max(1,Math.abs(a),Math.abs(b)),where);return}
    if(a&&b&&typeof a==="object"&&typeof b==="object"){assert.deepEqual(Object.keys(a).sort(),Object.keys(b).sort(),where+" keys");Object.keys(a).forEach(k=>parity(a[k],b[k],where+"."+k));return}
    assert.strictEqual(a,b,where)
}
parity(vectors(),expected,"vectors");
console.log(JSON.stringify({groups,parity_rows:expected.length,scope:"new_explicit_P2_finite_probe_controls_only"}));
