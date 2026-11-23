"""Independent gemma4:e2b token counter, v2 (follows llama.cpp b11351 gemma4 rules as read
from public source; not a byte-for-byte proof of the local binary).

Rules implemented:
  1. parse_special: rendered text is partitioned on special tokens (token_type CONTROL=3 or
     USER_DEFINED=4) by leftmost-longest match; each becomes one token.
  2. remaining text: ' ' -> U+2581 (escape_whitespaces), pre-split with regex [^\n]+|[\n]+,
     BPE by merge rank inside each piece, unknown final pieces -> <0xXX> bytes (skipped if absent).
  3. No BOS added (add_bos=false for gemma4; the Ollama renderer writes '<bos>' explicitly).
Offline, stdlib only; vocab strings decoded as strict UTF-8.
"""
import hashlib
import heapq
import json
import os
import re
import struct
from pathlib import Path

MODELS = Path(os.environ.get('GCS_OLLAMA_MODELS') or (Path.home() / '.ollama' / 'models'))   # 筆電版可用環境變數指定
MANIFEST = MODELS / 'manifests' / 'registry.ollama.ai' / 'library' / 'gemma4' / 'e2b'
EXPECTED_MANIFEST_SHA = 'b37049369adfe3d2b653af0ab301a062ca5cbe96ace6aa0d3f2559ee9b563fc2'
SP = '▁'
PRE = re.compile(r'[^\n]+|[\n]+')
SIZES = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
FMT = {0: 'B', 1: 'b', 2: 'H', 3: 'h', 4: 'I', 5: 'i', 6: 'f', 7: '?', 10: 'Q', 11: 'q', 12: 'd'}
WANT = ('tokenizer.ggml.tokens', 'tokenizer.ggml.merges', 'tokenizer.ggml.token_type',
        'tokenizer.ggml.pre', 'tokenizer.ggml.add_bos_token', 'tokenizer.ggml.add_space_prefix',
        'tokenizer.ggml.model', 'tokenizer.ggml.bos_token_id')


def blob_path():
    raw = MANIFEST.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXPECTED_MANIFEST_SHA:
        raise SystemExit('MANIFEST_DIGEST_DRIFT')
    layer = [l for l in json.loads(raw)['layers'] if l['mediaType'].endswith('.model')]
    if len(layer) != 1:
        raise SystemExit('MODEL_LAYER_AMBIGUOUS')
    return MODELS / 'blobs' / layer[0]['digest'].replace(':', '-'), layer[0]['digest']


def load_vocab():
    path, digest = blob_path()
    got = {}
    with path.open('rb') as f:
        u32 = lambda: struct.unpack('<I', f.read(4))[0]
        u64 = lambda: struct.unpack('<Q', f.read(8))[0]
        s = lambda: f.read(u64()).decode('utf-8', errors='strict')
        if f.read(4) != b'GGUF' or u32() != 3:
            raise SystemExit('GGUF_HEADER')
        u64()
        for _ in range(u64()):
            key, t = s(), u32()
            if t == 8:
                v = s()
            elif t == 9:
                et, n = u32(), u64()
                if et == 8:
                    v = [s() for _ in range(n)]
                else:
                    v = list(struct.unpack('<' + FMT[et] * n, f.read(SIZES[et] * n)))
            else:
                v = struct.unpack('<' + FMT[t], f.read(SIZES[t]))[0]
            if key in WANT:
                got[key] = v
    tokens, types = got['tokenizer.ggml.tokens'], got['tokenizer.ggml.token_type']
    vocab = {}
    for i, t in enumerate(tokens):
        vocab.setdefault(t, i)
    ranks = {}
    for i, m in enumerate(got['tokenizer.ggml.merges']):
        a, sep, b = m.partition(' ')
        if sep:
            ranks.setdefault((a, b), i)
    special = sorted({tokens[i] for i, ty in enumerate(types) if ty in (3, 4) and tokens[i]},
                     key=len, reverse=True)
    settings = {k: got.get(k) for k in WANT if k not in
                ('tokenizer.ggml.tokens', 'tokenizer.ggml.merges', 'tokenizer.ggml.token_type')}
    vocab_sha = hashlib.sha256(json.dumps([tokens, types, got['tokenizer.ggml.merges']],
                                          ensure_ascii=False).encode('utf-8')).hexdigest()
    return dict(vocab=vocab, ranks=ranks, special=special, blob_digest=digest,
                n_tokens=len(tokens), n_merges=len(got['tokenizer.ggml.merges']),
                n_special=len(special), settings=settings, vocab_merges_types_sha256=vocab_sha)


def bpe(chunk, ranks):
    syms = list(chunk)
    n = len(syms)
    if n < 2:
        return syms
    prev = list(range(-1, n - 1))
    nxt = list(range(1, n + 1))
    nxt[-1] = -1
    alive = [True] * n
    heap = []
    for i in range(n - 1):
        r = ranks.get((syms[i], syms[i + 1]))
        if r is not None:
            heapq.heappush(heap, (r, i, syms[i], syms[i + 1]))
    while heap:
        r, i, a, b = heapq.heappop(heap)
        if not alive[i]:
            continue
        j = nxt[i]
        if j == -1 or syms[i] != a or syms[j] != b:
            continue
        syms[i] = a + b
        alive[j] = False
        nxt[i] = nxt[j]
        if nxt[j] != -1:
            prev[nxt[j]] = i
        p = prev[i]
        if p != -1:
            rr = ranks.get((syms[p], syms[i]))
            if rr is not None:
                heapq.heappush(heap, (rr, p, syms[p], syms[i]))
        q = nxt[i]
        if q != -1:
            rr = ranks.get((syms[i], syms[q]))
            if rr is not None:
                heapq.heappush(heap, (rr, i, syms[i], syms[q]))
    return [syms[k] for k in range(n) if alive[k]]


def partition(text, special):
    present = [s for s in special if s in text]
    out, i, plain = [], 0, ''
    while i < len(text):
        hit = next((s for s in present if text.startswith(s, i)), None)
        if hit:
            if plain:
                out.append((False, plain))
                plain = ''
            out.append((True, hit))
            i += len(hit)
        else:
            plain += text[i]
            i += 1
    if plain:
        out.append((False, plain))
    return out


def encode(text, tok):
    ids = []
    for is_special, part in partition(text, tok['special']):
        if is_special:
            ids.append(tok['vocab'][part])
            continue
        for piece in PRE.findall(part.replace(' ', SP)):
            for sym in bpe(piece, tok['ranks']):
                if sym in tok['vocab']:
                    ids.append(tok['vocab'][sym])
                else:
                    for byte in sym.encode('utf-8'):
                        t = tok['vocab'].get('<0x%02X>' % byte)
                        if t is not None:
                            ids.append(t)
    return ids
