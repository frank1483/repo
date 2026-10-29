'use strict';
// NEW synthetic checks; first execution is assigned to Claude.
const assert=require('assert'),fs=require('fs'),path=require('path');
const C=require('./load_core')(),plain=x=>JSON.parse(JSON.stringify(x));
const profile=id=>C.loadAirframe(JSON.parse(fs.readFileSync(path.join(__dirname,'../../airframes',id+'.json'),'utf8')));
const near=(a,b)=>assert(Math.abs(a-b)<=2e-9*Math.max(1,Math.abs(a),Math.abs(b)),`${a} != ${b}`);
let groups=0;function test(name,f){try{f();groups++;}catch(e){e.message=name+': '+e.message;throw e}}
function loop(){return [{id:'H',lat:0,lon:0,alt:0},{id:'A',lat:.01,lon:0,alt:60},{id:'H',lat:0,lon:0,alt:0}]}
function hybrid(){return [{id:'H',lat:0,lon:0,alt:0,kind:'takeoff'},{id:'U',lat:0,lon:0,alt:60,kind:'takeoff'},
    {cmd:3000,to_mode:'fw'},{id:'A',lat:.01,lon:0,alt:60},{cmd:3000,to_mode:'mc'},
    {id:'R',lat:0,lon:0,alt:60},{id:'L',lat:0,lon:0,alt:0,kind:'landing'}]}
function result(v=profile('x500'),w=C.wind(3,0),points=loop(),speed=8,start=100,mode){return C.bounds(C.estimateForBounds(v,points,speed,w,start,0,mode),v)}
test('nominal whole loop',()=>{const v=profile('x500'),b=result(v);near(b.nominal.energy_wh,C.routeEstimate(v,loop(),8,C.wind(3,0),100,0).energy_wh)});
test('one wind outbound and return independent oracle',()=>{for(const row of result().scenarios){const w=row.wind.speed_mps,t=6371000*Math.PI/180*.01/8;
    const watts=a=>190+.5*1.225*.12*a**3/.7;const joules=(watts(8+w)+watts(Math.abs(8-w)))*t+2*9.81*60/.7+190*(60/3+60/2);
    near(row.base_energy_wh,joules/3600);near(row.legs[0].headwind_mps,w);near(row.legs[1].headwind_mps,-w)}});
test('capacity and start percentage',()=>{for(const r of result(undefined,undefined,undefined,8,72).scenarios)near(r.end_pct,72-r.energy_wh/r.capacity_wh*100)});
test('extrema are actual scenarios',()=>{const b=result();near(b.low_pct,Math.min(...b.scenarios.map(r=>r.end_pct)));near(b.high_pct,Math.max(...b.scenarios.map(r=>r.end_pct)));assert(b.scenarios.includes(b.conservative));assert(b.scenarios.includes(b.optimistic))});
test('deduplicate zero uncertainty',()=>{const v=profile('x500');v.airframe_profile.uncertainty={power_pct:0,capacity_pct:0,wind_mps:0};const b=result(v);assert.equal(b.scenarios.length,1);near(b.low_pct,b.high_pct)});
test('wind speed clamped',()=>{const b=result(undefined,C.wind(0,15));assert(b.scenarios.every(r=>r.wind.speed_mps>=0));assert.equal(b.scenarios.length,9)});
test('hybrid transitions scaled once',()=>{const b=result(profile('vtol_example'),undefined,hybrid(),16);assert(b.available);for(const r of b.scenarios){near(r.energy_wh,r.legs.reduce((s,l)=>s+l.energy_wh,0)*r.power_multiplier);assert.deepStrictEqual(plain(r.legs.filter(l=>l.to_mode).map(l=>l.to_mode)),['fw','mc']);assert(r.landing_modeled)}});
test('unsupported arc invalidates interval',()=>{const p=[{lat:0,lon:0,alt:60},{lat:.01,lon:0,alt:60},{lat:.01,lon:.01,alt:60}],b=result(profile('fw_example'),C.wind(),p,16);assert.equal(b.available,false);assert.equal(b.low_pct,null);assert.equal(b.optimistic,null);assert.equal(b.nominal.status,'ok');assert(b.scenarios.some(r=>r.status==='unsupported'))});
test('context required',()=>assert.throws(()=>C.bounds({energy_wh:1},profile('x500'))));
test('vehicle mismatch rejected',()=>{const v=profile('x500'),e=C.estimateForBounds(v,loop(),8,C.wind());assert.throws(()=>C.bounds(e,C.vehicle({...plain(v),calib:1.1})))});
test('inputs detached unchanged',()=>{const v=profile('x500'),p=loop(),before=JSON.stringify([p,v]),e=C.estimateForBounds(v,p,8,C.wind());C.bounds(e,v);assert.equal(JSON.stringify([p,v]),before);p[1].lat=.02;near(e.bounds_context.route[1].lat,.01)});
test('stale result numbers untrusted',()=>{const v=profile('x500'),e=C.estimateForBounds(v,loop(),8,C.wind()),b=plain(C.bounds(e,v));e.energy_wh=0;e.end_pct=100;assert.deepStrictEqual(plain(C.bounds(e,v)),b)});
test('invalid runtime numbers',()=>{const v=profile('x500');for(const s of [0,true,NaN,-1])assert.throws(()=>C.estimateForBounds(v,loop(),s,C.wind()));for(const p of [-1,101,true])assert.throws(()=>C.estimateForBounds(v,loop(),8,C.wind(),p))});
test('profile uncertainty required',()=>{const v=C.vehicle();assert.throws(()=>C.bounds(C.estimateForBounds(v,loop(),8,C.wind()),v))});
test('negative pct retained',()=>assert(result(undefined,undefined,undefined,8,0).low_pct<0));
test('no return or landing inference',()=>{const b=result(undefined,undefined,loop().slice(0,2));assert.equal(b.return_inferred,false);assert.equal(b.nominal.landing_modeled,false);assert.equal(b.nominal.legs.length,1)});
test('context schema validated',()=>{const v=profile('x500');for(const change of [{schema:true},{extra:1}]){const e=C.estimateForBounds(v,loop(),8,C.wind());Object.assign(e.bounds_context,change);assert.throws(()=>C.bounds(e,v))}});
test('capacity uncertainty validated',()=>{const v=profile('x500');v.airframe_profile.uncertainty.capacity_pct=100;assert.throws(()=>result(v))});
test('MC rejects mode events',()=>assert.throws(()=>C.estimateForBounds(profile('x500'),[loop()[0],{cmd:3000,to_mode:'fw'}],8,C.wind()),/hybrid/));
function vectorRows(){const rows=[];for(const w of [0,3,8]){const b=result(undefined,C.wind(w,25));rows.push([b.available,b.scenarios.length,b.low_pct,b.high_pct,b.nominal.energy_wh,b.nominal.end_pct])}
    const b=result(profile('vtol_example'),undefined,hybrid(),16);rows.push([b.available,b.scenarios.length,b.low_pct,b.high_pct,b.nominal.energy_wh,b.nominal.end_pct]);return rows}
const arg=process.argv.indexOf('--python-vectors');
if(arg>=0)test('Python parity 4 rows',()=>{const expected=JSON.parse(fs.readFileSync(process.argv[arg+1],'utf8')),actual=plain(vectorRows());assert.equal(expected.length,4);assert.equal(actual.length,4);
    expected.forEach((row,i)=>{assert.equal(actual[i][0],row[0]);assert.equal(actual[i][1],row[1]);for(let j=2;j<6;j++)near(actual[i][j],row[j])})});
console.log(JSON.stringify({batch:'T5b2b',groups,parity:arg>=0}));
