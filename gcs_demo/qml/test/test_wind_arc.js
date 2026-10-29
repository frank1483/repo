// New synthetic contracts; use the QML loader. Claude owns first execution.
"use strict";
const assert=require("assert"),fs=require("fs"),path=require("path");
const c=require("./load_core")();
const profile=id=>JSON.parse(fs.readFileSync(path.join(__dirname,"../../airframes",id+".json"),"utf8"));
const v=c.loadAirframe(profile("fw_example"));
const near=(a,b)=>assert(Math.abs(a-b)<=1e-8*Math.max(1,Math.abs(a),Math.abs(b)),`${a} != ${b}`);
let groups=0;
function test(name,fn){fn();groups++;console.log("PASS "+name);}
const arc=(w=c.wind(),angle=90,heading=0,clockwise=true)=>c.windArcEstimate(v,16,angle,w,heading,clockwise,undefined,40);
test("exports",()=>{assert.equal(typeof c.windArcEstimate,"function");assert.equal(typeof c.windLoiterEstimate,"function");});
test("quarter right",()=>{const r=arc();near(r.air_displacement_m.east,40);near(r.air_displacement_m.north,40);near(r.exit_air_heading_deg,90);});
test("quarter left",()=>{const r=arc(c.wind(),90,0,false);near(r.ground_displacement_m.east,-40);near(r.ground_displacement_m.north,40);near(r.exit_air_heading_deg,270);assert(r.bank_deg<0);});
test("wind drift",()=>{const r=arc(c.wind(5,270));near(r.ground_displacement_m.east,40+5*r.time_s);near(r.ground_displacement_m.north,40);});
test("calm legacy correspondence",()=>{const a=arc(),b=c.turnEstimate(v,16,90,c.wind(),undefined,40);near(a.energy_wh,b.energy_wh);near(a.air_dist_m,b.dist_m);near(a.time_s,b.time_s);});
test("air energy independent of wind",()=>{const a=arc(),b=arc(c.wind(5,40));assert.equal(a.energy_wh,b.energy_wh);assert.equal(a.time_s,b.time_s);assert.notDeepEqual(a.ground_displacement_m,b.ground_displacement_m);});
test("full circle drift",()=>{const r=arc(c.wind(3,270),360,37);near(r.ground_displacement_m.east,3*r.time_s);near(r.ground_displacement_m.north,0);near(r.exit_air_heading_deg,37);assert.equal(r.ground_fixed_orbit,false);});
test("rotated heading",()=>{const r=arc(c.wind(),90,90);near(r.ground_displacement_m.east,40);near(r.ground_displacement_m.north,-40);near(r.exit_air_heading_deg,180);});
test("zero sweep",()=>{const r=arc(c.wind(3,0),0,-20);assert.equal(r.time_s,0);assert.equal(r.energy_wh,0);near(r.ground_displacement_m.east,0);near(r.ground_displacement_m.north,0);near(r.exit_air_heading_deg,340);});
test("partial loiter",()=>{const a=arc(c.wind(4,80)),b=c.windLoiterEstimate(v,16,40*Math.PI/2/16,c.wind(4,80),0,true,40);assert.deepEqual(a,b);});
test("multiple revolutions",()=>{const seconds=(4*Math.PI+Math.PI/2)*40/16,r=c.windLoiterEstimate(v,16,seconds,c.wind(2,270),0,true,40);near(r.signed_sweep_deg,810);near(r.exit_air_heading_deg,90);near(r.ground_displacement_m.east,40+2*seconds);});
test("ground exit wind triangle",()=>{const r=arc(c.wind(5,180));near(r.exit_ground_heading_deg,Math.atan2(16,5)*180/Math.PI);near(r.exit_ground_speed_mps,Math.sqrt(281));});
test("ground stop heading null",()=>{const r=arc(c.wind(16,90));assert(r.exit_ground_speed_mps<1e-9);assert.equal(r.exit_ground_heading_deg,null);});
test("calibration and hybrid FW",()=>{const copy=JSON.parse(JSON.stringify(v));copy.calib=1.2;near(c.windArcEstimate(copy,16,90,c.wind(),0,true,undefined,40).energy_wh,arc().energy_wh*1.2);const h=c.loadAirframe(profile("vtol_example")),r=c.windArcEstimate(h,16,90,c.wind(2,0),0);assert.equal(r.mode,"fw");near(r.energy_wh,c.powerW(h,16,"fw",r.bank_deg)*r.time_s/3600);});
test("geometry and MC reject",()=>{for(const args of [[undefined,1],[0,undefined],[80,undefined],[20,40]])assert.throws(()=>c.windArcEstimate(v,16,90,c.wind(),0,true,...args));assert.throws(()=>c.windArcEstimate(c.loadAirframe(profile("x500")),16,90,c.wind(),0));assert.throws(()=>c.windArcEstimate(v,1,90,c.wind(),0));});
test("invalid inputs",()=>{for(const args of [[NaN,90,true],[true,90,true],[0,-1,true],[0,361,true],[0,90,1],[0,90,null]])assert.throws(()=>c.windArcEstimate(v,16,args[1],c.wind(),args[0],args[2]));for(const w of [c.wind(-1,0),c.wind(0,Infinity),c.wind(NaN,0)])assert.throws(()=>arc(w));for(const t of [-1,86401,true])assert.throws(()=>c.windLoiterEstimate(v,16,t,c.wind(),0));});
test("explicit direction determines bank",()=>{const a=c.windArcEstimate(v,16,90,c.wind(),0,false,20),b=c.windArcEstimate(v,16,90,c.wind(),0,false,-20);assert.deepEqual(a,b);assert(a.bank_deg<0);});
test("immutable inputs and scope",()=>{const w=c.wind(3,20),before=JSON.stringify([v,w]),r=arc(w);assert.equal(JSON.stringify([v,w]),before);assert(!("dist_m" in r));assert.equal(r.ground_fixed_orbit,false);assert(r.scope.includes("not_executable_route"));});
test("implicit route wind guard retained",()=>{const pts=[{lat:0,lon:0,alt:60},{lat:.01,lon:0,alt:60},{lat:.01,lon:.01,alt:60}];assert.throws(()=>c.routeEstimate(v,pts,16,c.wind(2,0)),/calm wind/);});
if(process.argv[2]) {
    const rows=JSON.parse(fs.readFileSync(process.argv[2],"utf8").replace(/^\uFEFF/,""));
    function compare(a,b,key){if(typeof a==="number")near(a,b);else if(a&&typeof a==="object"){assert.deepEqual(Object.keys(a).sort(),Object.keys(b).sort());for(const k of Object.keys(a))compare(a[k],b[k],key+"."+k);}else assert.equal(a,b,key);}
    assert.equal(rows.length,4);
    for(const row of rows){const [angle,heading,cw,speed,from]=row.args;compare(arc(c.wind(speed,from),angle,heading,cw),row.result,"result");}
    console.log("PASS 4 Python/JS parity vectors");
}
console.log("NEW wind arc groups: "+groups);
