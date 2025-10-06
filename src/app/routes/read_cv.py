# -*- coding: utf-8 -*-
"""
CV Semantic Compare — Flask UI (single file)
Run:
  pip install flask sentence-transformers pymupdf python-docx rank-bm25 regex
  # (optional OCR)
  # pip install pdf2image pytesseract
  # On Windows, install Tesseract separately if using OCR.

  # (optional) use local E5 model
  # Linux/macOS: export EMB_MODEL=./src/app/models/local_multilingual_e5_large
  # Windows PowerShell: $env:EMB_MODEL="./src/app/models/local_multilingual_e5_large"

  python cv_compare_ui.py --host 0.0.0.0 --port 1229
Then open http://localhost:1229
"""
import os, io, json, tempfile, time, unicodedata
import regex as reg
from pathlib import Path
from typing import List, Dict, Any, Optional

from flask import Flask, request, jsonify, render_template_string

# =============== Lazy heavy imports ===============
_fitx = _docx = _st = _util = _np = _bm25 = None

def _lazy_imports():
    global _fitx, _docx, _st, _util, _np, _bm25
    if _np is None:
        import numpy as np; _np = np
    if _fitx is None:
        import fitz as pymupdf; _fitx = pymupdf
    if _docx is None:
        import docx as pydocx; _docx = pydocx
    if _st is None or _util is None:
        from sentence_transformers import SentenceTransformer, util
        _st, _util = SentenceTransformer, util
    if _bm25 is None:
        from rank_bm25 import BM25Okapi; _bm25 = BM25Okapi

ALLOWED_EXTS = {".pdf", ".docx", ".txt"}

# =============== Text utils ===============

