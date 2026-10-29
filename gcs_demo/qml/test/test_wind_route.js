// NEW synthetic controls. Claude executes once; load QML through load_core.
"use strict";
const assert=require("assert"),fs=require("fs"),path=require("path");
const c=require("./load_core")();
const v=c.loadAirframe(JSON.parse(fs.readFileSync(path.join(__dirname,"../../airframes/fw_example.json"),"utf8")));
const entry={east_m:0,north_m:0,air_heading_deg:0},t=40*Math.PI/2/16;
const near=(a,b)=>assert(Math.abs(a-b)<=1e-9*Math.max(1,Math.abs(a),Math.abs(b)),`${a} != ${b}`);
const events=(speed=0,loiter=false,cw=true)=>[{kind:loiter?"loiter":"arc",v_air:16,clockwise:cw,radius_m:40,...(loiter?{duration_s:t}:{angle_deg:90})},
    {kind:"straight",east_m:(cw?40:-40)+speed*t+((cw?16:-16)+speed)*10,north_m:40,ground_mps:Math.abs((cw?16:-16)+speed)}];
const run=(ev=events(),w=c.wind(),en=entry,start=100,vehicle=v,mode=undefined)=>c.windRouteEstimate(vehicle,en,ev,w,start,mode);
let groups=0;
function test(name,fn){fn();groups++;console.log("PASS "+name);}
test("public export and independent energy",()=>{assert.equal(typeof c.windRouteEstimate,"function");const r=run(),bank=Math.atan(256/(9.81*40))*180/Math.PI;
    near(r.energy_wh,(c.powerW(v,16,"fw",bank)*t+c.powerW(v,16,"fw")*10)/3600);near(r.time_s,t+10);near(r.exit_local_m.east_m,200);near(r.exit_local_m.north_m,40);near(r.straight_dist_m,160);near(r.air_dist_m,40*Math.PI/2+160);});
test("wind drift drives straight origin",()=>{const r=run(events(5),c.wind(5,270));near(r.legs[1].entry_local_m.east_m,40+5*t);near(r.straight_dist_m,210);near(r.exit_ground_speed_mps,21);near(r.energy_wh,run().energy_wh);});
test("partial loiter tangent departure",()=>{const a=run(events(3),c.wind(3,270)),b=run(events(3,true),c.wind(3,270));near(a.energy_wh,b.energy_wh);near(a.exit_local_m.east_m,b.exit_local_m.east_m);});
test("left arc with wind",()=>{const r=run(events(2,false,false),c.wind(2,270));near(r.exit_air_heading_deg,270);near(r.exit_ground_speed_mps,14);});
test("air and ground tangent differ in crosswind",()=>{const r=run([events()[0],{kind:"straight",east_m:200,north_m:40+5*t+50,ground_mps:Math.hypot(16,5)}],c.wind(5,180));near(r.exit_air_heading_deg,90);assert(Math.abs(r.exit_ground_heading_deg-90)>1);near(r.legs[1].time_s,10);});
test("reject wrong tangent",()=>{const ev=events();ev[1].north_m+=20;assert.throws(()=>run(ev),/not tangent/);});
test("reject acceleration",()=>{const ev=events();ev[1].ground_mps=17;assert.throws(()=>run(ev),/airspeed discontinuity/);});
test("arc arc propagates pose and heading",()=>{const r=run([events()[0],events()[0]]);near(r.exit_air_heading_deg,180);near(r.exit_local_m.east_m,80);near(r.exit_local_m.north_m,0);});
test("translation and heading wrap",()=>{const ev=events();ev[1].east_m+=100;ev[1].north_m-=70;const r=run(ev,c.wind(),{east_m:100,north_m:-70,air_heading_deg:360});near(r.energy_wh,run().energy_wh);near(r.exit_local_m.east_m,300);});
test("straight only and tiny wrap",()=>{const r=run([{kind:"straight",east_m:0,north_m:160,ground_mps:16}],c.wind(),{...entry,air_heading_deg:-1e-8});near(r.time_s,10);near(r.exit_air_heading_deg,0);assert.equal(r.legs.length,1);});
test("explicit hybrid FW and reject MC",()=>{const load=id=>c.loadAirframe(JSON.parse(fs.readFileSync(path.join(__dirname,"../../airframes",id+".json"),"utf8"))),h=load("vtol_example");assert.equal(run(events(),c.wind(),entry,100,h,"fw").arrival_mode,"fw");for(const [vehicle,mode]of [[h,undefined],[h,"mc"],[load("x500"),undefined]])assert.throws(()=>run(events(),c.wind(),entry,100,vehicle,mode));});
test("airborne reserve does not authorize a mission",()=>{const r=run(events(),c.wind(),entry,0);assert.equal(r.energy_feasible,false);assert.equal(r.feasible,false);assert.equal(r.landing_modeled,false);assert(!("dist_m"in r));});
test("calibration once and immutable inputs",()=>{const ev=events(3),w=c.wind(3,270),before=JSON.stringify([v,entry,ev,w]),vv=JSON.parse(JSON.stringify(v));vv.calib=1.3;near(run(ev,w,entry,100,vv).energy_wh,run(ev,w).energy_wh*1.3);assert.equal(JSON.stringify([v,entry,ev,w]),before);});
test("strict schema and flight envelope",()=>{for(const ev of [[],[{}],[{kind:"unknown"}],[{...events()[0],alt:10}],[{...events()[0],clockwise:null}],[{...events()[0],v_air:1}],[{kind:"straight",east_m:0,north_m:0,ground_mps:16}],[{kind:"straight",east_m:true,north_m:160,ground_mps:16}]])assert.throws(()=>run(ev));assert.throws(()=>run(events(),c.wind(),{...entry,lat:0}));assert.throws(()=>run(events(),c.wind(-1,0)));});
if(process.argv[2]) {
    const rows=JSON.parse(fs.readFileSync(process.argv[2],"utf8").replace(/^\uFEFF/,""));assert.equal(rows.length,4);
    function compare(a,b,key){if(typeof a==="number")near(a,b);else if(a&&typeof a==="object"){assert.deepEqual(Object.keys(a).sort(),Object.keys(b).sort());for(const k of Object.keys(a))compare(a[k],b[k],key+"."+k);}else assert.strictEqual(a,b,key);}
    for(const row of rows)compare(run(row.events,row.wind,row.entry),row.result,"result");
    console.log("PASS 4 Python/JS parity rows");
}
console.log("NEW wind route groups: "+groups);
