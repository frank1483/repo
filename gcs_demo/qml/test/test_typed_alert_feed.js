"use strict";
// NEW controls; first functional execution is owned by Claude.
const assert=require("assert"),fs=require("fs"),path=require("path"),c=require("./load_core")();
const clone=x=>JSON.parse(JSON.stringify(x)),entry={lat:23,lon:120,alt:80,air_heading_deg:0},metres=Math.PI*6371000/180;
function vehicle(key="fw_example") {
    const v=c.loadAirframe(JSON.parse(fs.readFileSync(path.join(__dirname,"../../airframes",key+".json"),"utf8")));
    v.airframe_profile.uncertainty={power_pct:0,capacity_pct:0,wind_mps:0};return v;
}
const candidate=(id="current",bad=false)=>({id,entry:clone(entry),events:[{kind:"straight",lat:23+100/metres,lon:bad?120.001:120,alt:80,ground_mps:16}]});
const record=(seq=0,pct=100)=>Object.assign({},entry,{t_s:seq,battery_pct:pct,wind_mps:0,wind_from:0});
const feed=(r=2,k=2)=>c.createTypedGeographicAlertFeed(vehicle(),r,k);
const tick=(f,seq,pct=100,bad=false,version="v1")=>f.tick(seq,record(seq,pct),[candidate("current",bad)],"current",version);
const types=r=>r.events.map(e=>e.type);
let groups=0;
function test(name,f){f();groups++;console.log("PASS "+name)}
function summary(r){
    const out={};["sequence","t_s","mission_version","status","active","raise_streak","clear_streak","nominal_end_pct","low_pct","high_pct","unassessed_predictors","feasible","executable"].forEach(k=>out[k]=r[k]);
    out.event_types=types(r);out.event_active=r.events.map(e=>e.active);out.event_severity=r.events.map(e=>e.severity);return out;
}
test("known without synthetic power or current",()=>{const r=tick(feed(),0);assert.deepEqual(types(r),["known"]);assert.strictEqual(r.active,false)});
test("raise and resolve hysteresis",()=>{const f=feed(),rows=[20,20,100,100].map((pct,i)=>tick(f,i,pct));assert.deepEqual(rows.map(types),[["known"],["raise"],[],["resolve"]]);assert.strictEqual(rows[3].events[0].active,false)});
test("unknown is never a resolution",()=>{const f=feed(1,1);tick(f,0,20);const r=tick(f,1,100,true);assert.deepEqual(types(r),["unknown"]);assert.strictEqual(r.active,null);assert.strictEqual(r.events[0].active,null)});
test("repeated unknown and recovery",()=>{const f=feed();assert.deepEqual(types(tick(f,0,100,true)),["unknown"]);assert.deepEqual(types(tick(f,1,100,true)),[]);assert.deepEqual(types(tick(f,2)),["known"])});
test("version resets hysteresis",()=>{const f=feed();tick(f,0,20);const r=tick(f,1,20,false,"v2");assert(!r.active);assert.equal(r.raise_streak,1);assert.deepEqual(types(r),["reset","known"]);assert(tick(f,2,20,false,"v2").active)});
test("global order survives version changes",()=>{const f=feed();tick(f,2);assert.throws(()=>tick(f,1,100,false,"v2"),/sequence/);assert.equal(tick(f,3,100,false,"v2").sequence,3)});
test("all measured fields required without state consumption",()=>{const f=feed();Object.keys(record()).forEach(k=>{const r=record();delete r[k];assert.throws(()=>f.tick(0,r,[candidate()],"current","v1"))});assert.equal(tick(f,0).sequence,0)});
test("candidate pose equals measured pose",()=>{const f=feed();Object.keys(entry).forEach(k=>{const a=candidate();a.entry[k]+=0.001;assert.throws(()=>f.tick(0,record(),[a],"current","v1"),/measured geographic pose/)});assert.equal(tick(f,0).status,"ok")});
test("time and schema errors preserve latch",()=>{const f=feed();tick(f,0,20);assert.throws(()=>f.tick(1,record(0,20),[candidate()],"current","v1"));assert.throws(()=>f.tick(1,record(1,20),[candidate()],"absent","v1"));assert(tick(f,1,20).active)});
test("failed replacement preserves old predictor",()=>{const f=feed();tick(f,0,20);assert.throws(()=>f.tick(1,record(1,20),[candidate()],"absent","v2"));assert(tick(f,1,20).active)});
test("current selection requires version change",()=>{const f=feed();tick(f,0);assert.throws(()=>f.tick(1,record(1),[candidate("other")],"other","v1"));assert.equal(f.tick(1,record(1),[candidate("other")],"other","v2").current_id,"other")});
test("finite measured numbers and ranges",()=>{
    Object.keys(record()).forEach(k=>[true,NaN,Infinity].forEach(value=>{const r=record();r[k]=value;assert.throws(()=>feed().tick(0,r,[candidate()],"current","v1"))}));
    [["lat",76],["lon",181],["alt",-1],["wind_mps",-1],["battery_pct",-1],["battery_pct",101],["t_s",-1]].forEach(([k,v])=>{const r=record();r[k]=v;assert.throws(()=>feed().tick(0,r,[candidate()],"current","v1"))});
});
test("ASCII versions and safe integer sequences",()=>{[null,true,"","x".repeat(129),"版本","v1\n"].forEach(v=>assert.throws(()=>tick(feed(),0,100,false,v)));[true,-1,0.5,9007199254740992].forEach(seq=>assert.throws(()=>tick(feed(),seq)))});
test("hybrid explicit FW mode",()=>{const f=c.createTypedGeographicAlertFeed(vehicle("vtol_example"));assert.throws(()=>tick(f,0));const a=candidate();a.mode="fw";assert.equal(f.tick(0,record(),[a],"current","v1").status,"ok")});
test("MC rejection and strict thresholds",()=>{assert.throws(()=>c.createTypedGeographicAlertFeed(vehicle("x500")));[true,0,-1,1.5,10001].forEach(n=>{assert.throws(()=>feed(n,1));assert.throws(()=>feed(1,n))})});
test("snapshotted vehicle and detached data",()=>{const v=vehicle(),f=c.createTypedGeographicAlertFeed(v,1,1);v.reserve_pct=99;const rec=record(0,50),items=[candidate()],before=JSON.stringify([rec,items]),r=f.tick(0,rec,items,"current","v1");r.events[0].type="edited";assert.equal(JSON.stringify([rec,items]),before);assert.equal(tick(f,1,50).reserve_pct,20)});
test("P2-P5 unassessed and no flight authority",()=>{const r=tick(feed(),0);assert.deepEqual(r.unassessed_predictors,["P2","P3","P4","P5"]);["feasible","executable","return_inferred","landing_modeled"].forEach(k=>assert.strictEqual(r[k],false));assert.strictEqual(r.rule_choice,null)});

