"""ADR-0002 M4b：ID 圖（graphify 的資料形狀）、按方向檢索與預算分配。只用標準庫。

依「M4b 與新架構演算法說明 v3.4」（使用者 2026-11-19 12:49 裁決 ID-1、ID-2、預算；12:58 同意 M4b 照 v3.4 實作）。
- ID 首字母固定代表類別：U 介面、C 元件、D 無人機項目、S 狀態欄位、P 參數、A 巡檢區域、T 主題、M 模型、X 動作、H 手冊章節。
- 層級只由父子關係（parent）記錄；有類型的邊：讀取（C→S）、使用（C→P）、提供（D→S）。每條邊記來源，只有 EXTRACTED。
- 檢索：每句一個查詢向量；各方向在允許類別中挑起點，沿父子與有類型的邊展開 2 層；
  2 層找完仍缺該方向需要的型別才補第 3 層；起點是上層分類（U）時在其分支內重新搜尋。
- 預算：先放各方向的必要資料，再補可選；每方向 600，必要資料超過 600 才放寬到實際所需、最高 1,500；
  整次 3,000，必要資料總和超過就整份分批（延後者記「待處理」）。token 用呼叫端提供的 counter（live＝Gemma 4 tokenizer）。
- 校準紀錄分三種失敗：depth_not_found、trimmed、deferred_total。
"""
from __future__ import annotations

import array
import glob
import hashlib
import json
import math
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CATALOG = os.path.join(HERE, "id_catalog_v1.json")
AREAS = os.path.join(HERE, "areas_v1.json")
CORE_JS = os.path.join(REPO, "ui_agent", "qml", "GcpAgentCore.js")

DIRECTION_CATS = {"plan": ["A"], "ui": ["U"], "layout": ["C", "P", "U"], "color": ["T"], "model": ["M"],
                  "manual": [], "qa": ["S", "D"], "report": [], "chat": [], "flight_request": []}
REQUIRED_TYPES = {"plan": ["A"], "layout": ["C", "P"], "color": ["T"], "model": ["M"]}
SEEDS, DEPTH, DEPTH_MAX = 3, 2, 3
BUDGET_DIR, BUDGET_DIR_MAX, BUDGET_TOTAL = 600, 1500, 3000


def sha(b):
    return hashlib.sha256(b if isinstance(b, bytes) else b.encode("utf-8")).hexdigest()


