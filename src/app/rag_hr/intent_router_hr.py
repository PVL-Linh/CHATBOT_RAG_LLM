import re

_PAT = lambda *xs: [re.compile(x, re.I) for x in xs]

PAT_ORG  = _PAT(r"\bsơ\s*đồ\s*(tổ\s*chức|nhân\s*sự|nhân\s*viên)\b",
                r"\borg(?:anizational)?\s*chart\b", r"\bemployee\s*chart\b", r"\bcơ\s*cấu\s*tổ\s*chức\b")
PAT_FORM = _PAT(r"\bbiên\s*bản\s*bàn\s*giao\b", r"\bmẫu\b", r"\bform\b", r"\btemplate\b")
PAT_JD   = _PAT(r"\b(jd|mô\s*tả\s*công\s*việc|job\s*description)\b")

def classify_intent(q: str) -> str:
    s = (q or "").lower()
    def any_match(pats): return any(p.search(s) for p in pats)
    if any_match(PAT_ORG):  return "ORG"
    if any_match(PAT_FORM): return "FORM"
    if any_match(PAT_JD):   return "JD"
    return "OTHER"
