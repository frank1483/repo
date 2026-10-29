// NEW synthetic controls. One first execution with Python four-row JSON.
"use strict";
const assert=require("assert"),fs=require("fs"),path=require("path"),c=require("./load_core")();
const clone=x=>JSON.parse(JSON.stringify(x)),entry={lat:23,lon:120,alt:80,air_heading_deg:0},metres=Math.PI*6371000/180;
function vehicle(id="fw_example") {
    const v=c.loadAirframe(JSON.parse(fs.readFileSync(path.join(__dirname,"../../airframes",id+".json"),"utf8")));
    v.airframe_profile.uncertainty={power_pct:0,capacity_pct:0,wind_mps:0};return v;
}
const candidate=(id="current",north=100)=>({id,entry:clone(entry),events:[{kind:"straight",lat:entry.lat+north/metres,lon:120,alt:80,ground_mps:16}]});
const snap=(pct=100,items=[candidate()],id="current",v=vehicle())=>c.geographicEnergyAlertSnapshot(v,items,id,c.wind(0,0),pct);
const tick=(p,seq,pct=100,items=[candidate()],id="current")=>p.tick(seq,items,id,c.wind(0,0),pct);
const predictor=(r=3,k=10,v=vehicle())=>c.createGeographicEnergyAlertPredictor(v,r,k);
let groups=0;
function test(name,f){f();groups++;console.log("PASS "+name)}
function summary(r){
    const out={};["status","current_id","sampled_energy_risk","nominal_end_pct","low_pct","high_pct","reserve_pct","feasible","executable","rule_choice"].forEach(k=>out[k]=r[k]);
    if(Object.prototype.hasOwnProperty.call(r,"sequence")){
        ["sequence","active","raise_streak","clear_streak"].forEach(k=>out[k]=r[k]);out.severity=r.finding?r.finding.severity:null;
    }
    return out;
}
test("two public exports and default arguments",()=>{
    assert.equal(typeof c.geographicEnergyAlertSnapshot,"function");assert.equal(typeof c.createGeographicEnergyAlertPredictor,"function");
    assert.equal(c.geographicEnergyAlertSnapshot(vehicle(),[candidate()],"current",c.wind(0,0)).start_pct,100);
    const r=tick(c.createGeographicEnergyAlertPredictor(vehicle()),0);assert.equal(r.raise_ticks,3);assert.equal(r.clear_ticks,10);
});
test("safe snapshot includes evidence",()=>{const r=snap();assert.equal(r.status,"ok");assert.strictEqual(r.sampled_energy_risk,false);assert.equal(r.low_pct,r.comparison.candidates[0].bounds.low_pct)});
test("current risk is separate from best alternative",()=>{const r=snap(20.1,[candidate("current",1000),candidate("alternative",1)]);assert(r.sampled_energy_risk);assert.equal(r.comparison.best_energy_id,"alternative");assert.strictEqual(r.rule_choice,null)});
test("unsupported is unknown rather than clear",()=>{const a=candidate();a.events[0].lon+=0.001;const r=snap(100,[a]);assert.equal(r.status,"unsupported");["sampled_energy_risk","low_pct","high_pct"].forEach(k=>assert.strictEqual(r[k],null))});
test("current id and unique candidate ids",()=>{assert.throws(()=>snap(100,[candidate()],"absent"));assert.throws(()=>snap(100,[candidate(),candidate()]));assert.throws(()=>snap(100,[candidate()],true))});
test("all entry pose fields must match",()=>{Object.keys(entry).forEach(k=>{const a=candidate("other");a.entry[k]+=0.001;assert.throws(()=>snap(100,[candidate(),a]),/identical entry/)})});
test("entry shape and booleans rejected",()=>{[null,{},Object.assign({},entry,{extra:1}),Object.assign({},entry,{alt:true})].forEach(e=>{const a=candidate();a.entry=e;assert.throws(()=>snap(100,[a]))})});
test("hybrid explicit common FW mode",()=>{const h=vehicle("vtol_example");assert.throws(()=>snap(100,[candidate()],"current",h));const a=candidate();a.mode="fw";assert.equal(snap(100,[a],"current",h).status,"ok");const b=candidate("other");b.mode="mc";assert.throws(()=>snap(100,[a,b],"current",h))});
test("raise clear hysteresis and saturation",()=>{const p=predictor(2,2),rows=[20,20,20,100,100,100].map((pct,i)=>tick(p,i,pct));assert.deepEqual(rows.map(x=>x.active),[false,true,true,true,false,false]);assert.equal(rows[2].raise_streak,2);assert.equal(rows[5].clear_streak,2)});
test("nonconsecutive risk resets raise",()=>{const p=predictor(2,2);tick(p,0,20);tick(p,1,100);const r=tick(p,2,20);assert(!r.active);assert.equal(r.raise_streak,1)});
test("unsupported resets latch and consumes sequence",()=>{const p=predictor(1,1);assert(tick(p,0,0).active);const a=candidate();a.events[0].lon+=0.001;const r=tick(p,1,100,[a]);assert.strictEqual(r.active,null);assert.strictEqual(r.finding,null);assert.equal(r.raise_streak,0);assert.throws(()=>tick(p,1))});
test("schema failure consumes neither sequence nor streak",()=>{const p=predictor(2,2);tick(p,0,20);assert.throws(()=>tick(p,1,20,[candidate()],"absent"));assert(tick(p,1,20).active)});
test("strict safe integer sequence and ordering",()=>{const p=predictor();[true,-1,0.5,9007199254740992].forEach(seq=>assert.throws(()=>tick(p,seq)));tick(p,0);assert.throws(()=>tick(p,0))});
test("strict integer latch thresholds",()=>{[true,0,-1,1.5,10001].forEach(n=>{assert.throws(()=>predictor(n,1));assert.throws(()=>predictor(1,n))})});
test("severity and absent action authority",()=>{const p=predictor(1,1);[[100,5],[20,4],[0,2]].forEach(([pct,sev],seq)=>{const r=tick(p,seq,pct);assert.equal(r.finding.severity,sev);assert.equal(r.finding.candidates.length,0);assert.strictEqual(r.finding.rule_choice,null);["feasible","executable","return_inferred","landing_modeled"].forEach(k=>assert.strictEqual(r[k],false))})});
test("inputs and results detached",()=>{const a=[candidate()],before=JSON.stringify(a),r=snap(100,a);r.entry.lat=0;r.comparison.candidates[0].bounds.low_pct=0;assert.equal(JSON.stringify(a),before);assert.notEqual(snap().low_pct,0)});
test("predictor vehicle is a snapshot",()=>{const v=vehicle(),p=predictor(1,1,v);v.reserve_pct=99;const r=tick(p,0,50);assert.equal(r.reserve_pct,20);assert(!r.active)});
test("finite JSON percentages and MC rejection",()=>{[true,-1,101,NaN].forEach(pct=>assert.throws(()=>snap(pct)));const a=candidate();a.events[0].lat=NaN;assert.throws(()=>snap(100,[a]));const mc=vehicle("x500");assert.throws(()=>snap(100,[candidate()],"current",mc))});

assert.equal(process.argv.length,3,"usage: node test_typed_geographic_predictor.js <Python --vectors JSON>; first execution only");
const expected=JSON.parse(fs.readFileSync(process.argv[2],"utf8").replace(/^\uFEFF/,"")),p=predictor(2,2),bad=candidate();bad.events[0].lon+=0.001;
const actual=[summary(snap()),summary(tick(p,0,0)),summary(tick(p,1,0)),summary(tick(p,2,100,[bad]))];
assert.equal(expected.length,4);
function parity(a,b,pth){
    if(typeof a==="number"&&typeof b==="number"){assert(Math.abs(a-b)<=1e-8*Math.max(1,Math.abs(a),Math.abs(b)),pth+": "+a+" != "+b);return}
    if(a&&b&&typeof a==="object"&&typeof b==="object"){
        assert.deepEqual(Object.keys(a).sort(),Object.keys(b).sort(),pth+" keys");Object.keys(a).forEach(k=>parity(a[k],b[k],pth+"."+k));return;
    }
    assert.strictEqual(a,b,pth);
}
actual.forEach((r,i)=>parity(r,expected[i],"row"+i));
console.log(JSON.stringify({groups,parity_rows:actual.length,scope:"new_synthetic_typed_P1_controls_only"}));