def _ui_export():
    js = ("const C=require(process.argv[1]);console.log(JSON.stringify({pages:C.PAGES,sections:C.SECTIONS,"
          "modules:C.MODULES.map(m=>({id:m.id,name:m.name,page:m.page,aliases:m.aliases||[],locked:!!m.locked}))}))")
    loader = os.path.join(REPO, "ui_agent", "test", "load_core.js")
    out = subprocess.run(["node", "-e", js, loader], capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        raise SystemExit("讀取 GcpAgentCore.js 失敗：" + out.stderr[:200])
    return json.loads(out.stdout)


def build():
    """確定性建圖；回傳 {schema_version, sources, nodes, edges}。"""
    cat = json.load(open(CATALOG, encoding="utf-8"))
    ui = _ui_export()
    nodes, edges = {}, []

    def node(i, c, name, aliases=(), desc="", parent=None, src="", **kw):
        nodes[i] = dict({"id": i, "cat": c, "name": name, "aliases": list(aliases), "desc": desc, "parent": parent,
                         "source": src}, **kw)

    def edge(a, kind, b, src):
        edges.append({"from": a, "type": kind, "to": b, "confidence": "EXTRACTED", "source": src})

    page_id = {}
    for p in ui["pages"]:
        i = f"U{p['page'] + 1:03d}"
        page_id[p["page"]] = i
        node(i, "U", p["name"], p.get("aliases", []), "介面頁", None, "GcpAgentCore.js:PAGES")
    node("U100", "U", "首頁航線槽", ["首頁航線", "放到首頁"], "首頁顯示航線的位置", page_id[0], "id_catalog_v1.json")
    for k, s in enumerate(ui["sections"]):
        node(f"U{101 + k:03d}", "U", s["name"], s.get("aliases", []), "設定分區", page_id[s["page"]],
             "GcpAgentCore.js:SECTIONS")
    mod_id = {}
    for k, m in enumerate(ui["modules"]):
        i = f"C{k + 1:03d}"
        mod_id[m["id"]] = i
        node(i, "C", m["name"], m["aliases"], ("鎖定元件，不可隱藏" if m["locked"] else "介面元件"),
             page_id.get(m["page"]), "GcpAgentCore.js:MODULES", module=m["id"], locked=m["locked"])
    for p in cat["params"]:
        node(p["id"], "P", p["name"], p["aliases"], p["desc"], p.get("parent"), "id_catalog_v1.json",
             actions=p["actions"], allowed=p["allowed"])
    for m_id, i in mod_id.items():
        for pid in ("P002", "P003", "P004"):
            if pid == "P004" and nodes[i].get("locked"):
                continue
            edge(i, "使用", pid, "id_catalog_v1.json:params+MODULES.locked")
    for s in cat["states"]:
        node(s["id"], "S", s["name"], s["aliases"], s["desc"], None, "id_catalog_v1.json")
    for m_id, sids in cat["module_states"].items():
        for sid in sids:
            if m_id in mod_id:
                edge(mod_id[m_id], "讀取", sid, "id_catalog_v1.json:module_states")
    for d in cat["drones"]:
        node(d["id"], "D", d["name"], d["aliases"], d["desc"], None, "id_catalog_v1.json")
        for sid in d["provides"]:
            edge(d["id"], "提供", sid, "id_catalog_v1.json:drones.provides")
    for t in cat["themes"]:
        node(t["id"], "T", t["name"], t["aliases"], t["desc"], None, "id_catalog_v1.json")
    for m in cat["models"]:
        node(m["id"], "M", m["name"], m["aliases"], m["desc"], None, "id_catalog_v1.json", tag=m["tag"], mode=m["mode"])
    k = 10
    for f in sorted(glob.glob(os.path.join(HERE, "domains", "*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        if "recognition" not in d:
            continue
        k += 1
        node(f"M{k:03d}", "M", "巡檢辨識類別：" + d["name_zh"], d.get("keywords_zh", [])[:6],
             "切換巡檢辨識的任務類別", None, "domains/" + os.path.basename(f), domain=d["id"])
    areas = json.load(open(AREAS, encoding="utf-8"))["areas"]
    for k2, a in enumerate(areas):
        node(f"A{k2 + 1:03d}", "A", a["name"], a.get("aliases", []), "具名巡檢區域", None, "areas_v1.json", area=a["id"])
    for a in cat["actions"]:
        node(a["id"], "X", a["name"], [a["code"]], a["direction"], None, "id_catalog_v1.json", code=a["code"],
             direction=a["direction"], inputs=a["inputs"], outputs=a["outputs"], states=a.get("states"))
    sources = {}
    for f in (CATALOG, AREAS, CORE_JS):
        sources[os.path.relpath(f, REPO).replace("\\", "/")] = sha(open(f, "rb").read())
    for f in sorted(glob.glob(os.path.join(HERE, "domains", "*.json"))):
        sources[os.path.relpath(f, REPO).replace("\\", "/")] = sha(open(f, "rb").read())
    g = {"schema_version": "id-graph-v1", "sources": sources, "nodes": [nodes[i] for i in sorted(nodes)],
         "edges": sorted(edges, key=lambda e: (e["from"], e["type"], e["to"]))}
    return g


def path_of(g_nodes, i):
    out, cur = [], g_nodes.get(i)
    while cur is not None:
        out.append(cur["name"])
        cur = g_nodes.get(cur.get("parent"))
    return " → ".join(reversed(out))


def doc_text(g_nodes, n):
    return f"title: {n['name']} | text: {path_of(g_nodes, n['id'])}；{n['desc']}；{'、'.join(n['aliases'])}"


def line_of(g_nodes, n, with_desc=True):
    """候選一行格式：ID｜名稱／路徑／動作｜允許值。必要資料不含描述。"""
    s = f"{n['id']}｜{n['name']}\n路徑：{path_of(g_nodes, n['id'])}"
    if n.get("actions"):
        s += f"\n動作：{'、'.join(n['actions'])}｜允許值：{'、'.join(n.get('allowed', []))}"
    if n.get("locked"):
        s += "\n限制：鎖定元件，不可隱藏"
    if with_desc and n.get("desc"):
        s += f"\n說明：{n['desc']}"
    return s


class Graph:
    def __init__(self, g, vectors=None):
        self.g = g
        self.nodes = {n["id"]: n for n in g["nodes"]}
        self.adj = {i: set() for i in self.nodes}
        for n in g["nodes"]:
            if n.get("parent") in self.nodes:
                self.adj[n["id"]].add(n["parent"])
                self.adj[n["parent"]].add(n["id"])
        for e in g["edges"]:
            if e["from"] in self.nodes and e["to"] in self.nodes:
                self.adj[e["from"]].add(e["to"])
                self.adj[e["to"]].add(e["from"])
        self.vec = vectors or {}

    def children_all(self, i):
        out, stack = [], [c for c, n in self.nodes.items() if n.get("parent") == i]
        while stack:
            c = stack.pop()
            out.append(c)
            stack.extend(x for x, n in self.nodes.items() if n.get("parent") == c)
        return out

    def sim(self, qv, i):
        v = self.vec.get(i)
        return sum(a * b for a, b in zip(qv, v)) if v is not None and qv is not None else 0.0

    def retrieve(self, direction, qv):
        """回傳 {candidates:[id], log:{...}}；依 ID-2 規則展開。"""
        cats = DIRECTION_CATS.get(direction, [])
        pool = [i for i, n in self.nodes.items() if n["cat"] in cats]
        if not pool:
            return {"candidates": [], "log": {"seeds": [], "depth": 0, "depth_not_found": []}}
        ranked = sorted(pool, key=lambda i: (-self.sim(qv, i), i))
        seeds = ranked[:SEEDS]
        found = set(seeds)
        # 起點是上層分類（U）時：在其分支內用原句重新搜尋
        for s in list(seeds):
            if self.nodes[s]["cat"] == "U":
                branch = [c for c in self.children_all(s) if self.nodes[c]["cat"] in cats]
                found.update(sorted(branch, key=lambda i: (-self.sim(qv, i), i))[:SEEDS])
        frontier, depth = set(found), 0
        need = set(REQUIRED_TYPES.get(direction, []))
        while depth < DEPTH_MAX:
            if depth >= DEPTH:
                have = {self.nodes[i]["cat"] for i in found}
                if need <= have:
                    break
            depth += 1
            nxt = set()
            for i in frontier:
                nxt.update(self.adj[i])
            nxt -= found
            found |= nxt
            frontier = nxt
        have = {self.nodes[i]["cat"] for i in found}
        missing = sorted(need - have)
        cands = sorted(found, key=lambda i: (-self.sim(qv, i), i))
        return {"candidates": cands, "log": {"seeds": seeds, "depth": depth, "depth_not_found": missing}}


def required_items(graph, direction, cands):
    """必要資料：該方向需要的型別中，相似度最高的一個（含其限制）；layout 需要元件與參數。"""
    req = []
    for t in REQUIRED_TYPES.get(direction, []):
        for i in cands:
            if graph.nodes[i]["cat"] == t:
                req.append(i)
                break
    return req


def pack(graph, directions, retrieved, counter, must=None):
    """預算分配（v3.4 §2.3）。directions 依優先序；retrieved[d]＝retrieve() 結果；counter(text)→token 數。
    must[d]＝原句點名、一定要送出的 ID（v3.10）：和必要資料一起先放、一起計入預算，可選資料在剩餘額度內補。"""
    plan, used, pending = {}, 0, []
    log = {"trimmed": {}, "deferred_total": [], "expanded_to": {}, "must": {}}
    must = must or {}
    for d in directions:                                     # 1. 先放必要資料
        cands = retrieved[d]["candidates"]
        extra = [i for i in must.get(d, []) if i in graph.nodes]
        req = list(dict.fromkeys(extra + list(required_items(graph, d, cands))))
        added = [i for i in extra if i not in cands]
        if added:
            log["must"][d] = added
        req_text = "\n".join(line_of(graph.nodes, graph.nodes[i], with_desc=False) for i in req)
        need = counter(req_text) if req_text else 0
        cap = BUDGET_DIR if need <= BUDGET_DIR else min(need, BUDGET_DIR_MAX)
        if need > BUDGET_DIR_MAX or used + need > BUDGET_TOTAL:
            pending.append(d)
            log["deferred_total"].append(d)
            continue
        if cap > BUDGET_DIR:
            log["expanded_to"][d] = cap
        plan[d] = {"items": list(req), "lines": [line_of(graph.nodes, graph.nodes[i], with_desc=False) for i in req],
                   "tokens": need, "cap": cap}
        used += need
    for d in directions:                                     # 2. 再補可選資料
        if d not in plan:
            continue
        p = plan[d]
        for i in retrieved[d]["candidates"]:
            if i in p["items"]:
                continue
            ln = line_of(graph.nodes, graph.nodes[i], with_desc=True)
            t = counter(ln)
            if p["tokens"] + t > p["cap"] or used + t > BUDGET_TOTAL:
                log["trimmed"].setdefault(d, []).append(i)
                continue
            p["items"].append(i)
            p["lines"].append(ln)
            p["tokens"] += t
            used += t
    return {"plan": plan, "pending": pending, "total_tokens": used, "log": log}


def build_index(out_dir, embed_fn):
    """建 id_graph.json 與節點向量（文件前綴＋描述）。embed_fn(list[str])→list[list[float]]。"""
    if os.path.exists(out_dir):
        raise SystemExit("輸出已存在；只建一次，要更新請開新目錄")
    os.makedirs(out_dir)
    g = build()
    nodes = {n["id"]: n for n in g["nodes"]}
    ids = [n["id"] for n in g["nodes"]]
    vecs = []
    for k in range(0, len(ids), 32):
        vecs.extend(embed_fn([doc_text(nodes, nodes[i]) for i in ids[k:k + 32]]))
    dim = len(vecs[0])
    arr = array.array("f")
    for v in vecs:
        if len(v) != dim:
            raise SystemExit("向量維度不符")
        arr.extend(v)
    gj = json.dumps(g, ensure_ascii=False, sort_keys=True, indent=1)
    open(os.path.join(out_dir, "id_graph.json"), "w", encoding="utf-8", newline="\n").write(gj)
    with open(os.path.join(out_dir, "id_vectors.f32"), "wb") as f:
        arr.tofile(f)
    man = {"schema": "IdIndexManifest/1", "graph_sha256": sha(gj), "ids": ids, "dimension": dim,
           "vectors_sha256": sha(open(os.path.join(out_dir, "id_vectors.f32"), "rb").read()),
           "prefix_document": "title: {名稱} | text: {路徑}；{描述}；{別名}", "n_nodes": len(ids), "n_edges": len(g["edges"])}
    json.dump(man, open(os.path.join(out_dir, "ID_INDEX_MANIFEST.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return man


def load_index(d):
    man = json.load(open(os.path.join(d, "ID_INDEX_MANIFEST.json"), encoding="utf-8"))
    gj = open(os.path.join(d, "id_graph.json"), encoding="utf-8").read()
    if sha(gj) != man["graph_sha256"] or sha(open(os.path.join(d, "id_vectors.f32"), "rb").read()) != man["vectors_sha256"]:
        raise SystemExit("ID 索引雜湊不符")
    arr = array.array("f")
    arr.frombytes(open(os.path.join(d, "id_vectors.f32"), "rb").read())
    dim = man["dimension"]
    vecs = {i: list(arr[k * dim:(k + 1) * dim]) for k, i in enumerate(man["ids"])}
    return Graph(json.loads(gj), vecs), man
