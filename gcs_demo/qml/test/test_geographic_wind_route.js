// NEW synthetic controls; Claude owns first functional execution.
"use strict";
const assert=require("assert"),fs=require("fs"),path=require("path"),c=require("./load_core")();
const load=id=>c.loadAirframe(JSON.parse(fs.readFileSync(path.join(__dirname,"../../airframes",id+".json"),"utf8")));
const v=load("fw_example"),metres=Math.PI*6371000/180,entry={lat:23,lon:120,alt:80,air_heading_deg:0};
const target=(east,north,en=entry,speed=16)=>({kind:"straight",lat:en.lat+north/metres,lon:(((en.lon+east/(metres*Math.cos(en.lat*Math.PI/180))+180)%360+360)%360)-180,alt:en.alt,ground_mps:speed});
const events=(speed=0,loiter=false,cw=true,en=entry)=>[{kind:loiter?"loiter":"arc",id:"turn",v_air:16,clockwise:cw,radius_m:40,...(loiter?{duration_s:40*Math.PI/2/16}:{angle_deg:90})},target((cw?200:-200)+speed*(40*Math.PI/2/16+10),40,en,Math.abs((cw?16:-16)+speed))];
const run=(ev=events(),en=entry,w=c.wind(),vehicle=v,start=100,mode=undefined)=>c.geographicWindRouteEstimate(vehicle,en,ev,w,start,mode);
const near=(a,b)=>assert(Math.abs(a-b)<=1e-8*Math.max(1,Math.abs(a),Math.abs(b)),`${a} != ${b}`);
let groups=0;function test(name,fn){fn();groups++;console.log("PASS "+name);}
test("north straight independent distance time energy",()=>{const r=run([target(0,160)]);near(r.straight_dist_m,160);near(r.time_s,10);near(r.energy_wh,c.powerW(v,16,"fw")*10/3600);assert.equal(r.exit_geographic.alt,80);});
test("arc geography and independent energy",()=>{const r=run(),t=40*Math.PI/2/16,bank=Math.atan(256/(9.81*40))*180/Math.PI;near(r.energy_wh,(c.powerW(v,16,"fw",bank)*t+c.powerW(v,16,"fw")*10)/3600);near(r.exit_local_m.east_m,200);near(r.exit_local_m.north_m,40);near(r.legs[0].exit_geographic.lat,23+40/metres);assert.deepEqual(r.legs[1].entry_geographic,r.legs[0].exit_geographic);assert.equal(r.legs[0].id,"turn");});
test("wind drift and loiter",()=>{const a=run(events(5),entry,c.wind(5,270)),b=run(events(5,true),entry,c.wind(5,270));near(a.energy_wh,b.energy_wh);near(a.legs[1].straight_dist_m,210);assert(a.projection.path_budget_m>a.air_dist_m);});
test("date line shortest interval",()=>{const en={...entry,lat:0,lon:179.999,air_heading_deg:90},r=run([{kind:"straight",lat:0,lon:-179.999,alt:80,ground_mps:16}],en);near(r.straight_dist_m,.002*metres);near(r.exit_geographic.lon,-179.999);});
test("southern hemisphere wrapped heading",()=>{const en={...entry,lat:-45,lon:-120,air_heading_deg:360};near(run([target(0,160,en)],en).straight_dist_m,160);});
test("reject invented connector and acceleration",()=>{assert.throws(()=>run([target(160,0)]),/not tangent/);const ev=events();ev[1].ground_mps=17;assert.throws(()=>run(ev),/airspeed discontinuity/);});
test("strict schema and constant altitude",()=>{for(const ev of [[],[null],[{kind:"unknown"}],[{...target(0,160),east_m:0}],[{...target(0,160),alt:81}],[{...target(0,160),lat:true}],[{...target(0,160),id:"🚀".repeat(129)}],[{...events()[0],lat:23}],[{...events()[0],clockwise:null}],[{kind:"straight",lat:23,lon:120,ground_mps:16}]])assert.throws(()=>run(ev));assert.throws(()=>run(events(),{...entry,cmd:16}));});
test("polar origin distant target",()=>{assert.throws(()=>run(events(),{...entry,lat:76}));assert.throws(()=>run([target(0,11000)]),/10 km local frame/);});
test("loop path budget beyond endpoints",()=>{assert.throws(()=>run([{kind:"loiter",v_air:16,duration_s:800,clockwise:true,radius_m:40}]),/cumulative path budget/);});
test("explicit hybrid FW and MC rejection",()=>{const h=load("vtol_example");assert.equal(run(events(),entry,c.wind(),h,100,"fw").arrival_mode,"fw");for(const [vv,mode] of [[h,undefined],[h,"mc"],[load("x500"),undefined]])assert.throws(()=>run(events(),entry,c.wind(),vv,100,mode));});
test("detached inputs calibration once",()=>{const ev=events(),en={...entry},w=c.wind(),before=JSON.stringify([v,en,ev,w]),r=run(ev,en,w);near(run(ev,en,w,{...v,calib:1.3}).energy_wh,r.energy_wh*1.3);r.legs[0].exit_geographic.lat=0;r.projection.origin.lat=0;assert.equal(JSON.stringify([v,en,ev,w]),before);});
test("energy does not authorize landing",()=>{const r=run(events(),entry,c.wind(),v,0);assert.equal(r.energy_feasible,false);assert.equal(r.feasible,false);assert.equal(r.landing_modeled,false);assert(!("dist_m" in r));});
if(process.argv[2]){
 const rows=JSON.parse(fs.readFileSync(process.argv[2],"utf8").replace(/^\uFEFF/,""));assert.equal(rows.length,4);
 function compare(a,b,key){if(typeof a==="number")near(a,b);else if(a&&typeof a==="object"){assert.deepEqual(Object.keys(a).sort(),Object.keys(b).sort());for(const k of Object.keys(a))compare(a[k],b[k],key+"."+k);}else assert.strictEqual(a,b,key);}
 for(const row of rows)compare(run(row.events,row.entry,row.wind),row.result,"result");console.log("PASS 4 Python/JS parity rows");
}
console.log("NEW geographic wind route groups: "+groups);
