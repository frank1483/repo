'use strict';
// NEW synthetic checks only; first execution belongs to Claude.
const assert=require('assert'),fs=require('fs'),path=require('path');
const C=require('./load_core')();
const plain=x=>JSON.parse(JSON.stringify(x));
const profile=id=>C.loadAirframe(JSON.parse(fs.readFileSync(path.join(__dirname,'../../airframes',id+'.json'),'utf8')));
const fw=profile('fw_example'),vt=profile('vtol_example');
const near=(a,b)=>assert(Math.abs(a-b)<=2e-9*Math.max(1,Math.abs(a),Math.abs(b)),`${a} != ${b}`);
let groups=0;function test(name,f){try{f();groups++;}catch(e){e.message=name+': '+e.message;throw e}}
function corner(){return [{id:'A',lat:0,lon:0,alt:60},{id:'B',lat:.01,lon:0,alt:60},{id:'C',lat:.01,lon:.01,alt:60}]}
function hybrid(explicit=true){const a=[{id:'H',lat:0,lon:0,alt:0,kind:'takeoff'},{id:'U',lat:0,lon:0,alt:60,kind:'takeoff'},
    {cmd:3000,to_mode:'fw'},{id:'A',lat:.01,lon:0,alt:60}];if(explicit)a.push({cmd:3000,to_mode:'mc'});a.push({id:'L',lat:.01,lon:0,alt:0,kind:'landing'});return a}
const route=(p=corner(),v=fw,w=C.wind(),start=100,hover=5,mode)=>C.routeEstimate(v,p,16,w,start,hover,mode);
test('arc length and time',()=>{const e=C.turnEstimate(fw,16,90,C.wind());near(e.radius_m,40);near(e.dist_m,40*Math.PI/2);near(e.time_s,e.dist_m/16)});
test('n squared induced drag',()=>{const e=C.turnEstimate(fw,16,90,C.wind()),p=fw.airframe_profile.power,n=e.load_factor;
    const watts=(.5*1.225*16**3*p.wing_area_m2*p.cd0+2*p.k_induced*(fw.mass_kg*9.81)**2*n**2/(1.225*16*p.wing_area_m2))/p.eta_prop+p.p_avionics_w;
    near(e.energy_wh,watts*e.time_s/3600);assert(watts>C.powerW(fw,16))});
test('signed bank symmetry',()=>near(C.turnEstimate(fw,16,90,C.wind(),20).energy_wh,C.turnEstimate(fw,16,90,C.wind(),-20).energy_wh));
test('arc input and stall rejection',()=>{for(const a of [-1,361,true,NaN])assert.throws(()=>C.turnEstimate(fw,16,a,C.wind()));
    assert.throws(()=>C.turnEstimate(fw,16,90,C.wind(),0));assert.throws(()=>C.turnEstimate(fw,16,90,C.wind(),undefined,1));
    assert.throws(()=>C.turnEstimate(fw,16,90,C.wind(),20,100));assert.throws(()=>C.turnEstimate(fw,8.4,90,C.wind(),undefined,40))});
test('zero arc',()=>near(C.turnEstimate(fw,16,0,C.wind(),0).energy_wh,0));
test('banked loiter',()=>{const e=C.loiterEstimate(fw,16,60,C.wind());near(e.dist_m,960);near(e.energy_wh,C.powerW(fw,16,'fw',e.bank_deg)/60)});
test('mc hold under wind',()=>{const e=C.loiterEstimate(vt,16,30,C.wind(3,20),undefined,'mc');near(e.dist_m,0);near(e.energy_wh,C.powerW(vt,3,'mc')/120);
    assert.throws(()=>C.loiterEstimate(vt,16,30,C.wind(),40,'mc'))});
