"""ADR-0002／ADR-0001 §7：手冊向量檢索（EmbeddingGemma 2＋BM25＋RRF），只用標準庫。

依「向量檢索演算法說明 v1」（adr0002_algo/向量檢索_演算法說明_v1.md；使用者 2026-11-18 23:55「繼續：下載並建索引」）。
- 片段：約 256 token／重疊 32，以字元近似（英文約 4 字元／token → 1024／128 字元）〔候選，U-01〕。
- 前綴（H-16，取自官方模型卡 huggingface.co/google/embeddinggemma-2，2026-11-18 讀取）：
  查詢 "task: search result | query: {query}"；文件 "title: {title} | text: {content}"（無標題用 "none"）。
- 向量 L2 正規化；NaN、零向量、維度不符就失敗；片段上限 32,768。
- 查詢：BM25 前 50＋向量前 50，RRF k＝60；依 chunk_id、再依同文件同 text_sha256 去重；同分依 doc_id→byte_start→chunk_id；最多 5 段。
- LLM 之後不做 embedding；片段一律當資料。
"""
from __future__ import annotations

import array
import hashlib
import json
import math
import os
import re
import sys
import time
import urllib.request
from collections import Counter

EMBED_MODEL = "embeddinggemma-2:270m-q8_0-text"
PREFIX_QUERY = "task: search result | query: {query}"
PREFIX_DOC = "title: {title} | text: {content}"
CHUNK_CHARS, OVERLAP_CHARS = 1024, 128
MAX_CHUNKS = 32768
CHUNK_POLICY = f"chars{CHUNK_CHARS}-overlap{OVERLAP_CHARS}-v1"
GLOSSARY = {"返航": ["rtl", "return"], "起飛": ["takeoff"], "降落": ["land", "landing"], "高度": ["altitude"],
            "電池": ["battery"], "電量": ["battery"], "禁航區": ["geofence", "no-fly"], "航點": ["waypoint"],
            "參數": ["parameter"], "任務": ["mission"], "校準": ["calibration"], "感測器": ["sensor"],
            "飛行模式": ["flight mode"], "地理圍欄": ["geofence"], "遙控器": ["rc", "radio"]}
TOKEN_RE = re.compile(r"[a-z0-9_]+")


def sha(b):
    return hashlib.sha256(b if isinstance(b, bytes) else b.encode("utf-8")).hexdigest()


def embed(texts, url="http://127.0.0.1:11434"):
    body = json.dumps({"model": EMBED_MODEL, "input": texts}).encode("utf-8")
    req = urllib.request.Request(url + "/api/embed", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        vs = json.loads(r.read())["embeddings"]
    out = []
    for v in vs:
        if any(math.isnan(x) for x in v):
            raise ValueError("NaN 向量")
        n = math.sqrt(sum(x * x for x in v))
        if n == 0:
            raise ValueError("零向量")
        out.append([x / n for x in v])
    return out


def clean_md(text):
    text = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.S)            # front-matter
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)                      # 圖片
    return text


def chunk_doc(rel, data, manual, commit):
    text = clean_md(data.decode("utf-8", errors="replace"))
    raw = data.decode("utf-8", errors="replace")
    heading = []
    pieces = []
    pos = 0
    sections = re.split(r"(?m)^(#{1,6} .*)$", text)
    buf_head = ""
    for part in sections:
        if re.match(r"^#{1,6} ", part or ""):
            level = len(part) - len(part.lstrip("#"))
            heading = heading[:level - 1] + [part.lstrip("#").strip()]
            buf_head = " > ".join(heading)
            continue
        body = part.strip()
        i = 0
        while i < len(body):
            seg = body[i:i + CHUNK_CHARS]
            if seg.strip():
                pieces.append((buf_head, seg))
            i += CHUNK_CHARS - OVERLAP_CHARS
    out = []
    doc_sha = sha(data)
    for k, (head, seg) in enumerate(pieces):
        start = raw.find(seg[:64])
        start = start if start >= 0 else -1
        tsha = sha(seg)
        cid = sha(f"{doc_sha}|{start}|{start + len(seg)}|{CHUNK_POLICY}|{tsha}")[:24]
        out.append({"chunk_id": cid, "doc_id": f"{manual}:{rel}", "manual": manual, "path": rel, "version": commit,
                    "heading_path": head, "byte_start": start, "byte_end": start + len(seg) if start >= 0 else -1,
                    "text_sha256": tsha, "text": seg})
    return out


def tokens(s):
    return TOKEN_RE.findall(s.lower())


