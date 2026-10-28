// New offline tests only. Claude owns the first run; no model/network/equipment.
const assert=require('assert'),fs=require('fs'),path=require('path'),vm=require('vm')
const C=require('./load_core')(),plain=x=>JSON.parse(JSON.stringify(x))
let count=0
function test(name,fn){fn();count++;console.log('ok '+name)}
function fixture(){return {
    m:{name:'合成測試',home:{id:'H',lat:24,lon:121},cruise_alt_m:0,speed_mps:8,no_fly:[],limits:{max_altitude_m:120},
       targets:[1,2,3,4,5,6].map(i=>({id:String(i),lat:24+i*0.000001,lon:121,alt:0,priority:1}))},
    v:C.vehicle({battery_wh:1.8,usable_frac:1}),w:C.wind(0,0)}}
function stateFor(m){return {lat:24,lon:121,alt:0,battery_pct:80,observed_ratio:1.2345,remaining:m.targets.map(t=>t.id),completed:[]}}
test('six independent cross-runtime version vectors',()=>{
    const data=JSON.parse(fs.readFileSync(path.join(__dirname,'../../t3_version_vectors.json'),'utf8'))
    data.forEach(x=>{const i=x.inputs;assert.strictEqual(C.missionVersion(i.mission,i.vehicle,i.wind,i.state),x.mission_version)})
})
test('object order stable and list order significant',()=>{
    const {m,v,w}=fixture(),r=C.planMission(m,v,w),copy=plain(m)
    assert.strictEqual(C.checkApply(r,Object.fromEntries(Object.entries(copy).reverse()),v,w,null).ok,true)
    copy.targets.reverse();assert.strictEqual(C.checkApply(r,copy,v,w,null).ok,false)
})
test('mission vehicle wind state each invalidate',()=>{
    const {m,v,w}=fixture(),s=stateFor(m),r={mission_version:C.missionVersion(m,v,w,s)}
    for(let i=0;i<4;i++){
        const a=[plain(m),plain(v),plain(w),plain(s)]
        if(i===0)a[0].targets[0].lon+=0.01
        else if(i===1)a[1].calib+=0.1
        else if(i===2)a[2].speed_mps+=1
        else a[3].battery_pct-=1
        assert.deepStrictEqual(plain(C.checkApply(r,...a)),{ok:false,reason_zh:'任務已變更，請重新規劃'})
    }
})
test('missing version and nonfinite input fail closed',()=>{
    const {m,v,w}=fixture(),r=C.planMission(m,v,w)
    assert.strictEqual(C.checkApply({},m,v,w,null).ok,false)
    m.speed_mps=NaN;assert.strictEqual(C.checkApply(r,m,v,w,null).ok,false)
})
test('result hash survives mutation of caller objects',()=>{
    const {m,v,w}=fixture(),r=C.planMission(m,v,w),version=r.mission_version
    m.targets[0].lat+=0.1
    assert.strictEqual(r.mission_version,version);assert.strictEqual(C.checkApply(r,m,v,w,null).ok,false)
})
test('all four event contexts bind effective inputs without mutating caller',()=>{
    const {m,v,w}=fixture(),s=stateFor(m),before=JSON.stringify([m,v,w,s])
    const events=[{type:'wind',speed_mps:4,from_deg:90},{type:'battery',battery_pct:70},
        {type:'no_fly',zone:{id:'Z',lat:25,lon:122,radius_m:10}},
        {type:'add_target',target:{id:'NEW',lat:24.001,lon:121,alt:0}}]
    events.forEach(e=>{
        const r=C.replan(m,v,w,s,e),ctx=C.replanContext(m,v,w,s,e)
        assert.strictEqual(ctx.vehicle.calib,1.235)
        assert.strictEqual(C.checkApply(r,ctx.mission,ctx.vehicle,ctx.wind,ctx.state).ok,true)
        assert(!r.candidates.some(c=>c.id==='S1'))
        ctx.state.remaining.reverse();assert.strictEqual(C.checkApply(r,ctx.mission,ctx.vehicle,ctx.wind,ctx.state).ok,false)
    })
    assert.strictEqual(JSON.stringify([m,v,w,s]),before)
})
test('S1 has two feasible full-battery return-home sorties and exact target union',()=>{
    const {m,v,w}=fixture(),r=C.planMission(m,v,w),s=r.candidates.find(c=>c.id==='S1')
    assert(s);assert.strictEqual(r.rule_choice,'');assert.strictEqual(s.sorties.length,2) // 使用者 10/28：分兩趟只列建議，不當預設
    assert(r.candidates.filter(c=>c.id!=='S1').every(c=>!c.feasible))
    assert.deepStrictEqual(plain(s.order).sort(),m.targets.map(t=>t.id).sort())
    assert.strictEqual(new Set(s.order).size,m.targets.length)
    assert.strictEqual(s.requires_battery_swap,true);assert.deepStrictEqual(plain(s.path),[])
    s.sorties.forEach(x=>{
        assert(x.feasible);assert(x.end_pct>=v.reserve_pct)
        assert.strictEqual(x.path[0].kind,'home');assert.strictEqual(x.path[x.path.length-1].kind,'home')
        assert.deepStrictEqual(plain(x.missing_must),[]);assert.deepStrictEqual(plain(x.constraint_deltas),[])
        const used=x.legs.reduce((a,l)=>a+l.energy_wh,0)
        assert(Math.abs(x.end_pct-(100-used/1.8*100))<1)
    })
    assert.strictEqual(s.end_pct,Math.min(...s.sorties.map(x=>x.end_pct)))
    assert(Math.abs(s.energy_wh-s.sorties.reduce((a,x)=>a+x.energy_wh,0))<0.11)
})
test('no S1 when a single sortie covers all',()=>{
    const {m,v,w}=fixture();v.battery_wh=90
    const r=C.planMission(m,v,w);assert(!r.candidates.some(c=>c.id==='S1'));assert.notStrictEqual(r.pick.decision,'HOLD')
})
test('no unsafe two-sortie candidate when battery too small',()=>{
    const {m,v,w}=fixture();v.battery_wh=0.2
    const r=C.planMission(m,v,w);assert(!r.candidates.some(c=>c.id==='S1'));assert.strictEqual(r.pick.decision,'HOLD')
    assert(r.evidence.some(e=>e.value && e.value.violations.some(x=>x.violated==='reserve' && x.short_pct>0)))
})
test('S1 cannot hide an altitude violation',()=>{
    const {m,v,w}=fixture();m.targets[0].alt=121
    assert(!C.planMission(m,v,w).candidates.some(c=>c.id==='S1'))
})
test('quantified reserve altitude missing-target and no-fly deficits',()=>{
    const {m,v}=fixture();m.no_fly=[{id:'Z',lat:24,lon:121,radius_m:10}]
    const a=[{id:'a',lat:24,lon:121,alt:125},{id:'b',lat:24,lon:121.001,alt:0}]
    const ds=plain(C.constraintDeltas(m,v,a,{margin_pct:-4.2},['missing']))
    assert(ds.some(d=>d.violated==='reserve' && d.short_pct===4.2))
    assert(ds.some(d=>d.violated==='altitude' && d.over_m===5))
    assert(ds.some(d=>d.violated==='no_fly' && d.short_m===10))
    assert(ds.some(d=>d.violated==='required_targets' && d.missing_count===1))
})
test('ruleChoice retains coverage and energy ordering',()=>{
    const a={id:'C',order:[1],feasible:true,energy_wh:1,must_rank:0},b={id:'S1',order:[1,2],feasible:true,energy_wh:2,must_rank:1}
    assert.strictEqual(C.ruleChoice([a,b]),'S1');b.order=[1];assert.strictEqual(C.ruleChoice([a,b]),'C')
})
// Execute only extracted QML JS functions in a stub harness, not a Qt engine.
const qml=fs.readFileSync(path.join(__dirname,'../GcpMissionAiPanel.qml'),'utf8')
function qmlFunction(name,ctx){
    const re=new RegExp('    function '+name+'\\([^)]*\\) \\{[\\s\\S]*?\\n    \\}')
    const match=qml.match(re);assert(match,'missing QML function '+name)
    return vm.runInNewContext('('+match[0].trim()+')',ctx)
}
test('QML stale reorder gate runs before snapshot or restore',()=>{
    const {m,v,w}=fixture();v.battery_wh=90
    const r=C.planMission(m,v,w),changed=plain(m);changed.targets[0].lat+=0.01
    let writes=0
    const ctx={Core:C,result:r,stage:'plan',selected:r.rule_choice,cand:()=>r.candidates[0],
        readMission:()=>changed,vehicleParams:()=>v,currentWind:()=>w,snapshot:()=>{writes++;return[]},restore:()=>writes++,qsTr:x=>x,status:''}
    qmlFunction('applySelected',ctx)();assert.strictEqual(writes,0);assert.strictEqual(ctx.status,'任務已變更，請重新規劃')
})
test('QML fresh single-sortie reorder reaches restore once',()=>{
    const {m,v,w}=fixture();v.battery_wh=90
    const r=C.planMission(m,v,w),c=r.candidates.find(x=>x.id===r.rule_choice)
    let writes=0
    const q=x=>({arg(){return this},toString(){return x}})
    const ctx={Core:C,result:r,mission:m,stage:'plan',selected:c.id,cand:()=>c,readMission:()=>m,vehicleParams:()=>v,currentWind:()=>w,
        snapshot:()=>m.targets.map(t=>({lat:t.lat,lon:t.lon,alt:t.alt})),restore:a=>{writes++;assert.strictEqual(a.length,6)},
        undoStack:[],makePlanKeepStatus:()=>{},qsTr:q,status:''}
    qmlFunction('applySelected',ctx)();assert.strictEqual(writes,1);assert.strictEqual(ctx.undoStack.length,1)
})
test('QML S1 gate rejects flattening before snapshot',()=>{
    const {m,v,w}=fixture(),r=C.planMission(m,v,w),c=r.candidates.find(x=>x.id==='S1')
    let writes=0
    const ctx={Core:C,result:r,mission:m,stage:'plan',selected:'S1',cand:()=>c,readMission:()=>m,vehicleParams:()=>v,currentWind:()=>w,
        snapshot:()=>{writes++;return[]},restore:()=>writes++,qsTr:x=>x,status:''}
    qmlFunction('applySelected',ctx)();assert.strictEqual(writes,0);assert(ctx.status.includes('兩個獨立架次'))
})
test('QML stale simulation gate runs before MissionRun construction',()=>{
    const {m,v,w}=fixture(),r=C.planMission(m,v,w),changed=plain(m);changed.targets[0].lat+=0.01
    let starts=0
    const core=Object.assign({},C,{MissionRun:function(){starts++}})
    const ctx={Core:core,result:r,selected:'C1',cand:()=>r.candidates[0],readMission:()=>changed,vehicleParams:()=>v,currentWind:()=>w,qsTr:x=>x,status:''}
    qmlFunction('simulate',ctx)();assert.strictEqual(starts,0);assert.strictEqual(ctx.status,'任務已變更，請重新規劃')
})
test('QML stale continuation gate runs before final_choice or fly',()=>{
    const {m,v,w}=fixture(),s=stateFor(m),e={type:'wind',speed_mps:1,from_deg:90},r=C.replan(m,v,w,s,e),changed=plain(m)
    changed.targets[0].lat+=0.01
    let flights=0
    const ctx={Core:C,result:r,applyState:s,applyEvent:e,selected:'R1',cand:()=>r.candidates.find(c=>c.id==='R1'),
        readMission:()=>changed,vehicleParams:()=>v,currentWind:()=>w,run:{fly:()=>flights++},qsTr:x=>x,status:''}
    qmlFunction('continueFlight',ctx)();assert.strictEqual(flights,0);assert(!('final_choice' in r))
    assert.strictEqual(ctx.status,'任務已變更，請重新規劃')
})
test('0316 worst-leg display provenance and timeline text preserve raw value',()=>{
    const raw=1.6120229858953736,run={v:C.vehicle(),t:2,pct:98,energy_estimated:true,completed:['WP2'],
        provenance:{energy_source:'SOC delta'},
        data_quality:{missing_wind:true,missing_current:true,soc_estimated:true,calibration_eligible:false,sample_interval_s:{min:1,median:1,max:1}},
        log:[0,5,0].map((alt,i)=>({t_s:i,lat:24,lon:121,alt,battery_pct:100-i,ground_speed_mps:0,wind_mps:null,wind_from:null})),
        legs:[{from:'H',to:'WP2',actual_wh:0.9,pred_wh:raw,headwind_mps:null,end_t_s:1}]}
    const r=C.makeReport(run,{targets:[{id:'WP2',priority:1}]},{end_pct:99,speed_mps:8},[],[]),f=Object.fromEntries(r.facts.map(f=>[f.key,f]))
    assert(f.worst_leg.text.includes('預估 1.61 Wh'));assert(!f.worst_leg.text.includes(String(raw)))
    assert.strictEqual(f.worst_leg.value.pred_wh,raw)
    assert(f.telemetry_source.text.includes('已用 PX4 SITL 匯出核對欄位，尚未用實機核對'))
    assert(f.timeline.text.includes('1.0 秒 起飛'));assert(f.timeline.text.includes('到達航點 WP2'))
    assert.strictEqual(f.timeline.value.length,3);assert(f.completion.text.includes('完成目標 1/1'))
})
test('0316 timeline first five events and explicit empty preview',()=>{
    const events=Array.from({length:8},(_,i)=>({kind:'waypoint',t_s:i,target_id:'P'+i})),text=C.timelineText(events)
    assert(text.includes('另 3 件'));assert(text.includes('P4'));assert(!text.includes('P5'));assert.strictEqual(events.length,8)
    assert(C.timelineText([]).includes('無可推定事件'))
})
console.log(JSON.stringify({new_t3_part_b_groups:count,qml_scope:'extracted JavaScript stub functions, not Qt compilation'}))
