# -*- coding: utf-8 -*-
import re
from collections import Counter
from typing import List
from langchain_core.documents import Document
from .config_hr import CASE_NORM_HR, PRF_K_SEM_HR, PRF_NGRAMS_HR, PRF_TOP_PHRASES_HR, PRF_MIN_LEN_CHARS_HR, DEBUG_QE_HR
from .utils_hr import normalize_case

_STOP = set([
    "và","hoặc","của","cho","các","cần","được","là","với","trong","theo","đến",
    "nhân","viên","công","ty","tập","đoàn","phòng","ban","bộ","phận","công ty","tiximax"
])

def _tokenize(s: str) -> List[str]:
    s = normalize_case(s, CASE_NORM_HR)
    s = re.sub(r"[^\w\sÀ-ỹà-ỹ]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s.split()

def _ngrams(tokens: List[str], n: int) -> List[str]:
    out = []
    for i in range(len(tokens) - n + 1):
        g = tokens[i:i+n]
        if any(t in _STOP for t in g):
            continue
        phrase = " ".join(g)
        if len(phrase) >= PRF_MIN_LEN_CHARS_HR:
            out.append(phrase)
    return out

def prf_phrases_from_docs(docs: List[Document]) -> List[str]:
    text = "\n".join([d.page_content or "" for d in docs])
    toks = _tokenize(text)
    cand: Counter = Counter()
    for n in PRF_NGRAMS_HR:
        cand.update(_ngrams(toks, n))
    for bad in ["quy trình","chính sách","nhân sự","nhân viên"]:
        cand.pop(bad, None)
    phrases = [p for p,_ in cand.most_common(PRF_TOP_PHRASES_HR)]
    if DEBUG_QE_HR:
        print(f"[PRF] phrases={phrases}")
    return phrases
