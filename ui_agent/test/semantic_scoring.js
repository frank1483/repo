'use strict';
// Semantic-scoring experiment (UI, 2026-11-06): replace stage C (rule literal scoring) with semantic scores,
// keep stage D (top score >= tau AND lead over second >= gap). Pure functions; no network.
// Groups: rule | logprob (hierarchical joint probability) | embed (cosine) | combo (rule + semantic).
const C = require('./load_core');

const REGIONS = {TL: '左上角', TR: '右上角', BL: '左下角', BR: '右下角', TC: '上方中間', BC: '下方中間', ML: '左側中間', MR: '右側中間', C: '畫面中央'};
const NUDGES = {L: '往左', R: '往右', U: '往上', D: '往下'};
const SCALES = [[1.25, '放大一點'], [0.8, '縮小一點'], [2, '放到最大'], [0.5, '縮到最小']];
const TEXTS = [[0.85, '文字 85%（較小）'], [1.0, '文字 100%（預設）'], [1.15, '文字 115%（較大）'], [1.3, '文字 130%（最大）']];
const alias = e => [e.name].concat(e.aliases || []).join('、');

// Stage A (safety gate, cancel) stays fixed for every group. Everything after it in analyzeSingle is
// literal matching (C) plus its decisions (D), including the "final" literal clarifications such as
// 「請補充要調整的模組」, so semantic groups score those rows too.
function fixedStage(row) {
  if (C.preGate(row.intent)) return {fixed: true, decision: C.preGate(row.intent).rule};
  const r = C.analyzeTurn(row.intent, row.ctx, '');
  if (r.cancelled || r.gate === 'pre' || r.safety_hold) return {fixed: true, decision: r.rule, result: r};
  return {fixed: false, result: r};
}
// Rule group: decisions the rules make without the score threshold (final literal rules, compound
// clauses, generic settings) are kept as the rules made them; only the threshold rows are re-thresholded.
function ruleForced(result) {
  if (!(result.rule.final || result.compound || result.generic_settings)) return null;
  const sel = result.rule.decision === 'SELECT';
  const ids = sel ? (result.rule.steps ? result.rule.steps.map(x => x.choice_id) : [result.rule.choice_id]) : [];
  const top6 = result.candidates.slice(0, 6).map(c => c.id);
  return {decision: sel ? 'SELECT' : 'NOT_CONFIDENT', ids, confident: sel, top: top6[0] || '', top_s: 0, lead: 0, top6, forced: result.rule.reason_zh || ''};
}

function visibleModules(ctx) {
  return C.MODULES.filter(m => m.page === ctx.page && (!ctx.modules || (ctx.modules[m.id] && ctx.modules[m.id].registered && ctx.modules[m.id].visible)));
}

// Program-generated candidate inventory for one context. Every group scores exactly this list
// (the rule group's candidates are a subset of it; anything the rule did not emit scores 0).
function inventory(ctx) {
  const out = [];
  const pageName = p => C.PAGES.filter(x => x.page === p)[0].name;
  for (const p of C.PAGES) out.push({id: 'NAV_' + p.page, kind: 'nav', page: p.page, section: -1, path: ['NAV', 'P' + p.page, 'WHOLE'],
    desc: '切到「' + p.name + '」畫面（' + alias(p) + '）'});
  for (const s of C.SECTIONS) out.push({id: 'NAV_' + s.page + '_' + s.section, kind: 'nav', page: s.page, section: s.section,
    path: ['NAV', 'P' + s.page, 'S' + s.section], desc: '切到「' + pageName(s.page) + ' › ' + s.name + '」（' + alias(s) + '）'});
  for (const m of visibleModules(ctx)) {
    const leaf = (op, code, text) => out.push({id: 'LAY_' + m.id + '_' + op, kind: 'layout', module: m.id, path: ['LAYOUT', m.id, code],
      desc: text + '（' + alias(m) + '）'});
    for (const r of Object.keys(REGIONS)) leaf('MOVE_' + r, 'MOVE_' + r, '把' + m.name + '移到' + REGIONS[r]);
    for (const d of Object.keys(NUDGES)) leaf('NUDGE_' + d, 'NUDGE_' + d, '把' + m.name + NUDGES[d] + '移一點');
    for (const [f, zh] of SCALES) if ((m.scales || []).indexOf(f) >= 0) leaf('SCALE_' + Math.round(f * 100), 'SCALE_' + Math.round(f * 100), zh + m.name + '（×' + f + '）');
    if (!m.locked) leaf('HIDE', 'HIDE', '隱藏' + m.name);
    leaf('SHOW', 'SHOW', '重新顯示' + m.name);
    leaf('RESET', 'RESET', m.name + '回到原本位置與大小');
  }
  for (const [v, zh] of TEXTS) out.push({id: 'SYS_TEXT_SCALE_' + Math.round(v * 100), kind: 'text_scale', path: ['TEXT', 'T' + Math.round(v * 100)],
    desc: '全系統' + zh});
  out.push({id: 'UNDO', kind: 'undo', path: ['HISTORY', 'UNDO'], desc: '復原上一步介面變更', ok: !!ctx.canUndo});
  out.push({id: 'REDO', kind: 'redo', path: ['HISTORY', 'REDO'], desc: '重做剛剛復原的介面變更', ok: !!ctx.canRedo});
  out.push({id: 'RESET_ALL', kind: 'reset_all', path: ['HISTORY', 'RESET_ALL'], desc: '版面與畫面全部回到 agent 介入前'});
  return out;
}

