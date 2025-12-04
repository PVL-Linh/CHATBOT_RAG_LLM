from __future__ import annotations
import os
import time
from typing import Any, Dict, List, Optional
from langchain_core.documents import Document
from app.Helpers.prompt_internal import SYSTEM_PRIMER
from app.services.history import get_history
from app.Model_LLM.hybrid_retriever import rerank, TOP_K
from .utils_text import strip_source_citations, _is_internal_prompt_text
from .session_doc_vs import _get_session_doc_vs
from .file_utils import _extract_text_from_uploaded_file
from .gemini_helpers import _safe_gemini_generate

def _filter_internal_prompt_docs(docs: List[Document]) -> List[Document]:
    """
    Loại bỏ các Document mà nội dung là prompt hệ thống / hướng dẫn LLM,
    để model không trả lời kiểu 'Hình 1 là Prompt Hệ Thống...'
    """
    cleaned: List[Document] = []
    for d in docs or []:
        txt = (d.page_content or "").strip()
        if not txt:
            continue
        if _is_internal_prompt_text(txt):
            continue
        cleaned.append(d)
    return cleaned

def _to_gemini_history_no_system(history_msgs: List[Dict[str, str]]) -> List[Dict]:
    out = []
    for m in history_msgs:
        role = m.get("role", "user")
        content = (m.get("content") or "").strip()
        if not content:
            continue
        role = "model" if role == "assistant" else "user"
        out.append({"role": role, "parts": [{"text": content}]})
    return out

