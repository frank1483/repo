"""功能3 demo：python3 -m gcs_demo.recognition.demo [輸出.html]

照固定腳本操作一次切換器（文字指令 → 場域 → 候選 → 確認套用 → 辨識 → 復原），
把每一步的結果寫進單檔 HTML，可在瀏覽器逐步播放。辨識是合成權重，只示範切換流程。
"""
from __future__ import annotations

import html
import json
import sys

from .switcher import Switcher

SCENE = {"t": 0, "frame_id": "demo", "lat": 24.7869, "lon": 120.9966, "objects": [
    {"class": "crop_disease", "bbox": [0.12, 0.18, 0.12, 0.10]},
    {"class": "weed", "bbox": [0.30, 0.62, 0.10, 0.08]},
    {"class": "insulator_defect", "bbox": [0.55, 0.15, 0.08, 0.10]},
    {"class": "line_foreign_object", "bbox": [0.70, 0.10, 0.10, 0.06]},
    {"class": "bird_nest", "bbox": [0.82, 0.30, 0.08, 0.08]},
    {"class": "person", "bbox": [0.62, 0.66, 0.05, 0.12]},
    {"class": "car", "bbox": [0.40, 0.80, 0.12, 0.07]}]}

SCRIPT = [
    ("cmd", "起飛後幫我開辨識"),
    ("pick", "agriculture"),
    ("cmd", "設定任務：巡檢電線"),
    ("cmd", "改成三架編隊協同搜索"),
    ("undo", None),
    ("cmd", "回到農田噴灑"),
]


def run():
    s = Switcher()
    steps = []

    def snap(kind, text, result):
        frames = []
        if s.session is not None:
            vehicles = ["UAV-1", "UAV-2", "UAV-3"] if s.domain_id and s.domains[s.domain_id]["recognition"].get("per_vehicle") else ["UAV-1"]
            for i, v in enumerate(vehicles):
                frames.append({"vehicle_id": v, "dets": s.detect({**SCENE, "frame_id": f"s{len(steps)}-{i}", "vehicle_id": v})})
        steps.append({"kind": kind, "text": text, "result": result, "domain": s.domain_id,
                      "domain_zh": s.domains[s.domain_id]["name_zh"] if s.domain_id else None,
                      "ui_template": s.domains[s.domain_id]["ui_template"] if s.domain_id else None,
                      "model": s.model_id, "frames": frames, "can_undo": bool(s.history)})

    for kind, arg in SCRIPT:
        if kind == "undo":
            snap("undo", "復原上一個切換", s.undo())
            continue
        p = s.propose(arg) if kind == "cmd" else s.propose(domain_id=arg)
        text = arg if kind == "cmd" else f"（使用者點選場域：{s.domains[arg]['name_zh']}）"
        if p["status"] in ("SELECT", "HOLD"):
            r = s.apply(p["proposal_id"])
            p = {**p, "applied": r}
        snap(kind, text, p)
    rows = [{"id": r["id"], "name_zh": r["manifest"].get("name_zh"), "runtime": r["manifest"].get("runtime"),
             "installed": r["installed"], "problems": r["problems"], "latency_ms": r.get("latency_ms")}
            for r in s.rows()]
    return {"steps": steps, "models": rows, "events": s.events,
            "domains": {k: {"name_zh": v["name_zh"], "ui_template": v["ui_template"],
                            "required": v["recognition"]["required_classes"],
                            "assumption_zh": v.get("assumption_zh")} for k, v in s.domains.items()},
            "class_zh": s.class_zh, "scene": SCENE}


