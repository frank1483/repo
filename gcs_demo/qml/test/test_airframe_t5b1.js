// NEW synthetic checks. Do not run old research or nominal suites here.
'use strict';
const assert=require('assert'),fs=require('fs'),path=require('path');
const C=require('./load_core')(),plain=x=>JSON.parse(JSON.stringify(x));
const load=id=>C.loadAirframe(JSON.parse(fs.readFileSync(path.join(__dirname,'../../airframes',id+'.json'),'utf8')));
const fw=load('fw_example'),vt=load('vtol_example'),mc=load('x500');
const a={lat:.01,lon:0,alt:60},h={lat:0,lon:0,alt:0};
const near=(x,y,tol=1e-10)=>assert(Math.abs(x-y)<=tol*Math.max(1,Math.abs(x),Math.abs(y)),`${x} != ${y}`);
let groups=0;
function test(name,fn){try{fn();groups++;}catch(e){e.message=name+': '+e.message;throw e;}}
const leg=(v,alt=60,w=C.wind(),mode)=>C.legEstimate(v,[0,0],[.01,0],60,alt,16,w,mode);
test('FW level power',()=>{const e=leg(fw);near(e.energy_wh,C.powerW(fw,16)*e.time_s/3600);near(e.time_s,e.dist_m/16)});
test('FW climb exactly once',()=>{const x=leg(fw),y=leg(fw,90);near(y.energy_wh-x.energy_wh,fw.mass_kg*9.81*30/fw.airframe_profile.power.eta_prop/3600);near(x.time_s,y.time_s)});
test('FW no descent regeneration',()=>near(leg(fw).energy_wh,leg(fw,0).energy_wh));
test('FW zero distance rejected',()=>assert.throws(()=>C.legEstimate(fw,[0,0],[0,0],60,0,16,C.wind())));
test('wind is vector',()=>{const e=leg(fw,60,C.wind(3,0));near(e.v_air,19);near(e.headwind_mps,3)});
test('stall rejected',()=>assert.throws(()=>C.legEstimate(fw,[0,0],[.01,0],0,0,4,C.wind())));
test('hybrid explicit mode',()=>{assert.throws(()=>leg(vt));assert.equal(leg(vt,60,C.wind(),'mc').mode,'mc');assert.equal(leg(vt,60,C.wind(),'fw').mode,'fw')});
test('MC vertical wind and climb',()=>{const e=C.legEstimate(vt,[0,0],[0,0],60,0,16,C.wind(3,70),'mc');near(e.time_s,30);near(e.energy_wh,C.powerW(vt,3,'mc')*30/3600);
    const c=C.legEstimate(vt,[0,0],[0,0],0,30,16,C.wind(),'mc');near(c.energy_wh,(C.powerW(vt,0,'mc')*10+vt.mass_kg*9.81*30/vt.airframe_profile.power.mc.eta)/3600)});
test('transition allowances',()=>{for(const [from,to]of [['mc','fw'],['fw','mc']]){const t=C.transitionEstimate(vt,from,to);near(t.energy_wh,vt.airframe_profile.transition['to_'+to+'_wh']);near(t.dist_m,to==='fw'?100:0)}
    for(const m of ['mc','fw'])near(C.transitionEstimate(vt,m,m).energy_wh,0)});
test('transition errors',()=>{assert.throws(()=>C.transitionEstimate(fw,'fw','mc'));assert.throws(()=>C.transitionEstimate(vt,'unknown','fw'))});
test('hybrid RTL to_mc once',()=>{const e=C.rtlEnergy(a,h,vt,C.wind());assert.equal(e.legs.length,3);assert.equal(e.legs.filter(x=>x.to_mode==='mc').length,1);near(e.energy_wh,e.legs.reduce((n,x)=>n+x.energy_wh,0));near(e.used_pct,e.energy_wh/162*100)});
test('already home fw still transitions',()=>{const e=C.rtlEnergy({...h,alt:60},h,vt,C.wind());assert.equal(e.legs.length,2);assert.equal(e.legs[0].to_mode,'mc')});
test('MC RTL no transition',()=>{const e=C.rtlEnergy(a,h,vt,C.wind(),undefined,'mc');assert.equal(e.legs.length,1);assert(e.landing_modeled)});
test('FW RTL airborne',()=>{const e=C.rtlEnergy(a,h,fw,C.wind());assert.equal(e.arrival_mode,'fw');assert.equal(e.landing_modeled,false);near(e.energy_wh,leg(fw).energy_wh)});
test('calib applies once',()=>{const v=C.vehicle({...plain(vt),calib:1.7});near(C.rtlEnergy(a,h,v,C.wind()).energy_wh,C.rtlEnergy(a,h,vt,C.wind()).energy_wh*1.7);near(C.transitionEstimate(v,'fw','mc').energy_wh,1.5*1.7)});
test('best speed wind triangle',()=>{const w=C.wind(4,90),b=C.bestSpeed(fw,w),range=C.speedRange(fw);assert(b.airspeed_mps>=range[0]&&b.airspeed_mps<=range[1]);near(Math.hypot(b.speed_mps,4),b.airspeed_mps);
    const e=C.legEstimate(fw,[0,0],[.01,0],0,0,b.speed_mps,w);near(Math.round(e.energy_wh/e.dist_m*100000)/100,b.wh_per_km)});