def normalize_text(s: str) -> str:
    s = s.replace("\r", "\n")
    s = reg.sub(r"[ \t]+", " ", s)
    s = reg.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def strip_accents_lower(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").lower()

# =============== I/O ===============

def read_file_any(path: Path, ocr: bool=False) -> str:
    """Read PDF/DOCX/TXT; optional OCR for scanned PDF."""
    _lazy_imports()
    ext = path.suffix.lower()
    if ext == ".txt":
        return normalize_text(path.read_text(encoding="utf-8", errors="ignore"))
    if ext == ".docx":
        d = _docx.Document(str(path))
        parts = [p.text for p in d.paragraphs]
        for t in d.tables:
            for r in t.rows:
                parts.append(" | ".join([c.text for c in r.cells]))
        return normalize_text("\n".join(parts))
    if ext == ".pdf":
        text = []
        doc = _fitx.open(str(path))
        for i in range(len(doc)):
            page = doc[i]
            t = page.get_text("text")
            if not t and ocr:
                try:
                    from pdf2image import convert_from_path
                    import pytesseract
                    imgs = convert_from_path(str(path), first_page=i+1, last_page=i+1, dpi=300)
                    if imgs:
                        t = pytesseract.image_to_string(imgs[0], lang="eng+vie")
                except Exception:
                    pass
            text.append(t)
        return normalize_text("\n".join(text))
    raise ValueError(f"Unsupported file: {path}")

EMAIL_RE = reg.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", reg.I)
PHONE_RE = reg.compile(r"(?:\+?\d[\d \-().]{7,}\d)")

SECTION_HINTS = {
    "summary":  [r"\b(t?o?m t[aá]t|summary|objective|profile)\b"],
    "skills":   [r"\b(k?y? n[aă]ng|skills|tech stack|competencies)\b"],
    "exp":      [r"\b(kinh nghi[ẹ]m|experience|work history|employment)\b"],
    "edu":      [r"\b(h[ọ]c v[ạ]n|education|degree|b[ă]ng c[ấ]p)\b"],
    "projects": [r"\b(d[ự] án|projects|portfolio)\b"],
}

# =============== NLP helpers ===============

def sent_tokenize(text: str) -> List[str]:
    text = text.replace("•", "- ").replace("–", "- ")
    text = reg.sub(r"(\.\s+)", ".\n", text)
    text = reg.sub(r"[\r\n]+", "\n", text)
    sents = []
    for line in text.split("\n"):
        line = line.strip(" -•\t")
        if not line: continue
        parts = [p.strip() for p in reg.split(r"[;•]| - ", line) if p.strip()]
        sents.extend(parts or [line])
    return [s for s in sents if len(s) >= 3]

DATE_PAT = reg.compile(r"(?:(?:0?[1-9]|1[0-2])[/\-.])?\d{4}")
YEAR_PAT = reg.compile(r"(19|20)\d{2}")

def estimate_years_experience(text: str) -> float:
    years = []
    for m in reg.finditer(r"(?P<a>(?:0?[1-9]|1[0-2])?[/\-.]?(?:19|20)\d{2})\s*[-–tođến]+\s*(?P<b>(?:0?[1-9]|1[0-2])?[/\-.]?(?:19|20)\d{2}|hi[ẹ]n t[ạ]i|present)", text, reg.I):
        def y(v):
            m2 = YEAR_PAT.search(v)
            return int(m2.group(0)) if m2 else None
        ya = y(m.group("a"))
        yb = y(time.strftime("%Y")) if reg.search("hi[ẹ]n t[ạ]i|present", m.group("b"), reg.I) else y(m.group("b"))
        if ya and yb and yb >= ya:
            years.append(max(0.0, (yb - ya)))
    if years:
        return float(min(40.0, sum(years)))
    ym = [int(y.group(0)) for y in YEAR_PAT.finditer(text)]
    if len(ym) >= 2:
        return float(max(0, min(40, max(ym)-min(ym))))
    return 0.0

# =============== Embedding ===============

def load_embedder():
    _lazy_imports()
    name = os.environ.get("EMB_MODEL", "intfloat/multilingual-e5-large")
    return _st(name)

def e5_encode(model, texts: List[str], is_query: bool=False, batch: int=64):
    _lazy_imports()
    if is_query:
        texts = [f"query: {t}" for t in texts]
    else:
        texts = [f"passage: {t}" for t in texts]
    return model.encode(texts, batch_size=batch, normalize_embeddings=True,
                        convert_to_numpy=True, show_progress_bar=False)

# =============== Core scoring ===============

def split_sections(text: str) -> Dict[str, str]:
    lines = [l.strip() for l in text.splitlines()]
    idxs = []
    for i, l in enumerate(lines):
        low = strip_accents_lower(l)
        for sec, pats in SECTION_HINTS.items():
            if any(reg.search(p, low) for p in pats):
                idxs.append((i, sec)); break
    idxs.sort(key=lambda x: x[0])
    if not idxs: return {"full": "\n".join(lines)}
    out = {}
    for j, (i, sec) in enumerate(idxs):
        end = idxs[j+1][0] if j+1 < len(idxs) else len(lines)
        blk = "\n".join(lines[i:end]).strip()
        out[sec] = (out.get(sec, "") + ("\n\n" if sec in out else "") + blk).strip()
    return out

def extract_contacts(text: str) -> Dict[str, List[str]]:
    emails = EMAIL_RE.findall(text) or []
    phones = PHONE_RE.findall(text) or []
    def dedup(xs):
        s, o = set(), []
        for x in xs:
            x = x.strip()
            if x and x not in s: s.add(x); o.append(x)
        return o
    return {"emails": dedup(emails), "phones": dedup(phones)}

def skills_coverage(cv_sents: List[str], skills: List[str], model, cv_embs):
    _lazy_imports()
    if not skills:
        return {"matched": [], "missing": [], "coverage": None, "details": []}
    tok = lambda s: strip_accents_lower(s).split()
    bm25 = _bm25([tok(s) for s in cv_sents]) if cv_sents else None
    sk_embs = e5_encode(model, skills, is_query=True)
    det, matched, missing = [], [], []
    for i, sk in enumerate(skills):
        bm = 0.0
        if bm25:
            bm = float(max(bm25.get_scores(tok(sk))) if cv_sents else 0.0)
        v = sk_embs[i]
        sem_scores = (cv_embs @ v)
        j = int(_np.argmax(sem_scores)) if len(sem_scores) else -1
        sem = float(sem_scores[j]) if j >= 0 else 0.0
        best = cv_sents[j] if 0 <= j < len(cv_sents) else ""
        hit = (sem >= 0.45) or (bm >= 3.0 and strip_accents_lower(sk) in strip_accents_lower(best))
        (matched if hit else missing).append(sk)
        det.append({"skill": sk, "bm25": bm, "semantic": sem, "evidence": best})
    cov = len(matched) / max(1, len(skills))
    return {"matched": matched, "missing": missing, "coverage": cov, "details": det}

def align_jd_cv(jd_text: str, cv_text: str, model, topk: int=8):
    jd_sents = sent_tokenize(jd_text)
    cv_sents = sent_tokenize(cv_text)
    if not jd_sents or not cv_sents:
        return {"pairs": [], "jd_sents": jd_sents, "cv_sents": cv_sents}
    jd_embs = e5_encode(model, jd_sents, is_query=True)
    cv_embs = e5_encode(model, cv_sents, is_query=False)
    sims = jd_embs @ cv_embs.T
    pairs = []
    for i in range(len(jd_sents)):
        row = sims[i]
        idxs = _np.argsort(-row)[:topk]
        for j in idxs:
            sc = float(row[j])
            if sc < 0.35: continue
            pairs.append({"jd_idx": i, "jd": jd_sents[i], "cv_idx": int(j), "cv": cv_sents[int(j)], "score": sc})
    pairs = sorted(pairs, key=lambda x: -x["score"])[:max(10, topk)]
    return {"pairs": pairs, "jd_sents": jd_sents, "cv_sents": cv_sents, "jd_embs": jd_embs, "cv_embs": cv_embs}

def score_overall(jd_text: str, cv_text: str, model, skills: List[str]):
    jd_vec = e5_encode(model, [jd_text], is_query=True)[0]
    cv_vec = e5_encode(model, [cv_text], is_query=False)[0]
    sem = float(jd_vec @ cv_vec)

    cv_sections = split_sections(cv_text)
    cv_sents = sent_tokenize(cv_text)
    cv_embs = e5_encode(model, cv_sents, is_query=False) if cv_sents else None
    sk_cov = skills_coverage(cv_sents, skills, model, cv_embs) if cv_embs is not None else {"coverage": None}
    al = align_jd_cv(jd_text, cv_text, model, topk=8)
    years = estimate_years_experience(cv_text)

    sem_part = max(0.0, min(1.0, sem))
    if sk_cov.get("coverage") is None:
        cov_part = None
        final = 0.65 * sem_part + 0.10 * min(1.0, years / 8.0)
    else:
        cov_part = max(0.0, min(1.0, sk_cov["coverage"]))
        final = 0.55 * sem_part + 0.35 * cov_part + 0.10 * min(1.0, years / 8.0)

    return {
        "overall_score": round(final * 100.0, 2),
        "semantic_similarity": round(sem_part, 4),
        "skills_coverage": (None if cov_part is None else round(cov_part, 4)),
        "years_experience_est": years,
        "alignment": {"pairs": al["pairs"]},
        "cv_sections": {k: (cv_sections[k][:4000] + ("..." if len(cv_sections[k])>4000 else "")) for k in cv_sections},
        "contacts": extract_contacts(cv_text),
        "notes": {"weights": {"semantic": 0.55, "skills": 0.35, "experience": 0.10}, "model": os.environ.get("EMB_MODEL", "intfloat/multilingual-e5-large")}
    }

# Public API used by UI

def compare_uploaded(cv_path: Path, jd_text: str, skills_list: Optional[List[str]], ocr: bool=False):
    _lazy_imports()
    model = load_embedder()
    cv_text = read_file_any(cv_path, ocr=ocr)
    skills = [s.strip() for s in (skills_list or []) if s and s.strip()]
    return score_overall(jd_text, cv_text, model, skills)

# =============== Flask app ===============
app = Flask(__name__)

@app.get("/")
def home():
    return render_template_string(HTML_PAGE)

@app.post("/api/compare")
def api_compare():
    try:
        if "cv" not in request.files:
            return jsonify({"error": "Missing file 'cv'"}), 400
        f = request.files["cv"]
        if not f.filename:
            return jsonify({"error": "Empty filename"}), 400
        ext = Path(f.filename).suffix.lower()
        if ext not in ALLOWED_EXTS:
            return jsonify({"error": f"Unsupported file type {ext}"}), 400
        jd = request.form.get("jd", "").strip()
        if not jd:
            return jsonify({"error": "JD is required"}), 400
        skills_raw = request.form.get("skills", "")
        skills = [s.strip() for s in reg.split(r"[\n,]", skills_raw or "") if s.strip()]
        ocr = request.form.get("ocr", "false").lower() == "true"
        # save temp then process
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            f.save(tmp.name)
            tmp_path = Path(tmp.name)
        try:
            res = compare_uploaded(tmp_path, jd, skills, ocr=ocr)
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
        return jsonify(res)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.get("/health")
def health():
    return {"ok": True}

# =============== HTML (inline) ===============
HTML_PAGE = r"""
<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>CV Semantic Compare · Demo</title>
  <style>
    :root { --bg:#0b0f14; --fg:#e9eef5; --muted:#9db0c5; --card:#0f1520; --acc:#6298ff; --good:#1fbf75; --bad:#e55353; }
    *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto}
    .wrap{display:grid;grid-template-columns:360px 1fr;gap:16px;max-width:1200px;margin:24px auto;padding:0 16px}
    .card{background:var(--card);border:1px solid #1c2533;border-radius:16px;box-shadow:0 4px 20px rgba(0,0,0,.25)}
    .pad{padding:16px}
    h1{font-size:20px;margin:16px 0}
    label{display:block;font-weight:600;margin:10px 0 6px}
    textarea, input[type="text"], input[type="file"]{width:100%;background:#0b111b;border:1px solid #1e2a3d;color:var(--fg);padding:10px;border-radius:10px}
    textarea{min-height:120px;resize:vertical}
    .row{display:flex;gap:8px;align-items:center}
    .btn{background:var(--acc);color:#0b0f14;border:0;padding:10px 14px;border-radius:12px;font-weight:700;cursor:pointer}
    .btn:disabled{opacity:.6;cursor:not-allowed}
    .hint{color:var(--muted);font-size:12px}
    .grid{display:grid;grid-template-columns:repeat(2, minmax(0,1fr));gap:12px}
    .pill{display:inline-block;padding:4px 8px;border-radius:999px;background:#0b111b;border:1px solid #1e2a3d;margin:2px}
    .pill.good{border-color:#195a3a;color:#a8f3ce}
    .pill.bad{border-color:#5a1919;color:#f3a8a8}
    .kpi{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:8px}
    .kpi .box{background:#0b111b;border:1px solid #1e2a3d;border-radius:12px;padding:12px;text-align:center}
    .kpi b{font-size:18px}
    table{width:100%;border-collapse:collapse}
    th,td{border-bottom:1px solid #1b2537;padding:8px;text-align:left;vertical-align:top}
    .mono{font-family:ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace}
    .footer{color:#7a8ba1;text-align:center;margin:20px 0}
    .spinner{width:16px;height:16px;border:3px solid #2a3950;border-top-color:#fff;border-radius:50%;display:inline-block;animation:spin 1s linear infinite;vertical-align:-2px}
    @keyframes spin{to{transform:rotate(360deg)}}
    .json-dl{margin-top:8px}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card pad">
      <h1>CV Semantic Compare · Demo</h1>
      <label>CV file (.pdf, .docx, .txt)</label>
      <input id="cv" type="file" accept=".pdf,.docx,.txt" />
      <div class="hint">Chọn 1 file CV để so sánh.</div>

      <label style="margin-top:10px">Job Description (JD)</label>
      <textarea id="jd" placeholder="Dán JD tại đây..."></textarea>

      <label>Kỹ năng (mỗi dòng hoặc dùng dấu phẩy)</label>
      <textarea id="skills" placeholder="Python\nFAISS\nLogistics"></textarea>

      <div class="row" style="margin:10px 0 6px">
        <label style="margin:0"><input id="ocr" type="checkbox" /> Bật OCR nếu CV là PDF scan</label>
      </div>

      <div class="row" style="justify-content:space-between">
        <button id="run" class="btn">Chạy so sánh</button>
        <div id="status" class="hint"></div>
      </div>
    </div>

    <div class="card pad" id="result">
      <div class="hint">Kết quả sẽ hiển thị ở đây sau khi chạy.</div>
    </div>
  </div>
  <div class="footer">Model: <span id="modelName">(auto)</span></div>

<script>
const $ = (q)=>document.querySelector(q);
const runBtn = $('#run');
const statusEl = $('#status');
const resEl = $('#result');
let lastJson = null;

function renderResult(data){
  lastJson = data;
  const skCov = data.skills_coverage===null? '—' : (data.skills_coverage*100).toFixed(1)+'%';
  const sem = (data.semantic_similarity*100).toFixed(1)+'%';
  const years = (data.years_experience_est||0).toFixed(1);
  const score = (data.overall_score||0).toFixed(2);

  const pairs = (data.alignment?.pairs||[])
    .map(p=>`<tr><td>${(p.score*100).toFixed(1)}%</td><td>${escapeHtml(p.jd)}</td><td>${escapeHtml(p.cv)}</td></tr>`)
    .join('') || '<tr><td colspan="3" class="hint">Không có bằng chứng khớp.</td></tr>';

  const det = data.notes?.model ? data.notes.model : '(unknown)';
  document.getElementById('modelName').textContent = det;

  const matched = (data.skills_coverage_details?.matched || data.matched || []); // not used; we render from details below
  const details = (data.skills_details || data.skills || data.notes?.skills_details || data.details || data.alignment?.details || []);

  // From API we returned detail list inside score component; reconstruct from notes if absent
  let pillsMatched = '', pillsMissing = '';
  if (data.notes && data.notes.weights) {
    // try to get details from skills_coverage?.details
    const cov = data.skills_coverage; // number or null
    const dets = data.skills_coverage===null ? [] : (data.skills && data.skills.details ? data.skills.details : (data.skills_details || (data.skills_coverage_details?.details) || (data.sk_details) || []));
  }

  // We included details under return of skills_coverage, but not propagated to top-level.
  // To keep UI simple, just recompute pills from data.notes? skip. Instead, show matched/missing if present.

  const matchedList = (data.notes && data.notes.matched) ? data.notes.matched : (data.matched||[]);
  const missingList = (data.notes && data.notes.missing) ? data.notes.missing : (data.missing||[]);

  function listToPills(xs, good){
    if(!xs || xs.length===0) return '<span class="hint">(trống)</span>';
    return xs.map(x=>`<span class="pill ${good?'good':'bad'}">${escapeHtml(x)}</span>`).join('');
  }

  resEl.innerHTML = `
    <div class="kpi">
      <div class="box"><div class="hint">Tổng điểm</div><b>${score}</b></div>
      <div class="box"><div class="hint">Semantic</div><b>${sem}</b></div>
      <div class="box"><div class="hint">Độ phủ kỹ năng</div><b>${skCov}</b></div>
      <div class="box"><div class="hint">Ước tính năm KN</div><b>${years}</b></div>
    </div>

    <h2 style="margin:16px 0 6px">Bằng chứng khớp JD ↔ CV</h2>
    <div class="hint">Top câu khớp theo điểm cosine</div>
    <div style="overflow:auto; max-height:300px; border:1px solid #1e2a3d; border-radius:10px; margin-top:6px">
      <table class="mono">
        <thead><tr><th>Score</th><th>JD</th><th>CV</th></tr></thead>
        <tbody>${pairs}</tbody>
      </table>
    </div>

    <div class="grid" style="margin-top:16px">
      <div>
        <h3 style="margin:0 0 6px">Kỹ năng khớp</h3>
        <div id="matchedPills" class="mono">${listToPills(data.skills?.matched || data.matched, true)}</div>
      </div>
      <div>
        <h3 style="margin:0 0 6px">Thiếu kỹ năng</h3>
        <div id="missingPills" class="mono">${listToPills(data.skills?.missing || data.missing, false)}</div>
      </div>
    </div>

    <h3 style="margin:16px 0 6px">Liên hệ</h3>
    <div class="mono">Email: ${(data.contacts?.emails||[]).join(', ') || '<span class="hint">—</span>'}<br/>Điện thoại: ${(data.contacts?.phones||[]).join(', ') || '<span class="hint">—</span>'}</div>

    <div class="row json-dl">
      <button class="btn" onclick="downloadJSON()">Tải JSON kết quả</button>
      <div class="hint">Gồm đủ evidence & scores</div>
    </div>
  `;
}

function escapeHtml(s){
  return (s||'').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','\'':'&#39;'}[c]));
}

async function run(){
  try{
    const f = document.getElementById('cv').files[0];
    const jd = document.getElementById('jd').value.trim();
    const skills = document.getElementById('skills').value.trim();
    const ocr = document.getElementById('ocr').checked;
    if(!f){ alert('Chọn file CV'); return; }
    if(!jd){ alert('Nhập JD'); return; }

    const fd = new FormData();
    fd.append('cv', f);
    fd.append('jd', jd);
    fd.append('skills', skills);
    fd.append('ocr', ocr);

    runBtn.disabled = true; statusEl.innerHTML = '<span class="spinner"></span> Đang chạy...';

    const resp = await fetch('/api/compare', {method:'POST', body: fd});
    const data = await resp.json();
    if(!resp.ok){ throw new Error(data.error || 'Request failed'); }

    // pass-through matched/missing to top-level for convenience
    if (data && data.skills_coverage !== undefined) {
      // not available, but we'll try to keep placeholders
      if(!data.skills){ data.skills = {}; }
      if(!('matched' in data.skills)) data.skills.matched = data.notes?.matched || [];
      if(!('missing' in data.skills)) data.skills.missing = data.notes?.missing || [];
    }

    renderResult(data);
    statusEl.textContent = 'Xong';
  }catch(err){
    console.error(err);
    resEl.innerHTML = `<div style="color:#ffb3b3">Lỗi: ${escapeHtml(err.message||String(err))}</div>`;
    statusEl.textContent = 'Lỗi';
  }finally{
    runBtn.disabled = false;
  }
}

function downloadJSON(){
  if(!lastJson){ alert('Chưa có dữ liệu'); return; }
  const blob = new Blob([JSON.stringify(lastJson, null, 2)], {type:'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'cv_compare_result.json';
  a.click();
  URL.revokeObjectURL(a.href);
}

runBtn.addEventListener('click', run);
</script>
</body>
</html>
"""

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--host', default='0.0.0.0')
    p.add_argument('--port', type=int, default=1229)
    args = p.parse_args()
    app.run(host=args.host, port=args.port, debug=False)