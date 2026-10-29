// NEW synthetic T5a unit/parity tests; Claude performs first execution.
// Optional --python-vectors <file> consumes output of python -m gcs_demo.t5a_vectors.
'use strict';
const assert = require('assert'), fs = require('fs'), path = require('path');
const C = require('./load_core')();
const plain = x => JSON.parse(JSON.stringify(x));
const json = name => JSON.parse(fs.readFileSync(path.join(__dirname, '../../airframes', name+'.json'), 'utf8'));
const profiles = Object.fromEntries(['x500','fw_example','vtol_example'].map(id => [id,json(id)]));
const load = id => C.loadAirframe(profiles[id]);
const mc = load('x500'), fw = load('fw_example'), vt = load('vtol_example');
let groups = 0;
const test = (name, fn) => { try { fn(); groups++; } catch (e) { e.message = name+': '+e.message; throw e; } };
const near = (a,b,tol=1e-10) => assert(Math.abs(a-b) <= tol*Math.max(1,Math.abs(a),Math.abs(b)), `${a} != ${b}`);

test('labels and no imported propeller data', () => {
    assert.equal(mc.airframe_profile.source, 'assumed');
    for (const v of [fw,vt]) assert.equal(v.airframe_profile.source,'placeholder');
    for (const v of [mc,fw,vt]) assert(!('eta_table' in v.airframe_profile));
});
test('legacy vehicle payload unchanged', () => {
    assert.deepStrictEqual(Object.keys(C.vehicle()).sort(), ['vehicle_id','mass_kg','battery_wh','usable_frac','p_hover_w','cda_m2','eta','cruise_mps','max_mps','reserve_pct','calib'].sort());
});
test('partial JSON and copy independence', () => {
    const p = {id:'custom',limits:{reserve_pct:25},notes:{kind:'synthetic'}};
    const v = C.loadAirframe(p); v.airframe_profile.notes.kind='changed';
    assert.equal(p.notes.kind,'synthetic'); assert.equal(v.reserve_pct,25); assert.equal(v.p_hover_w,190);
    assert.equal(C.loadAirframe('\ufeff'+JSON.stringify(p)).vehicle_id,'custom');
});
test('reject bad values without coercion', () => {
    for (const p of [{mass_kg:true},{mass_kg:NaN},{battery:{wh:0}},{battery:{usable_frac:1.1}},
                     {battery:{cell_count:4.5}},{limits:{reserve_pct:101}},{limits:{cruise_mps:16}},
                     {uncertainty:{capacity_pct:100}},{power:{eta:0}},{power:{p_hover_w:'190'}}])
        assert.throws(() => C.loadAirframe(p));
});
test('reject invalid structure/schema/provenance', () => {
    for (const p of [[],{battery:null},{type:'plane'},{schema:true},{schema:1},{source:''},{id:''},{note:Infinity},JSON.parse('{"constructor":1}')])
        assert.throws(() => C.loadAirframe(p));
});
test('require fixed-wing and hybrid transition parameters', () => {
    assert.throws(() => C.loadAirframe({type:'fixed_wing'}));
    const p = plain(profiles.vtol_example); delete p.transition.to_mc_wh;
    assert.throws(() => C.loadAirframe(p));
});
test('multirotor monotonic and exact legacy power', () => {
    let last=-1;
    for (const s of [0,4,8,15]) { const w=C.powerW(mc,s); assert(w>last); last=w; assert.strictEqual(w,C.powerW(C.vehicle(),s)); }
    assert.strictEqual(C.powerW(mc,0),190);
});
test('new synthetic x500 route matches legacy', () => {
    const pts=[{id:'a',lat:0,lon:0,alt:0},{id:'b',lat:.001,lon:.002,alt:12,kind:'target'},{id:'c',lat:0,lon:0,alt:0}];
    for (const w of [C.wind(),C.wind(3,30)])
        assert.deepStrictEqual(plain(C.routeEstimate(mc,pts,8,w)),plain(C.routeEstimate(C.vehicle(),pts,8,w)));
});
test('speed ranges are airspeed and fixed-wing stall rejects', () => {
    assert.deepStrictEqual(plain(C.speedRange(mc)),[0,15]); near(C.speedRange(fw)[0],8.4); near(C.speedRange(vt)[0],9.6);
    for (const s of [0,8.4-1e-6,35.01]) assert.throws(() => C.powerW(fw,s));
});
test('fixed-wing and hybrid-fw U shape', () => {
    assert(C.powerW(fw,8.4)>C.powerW(fw,12)); assert(C.powerW(fw,35)>C.powerW(fw,12));
    assert(C.powerW(vt,9.6,'fw')>C.powerW(vt,12,'fw')); assert(C.powerW(vt,35,'fw')>C.powerW(vt,12,'fw'));
});
test('induced drag follows n squared', () => {
    const p=fw.airframe_profile.power,s=24;
    const parasite=.5*1.225*s**3*p.wing_area_m2*p.cd0;
    const induced=bank => (C.powerW(fw,s,null,bank)-p.p_avionics_w)*p.eta_prop-parasite;
    near(induced(60)/induced(0),4);
});
test('bank-adjusted stall', () => {
    const lo=C.speedRange(fw,60)[0]; near(lo,8.4*Math.sqrt(2));
    assert.throws(() => C.powerW(fw,lo-1e-6,null,60));
});
test('coordinated turn primitive', () => {
    const t=C.turnGeometry(fw,16); near(t.radius_m,40); near(t.load_factor,1/Math.cos(t.bank_deg*Math.PI/180));
    near(16**2/(9.81*Math.tan(t.bank_deg*Math.PI/180)),40);
    assert.strictEqual(C.turnGeometry(fw,16,0).radius_m,null);
    near(C.turnGeometry(fw,16,-20).radius_m,C.turnGeometry(fw,16,20).radius_m);
});
test('invalid coordinated turns reject', () => {
    for (const call of [()=>C.turnGeometry(fw,16,null,10),()=>C.turnGeometry(fw,16,90),
                        ()=>C.turnGeometry(fw,16,NaN),()=>C.turnGeometry(fw,16,20,40),()=>C.turnGeometry(mc,8)])
        assert.throws(call);
});
test('same mechanical climb work for all types and modes', () => {
    for (const [v,mode,s] of [[mc,null,8],[fw,null,16],[vt,'mc',0],[vt,'fw',16]]) {
        const base=C.powerW(v,s,mode); near(C.powerW(v,s,mode,0,2)-base,v.mass_kg*9.81*2/.7);
        assert.strictEqual(C.powerW(v,s,mode,0,-2),base);
    }
});
test('explicit hybrid modes and incompatible modes', () => {
    assert.throws(()=>C.powerW(vt,16)); assert.strictEqual(C.powerW(vt,0,'mc'),480);
    assert(C.powerW(vt,16,'fw')<C.powerW(vt,16,'mc'));
    assert.throws(()=>C.powerW(fw,16,'mc')); assert.throws(()=>C.powerW(mc,8,null,10));
});
test('synthetic J interpolation, clamping and fallback', () => {
    const p=plain(profiles.fw_example); p.prop_model='synthetic-test-only'; p.eta_table=[[0,.4],[1,.8]];
    const v=C.loadAirframe(p),q=v.airframe_profile;
    assert.equal(C.propEfficiency(q,16,.7),.7); near(C.propEfficiency(q,16,.7,.5),.6);
    assert.equal(C.propEfficiency(q,16,.7,0),.4); assert.equal(C.propEfficiency(q,16,.7,2),.8);
    near((C.powerW(v,16,null,0,0,0)-10)/(C.powerW(v,16,null,0,0,1)-10),2);
});
test('RPM converts speed to dimensionless J and per-call J overrides', () => {
    const p=plain(profiles.fw_example); p.prop_model={id:'synthetic-test-only',rpm:6000,diameter_m:.4}; p.eta_table=[[0,.4],[1,.8]];
    const q=C.loadAirframe(p).airframe_profile;
    near(C.propEfficiency(q,16,.7),.56); near(C.propEfficiency(q,16,.7,.5),.6);
});
test('bad efficiency tables and incomplete prop context reject', () => {
    for (const table of [[[0,.4]],[[0,.4],[0,.8]],[[1,.4],[0,.8]],[[0,0],[1,.8]],[[0,.4],[1,1.1]],[[0,.4],[1,true]]]) {
        const p=plain(profiles.fw_example); p.prop_model='test'; p.eta_table=table;
        assert.throws(()=>C.loadAirframe(p));
    }
    assert.throws(()=>C.loadAirframe({eta_table:[[0,.4],[1,.8]]}));
    assert.throws(()=>C.loadAirframe({prop_model:{id:'test',rpm:6000}}));
});
test('new model numeric inputs are strict', () => {
    for (const call of [()=>C.powerW(fw,16,null,true),()=>C.powerW(fw,16,null,90),()=>C.powerW(fw,16,null,0,NaN),
                        ()=>C.powerW(mc,-1),()=>C.powerW(mc,NaN),()=>C.powerW(mc,true)]) assert.throws(call);
});
test('pending route integration cannot produce a flight estimate', () => {
    for (const v of [fw,vt]) {
        assert.throws(()=>C.routeEstimate(v,[],16,C.wind()),/T5b/);
        assert.throws(()=>C.legEstimate(v,[0,0],[.001,0],10,0,16,C.wind()),/T5b/);
        assert.throws(()=>C.bestSpeed(v,C.wind()),/T5b/);
    }
});

