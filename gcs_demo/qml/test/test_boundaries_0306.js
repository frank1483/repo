// New offline engineering boundaries only; no Python, HTTP, model or equipment.
const assert = require("assert")
module.exports = function boundaryTests(C) {
    let n = 0
    function check(ok, label) { assert(ok, label); n++ }
    function fresh() { return {home:{id:"H",lat:25,lon:121}, cruise_alt_m:40, speed_mps:8,
        targets:[{id:"T1",lat:25.001,lon:121,alt:40,priority:1}], no_fly:[]} }
    function st() { return {lat:25.0005,lon:121,alt:40,battery_pct:90,observed_ratio:1,remaining:["T1"],completed:[]} }
    function held(r,label) { check(r.pick.decision === "HOLD" && r.rule_choice === "", label) }
    function finiteCandidates(r,label) {
        check(r.candidates.every(c => [c.energy_wh,c.end_pct,c.dist_km,c.speed_mps].every(Number.isFinite)),label)
    }
    const v=C.vehicle(), w=C.wind(0,0)
    let m=fresh();m.targets=[]
    held(C.planMission(m,v,w),"0 target HOLD")
    let r=C.planMission(fresh(),v,w)
    check(r.pick.decision === "SELECT","1 target may plan")
    check(r.candidates.every(c => c.order.length === 1 && c.order[0] === "T1"),"1 target identity")
    finiteCandidates(r,"1 target finite")
    m=fresh();m.targets.push(Object.assign({},m.targets[0]))
    held(C.planMission(m,v,w),"duplicate ID HOLD")
    m=fresh();m.targets.push(Object.assign({},m.targets[0],{id:"T2"}))
    held(C.planMission(m,v,w),"duplicate coordinate HOLD; no silent dedup")
    m=fresh();m.targets[0].id="H"
    held(C.planMission(m,v,w),"home/target ID collision HOLD")
    held(C.planMission(fresh(),v,C.wind(NaN,0)),"NaN wind speed not calm")
    held(C.planMission(fresh(),v,C.wind(1,NaN)),"NaN wind direction not north")
    held(C.planMission(fresh(),v,C.wind(Infinity,0)),"infinite wind HOLD")
    held(C.planMission(fresh(),C.vehicle({max_mps:3}),w),"empty speed search HOLD")
    held(C.planMission(fresh(),C.vehicle({battery_wh:0}),w),"zero capacity HOLD")
    m=fresh();m.speed_mps=0
    held(C.planMission(m,v,w),"zero speed HOLD")
    m=fresh();m.targets[0].lat=NaN
    held(C.planMission(m,v,w),"NaN coordinate HOLD")
    m=fresh();m.targets[0].lat=91
    held(C.planMission(m,v,w),"latitude range HOLD")
    m=fresh();m.no_fly=[{id:"Z",lat:25,lon:121,radius_m:200}]
    r=C.planMission(m,v,w)
    held(r,"home enclosed: all plan candidates HOLD")
    check(r.candidates.length>0 && r.candidates.every(c=>!c.feasible),"home enclosed candidates infeasible")
    finiteCandidates(r,"home enclosed finite outputs")
    r=C.replan(m,v,w,st(),{type:"wind",speed_mps:0,from_deg:0})
    held(r,"enclosed home must not select R1 merely for positive SOC")
    check(r.candidates.some(c=>c.id==="R1"&&!c.feasible),"blocked R1 stays infeasible")
    const badPick=C.validatePick(r,JSON.stringify({decision:"SELECT",choice_id:"R1",evidence_ids:[]}))
    check(badPick.decision==="HOLD" && badPick.source==="rule","model cannot override infeasible R1")
    r=C.replan(fresh(),v,w,Object.assign(st(),{battery_pct:0}),{type:"battery",battery_pct:0})
    held(r,"0 SOC all infeasible HOLD")
    check(r.candidates.every(c=>!c.feasible),"0 SOC no feasible candidate")
    held(C.replan(fresh(),v,w,st(),{type:"wind",speed_mps:NaN,from_deg:0}),"event NaN HOLD")
    held(C.replan(fresh(),v,w,Object.assign(st(),{remaining:["T1","T1"]}),{}),"duplicate remaining HOLD")
    held(C.replan(fresh(),v,w,Object.assign(st(),{remaining:["ghost"]}),{}),"unknown remaining HOLD")
    held(C.replan(fresh(),v,w,Object.assign(st(),{observed_ratio:NaN}),{}),"invalid learned ratio HOLD")
    held(C.replan(fresh(),v,w,st(),{type:"add_target",target:{id:"T1",lat:25.002,lon:121,alt:40}}),"duplicate added ID HOLD")
    m=fresh();m.no_fly=[{id:"Z",lat:25,lon:121,radius_m:0}]
    held(C.planMission(m,v,w),"invalid zone radius HOLD")
    // Original 15-candidate comparison code is separate and unchanged.
    console.log("Boundary assertions: "+n)
    return n
}
if(require.main===module) module.exports(require("./load_core")())