test('windy arcs fail closed',()=>{assert.throws(()=>C.turnEstimate(fw,16,90,C.wind(1,0)),/ground-track/);assert.throws(()=>C.loiterEstimate(fw,16,60,C.wind(1,0)),/ground-track/);assert.throws(()=>route(corner(),fw,C.wind(1,0)),/ground-track/)});
test('route corner and component sums',()=>{const e=route();assert.equal(e.legs.length,3);assert.equal(e.legs.filter(x=>x.angle_deg>0).length,1);for(const k of ['dist_m','time_s','energy_wh'])near(e[k],e.legs.reduce((s,x)=>s+x[k],0))});
test('collinear no arc',()=>{const p=corner();p[2].lat=.02;p[2].lon=0;assert.equal(route(p).legs.length,2)});
test('airborne FW cannot be complete feasible',()=>{const e=route();assert(e.energy_feasible);assert.equal(e.feasible,false);assert.equal(e.landing_modeled,false)});
test('target dwell loiters',()=>{const p=corner().slice(0,2);p[1].kind='target';const a=route(p),b=route(p,fw,C.wind(),100,0);near(a.time_s-b.time_s,5);assert.equal(a.legs.at(-1).scope,'air_relative_loiter_allowance')});
test('same pose loiter skips FW zero leg',()=>{const p=corner()[0];assert.equal(route([p,{...p,kind:'loiter',loiter_s:30}]).legs.length,1)});
test('FW departure after loiter needs exit heading',()=>{const p=corner();p[1].loiter_s=5;assert.throws(()=>route(p),/exit-heading/)});
test('hybrid transitions and landing',()=>{const e=route(hybrid(),vt);assert.deepStrictEqual(plain(e.legs.filter(x=>x.to_mode).map(x=>x.to_mode)),['fw','mc']);assert(e.feasible);assert(e.landing_modeled);assert.equal(e.arrival_mode,'mc');near(e.transition_allowance_dist_m,100)});
test('landing to_mc once',()=>{const a=route(hybrid(),vt),b=route(hybrid(false),vt);near(a.energy_wh,b.energy_wh);assert.equal(b.legs.filter(x=>x.to_mode==='mc').length,1)});
test('transition allowance not flown distance',()=>near(route(hybrid(),vt).dist_m,C.legEstimate(vt,[0,0],[.01,0],60,60,16,C.wind(),'fw').dist_m));
test('repeat mode costs zero',()=>{const p=hybrid();p.splice(3,0,{cmd:3000,to_mode:'fw'});near(route(p,vt).energy_wh,route(hybrid(),vt).energy_wh)});
test('hybrid initial mode required',()=>{assert.throws(()=>route(corner(),vt));assert.equal(route(corner(),vt,C.wind(),100,5,'fw').arrival_mode,'fw')});
test('normalized commands reject raw params or displacement',()=>{for(const event of [{cmd:3000,to_mode:'fw',lat:1},{cmd:3000,param1:4},{cmd:16},{cmd:true},{cmd:3000,to_mode:'unknown'}]){const p=hybrid();p[2]=event;assert.throws(()=>route(p,vt))}});
test('FW terminal geometry and events after landing reject',()=>{for(const kind of ['takeoff','landing']){const p=corner().slice(0,2);p[1].kind=kind;assert.throws(()=>route(p))}assert.throws(()=>route([...hybrid(),{cmd:3000,to_mode:'fw'}],vt))});
test('malformed route and mode fields reject',()=>{const a=corner()[0],b=corner()[1];for(const p of [[],[a],Array(1001).fill(a),[a,{...b,alt:true}],[a,{...b,kind:'loiter'}],[a,{...b,mode:'mc'}]])assert.throws(()=>route(p))});
test('calib and percentage',()=>{const a=route(hybrid(),vt),v=C.vehicle({...plain(vt),calib:1.7}),b=route(hybrid(),v,C.wind(),80);near(b.energy_wh,a.energy_wh*1.7);near(b.end_pct,80-b.energy_wh/162*100)});
test('shared entry and immutability',()=>{const p=hybrid(),before=JSON.stringify(p);assert.deepStrictEqual(plain(route(p,vt,C.wind(),100,0)),plain(C.estimateRouteEnergy(p,vt,C.wind(),16)));assert.equal(JSON.stringify(p),before)});
test('legacy MC x500 equals legacy vehicle',()=>{for(const w of [C.wind(),C.wind(3,20)])assert.deepStrictEqual(plain(C.routeEstimate(profile('x500'),corner(),8,w)),plain(C.routeEstimate(C.vehicle(),corner(),8,w)))});
test('windy straight FW works',()=>near(route(corner().slice(0,2),fw,C.wind(3,0)).legs[0].v_air,19));
function vectorRows(){const out=[];for(const v of [fw,vt]){for(const angle of [0,90,180])out.push(C.turnEstimate(v,16,angle,C.wind()));out.push(C.loiterEstimate(v,16,60,C.wind(),undefined,'fw'))}
    out.push(route());out.push(route(corner().slice(0,2),fw,C.wind(3,0)));out.push(route(hybrid(),vt));out.push(route(hybrid(false),vt));out.push(C.loiterEstimate(vt,16,30,C.wind(3,20),undefined,'mc'));return plain(out)}
const at=process.argv.indexOf('--python-vectors');
if(at>=0){const expected=JSON.parse(fs.readFileSync(process.argv[at+1],'utf8').replace(/^\uFEFF/,''));
    test('Python JS parity',()=>{function eq(a,b){if(typeof a==='number'&&typeof b==='number')return near(a,b);if(Array.isArray(a)){assert.equal(a.length,b.length);return a.forEach((x,i)=>eq(x,b[i]))}
        if(a&&typeof a==='object'){assert.deepStrictEqual(Object.keys(a).sort(),Object.keys(b).sort());for(const k of Object.keys(a))eq(a[k],b[k]);return}assert.strictEqual(a,b)}eq(expected,vectorRows())})}
console.log(JSON.stringify({suite:'T5b2a NEW synthetic',groups,legacy_research_run:false}));
