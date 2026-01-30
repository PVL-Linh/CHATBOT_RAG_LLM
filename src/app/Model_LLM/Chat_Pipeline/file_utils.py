from __future__ import annotations
import os
import re
from typing import Any, Dict, List, Optional

import fitz
import docx as docx_lib

from .utils_text import _auto_detect_lang, _normalize_for_filename_match
from .gemini_helpers import _safe_gemini_generate
from .utils_text import _normalize_vi
from app.routes.image_ocr_utils import extract_text_from_image, is_image_path

def _extract_text_from_uploaded_file(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()

    if ext == ".txt":
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return ""

    if ext == ".docx":
        try:
            d = docx_lib.Document(path)
            lines = []
            for p in d.paragraphs:
                t = (p.text or "").strip()
                if t:
                    lines.append(t)
            for tbl in d.tables:
                for row in tbl.rows:
                    cells = [(cell.text or "").strip() for cell in row.cells]
                    line = " | ".join(c for c in cells if c)
                    if line:
                        lines.append(line)
            return "\n".join(lines)
        except Exception:
            return ""

    if ext == ".pdf":
        try:
            doc = fitz.open(path)
            pages = []
            for p in doc:
                t = p.get_text()
                if t.strip():
                    pages.append(t)
            doc.close()
            return "\n".join(pages)
        except Exception:
            return ""

    # ẢNH: gọi OCR utils
    if is_image_path(path):
        try:
            return extract_text_from_image(path)
        except Exception:
            return ""

    return ""


def _summarize_uploaded_file(
    gclient,
    GEMINI_MODEL,
    GEN_CFG,
    path: str,
    max_lines: int = 10,  # tham số vẫn giữ để không vỡ chỗ khác, nhưng prompt sẽ chi tiết hơn
) -> str:
    """
    - ẢNH: chỉ OCR → trả về raw text (để bạn toàn quyền xử lý sau).
    - PDF/DOCX/TXT: gọi LLM để tóm tắt CHI TIẾT HƠN (multi-bullet, có cấu trúc).
    """

    if is_image_path(path):
        raw = _extract_text_from_uploaded_file(path)
        return (raw or "").strip()
    raw_text = _extract_text_from_uploaded_file(path)
    if not raw_text or not raw_text.strip():
        return ""

    detected_lang = _auto_detect_lang(raw_text)
    lang_name = "Việt" if detected_lang == "vi" else "Anh"
    snippet = raw_text[:2000]

    prompt = f"""Bạn đang đọc một tài liệu nội bộ (pdf/doc/txt).

        NHIỆM VỤ:
        Tóm tắt TƯƠNG ĐỐI CHI TIẾT tài liệu dưới đây.

        YÊU CẦU:
        - Viết một đoạn TÓM TẮT NGẮN 1–2 câu ở đầu.
        - Sau đó viết 5–12 gạch đầu dòng mô tả chi tiết:
        + Mục tiêu / chủ đề chính của tài liệu.
        + Đối tượng, bối cảnh (nếu nhận diện được).
        + Cấu trúc các chương / mục chính (liệt kê tên chương hoặc chủ đề).
        + Phương pháp / kỹ thuật / nội dung quan trọng.
        + Kết quả, kết luận hoặc kiến nghị chính.
        + Ứng dụng hoặc ý nghĩa thực tiễn (nếu có).
        - BÁM SÁT nội dung thực tế trong tài liệu, không nói chung chung.
        - Nếu tài liệu là khóa luận / luận văn:
        + Ghi rõ tên đề tài (title), tên tác giả, loại luận văn (khóa luận tốt nghiệp, luận văn thạc sĩ...).
        + Tóm tắt ngắn gọn nội dung các chương chính (Chương 1, Chương 2...).
        - Nếu tài liệu là slide / ebook về AI:
        + Liệt kê các khái niệm, kỹ thuật, hoặc chương quan trọng (ví dụ: khái niệm AI, Machine Learning, Deep Learning, ứng dụng AI trong doanh nghiệp...).
        - Không cần nhắc lại đường dẫn file, chỉ tập trung vào nội dung.
        - Trả lời bằng tiếng {lang_name}.

        [TÀI LIỆU]
        {snippet}
        """

    contents = [{"role": "user", "parts": [{"text": prompt}]}]

    try:
        summary, _ = _safe_gemini_generate(gclient, GEMINI_MODEL, contents, GEN_CFG)
        summary = (summary or "").strip()

        # Nếu LLM trả lời quá ngắn (ví dụ < 200 ký tự) → fallback một phần raw_text
        if len(summary) < 200:
            fallback = raw_text[:2000].strip()
            return summary + "\n\n" + fallback if summary else fallback

        return summary
    except Exception:
        # Lỗi LLM → fallback raw text rút gọn
        return raw_text[:2000].strip()

def _split_text_to_chunks(text: str, max_chars: int = 800, overlap: int = 200) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []

    chunks: List[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + max_chars, n)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == n:
            break
        start = max(0, end - overlap)
    return chunks

def _detect_focus_sources_from_query(
    user_text: str,
    uploaded_files_meta: List[Dict[str, Any]],
) -> Optional[List[str]]:
    """
    Tìm xem câu hỏi đang nhắc tới file nào (hoặc nhiều file nào) theo TÊN.

    - User có thể gõ: 
      + đúng tên: "vi-du-phieu-chi.jpg"
      + gần đúng: "vi du phieu chi", "vi_du_phieu_chi"
      + thiếu bớt đuôi: "vi-du-phieu-chi"
    - So khớp tolerant:
      + bỏ dấu tiếng Việt
      + coi "_", "-", "." như khoảng trắng
    - Trả về danh sách basename (stored_name) để khớp với metadata["source"].
    Nếu không match được file nào thì trả về None (nghĩa là dùng tất cả file).
    """
    if not user_text or not uploaded_files_meta:
        return None

    # Chuẩn hoá câu hỏi
    q_norm = _normalize_for_filename_match(user_text)

    matched_sources: List[str] = []

    for item in uploaded_files_meta:
        if not isinstance(item, dict):
            continue

        raw_name = (item.get("name") or "")
        stored   = (item.get("stored_name") or "")
        path     = (item.get("path") or "")

        basename = os.path.basename(path or stored or raw_name)
        basename_lower = basename.lower()

        # Các candidate gốc (chưa normalize)
        candidates_raw = [
            raw_name,
            stored,
            os.path.splitext(raw_name)[0],
            os.path.splitext(basename_lower)[0],
        ]

        # Chuẩn hoá từng candidate để so với q_norm
        found = False
        for c in candidates_raw:
            if not c:
                continue
            c_norm = _normalize_for_filename_match(c)

            # Nếu chuỗi rỗng sau normalize thì bỏ
            if not c_norm:
                continue

            # Ví dụ:
            #   c_norm = "khai thac du lieu va ung dung du oan benh tim mach"
            #   q_norm = "khai thac du lieu va ung dung du oan benh tim mach pdf noi dung 2 file tren"
            if c_norm in q_norm:
                if basename not in matched_sources:
                    matched_sources.append(basename)
                found = True
                break

        # Nếu chưa match theo full tên, thử match theo "core name" rút gọn:
        if not found:
            core = os.path.splitext(basename_lower)[0]
            core_norm = _normalize_for_filename_match(core)

            # Nếu core_norm dài đủ (tránh các tên quá ngắn kiểu "cv" / "a")
            if core_norm and len(core_norm) >= 6 and core_norm in q_norm:
                if basename not in matched_sources:
                    matched_sources.append(basename)

    if not matched_sources:
        return None
    return matched_sources

def _get_latest_batch_paths(flat_metas: List[Dict[str, Any]]) -> List[str]:
    """
    Dựa vào stored_name = "<timestamp>_xxx.ext" để suy ra batch upload mới nhất.
    Trả về list path của batch mới nhất (không trùng, có tồn tại trên disk).
    """
    if not flat_metas:
        return []

    batches: Dict[str, List[Dict[str, Any]]] = {}

    for m in flat_metas:
        if not isinstance(m, dict):
            continue
        stored = str(m.get("stored_name") or "")
        path = m.get("path")

        if not path:
            continue

        # tách prefix trước "_" làm batch_id
        batch_id = ""
        if "_" in stored:
            batch_id = stored.split("_", 1)[0]
        else:
            batch_id = "legacy"

        batches.setdefault(batch_id, []).append(m)

    if not batches:
        return []

    # ưu tiên batch_id là số (timestamp), chọn lớn nhất
    numeric_ids = [bid for bid in batches.keys() if bid.isdigit()]
    if numeric_ids:
        latest_id = max(numeric_ids, key=int)
        latest_metas = batches[latest_id]
    else:
        # fallback: nếu không có numeric id → lấy nhóm "legacy" hoặc tất cả
        latest_metas = batches.get("legacy", flat_metas[-3:])

    paths: List[str] = []
    seen: set[str] = set()
    for m in latest_metas:
        p = m.get("path")
        if p and isinstance(p, str) and os.path.exists(p) and p not in seen:
            paths.append(p)
            seen.add(p)

    return paths

def _is_request_uploaded_files_content(text: str) -> bool:
    """
    Nhận diện các câu kiểu:
    - "nội dung các file trên"
    - "tôi muốn biết nội dung 2 file này"
    - "nội dung mấy file vừa up"
    Mục tiêu: user muốn biết nội dung từng file, không phải hỏi quy trình hay hỏi DB.
    """
    if not text:
        return False

    t = _normalize_vi(text.lower())

    # Phải có "nội dung"
    if "noi dung" not in t:
        return False

    # Và có từ chỉ file / hình / tài liệu
    if (
        "file" in t
        or "tai lieu" in t
        or "hinh" in t
        or "anh" in t
        or "hoa don" in t
    ):
        return True

    return False