let parity=0;
const arg=process.argv.indexOf('--python-vectors');
if (arg>=0) {
    assert(process.argv[arg+1],'--python-vectors requires a JSON path');
    const v=JSON.parse(fs.readFileSync(process.argv[arg+1],'utf8').replace(/^\uFEFF/,''));
    test('Python/JS profile parity',()=> {
        for (const [id,row] of Object.entries(v.profiles)) {
            assert.deepStrictEqual(plain(load(id)),row.vehicle);
            assert.deepStrictEqual(plain(C.speedRange(load(id))),row.speed_range);
        }
    });
    test('Python/JS numeric parity',()=> {
        for (const row of v.power) { near(C.powerW(load(row.id),row.v_air,row.mode,row.bank_deg,row.climb_mps),row.watts); parity++; }
        for (const row of v.turns) {
            const actual=C.turnGeometry(load(row.id),row.v_air,null,row.radius_m);
            for (const k of Object.keys(row.result)) near(actual[k],row.result[k]);
            parity++;
        }
        const prop=C.loadAirframe(v.prop.profile);
        near(C.powerW(prop,v.prop.v_air),v.prop.watts_nominal_rpm);
        near(C.powerW(prop,v.prop.v_air,null,0,0,.5),v.prop.watts_actual_j); parity+=2;
    });
}
console.log(JSON.stringify({suite:'T5a NEW synthetic',groups,python_js_numeric_vectors:parity,legacy_nominal_suite_run:false}));
