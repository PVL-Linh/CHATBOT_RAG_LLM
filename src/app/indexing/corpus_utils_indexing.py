from __future__ import annotations

import io
import json
import re
from pathlib import Path
from typing import Iterable, List, Dict, Any, Optional
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from .config_indexing import CHUNK_SIZE, CHUNK_OVERLAP

SEPARATORS = ["\n\n", "\n", ". ", " ", ""]


def clean_text(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"\s+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.strip()


def chunk_text_to_docs(text: str, rel_source: str) -> List[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=SEPARATORS,
        add_start_index=True,
    )
    docs = [Document(page_content=text, metadata={"source": rel_source, "page": -1})]
    chunks = splitter.split_documents(docs)
    for i, d in enumerate(chunks):
        d.metadata["chunk_id"] = i
    return chunks


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path or not Path(path).is_file():
        return []
    rows: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def _write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with io.open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _extract_source(row: Dict[str, Any]) -> Optional[str]:
    if "source" in row and isinstance(row["source"], str):
        return row["source"]
    meta = row.get("metadata")
    if isinstance(meta, dict):
        s = meta.get("source")
        if isinstance(s, str):
            return s
    return None


def filter_corpus_by_sources(
    corpus_path: str | Path,
    keep_sources: Optional[List[str]] = None,
    drop_sources: Optional[List[str]] = None,
) -> Dict[str, int]:
    cpath = Path(corpus_path)
    if not cpath.is_file():
        return {"before": 0, "after": 0, "removed": 0}

    rows = _read_jsonl(cpath)
    before = len(rows)
    if before == 0:
        return {"before": 0, "after": 0, "removed": 0}

    keep_set = set(keep_sources or [])
    drop_set = set(drop_sources or [])

    new_rows: List[Dict[str, Any]] = []
    if keep_set:
        for r in rows:
            src = _extract_source(r)
            if src and src in keep_set:
                new_rows.append(r)
    elif drop_set:
        for r in rows:
            src = _extract_source(r)
            if (src is None) or (src not in drop_set):
                new_rows.append(r)
    else:
        return {"before": before, "after": before, "removed": 0}

    _write_jsonl(cpath, new_rows)
    after = len(new_rows)
    return {"before": before, "after": after, "removed": before - after}
