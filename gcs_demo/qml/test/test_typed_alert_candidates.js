// NEW synthetic controls; Claude owns first functional execution.
"use strict";
const assert=require("assert"),fs=require("fs"),path=require("path"),c=require("./load_core")();
const load=id=>c.loadAirframe(JSON.parse(fs.readFileSync(path.join(__dirname,"../../airframes",id+".json"),"utf8")));
const v=load("fw_example"),h=load("vtol_example");
const candidate=(id="C1",distance=.001,speed=16,extra={})=>Object.assign({id,points:[{id:"start",lat:23,lon:120,alt:80},{id:"end",lat:23+distance,lon:120,alt:80}],ground_mps:speed},extra);
const run=(items=[candidate()],vv=v,start=100,w=c.wind())=>c.evaluateTypedAlertCandidates(vv,items,w,start);
const near=(a,b)=>assert(Math.abs(a-b)<=1e-8*Math.max(1,Math.abs(a),Math.abs(b)),`${a} != ${b}`);
let groups=0;function test(name,fn){fn();groups++;console.log("PASS "+name);}
test("stall options sorted unique airspeed",()=>{const r=c.typedAlertSpeeds(v,[16,4,16,35,36]);assert.deepEqual(r.accepted_mps,[16,35]);assert.deepEqual(r.rejected_mps,[4,36]);assert(r.basis.includes("not_ground"));});
test("bank increases minimum",()=>{assert(c.typedAlertSpeeds(v,[16],undefined,60).minimum_mps>c.typedAlertSpeeds(v,[16]).minimum_mps);});
test("hybrid requires mode",()=>{assert.throws(()=>c.typedAlertSpeeds(h,[4]));assert.equal(run([candidate()],h).candidates[0].status,"unsupported");});
test("hybrid MC no FW stall",()=>{assert.deepEqual(c.typedAlertSpeeds(h,[0,4,16],"mc").accepted_mps,[0,4,16]);assert.deepEqual(c.typedAlertSpeeds(h,[4,16],"fw").accepted_mps,[16]);});
test("MC bank unsupported",()=>assert.throws(()=>c.typedAlertSpeeds(load("x500"),[4],undefined,5)));
test("invalid speed input",()=>{for(const speeds of [[],[true],[NaN],[-1],Array(102).fill(1)])assert.throws(()=>c.typedAlertSpeeds(v,speeds));assert.throws(()=>c.typedAlertSpeeds(v,[16],"mc"));});
test("conservative ranking only",()=>{const r=run([candidate("long",.002),candidate("short")]);assert.equal(r.best_energy_id,"short");assert.equal(r.feasible,false);assert.equal(r.executable,false);assert.equal(r.return_inferred,false);assert(r.candidates.every(x=>!x.feasible));});
test("tie preserves input order",()=>assert.equal(run([candidate("a"),candidate("b")]).best_energy_id,"a"));
test("negative bounds retained",()=>{const r=run(undefined,v,0);assert.equal(r.best_energy_id,null);assert(r.candidates[0].bounds.low_pct<0);});
test("full route scenarios visible",()=>{const row=run().candidates[0];assert.equal(row.status,"ok");assert(row.bounds.scenarios.length>1);assert.deepEqual(row.bounds.nominal.wind,{speed_mps:0,from_deg:0});assert(row.bounds.scenarios.every(s=>s.energy_wh>=0));});
test("unsupported perturbed turn does not vanish",()=>{const item=candidate();item.points.push({id:"return",lat:23,lon:120,alt:80});const row=run([item]).candidates[0];assert.equal(row.status,"unsupported");assert.equal(row.bounds.available,false);assert.equal(row.bounds.low_pct,null);assert(row.bounds.scenarios.some(s=>s.status==="unsupported"));});
test("one invalid row retains valid alternative",()=>{const r=run([candidate("slow",.001,1),candidate("valid")]);assert.deepEqual(r.candidates.map(x=>x.status),["unsupported","ok"]);assert.equal(r.best_energy_id,"valid");});
test("invalid batch schema IDs limits",()=>{for(const items of [[],[candidate(),candidate()],[candidate("")],[Object.assign(candidate(),{action:"LAND"})],Array(17).fill(candidate())])assert.throws(()=>run(items));});
test("malformed route stays unsupported",()=>{for(const points of [null,[],[{},{}]])assert.equal(run([Object.assign(candidate(),{points})]).candidates[0].status,"unsupported");});
test("detached context cannot mutate inputs",()=>{const items=[candidate()],w=c.wind(),before=JSON.stringify([v,items,w]),r=run(items,v,100,w);r.candidates[0].estimate.bounds_context.route[0].lat=0;assert.equal(JSON.stringify([v,items,w]),before);});
test("calibration once",()=>near(run(undefined,Object.assign({},v,{calib:1.3})).candidates[0].estimate.energy_wh,run().candidates[0].estimate.energy_wh*1.3));
function summary(r){return {best_energy_id:r.best_energy_id,feasible:r.feasible,executable:r.executable,candidates:r.candidates.map(x=>({id:x.id,status:x.status,sampled_energy_feasible:x.sampled_energy_feasible,low_pct:x.bounds?x.bounds.low_pct:null,high_pct:x.bounds?x.bounds.high_pct:null}))};}
if(process.argv[2]) {
 const rows=JSON.parse(fs.readFileSync(process.argv[2],"utf8").replace(/^\uFEFF/,""));assert.equal(rows.length,4);
 function compare(a,b){if(typeof a==="number")near(a,b);else if(a&&typeof a==="object"){assert.deepEqual(Object.keys(a).sort(),Object.keys(b).sort());Object.keys(a).forEach(k=>compare(a[k],b[k]));}else assert.strictEqual(a,b);}
 rows.forEach(row=>compare(summary(run(row.candidates,load(row.profile),row.start_pct,row.wind)),row.result));console.log("PASS 4 Python/JS parity summaries");
}
console.log("NEW typed alert groups: "+groups);
