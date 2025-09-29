# -*- coding: utf-8 -*-
from __future__ import annotations
import re
from collections import Counter
from typing import List
from langchain_core.documents import Document
from .config_hr import CASE_NORM, PRF_K_SEM, PRF_NGRAMS, PRF_TOP_PHRASES, PRF_MIN_LEN_CHARS, DEBUG_QE
from .utils_hr import normalize_case

_STOP = set([
    "và","hoặc","của","cho","các","cần","được","là","với","trong","theo","đến",
    "nhân","viên","công","ty","tập","đoàn","phòng","ban","bộ","phận","công ty","tiximax"
])

def _tokenize(s: str) -> List[str]:
    s = normalize_case(s, CASE_NORM)
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
        if len(phrase) >= PRF_MIN_LEN_CHARS:
            out.append(phrase)
    return out

def prf_expand_from_semantic(docs: List[Document]) -> List[str]:
    text = "\n".join([d.page_content or "" for d in docs])
    toks = _tokenize(text)
    cand: Counter = Counter()
    for n in PRF_NGRAMS:
        cand.update(_ngrams(toks, n))
    for bad in ["quy trình","chính sách","nhân sự","nhân viên"]:
        cand.pop(bad, None)
    phrases = [p for p,_ in cand.most_common(PRF_TOP_PHRASES)]
    if DEBUG_QE:
        print(f"[PRF] phrases={phrases}")
    return phrases