def build(corpus_dir, out_dir, url="http://127.0.0.1:11434", batch=32):
    if os.path.exists(out_dir):
        raise SystemExit("索引輸出已存在；索引只整包重建成新版本，不原地更新")
    os.makedirs(out_dir)
    chunks, corpus = [], []
    for manual in ("px4", "qgc"):
        man = json.load(open(os.path.join(corpus_dir, manual, "FETCH_MANIFEST.json"), encoding="utf-8"))
        base = os.path.join(corpus_dir, manual, man["commit"])
        for f in man["files"]:
            data = open(os.path.join(base, f["path"]), "rb").read()
            if sha(data) != f["sha256"]:
                raise SystemExit(f"文件雜湊不符：{f['path']}")
            corpus.append({"doc_id": f"{manual}:{f['path']}", "relative_path": f"{manual}/{man['commit']}/{f['path']}",
                           "sha256": f["sha256"], "manual": manual, "version": man["commit"], "language": "en",
                           "license_ref": man["source"]["license"]})
            chunks.extend(chunk_doc(f["path"], data, manual, man["commit"]))
    if len(chunks) > MAX_CHUNKS:
        raise SystemExit(f"片段 {len(chunks)} 超過上限 {MAX_CHUNKS}，停止建包")
    vec = array.array("f")
    dim = None
    t0 = time.time()
    for i in range(0, len(chunks), batch):
        part = chunks[i:i + batch]
        vs = embed([PREFIX_DOC.format(title=c["heading_path"] or "none", content=c["text"]) for c in part], url)
        for v in vs:
            if dim is None:
                dim = len(v)
            if len(v) != dim:
                raise SystemExit("向量維度不符")
            vec.extend(v)
        if i % (batch * 20) == 0:
            print(f"embedded {i}/{len(chunks)} {time.time() - t0:.0f}s", flush=True)
    with open(os.path.join(out_dir, "vectors.f32"), "wb") as f:
        vec.tofile(f)
    with open(os.path.join(out_dir, "chunks.jsonl"), "w", encoding="utf-8") as f:
        for k, c in enumerate(chunks):
            f.write(json.dumps(dict(c, vector_row=k), ensure_ascii=False) + "\n")
    df = Counter()
    for c in chunks:
        df.update(set(tokens(c["text"])))
    lex = {"N": len(chunks), "avgdl": sum(len(tokens(c["text"])) for c in chunks) / max(1, len(chunks)), "df": df}
    with open(os.path.join(out_dir, "lexical.json"), "w", encoding="utf-8") as f:
        json.dump(lex, f)
    model_manifest = os.path.join(os.path.expanduser("~"), ".ollama", "models", "manifests", "registry.ollama.ai",
                                  "library", "embeddinggemma-2", "270m-q8_0-text")
    manifest = {"schema": "IndexManifest/1", "index_id": "manuals-px4-qgc-v1", "corpus": corpus,
                "preprocessing_id": "strip-frontmatter-images-v1", "glossary_hash": sha(json.dumps(GLOSSARY, sort_keys=True)),
                "chunk_policy": CHUNK_POLICY, "embedding_model": EMBED_MODEL,
                "embedding_model_manifest_sha256": sha(open(model_manifest, "rb").read()),
                "runtime": {"name": "ollama", "endpoint": url}, "dimension": dim, "dtype": "float32",
                "normalization": "l2", "prefix_document": PREFIX_DOC, "prefix_query": PREFIX_QUERY,
                "prefix_source": "https://huggingface.co/google/embeddinggemma-2（2026-11-18 讀取）",
                "n_chunks": len(chunks), "vector_file_hash": sha(open(os.path.join(out_dir, "vectors.f32"), "rb").read()),
                "chunks_file_hash": sha(open(os.path.join(out_dir, "chunks.jsonl"), "rb").read()),
                "lexical_index_hash": sha(open(os.path.join(out_dir, "lexical.json"), "rb").read()),
                "build_seconds": round(time.time() - t0, 1)}
    with open(os.path.join(out_dir, "INDEX_MANIFEST.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    return manifest


class Index:
    def __init__(self, index_dir, url="http://127.0.0.1:11434"):
        self.dir = index_dir
        self.url = url
        self.man = json.load(open(os.path.join(index_dir, "INDEX_MANIFEST.json"), encoding="utf-8"))
        for fn, key in (("vectors.f32", "vector_file_hash"), ("chunks.jsonl", "chunks_file_hash"),
                        ("lexical.json", "lexical_index_hash")):
            if sha(open(os.path.join(index_dir, fn), "rb").read()) != self.man[key]:
                raise SystemExit(f"索引檔雜湊不符：{fn}")
        self.chunks = [json.loads(l) for l in open(os.path.join(index_dir, "chunks.jsonl"), encoding="utf-8")]
        self.vec = array.array("f")
        with open(os.path.join(index_dir, "vectors.f32"), "rb") as f:
            self.vec.frombytes(f.read())
        self.dim = self.man["dimension"]
        lex = json.load(open(os.path.join(index_dir, "lexical.json"), encoding="utf-8"))
        self.N, self.avgdl, self.df = lex["N"], lex["avgdl"], lex["df"]
        self.toks = [tokens(c["text"]) for c in self.chunks]
        self.calls = []        # 每次 embedding 請求：端點、延遲、成功與否（與 LLM 呼叫分開記）

    def _bm25(self, q, top=50, k1=1.2, b=0.75):
        qt = tokens(q)
        for zh, en in GLOSSARY.items():
            if zh in q:
                qt += [t for e in en for t in tokens(e)]
        scores = []
        for i, toks in enumerate(self.toks):
            tf = Counter(toks)
            s = 0.0
            for t in set(qt):
                if t in tf:
                    n = self.df.get(t, 0)
                    idf = math.log(1 + (self.N - n + 0.5) / (n + 0.5))
                    s += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(toks) / self.avgdl))
            if s > 0:
                scores.append((s, i))
        scores.sort(key=lambda x: -x[0])
        return [i for _, i in scores[:top]]

    def _vector(self, q, top=50, vector=None):
        t0 = time.monotonic()
        try:
            qv = vector or embed([PREFIX_QUERY.format(query=q)], self.url)[0]
            if len(qv) != self.dim:
                raise ValueError(f"查詢向量維度 {len(qv)} 與索引 {self.dim} 不符")
            if vector is None:
                self.calls.append({"url": self.url, "latency_s": round(time.monotonic() - t0, 3), "ok": True})
        except Exception as e:  # noqa: BLE001
            self.calls.append({"url": self.url, "latency_s": round(time.monotonic() - t0, 3), "ok": False,
                               "error": repr(e)})
            raise
        d = self.dim
        scores = []
        v = self.vec
        for i in range(len(self.chunks)):
            off = i * d
            s = 0.0
            for j in range(d):
                s += qv[j] * v[off + j]
            scores.append((s, i))
        scores.sort(key=lambda x: -x[0])
        return [i for _, i in scores[:top]]

    def query_vector(self, q):
        """在 LLM 之前呼叫一次；回傳正規化向量或 None（失敗時記錄）。"""
        t0 = time.monotonic()
        try:
            v = embed([PREFIX_QUERY.format(query=q)], self.url)[0]
            if len(v) != self.dim:
                raise ValueError(f"查詢向量維度 {len(v)} 與索引 {self.dim} 不符")
            self.calls.append({"url": self.url, "latency_s": round(time.monotonic() - t0, 3), "ok": True,
                               "stage": "pre_llm"})
            return v
        except Exception as e:  # noqa: BLE001
            self.calls.append({"url": self.url, "latency_s": round(time.monotonic() - t0, 3), "ok": False,
                               "stage": "pre_llm", "error": repr(e)})
            return None

    def search(self, q, k=5, use_vector=True, vector=None, require_pre=False):
        lex = self._bm25(q)
        reason = None
        try:
            if not use_vector:
                vec, reason = [], "vector_disabled"
            elif vector is None and require_pre:
                vec, reason = [], "no_query_vector"
            elif vector is None:
                vec = self._vector(q)
            else:
                vec = self._vector(q, vector=vector)
        except Exception as e:  # noqa: BLE001 - 向量不可用時只用關鍵字並標降級
            vec, reason = [], "vector_error:" + repr(e)[:80]
        degraded = reason is not None
        score = {}
        for ranks in (lex, vec):
            for r, i in enumerate(ranks, 1):
                score[i] = score.get(i, 0.0) + 1.0 / (60 + r)
        order = sorted(score, key=lambda i: (-score[i], self.chunks[i]["doc_id"], self.chunks[i]["byte_start"],
                                              self.chunks[i]["chunk_id"]))
        out, seen_id, seen_text = [], set(), set()
        for i in order:
            c = self.chunks[i]
            key2 = (c["doc_id"], c["text_sha256"])
            if c["chunk_id"] in seen_id or key2 in seen_text:
                continue
            seen_id.add(c["chunk_id"])
            seen_text.add(key2)
            out.append({k2: c[k2] for k2 in ("chunk_id", "manual", "path", "version", "heading_path", "text")}
                       | {"score": round(score[i], 6)})
            if len(out) >= k:
                break
        if not lex and reason is None:
            reason = "no_lexical_hits"
        mode = "rrf" if vec and lex else ("vector_only" if vec else ("lexical_only" if lex else "none"))
        return {"results": out, "degraded": degraded or not vec or not lex, "degraded_reason": reason,
                "mode": mode, "status": "OK" if out else "NOT_FOUND"}


if __name__ == "__main__":
    print(json.dumps(build(sys.argv[1], sys.argv[2]), ensure_ascii=False)[:2000])
