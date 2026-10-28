// New tests only; Claude preserves first execution output. No model or equipment.
const assert=require('assert'),crypto=require('crypto')
module.exports=function(C) {
    let n=0
    function test(name,fn){fn();n++}
    const plain=x=>JSON.parse(JSON.stringify(x))
    function fixture(){
        const v=C.vehicle({calib:1.2})
        return {v,t:2,pct:98,completed:['A'],energy_estimated:true,
            data_quality:{missing_wind:true,missing_current:true,soc_estimated:true,calibration_eligible:false,
                sample_count:3,trimmed_samples:2,sample_interval_s:{min:1,median:1,max:1}},
            log:[{t_s:0,lat:24,lon:121,alt:0,battery_pct:100,ground_speed_mps:0,wind_mps:null,wind_from:null},
                 {t_s:1,lat:24,lon:121,alt:5,battery_pct:99,ground_speed_mps:1,wind_mps:null,wind_from:null},
                 {t_s:2,lat:24,lon:121,alt:0,battery_pct:98,ground_speed_mps:0,wind_mps:null,wind_from:null}],
            legs:[{from:'H',to:'A',actual_wh:0.8,pred_wh:0.7,headwind_mps:null,partial:false,end_t_s:1}]}
    }
    const mission={targets:[{id:'A',priority:1}]},plan={speed_mps:8,end_pct:90}
    const run=fixture(),rep=C.makeReport(run,mission,plan,[],[],{git_short_hash:'caller-hash'})
    test('unknown wind facts and calibration',()=>{
        assert(!rep.facts.some(f=>['headwind','wind_change','best_speed'].includes(f.key)))
        assert.strictEqual(rep.next_calib,1.2)
        assert.strictEqual(rep.data_quality.calibration_eligible,false)
        assert(!rep.facts.find(f=>f.key==='worst_leg').value.hasOwnProperty('headwind_mps'))
    })
    test('timeline and margin',()=>{
        assert.deepStrictEqual(plain(rep.timeline.map(e=>e.kind)),['takeoff','waypoint','landing'])
        assert.strictEqual(rep.energy_margin.margin_pct,78)
        assert.strictEqual(rep.energy_margin.landing_inferred,true)
        assert(!('alert_lead_time' in rep))
    })
    test('rule versions',()=>assert.deepStrictEqual(plain(rep.versions),{git_short_hash:'caller-hash',prompt_hash:null,model:null}))
    test('numeric precision including percent',()=>{
        const facts=[{text:'落地 80.0%',value:{margin:12.345}}]
        assert.deepStrictEqual(plain(C.unsupportedNumbers(['落地 80%，餘裕 12.35%'],facts)),[])
        assert.deepStrictEqual(plain(C.unsupportedNumbers(['落地 80.1%'],facts)),['80.1'])
    })
    function rewrite(summary,suggestion){return JSON.stringify({summary_zh:summary,suggestions:[{text_zh:suggestion,evidence_ids:['F1']}]})}
    test('summary fabrication -> complete rule fallback',()=>{
        const r=C.applyReportLlm(rep,rewrite('落地 8765.4321%','補充量測'))
        assert.strictEqual(r.source,'rule');assert(r.llm_fallback_reason.startsWith('unsupported_numbers:'))
        assert.deepStrictEqual(plain(r.suggestions),plain(rep.suggestions))
    })
    test('suggestion fabrication -> complete rule fallback',()=>{
        const r=C.applyReportLlm(rep,rewrite('任務結束','增加 8765.4321%'))
        assert.strictEqual(r.source,'rule');assert.strictEqual(r.summary_zh,rep.summary_zh)
    })
    test('wind advice cannot bypass quality gate',()=>assert.strictEqual(C.applyReportLlm(rep,rewrite('任務結束','逆風時改速')).llm_fallback_reason,'wind_advice_without_measurements'))
    test('accepted model rewrite and versions',()=>{
        const r=C.applyReportLlm(rep,rewrite('任務結束','補充量測'),{model:'offline-test-stub',prompt_hash:'caller-prompt'})
        assert.strictEqual(r.source,'llm');assert.strictEqual(r.versions.model,'offline-test-stub')
        assert.strictEqual(r.versions.prompt_hash,'caller-prompt')
    })
    test('later invalid rewrite restores original rule snapshot',()=>{
        const r=C.applyReportLlm(rep,rewrite('任務結束','補充量測'))
        const bad=C.applyReportLlm(r,rewrite('捏造 8765.4321%','補充量測'))
        assert.strictEqual(bad.source,'rule');assert.strictEqual(bad.summary_zh,rep.summary_zh)
    })
    test('invalid evidence list does not throw',()=>{
        assert.strictEqual(C.applyReportLlm(rep,JSON.stringify({summary_zh:'結束',suggestions:[{text_zh:'量測',evidence_ids:42}]})).source,'rule')
    })
    test('alert lead uses no future data and ignores generic lead_s',()=>{
        const a=C.reserveAlertLeads(run,[{t_s:1,lead_s:9999}]);assert.strictEqual(a[0].lead_s,79)
        const changed=fixture();changed.log[2].battery_pct=0
        assert.strictEqual(C.reserveAlertLeads(changed,[{t_s:1}])[0].lead_s,79)
        assert.strictEqual(C.reserveAlertLeads(run,[{t_s:100}]).length,0)
    })
    test('explicit reserve prediction',()=>assert.strictEqual(C.reserveAlertLeads(run,[{t_s:1,predicted_reserve_breach_t_s:21}])[0].lead_s,20))
    test('current measured but wind unknown stays ineligible',()=>{
        const r=fixture();r.energy_estimated=false;r.data_quality.missing_current=false;r.data_quality.soc_estimated=false
        assert.strictEqual(C.makeReport(r,mission,plan,[],[]).next_calib,1.2)
    })
    test('SHA256 UTF-8 known and crypto-reference vectors',()=>{
        for(const s of ['', 'abc', '繁體中文\n---\n%', '✈️', 'x'.repeat(1000)]) assert.strictEqual(C.sha256Text(s),crypto.createHash('sha256').update(s).digest('hex'))
    })
    test('prompt hash covers exact requested bytes',()=>{
        const p=C.reportPrompt(rep)
        assert.strictEqual(p.prompt_hash,crypto.createHash('sha256').update(p.system+'\n---\n'+p.user).digest('hex').slice(0,16))
    })
    console.log('T3 Part A new JS tests: '+n+' passed')
}
if(require.main===module)module.exports(require('./load_core')())
