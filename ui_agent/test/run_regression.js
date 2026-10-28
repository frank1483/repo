// Rule-only checks with an explicitly simulated shell. Never opens HTTP, Qt or devices.
const fs = require('fs'), path = require('path'), C = require('./load_core');
const input = process.argv[2] || path.join(__dirname,'regression_ui_agent.jsonl');
const rows = fs.readFileSync(input,'utf8').split(/\r?\n/).filter(s=>s.trim()).map(JSON.parse);
if(rows.length<200) throw Error('Expected at least 200 fixtures');
const seen = new Set();
function simulate(cs,ctx) {
    const original={page:ctx.page,section:ctx.section};
    let loc={...original}, applied=true, undo=(ctx.undo||[]).slice(), redo=(ctx.redo||[]).slice();
    for(const c of cs) {
        if(c.kind==='nav') {
            if((ctx.permission_denied_pages||[]).includes(c.page))return {...original,applied:false};
            loc={page:c.page,section:c.section};
        } else if(c.kind==='layout') {
            const m=C.MODULES.find(m=>m.id===c.module);
            if(!m || (m.locked&&c.op==='hide') || (ctx.permission_denied_pages||[]).includes(m.page))return {...original,applied:false};
            if(loc.page!==m.page)loc={page:m.page,section:-1};
        } else if(c.kind==='undo') {
            for(let i=0;i<(c.steps||1)&&undo.length;i++)loc=undo.pop();
        } else if(c.kind==='redo'&&redo.length)loc=redo.pop();
        else if(c.kind==='reset_all'&&ctx.initial)loc=ctx.initial;
        else if(c.kind==='layout_load') {
            const saved=(ctx.layoutSnapshots||{})[c.name];
            if(!saved||(ctx.permission_denied_pages||[]).includes(saved.page))return {...original,applied:false};
            loc={page:saved.page,section:saved.section};
        }
        // Save/default have no location change. Settings persistence and geometry require Qt tests.
    }
    return {...loc,applied};
}
let actions=0,locations=0,passed=0;const failures=[],by_category={};
for(const r of rows) {
    if(!r.id||seen.has(r.id)||typeof r.intent!=='string'||!r.ctx||!r.expect||!Array.isArray(r.expect.ids))throw Error('Invalid fixture '+r.id);
    seen.add(r.id);
    const result=C.analyze(r.intent,r.ctx), decision=result.rule;
    const ids=decision.decision==='SELECT'?(decision.steps?decision.steps.map(s=>s.choice_id):[decision.choice_id]):[];
    const candidates=ids.map(id=>C.candidateById(result,id));
    const actionOK=decision.decision===r.expect.decision&&JSON.stringify(ids)===JSON.stringify(r.expect.ids)&&candidates.every(Boolean);
    const final=candidates.every(Boolean)?simulate(candidates,r.ctx):{page:r.ctx.page,section:r.ctx.section,applied:false};
    const locationOK=final.page===r.expect.final_page&&final.section===r.expect.final_section&&
        (r.expect.applied===undefined||final.applied===r.expect.applied);
    if(actionOK)actions++;if(locationOK)locations++;if(actionOK&&locationOK)passed++;
    const bucket=by_category[r.category]||(by_category[r.category]={total:0,passed:0});bucket.total++;if(actionOK&&locationOK)bucket.passed++;
    if(!actionOK||!locationOK)failures.push({id:r.id,intent:r.intent,expect:r.expect,
        actual:{decision:decision.decision,ids,final_page:final.page,final_section:final.section,applied:final.applied}});
}
console.log(JSON.stringify({verification_scope:'rules + simulated shell only; no Qt/HTTP/Settings/device',total:rows.length,passed,
    action_accuracy:actions/rows.length,final_page_accuracy:locations/rows.length,by_category,failures},null,2));
process.exitCode=failures.length?1:0;

