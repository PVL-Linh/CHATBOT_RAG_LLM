from __future__ import annotations
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from flask import session
# from app.services.history import get_history, add_message, create_new_session
from app.Helpers.prompt_internal import SYSTEM_PRIMER_SALES
from app.Model_LLM.model_llm import LLM_model
from app.config.paths import DATA_DIR_SALES, FAISS_ALL_DIR_SALES
from app.Model_LLM.Chat_Database.db_router import handle_db_message
from app.Model_LLM.Chat_Database.redis_ctx import update_ctx
from app.config.settings import Chat_engine
from app.routes.image_ocr_utils import is_image_path
from app.services.wrapper import (
    get_current_session_id,
    get_session_messages,
    add_message,
    create_new_session,
)
from app.Model_LLM.Chat_Pipeline.utils_text import (
    strip_source_citations,
    _auto_detect_lang,
)
from app.Model_LLM.Chat_Pipeline.history_ctx import _get_history_msgs_for_ctx, _load_ctx
from app.Model_LLM.Chat_Pipeline.gemini_helpers import (
    _analyze_followup_and_lang,
    _is_generic_current_file_query,
    _is_query_about_uploaded_file,
    _safe_gemini_generate,
)
from app.Model_LLM.Chat_Pipeline.file_utils import (
    _detect_focus_sources_from_query,
    _get_latest_batch_paths,
    _summarize_uploaded_file,
    _is_request_uploaded_files_content,
)
from app.Model_LLM.Chat_Pipeline.session_doc_vs import _clear_session_doc_vs
from app.Model_LLM.Chat_Pipeline.rag_core import _rag_answer

REWRITE_DB_WITH_LLM = Chat_engine.REWRITE_DB_WITH_LLM

def _rewrite_db_answer(
    gclient,
    GEMINI_MODEL,
    GEN_CFG,
    answer_text: str,
    lang_hint: str | None = None,
) -> str:
    if not REWRITE_DB_WITH_LLM:
        return answer_text

    lang_hint = (lang_hint or "vi").lower()
    if lang_hint.startswith("en"):
        lang_rule = "\nTrả lời bằng tiếng Anh. Giữ nguyên số liệu, mã đơn, phần trăm, mã lô."
    else:
        lang_rule = (
            "\nTrả lời bằng tiếng Việt. Giữ nguyên số liệu, mã đơn, phần trăm, mã lô."
        )

    guard = (
        SYSTEM_PRIMER_SALES
        + lang_rule
        + "\nYÊU CẦU: giữ NGUYÊN số liệu, số tiền, phần trăm, mã đơn, mã lô.\n"
          "Không thêm bớt số. Nếu một số không cần thiết có quyền bỏ. "
          "Chỉ chỉnh lại câu chữ cho tự nhiên, gọn trong 1-2 đoạn & giữ nguyên bảng ASCII nếu có."
    )

    contents = [
        {
            "role": "user",
            "parts": [
                {
                    "text": f"[INSTRUCTION]\n{guard}\n\n[TEXT]\n{answer_text}",
                }
            ],
        }
    ]
    try:
        out, _ = _safe_gemini_generate(gclient, GEMINI_MODEL, contents, GEN_CFG)
        out = strip_source_citations(out or "")
        has_num_old = re.search(r"\d", answer_text or "") is not None
        has_num_new = re.search(r"\d", out or "") is not None
        if has_num_old and not has_num_new:
            return answer_text
        return out or answer_text
    except Exception:
        return answer_text