PAGE = r"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>場域辨識切換</title>
<style>
:root{--bg:#f7f7f5;--fg:#1d1d1b;--mut:#6b6b66;--card:#fff;--line:#deded8;--acc:#1f6feb;--ok:#1a7f37;--bad:#c62828;--warn:#9a6700}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#161615;--fg:#ececea;--mut:#9d9d97;--card:#20201f;--line:#34342f;--acc:#58a6ff;--ok:#3fb950;--bad:#f85149;--warn:#d29922}}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,"Noto Sans TC",sans-serif}
main{max-width:1000px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:4px 0}.mut{color:var(--mut)}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:12px 0}
button{font:inherit;padding:6px 14px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--fg);cursor:pointer}button.p{background:var(--acc);color:#fff;border-color:var(--acc)}
table{border-collapse:collapse;width:100%;font-size:14px}td,th{border-bottom:1px solid var(--line);padding:5px 6px;text-align:left;vertical-align:top}
.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}.pill{display:inline-block;padding:1px 8px;border-radius:99px;border:1px solid var(--line);font-size:13px;margin-right:4px}
.cmd{font-size:17px;font-weight:600}.wrap{overflow-x:auto}
svg{width:100%;max-width:420px;height:auto;border:1px solid var(--line);border-radius:8px;background:var(--bg)}
.grid{display:flex;flex-wrap:wrap;gap:12px}.grid>div{flex:1 1 280px}
</style></head><body><main>
<h1>依場域切換辨識模型 demo</h1>
<p class="mut">文字指令 → 程式判斷場域 → 從本機已安裝模型挑候選 → 確認後先載入試跑再切換 → 可復原。辨識結果是合成資料，只示範切換流程。</p>
<div class="card"><button id="prev">上一步</button> <button class="p" id="next">下一步</button> <span id="pos" class="mut"></span></div>
<div id="step"></div>
<div class="card"><b>本機模型清單</b><div class="wrap"><table id="models"></table></div></div>
<div class="card"><b>事件紀錄（給任務報告用）</b><div class="wrap"><table id="events"></table></div></div>
</main><script>
const D=__DATA__;let i=0;const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const st={SELECT:['切換','ok'],KEEP:['不換','mut'],HOLD:['保留原模型','warn'],CLARIFY:['反問','warn']};
function svg(f){let r='';for(const o of D.scene.objects){const[x,y,w,h]=o.bbox;r+=`<rect x="${x*400}" y="${y*240}" width="${w*400}" height="${h*240}" fill="none" stroke="var(--line)" stroke-dasharray="3"/>`}
for(const d of f.dets){const[x,y,w,h]=d.bbox;r+=`<rect x="${x*400}" y="${y*240}" width="${w*400}" height="${h*240}" fill="none" stroke="var(--acc)" stroke-width="2"/><text x="${x*400}" y="${y*240-3}" font-size="11" fill="var(--acc)">${esc(d.class_zh)} ${d.conf}</text>`}
return `<div><b>${esc(f.vehicle_id)}</b><svg viewBox="0 0 400 240">${r}</svg></div>`}
function show(){const s=D.steps[i];document.getElementById('pos').textContent=`第 ${i+1} / ${D.steps.length} 步`;
let h=`<div class="card"><div class="mut">${s.kind==='undo'?'復原':'指令'}</div><div class="cmd">${esc(s.text)}</div>`;const r=s.result;
if(s.kind==='undo'){h+=`<p class="${r.ok?'ok':'bad'}">${r.ok?'已回到前一個場域與模型':esc(r.error)}</p>`}
else if(r.status==='CLARIFY'){h+=`<p class="warn">${esc(r.resolution.question_zh)}</p><p>${r.resolution.options.map(o=>`<span class="pill">${esc(o.name_zh)}</span>`).join('')}</p><p class="mut">判斷 ${r.judge_ms} ms；沒有改變任何設定</p>`}
else{const[t,c]=st[r.status];const hits=r.resolution.hits||{};const hl=Object.entries(hits).filter(([k,v])=>v.length).map(([k,v])=>`${esc(D.domains[k].name_zh)}：${v.map(esc).join('、')}`).join('；');
h+=`<p>場域 <b>${esc(r.domain_name_zh)}</b> ${hl?`<span class="mut">（關鍵字 ${hl}）</span>`:''} → <span class="${c}"><b>${t}</b></span>　${esc(r.reason_zh)}</p><p class="mut">判斷 ${r.judge_ms} ms；來源：${r.source==='llm'?'模型在候選內選':'規則'}${r.applied?`；載入試跑 ${r.applied.load_ms??0} ms`:''}</p>`;
if(D.domains[r.domain_id].assumption_zh)h+=`<p class="warn">假設：${esc(D.domains[r.domain_id].assumption_zh)}</p>`;
h+=`<div class="wrap"><table><tr><th>候選</th><th>模型</th><th>分數</th><th>延遲</th><th>選配類別涵蓋</th></tr>${r.evaluation.candidates.map(c=>`<tr><td>${c.cid}</td><td>${esc(c.name_zh)}${c.id===r.model_id?' ✔':''}</td><td>${c.score}</td><td>${c.latency_ms??'未量測'}</td><td>${c.pref_coverage}</td></tr>`).join('')}
${r.evaluation.rejected.map(c=>`<tr class="mut"><td>✗</td><td>${esc(c.name_zh)}</td><td colspan="3">${c.reasons.map(esc).join('；')}</td></tr>`).join('')}</table></div>`}
h+=`</div><div class="card"><b>目前狀態</b>　場域 <span class="pill">${esc(s.domain_zh??'未設定')}</span> UI 模板 <span class="pill">${esc(s.ui_template??'—')}</span> 辨識模型 <span class="pill">${esc(s.model??'無')}</span> ${s.can_undo?'<span class="mut">可復原</span>':''}
<div class="grid" style="margin-top:8px">${s.frames.length?s.frames.map(svg).join(''):'<p class="mut">尚未載入辨識模型</p>'}</div><p class="mut">虛線框＝畫面中的物件；藍框＝目前模型辨識到且高於門檻的。</p></div>`;
document.getElementById('step').innerHTML=h}
document.getElementById('models').innerHTML='<tr><th>模型</th><th>執行方式</th><th>狀態</th></tr>'+D.models.map(m=>`<tr><td>${esc(m.name_zh)}</td><td>${esc(m.runtime)}</td><td class="${m.installed?'ok':'bad'}">${m.installed?'已安裝':esc(m.problems.join('；'))}</td></tr>`).join('');
document.getElementById('events').innerHTML='<tr><th>#</th><th>事件</th><th>場域</th><th>模型</th><th>說明</th></tr>'+D.events.map((e,k)=>`<tr><td>${k+1}</td><td>${esc(e.kind)}</td><td>${esc(e.domain)}</td><td>${esc(e.model)}</td><td class="mut">${esc(e.text??e.note??e.error??(e.status?e.status+' → '+(e.to_model??''):''))}</td></tr>`).join('');
document.getElementById('next').onclick=()=>{if(i<D.steps.length-1){i++;show()}};document.getElementById('prev').onclick=()=>{if(i>0){i--;show()}};show();
</script></body></html>"""


def build_html(data):
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return PAGE.replace("__DATA__", blob)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    data = run()
    for k, st in enumerate(data["steps"], 1):
        r = st["result"]
        print(f"{k}. {st['text']} → {r.get('status', 'UNDO' if st['kind'] == 'undo' else '')} "
              f"場域={st['domain_zh']} 模型={st['model']} 辨識={sum(len(f['dets']) for f in st['frames'])}")
    if argv:
        with open(argv[0], "w", encoding="utf-8") as f:
            f.write(build_html(data))
        print("寫出", html.escape(argv[0]))


if __name__ == "__main__":
    main()