test('best speed no interval or wind solution',()=>{assert.throws(()=>C.bestSpeed(fw,C.wind(),0,100));assert.throws(()=>C.bestSpeed(fw,C.wind(),0,4,1));assert.throws(()=>C.bestSpeed(fw,C.wind(40,90)))});
test('hybrid best defaults fw',()=>assert(C.bestSpeed(vt,C.wind()).airspeed_mps>=C.speedRange(vt)[0]));
test('inputs not mutated',()=>{const before=JSON.stringify([a,h,vt]);C.rtlEnergy(a,h,vt,C.wind());assert.equal(JSON.stringify([a,h,vt]),before)});
test('invalid values reject',()=>{for(const s of [0,-1,true,NaN])assert.throws(()=>C.legEstimate(fw,[0,0],[.01,0],0,0,s,C.wind()));
    assert.throws(()=>C.rtlEnergy({...a,alt:-1},h,vt,C.wind()));assert.throws(()=>C.rtlEnergy(a,{...h,alt:10},vt,C.wind()));assert.throws(()=>C.rtlEnergy(a,h,vt,C.wind(-1,0)))});
test('legacy MC unchanged synthetic',()=>{const pts=[{...a,id:'a'},{...h,id:'h'}];for(const w of [C.wind(),C.wind(3,80)]){
    assert.deepStrictEqual(plain(C.rtlEnergy(a,h,mc,w)),plain(C.rtlEnergy(a,h,C.vehicle(),w)));
    assert.deepStrictEqual(plain(C.routeEstimate(mc,pts,8,w)),plain(C.routeEstimate(C.vehicle(),pts,8,w)))}});
test('incomplete typed route stays gated',()=>{assert.equal(C.estimateRouteEnergy([a,h],fw,C.wind()).landing_modeled,false);assert.throws(()=>C.estimateRouteEnergy([a,h],vt,C.wind()))});
// Optional evidence produced by NEW Python vector emitter, not a model response.
const at=process.argv.indexOf('--python-vectors');
if(at>=0){const rows=JSON.parse(fs.readFileSync(process.argv[at+1],'utf8').replace(/^\uFEFF/,''));
    test('Python JS vectors',()=>{function eq(x,y){if(typeof x==='number'&&typeof y==='number')return near(x,y);if(Array.isArray(x)){assert.equal(x.length,y.length);x.forEach((v,i)=>eq(v,y[i]));return;}
        if(x&&typeof x==='object'){assert.deepStrictEqual(Object.keys(x).sort(),Object.keys(y).sort());for(const k of Object.keys(x))eq(x[k],y[k]);return;}assert.strictEqual(x,y);}
        const actual=vectorRows();assert.equal(rows.length,actual.length);rows.forEach((row,i)=>eq(row,actual[i]));});}
function vectorRows(){const out=[];for(const v of [fw,vt])for(const w of [C.wind(),C.wind(3,0),C.wind(4,90)]){
    out.push(leg(v,75,w,v===vt?'fw':undefined));out.push(C.rtlEnergy(a,h,v,w));out.push(C.bestSpeed(v,w));}
    out.push(C.rtlEnergy(a,h,vt,C.wind(3,70),undefined,'mc'));out.push(C.transitionEstimate(vt,'mc','fw'));return plain(out);}
console.log(JSON.stringify({suite:'T5b1 NEW synthetic',groups,legacy_nominal_suite_run:false}));