def handle_chat_request(
    user_text: str,
    session_id: str,
    principal: Any,
    bm25_folder: Optional[Path] = None,
    corpus_path: Optional[Path] = None,
) -> dict:
    """
    Hàm xử lý 1 lượt chat sync:
    - Ưu tiên DB (handle_db_message)
    - Nếu không phải câu DB → RAG (global + session docs upload)
    - Hỗ trợ multi-file upload (list/dict) + ảnh (OCR → summary → RAG)
    """
    user_text = (user_text or "").strip()
    if not user_text:
        return {"ok": False, "error": "Missing message"}

    full_start = time.time()

    # 0. Tạo session_id nếu chưa có
    if not session_id:
        title = user_text[:50].strip() or "Cuộc trò chuyện mới"
        info = create_new_session(title=title)  # Không truyền user nữa
        session_id = info["session_id"]

    # Lưu message user vào history
    add_message("user", user_text, session_id=session_id)

    # 1. Load LLM + RAG
    bm25_folder = bm25_folder or DATA_DIR_SALES
    corpus_path = corpus_path or (FAISS_ALL_DIR_SALES / "corpus.jsonl")
    embeddings, vector_store, retriever, gclient, GEMINI_MODEL, GEN_CFG = LLM_model(
        bm25_folder=bm25_folder,
        corpus_path=corpus_path,
    )

    # 2. Load context & history
    ctx = _load_ctx(session_id)
    history_msgs = _get_history_msgs_for_ctx(session_id)

    # 3. Editor (dịch / viết lại câu trả lời trước)
    analysis = _analyze_followup_and_lang(
        gclient, GEMINI_MODEL, GEN_CFG, user_text, history_msgs, ctx
    )
    if analysis.get("mode") == "edit":
        final_answer = strip_source_citations(analysis.get("output", ""))
        add_message("assistant", final_answer, session_id=session_id)

        # cập nhật ngôn ngữ ưu tiên
        ctx["lang"] = analysis.get("set_lang") or ctx.get("lang", "vi")
        ctx["last_branch"] = "editor"
        update_ctx(session_id, ctx)

        return {
            "ok": True,
            "answer": final_answer,
            "session_id": session_id,
            "branch": "editor",
            "timing": {"total": round(time.time() - full_start, 2)},
        }

    # 4. Lệnh xoá file upload trong session
    if user_text.lower().strip() in ["xóa file", "xoá file", "hủy file", "delete file", "clear file"]:
        uploaded_files_meta = session.get("uploaded_files", [])
        session_doc_paths: List[str] = []

        # cố gắng log 1 file để debug (không bắt buộc)
        if isinstance(uploaded_files_meta, list):
            for item in reversed(uploaded_files_meta):
                if isinstance(item, dict):
                    p = item.get("path")
                    if p and os.path.exists(p):
                        session_doc_paths = [p]
                        print(f"[RAG] Đã nhận diện file: {p}")
                        break
        elif isinstance(uploaded_files_meta, dict) and session_id in uploaded_files_meta:
            for item in reversed(uploaded_files_meta[session_id]):
                if isinstance(item, dict):
                    p = item.get("path")
                    if p and os.path.exists(p):
                        session_doc_paths = [p]
                        print(f"[RAG] Đã nhận diện file từ dict: {p}")
                        break

        # Xoá metadata trong session
        if isinstance(uploaded_files_meta, dict):
            uploaded_files_meta.pop(session_id, None)
            session["uploaded_files"] = uploaded_files_meta
        else:
            session.pop("uploaded_files", None)

        # clear FAISS + summary cache
        _clear_session_doc_vs(session_id)

        final_answer = "Đã xoá toàn bộ file đã upload trong phiên này."
        add_message("assistant", final_answer, session_id=session_id)
        return {
            "ok": True,
            "answer": final_answer,
            "session_id": session_id,
            "branch": "doc_clear",
            "timing": {"total": round(time.time() - full_start, 2)},
        }

    # 5. Lấy file upload (multi-file + hỗ trợ cả list/dict)
    uploaded_files_meta = session.get("uploaded_files", [])
    session_doc_paths: List[str] = []
    seen_paths: set[str] = set()
    flat_metas: List[Dict[str, Any]] = []

    if isinstance(uploaded_files_meta, list):
        # format mới: session["uploaded_files"] = [ {name, stored_name, path, file_type}, ... ]
        flat_metas = [m for m in uploaded_files_meta if isinstance(m, dict)]
        for item in reversed(flat_metas):
            p = item.get("path")
            if (
                p
                and isinstance(p, str)
                and os.path.exists(p)
                and p not in seen_paths
            ):
                session_doc_paths.append(p)
                seen_paths.add(p)
    elif isinstance(uploaded_files_meta, dict):
        # format cũ: session["uploaded_files"][session_id] = [ {...}, ... ]
        meta_for_session = uploaded_files_meta.get(session_id) or []
        flat_metas = [m for m in meta_for_session if isinstance(m, dict)]
        if isinstance(meta_for_session, list):
            for item in reversed(meta_for_session):
                if not isinstance(item, dict):
                    continue
                p = item.get("path")
                if (
                    p
                    and isinstance(p, str)
                    and os.path.exists(p)
                    and p not in seen_paths
                ):
                    session_doc_paths.append(p)
                    seen_paths.add(p)

    # Map path → full meta (để lấy file_type / is_image nếu cần)
    file_meta_map: Dict[str, Dict[str, Any]] = {}
    for m in flat_metas:
        p = m.get("path")
        if p and isinstance(p, str):
            file_meta_map[p] = m

    active_file_path: Optional[str] = session_doc_paths[0] if session_doc_paths else None
    active_source: Optional[str] = os.path.basename(active_file_path) if active_file_path else None

    # 5.1 LLM detect câu kiểu "file này / 2 file này / các file trên..."
    is_generic_current = _is_generic_current_file_query(
        user_text=user_text,
        gclient=gclient,
        GEMINI_MODEL=GEMINI_MODEL,
        GEN_CFG=GEN_CFG,
    )

    # 5.2 Detect xem user có GÕ RÕ TÊN FILE trong câu hỏi không
    focus_sources: Optional[List[str]] = None
    if flat_metas:
        focus_sources = _detect_focus_sources_from_query(user_text, flat_metas)

    # Nếu chỉ có 1 file + câu kiểu "file này" → focus vào file đó
    if not focus_sources and is_generic_current and len(session_doc_paths) == 1 and active_source:
        focus_sources = [active_source]

    # Nếu user đã gõ rõ tên file → KHÔNG coi là "file này / file trên" nữa
    if focus_sources:
        is_generic_current = False

    # 5.3 NHÁNH ĐẶC BIỆT:
    # Nếu user hỏi rõ "nội dung các file" → tóm tắt từng file trực tiếp, không đi qua DB/RAG.
    if session_doc_paths and _is_request_uploaded_files_content(user_text):
        if focus_sources:
            allowed = set(focus_sources)
            target_paths = [
                p for p in session_doc_paths
                if os.path.basename(p) in allowed
            ]
        else:
            target_paths = _get_latest_batch_paths(flat_metas) or list(session_doc_paths)

        parts: List[str] = []
        for p in target_paths:
            meta_for_file = next(
                (m for m in flat_metas if m.get("path") == p),
                {},
            )
            display_name = meta_for_file.get("name") or os.path.basename(p)

            summary = _summarize_uploaded_file(
                gclient=gclient,
                GEMINI_MODEL=GEMINI_MODEL,
                GEN_CFG=GEN_CFG,
                path=p,
                max_lines=12,  # cho chi tiết hơn chút
            )
            summary = (summary or "").strip()
            if not summary:
                summary = "Không đọc được nội dung file này (có thể là ảnh/scan mờ hoặc file trống)."

            parts.append(f"{display_name}:\n{summary}")

        final_answer = (
            f"Bạn đã cung cấp {len(parts)} file, nội dung tóm tắt như sau:\n\n"
            + "\n\n".join(parts)
        )

        final_answer = strip_source_citations(final_answer)
        add_message("assistant", final_answer, session_id=session_id)
        ctx["last_branch"] = "file_direct_summary"
        try:
            update_ctx(session_id, ctx)
        except Exception:
            pass

        elapsed = time.time() - full_start
        return {
            "ok": True,
            "answer": final_answer,
            "session_id": session_id,
            "branch": ctx.get("last_branch", "file_direct_summary"),
            "meta": {},
            "timing": {
                "total": round(elapsed, 2),
            },
        }

    # 6. Cập nhật ngôn ngữ ưu tiên trong ctx
    if analysis.get("set_lang") in ("vi", "en"):
        ctx["lang"] = analysis.get("set_lang")
    elif "lang" not in ctx:
        ctx["lang"] = _auto_detect_lang(user_text)

    # 7. Kiểm tra DB trước (SQL / Supabase / hệ thống nội bộ)
    handled, db_answer, meta = handle_db_message(
        user_text,
        session_id,
        principal=principal,
    )

    if handled:
        # Có câu trả lời từ DB → cho Gemini rewrite cho gọn, giữ nguyên số liệu
        final_answer = _rewrite_db_answer(
            gclient,
            GEMINI_MODEL,
            GEN_CFG,
            db_answer,
            lang_hint=ctx.get("lang"),
        )
        ctx["last_branch"] = "db"
        timing = {}
    else:
        # 8. RAG – chọn subset file dùng trong lượt này + only_use_session_docs
        session_paths_for_rag = list(session_doc_paths)
        only_use_session_docs = False

        if session_doc_paths:
            # (1) LLM detect: câu hỏi có đang nói về FILE đã upload không?
            only_llm_file = _is_query_about_uploaded_file(
                user_text=user_text,
                lang=ctx.get("lang", "vi"),
                gclient=gclient,
                GEMINI_MODEL=GEMINI_MODEL,
                GEN_CFG=GEN_CFG,
            )
            only_use_session_docs = only_llm_file

            # (2) Nếu user GÕ RÕ TÊN FILE (focus_sources != None)
            if focus_sources:
                only_use_session_docs = True
                allowed = set(focus_sources)
                session_paths_for_rag = [
                    p for p in session_doc_paths
                    if os.path.basename(p) in allowed
                ]

            # (3) Nếu KHÔNG nêu tên file nhưng là câu “file này / ảnh này / 2 ảnh này…”
            elif is_generic_current and session_doc_paths:
                lower_q = user_text.lower()
                image_paths = []
                other_paths = []
                for p in session_doc_paths:
                    if is_image_path(p):
                        image_paths.append(p)
                    else:
                        other_paths.append(p)

                # CASE A: chỉ có ảnh
                if image_paths and not other_paths:
                    # mặc định dùng TẤT CẢ ảnh
                    n = len(image_paths)

                    # "2 ảnh / 3 hình / 2 phiếu / 2 hóa đơn ..."
                    m_num = re.search(
                        r'(\d+)\s*(file|tập tin|tap tin|ảnh|anh|hình|hinh|image|picture|'
                        r'phiếu|phieu|hóa đơn|hoa don|giấy|giay|tờ|to)',
                        lower_q,
                    )
                    if m_num:
                        try:
                            n = int(m_num.group(1))
                        except ValueError:
                            n = len(image_paths)
                    elif any(
                        kw in lower_q
                        for kw in [
                            "hai file", "hai ảnh", "hai anh", "hai hình", "hai hinh",
                            "hai phiếu", "hai phieu", "hai hóa đơn", "hai hoa don",
                        ]
                    ):
                        n = 2

                    # "các ảnh / những ảnh ..." → giữ n = len(image_paths)
                    n = max(1, min(n, len(image_paths)))

                    session_paths_for_rag = []
                    for i, p in enumerate(image_paths):
                        if i >= n:
                            break
                        session_paths_for_rag.append(p)

                    only_use_session_docs = True

                # CASE B: trộn cả doc + image
                else:
                    n = 1
                    m_num = re.search(
                        r'(\d+)\s*(file|tập tin|tap tin|tài liệu|tai lieu)',
                        lower_q,
                    )
                    if m_num:
                        try:
                            n = int(m_num.group(1))
                        except ValueError:
                            n = 1
                    elif any(
                        kw in lower_q
                        for kw in ["hai file", "hai tài liệu", "hai tai lieu"]
                    ):
                        n = 2
                    elif any(
                        kw in lower_q
                        for kw in ["các file", "cac file", "những file", "nhung file"]
                    ):
                        n = len(session_doc_paths)

                    n = max(1, min(n, len(session_doc_paths)))
                    session_paths_for_rag = session_doc_paths[:n]
                    only_use_session_docs = True

        print(
            f"[RAG MODE] session_id={session_id} | all_files={len(session_doc_paths)} "
            f"| used_files={len(session_paths_for_rag)} "
            f"| only_use_session_docs={only_use_session_docs} "
            f"| active_source={active_source} | is_generic_current={is_generic_current} "
            f"| focus_sources={focus_sources}"
        )

        # Gọi RAG chính (global + session docs)
        final_answer, timing = _rag_answer(
            user_text=user_text,
            gclient=gclient,
            GEMINI_MODEL=GEMINI_MODEL,
            GEN_CFG=GEN_CFG,
            embeddings=embeddings,
            retriever=retriever,
            lang_hint=ctx.get("lang"),
            session_id=session_id,
            session_doc_paths=session_paths_for_rag,
            only_use_session_docs=only_use_session_docs,
            focus_sources=focus_sources if focus_sources else None,
            file_meta_map=file_meta_map,
        )

        ctx["last_branch"] = "rag_file_only" if only_use_session_docs else "rag"
        if session_doc_paths:
            ctx["last_docs"] = [os.path.basename(p) for p in session_doc_paths]

    # 9. Ghi trả lời + cập nhật context
    final_answer = strip_source_citations(final_answer or "")
    add_message("assistant", final_answer, session_id=session_id)
    try:
        update_ctx(session_id, ctx)
    except Exception:
        pass

    # 10. Smart summary (hook, để nguyên nếu sau này cần)
    try:
        msgs = get_session_messages(session_id, limit=300)
        user_count = len([m for m in msgs if m["role"] == "user"])
        if user_count >= 10 and user_count % 10 == 0:
            # Trigger auto-summary nếu cần trong tương lai
            pass
    except Exception:
        pass

    elapsed = time.time() - full_start
    return {
        "ok": True,
        "answer": final_answer,
        "session_id": session_id,
        "branch": ctx.get("last_branch", "rag"),
        "meta": meta or {},
        "timing": {
            "total": round(elapsed, 2),
            **(timing if "timing" in locals() else {}),
        },
    }