def _rag_answer(
    user_text: str,
    gclient,
    GEMINI_MODEL,
    GEN_CFG,
    embeddings,
    retriever,
    lang_hint: str | None = None,
    session_id: str | None = None,
    session_doc_paths: Optional[List[str]] = None,
    only_use_session_docs: bool = False,
    focus_sources: Optional[List[str]] = None,
    file_meta_map: Optional[Dict[str, Dict[str, Any]]] = None,
) -> tuple[str, dict]:
    """
    Sinh câu trả lời bằng cách:
    - Lấy context từ file upload (ảnh + pdf/docx/txt) qua FAISS session (summary).
    - (Tuỳ) lấy thêm context từ global RAG.
    - Rerank → ghép vào 1 khối context → gửi Gemini.

    BẢO VỆ:
    - Không đưa các đoạn giống PROMPT HỆ THỐNG vào context.
    - Khi nhận diện đây là CÂU HỎI VỀ FILE (chỉ định tên file, 'nội dung', v.v.)
      thì KHÔNG ĐƯỢC trả về câu chào mặc định, mà phải mô tả/tóm tắt nội dung file.
    """

    session_doc_paths = session_doc_paths or []
    file_meta_map = file_meta_map or {}
    start_total = time.time()

    session_docs: List[Document] = []
    global_docs: List[Document] = []
    search_time_session = 0.0
    search_time_global = 0.0
    rerank_time = 0.0

    has_uploaded_files = bool(session_doc_paths)

    # ==========================================================
    # 1. Tìm trong file upload (session docs – summary ảnh + văn bản)
    # ==========================================================
    if has_uploaded_files and session_id:
        try:
            vs = _get_session_doc_vs(
                session_id=session_id,
                embeddings=embeddings,
                file_paths=session_doc_paths,
                gclient=gclient,
                GEMINI_MODEL=GEMINI_MODEL,
                GEN_CFG=GEN_CFG,
                file_meta_map=file_meta_map,
            )
            if vs is not None:
                t0 = time.time()
                session_docs = vs.similarity_search(user_text, k=20)
                search_time_session = time.time() - t0
        except Exception as e:
            print(f"[RAG] Lỗi khi tìm trong session docs: {e}")
            session_docs = []

    # Loại bỏ mọi doc mà nội dung là PROMPT HỆ THỐNG
    session_docs = _filter_internal_prompt_docs(session_docs)

    # Nếu user focus vào 1 hoặc vài file cụ thể → filter theo metadata["source"]
    if focus_sources:
        allowed = set(focus_sources)
        filtered = [
            d for d in session_docs
            if (d.metadata or {}).get("source") in allowed
        ]
        if filtered:
            print(
                f"[RAG] focus_sources={focus_sources} | "
                f"before={len(session_docs)} | after={len(filtered)}"
            )
            session_docs = filtered

    # ==========================================================
    # 2. Tìm trong global RAG (chỉ khi không chỉ dùng file upload)
    # ==========================================================
    if not only_use_session_docs:
        try:
            t0 = time.time()
            global_docs = retriever.get_relevant_documents("query: " + user_text)
            search_time_global = time.time() - t0
        except Exception as e:
            print(f"[RAG] Lỗi global RAG: {e}")
            global_docs = []

    # Loại prompt hệ thống khỏi global docs luôn
    global_docs = _filter_internal_prompt_docs(global_docs)

    # ==========================================================
    # 3. Gộp candidate + RERANK
    # ==========================================================
    if only_use_session_docs:
        all_candidates = session_docs
    else:
        all_candidates = session_docs + global_docs

    context_hint = ""

    if not all_candidates:
        # Không tìm được doc nào: fallback đọc raw từ file upload (nếu có)
        if only_use_session_docs and session_doc_paths:
            raw_snippets = []
            for p in session_doc_paths:
                try:
                    raw = _extract_text_from_uploaded_file(p)
                except Exception as e:
                    print(f"[RAG FALLBACK] Lỗi đọc file {p}: {e}")
                    raw = ""

                # Bỏ qua file mà bản thân nội dung là PROMPT HỆ THỐNG
                if raw and raw.strip() and not _is_internal_prompt_text(raw):
                    raw_snippets.append(raw[:4000])

            if raw_snippets:
                docs_text = "\n\n---\n\n".join(raw_snippets)
                context_hint = f"[DỮ LIỆU THAM KHẢO TỪ FILE UPLOAD]\n{docs_text}"
            else:
                context_hint = (
                    "(Không tìm thấy thông tin phù hợp trong các file bạn đã upload.)"
                )
        else:
            context_hint = "(Không tìm thấy thông tin phù hợp từ tài liệu nội bộ.)"
    else:
        # Có candidate → RERANK
        try:
            t0 = time.time()
            ranked = rerank(user_text, all_candidates, top_k=TOP_K)
            rerank_time = time.time() - t0

            parts = []
            for doc, score in ranked:
                txt = (doc.page_content or "").strip()
                if not txt:
                    continue

                # Bảo vệ thêm: nếu txt là prompt hệ thống thì skip luôn
                if _is_internal_prompt_text(txt):
                    continue

                if txt.lower().startswith("passage: "):
                    txt = txt[len("passage: "):].strip()

                meta = doc.metadata or {}
                src_name = (
                    meta.get("source")
                    or meta.get("title")
                    or os.path.basename(meta.get("path", ""))  # path có thể trống
                    or ""
                )
                is_summary = meta.get("is_summary", False)

                suffix = ""
                if src_name:
                    suffix = f" (Nguồn: {src_name}"
                    if is_summary:
                        suffix += " - Tóm tắt)"
                    else:
                        suffix += ")"
                else:
                    if is_summary:
                        suffix = " (Nguồn: tài liệu nội bộ - Tóm tắt)"
                    else:
                        suffix = " (Nguồn: tài liệu nội bộ)"

                parts.append(txt + suffix)

            if parts:
                docs_text = "\n\n---\n\n".join(parts)
                context_hint = f"[DỮ LIỆU THAM KHẢO]\n{docs_text}"
            else:
                context_hint = (
                    "(Không có đoạn nội dung nào phù hợp sau khi lọc prompt hệ thống.)"
                )
        except Exception as e:
            print(f"[RAG] Lỗi rerank: {e}")
            context_hint = "(Có lỗi khi xử lý tài liệu tham khảo.)"

    # ==========================================================
    # 4. Gọi LLM (Gemini) với SYSTEM_PRIMER + context RAG
    # ==========================================================
    lang = (lang_hint or "vi").lower()
    lang_instruction = (
        "\nTrả lời bằng tiếng Anh, rõ ràng, chuyên nghiệp."
        if lang.startswith("en")
        else "\nTrả lời bằng tiếng Việt, tự nhiên, dễ hiểu."
    )

    # ⚠️ Nhận diện đây có phải CÂU HỎI VỀ FILE không
    # Ở đây: nếu có file upload + only_use_session_docs=True thì hiểu là đang hỏi về file.
    is_file_question = bool(has_uploaded_files and only_use_session_docs)

    extra_file_rule = ""
    if is_file_question:
        extra_file_rule = """
QUAN TRỌNG (OVERRIDE):
- Người dùng đang hỏi về NỘI DUNG CÁC FILE đã upload (ảnh / pdf / docx / txt).
- Tuyệt đối KHÔNG coi đây là lời chào đơn thuần.
- KHÔNG sử dụng câu chào mặc định kiểu "Tôi là trợ lý ảo nội bộ của Tiximax Logistics. Tôi có thể hỗ trợ gì?".
- Bắt buộc phải:
  + Mô tả hoặc tóm tắt nội dung CÁC FILE đang được dùng làm ngữ cảnh.
  + Nếu người dùng liệt kê nhiều file (ví dụ: "vi-du-phieu-chi.jpg", "giay-bao-dien.png"),
    hãy trình bày RIÊNG cho từng file, ghi rõ file nào là file nào.
"""

    # SYSTEM_PRIMER là guardrail, không phải để AI mô tả lại.
    system_block = f"""{SYSTEM_PRIMER}
{lang_instruction}
{extra_file_rule}
"""

    user_block = f"""[NGỮ CẢNH NỘI BỘ / DỮ LIỆU THAM KHẢO]
{context_hint}

[NGƯỜI DÙNG HỎI]
{user_text}
"""

    # Lịch sử chat (không include system)
    hist_msgs = [
        m for m in get_history()
        if m.get("role") in ("user", "assistant")
    ]
    contents = _to_gemini_history_no_system(hist_msgs)

    # Thêm lượt cuối: system + context + câu hỏi
    contents.append(
        {
            "role": "user",
            "parts": [
                {
                    "text": f"[SYSTEM]\n{system_block}\n\n{user_block}"
                }
            ],
        }
    )

    result, llm_time = _safe_gemini_generate(
        gclient,
        GEMINI_MODEL,
        contents,
        GEN_CFG,
    )

    final_answer = strip_source_citations((result or "").strip())

    timing = {
        "embedding": 0.0,  # nếu sau này bạn đo embedding time thì set lại
        "search": round(search_time_session + search_time_global + rerank_time, 2),
        "llm": round(llm_time, 2),
        "total": round(time.time() - start_total, 2),
    }

    return final_answer, timing