assert.equal(process.argv.length,3,"usage: node test_typed_alert_feed.js <Python --vectors JSON>");
const expected=JSON.parse(fs.readFileSync(process.argv[2],"utf8").replace(/^\uFEFF/,"")),f=feed();
const args=[[100,false,"v1"],[20,false,"v1"],[20,false,"v1"],[100,true,"v1"],[100,false,"v1"],[20,false,"v1"],[20,false,"v2"],[20,false,"v2"]];
const actual=args.map((a,i)=>summary(tick(f,i,...a)));assert.equal(expected.length,8);
function parity(a,b,where){
    if(typeof a==="number"&&typeof b==="number"){assert(Math.abs(a-b)<=1e-8*Math.max(1,Math.abs(a),Math.abs(b)),where+": "+a+" != "+b);return}
    if(a&&b&&typeof a==="object"&&typeof b==="object"){assert.deepEqual(Object.keys(a).sort(),Object.keys(b).sort(),where+" keys");Object.keys(a).forEach(k=>parity(a[k],b[k],where+"."+k));return}
    assert.strictEqual(a,b,where);
}
actual.forEach((r,i)=>parity(r,expected[i],"row"+i));
console.log(JSON.stringify({groups,parity_rows:actual.length,scope:"new_synthetic_typed_feed_controls_only"}));