// Stage D on any score map {id: score}. Program filters: precondition-false leaves are dropped;
// a confident nav to where the user already is becomes HOLD (same as the rule "already here").
function decide(scores, inv, ctx, tau, gap) {
  const extra = Object.keys(scores).filter(id => !inv.some(c => c.id === id)).map(id => ({id, kind: 'other'}));
  const ranked = inv.concat(extra).filter(c => c.ok !== false).map(c => ({c, s: scores[c.id] || 0})).sort((a, b) => b.s - a.s || (a.c.id < b.c.id ? -1 : 1));
  const top = ranked[0], second = ranked[1] || {s: -Infinity};
  const lead = top.s - second.s;
  const ids6 = ranked.slice(0, 6).map(x => x.c.id);
  if (top.s >= tau && lead >= gap) {
    const here = top.c.kind === 'nav' && top.c.page === ctx.page && (top.c.section < 0 || top.c.section === ctx.section);
    return {decision: here ? 'HOLD' : 'SELECT', ids: here ? [] : [top.c.id], confident: true, top: top.c.id, top_s: top.s, lead, top6: ids6};
  }
  return {decision: 'NOT_CONFIDENT', ids: [], confident: false, top: top.c.id, top_s: top.s, lead, top6: ids6};
}

// ---- scorers: each returns {id: score} over the inventory
function ruleScores(result) {
  const s = {}; for (const c of result.candidates) s[c.id] = Math.max(s[c.id] || 0, c.score); return s;
}
function cosine(a, b) { let d = 0, x = 0, y = 0; for (let i = 0; i < a.length; ++i) { d += a[i] * b[i]; x += a[i] * a[i]; y += b[i] * b[i]; } return d / Math.sqrt(x * y); }
function embedScores(qvec, inv, vecOf) { const s = {}; for (const c of inv) s[c.id] = cosine(qvec, vecOf(c.desc)); return s; }
// Joint probability over the slot tree: P(kind) * P(next | kind) * ... ; unexpanded branches score 0.
function logprobScores(inv, distOf) {
  const s = {};
  for (const c of inv) {
    let p = 1;
    for (let k = 0; k < c.path.length && p > 0; ++k) {
      const d = distOf(c.path.slice(0, k));
      if (!d) { p = 0; break; }
      p *= d[c.path[k]] || 0;
    }
    s[c.id] = p;
  }
  return s;
}
// combo: weighted sum of rule (scaled to 0..1 by the rule's max 1.36) and a semantic score.
function comboScores(rule, sem, w) { const s = {}; for (const id of new Set(Object.keys(rule).concat(Object.keys(sem)))) s[id] = w * Math.min((rule[id] || 0) / 1.36, 1) + (1 - w) * (sem[id] || 0); return s; }

// ---- metrics
function judge(row, d) {
  const gold = row.expect, goldSel = gold.decision === 'SELECT';
  const right = d.confident ? (d.decision === 'SELECT' ? goldSel && JSON.stringify(d.ids) === JSON.stringify(gold.ids) : !goldSel) : !goldSel;
  return {right, confident_wrong: d.confident && !right, abstain_on_select: !d.confident && goldSel,
    top1: goldSel ? d.top === gold.ids[0] : null, in_top6: goldSel ? d.top6.indexOf(gold.ids[0]) >= 0 : null};
}
function summarize(judged) {
  const n = judged.length, conf = judged.filter(j => j.d.confident).length, wrong = judged.filter(j => j.j.confident_wrong).length;
  const sel = judged.filter(j => j.j.top1 !== null);
  const r = x => Math.round(x * 1000) / 1000;
  return {n, correct: judged.filter(j => j.j.right).length, acc: r(judged.filter(j => j.j.right).length / n), confident: conf, coverage: r(conf / n),
    confident_wrong: wrong, risk: conf ? r(wrong / conf) : 0, abstain_on_select: judged.filter(j => j.j.abstain_on_select).length,
    top1: sel.filter(j => j.j.top1).length + '/' + sel.length, top6: sel.filter(j => j.j.in_top6).length + '/' + sel.length};
}
function grid(values) {
  const lo = Math.min(...values), hi = Math.max(...values), taus = [], gaps = [];
  for (let i = 0; i <= 40; ++i) taus.push(lo + (hi - lo) * i / 40);
  for (let i = 0; i <= 20; ++i) gaps.push((hi - lo) / 2 * i / 20);
  return {taus, gaps};
}
// Pick (tau, gap) on DEV only: most correct, then fewest confident-wrong, then smallest tau.
function sweep(rows, scoreRows) {
  const tops = scoreRows.filter(x => !x.forced).map(x => decide(x.scores, x.inv, x.row.ctx, -Infinity, -Infinity).top_s);
  const {taus, gaps} = grid(tops), table = [];
  for (const tau of taus) for (const gap of gaps) {
    const judged = scoreRows.map(x => { const d = x.forced || decide(x.scores, x.inv, x.row.ctx, tau, gap); return {d, j: judge(x.row, d)}; });
    table.push(Object.assign({tau: +tau.toFixed(4), gap: +gap.toFixed(4)}, summarize(judged)));
  }
  const best = table.slice().sort((a, b) => b.correct - a.correct || a.confident_wrong - b.confident_wrong || a.tau - b.tau)[0];
  return {table, best};
}
function evaluate(scoreRows, tau, gap) {
  const judged = scoreRows.map(x => { const d = x.forced || decide(x.scores, x.inv, x.row.ctx, tau, gap); return {id: x.row.id, d, j: judge(x.row, d)}; });
  return {summary: summarize(judged), rows: judged};
}

module.exports = {fixedStage, ruleForced, inventory, decide, ruleScores, embedScores, logprobScores, comboScores, cosine, judge, summarize, sweep, evaluate, visibleModules};
