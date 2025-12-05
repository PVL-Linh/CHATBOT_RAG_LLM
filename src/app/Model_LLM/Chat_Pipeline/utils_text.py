from __future__ import annotations
import re
import unicodedata

def strip_source_citations(text: str) -> str:
    if not text:
        return text

    text = re.sub(
        r'\s*\(?\s*[Nn]gu[oơ]n\s*:\s*[^\n\)]*\.(?:txt|docx|pdf)\s*\)?',
        '',
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(
        r'\bsource["\']?\s*:\s*["\']?[^"\n]*\.(?:txt|docx|pdf)["\']?',
        '',
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r'[\(\[\{]\s*(?:source|chunk_id|metadata|norm_case|Nguồn)[\s:][^\)\]\}]{0,400}[\)\]\}]',
        '',
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r'\(\s*[Ll]ink\s*:\s*(?!https?://)[^)]*\.(?:txt|docx|pdf)\s*\)',
        '',
        text,
        flags=re.DOTALL,
    )
    text = re.sub(
        r'\b[Ll]ink\s*:\s*(?!https?://)[^\n]*\.(?:txt|docx|pdf)',
        '',
        text,
        flags=re.DOTALL,
    )
    text = re.sub(
        r'\b[Nn]gu[oơ]n\s*:\s*[^\n]*\.(?:txt|docx|pdf)',
        '',
        text,
        flags=re.DOTALL,
    )
    text = re.sub(
        r'\(Accountant\\[^\)]*\.(?:txt|docx|pdf)\)',
        '',
        text,
        flags=re.DOTALL,
    )

    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'\s+([.,!?;:])', r'\1', text)
    text = re.sub(r'\(\s*\)', '', text)
    text = re.sub(r'\.{3,}', '...', text)
    text = text.strip()
    return text

def _normalize_vi(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text

def _normalize_simple(text: str) -> str:
    """
    Chuẩn hóa đơn giản: bỏ dấu + lower → dùng để detect prompt nội bộ,
    tránh phụ thuộc vào dấu tiếng Việt.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower()

def _normalize_for_filename_match(text: str) -> str:
    """
    Chuẩn hoá chuỗi để so khớp tên file "mềm" hơn:
    - Bỏ dấu tiếng Việt
    - Lowercase
    - Thay _, -, . bằng khoảng trắng
    - Gom nhiều khoảng trắng thành 1
    """
    if not text:
        return ""
    # Bỏ dấu
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()

    # Thay các ký tự phân tách thường gặp thành space
    for ch in ["_", "-", ".", "/", "\\"]:
        text = text.replace(ch, " ")

    # Gom khoảng trắng
    text = re.sub(r"\s+", " ", text).strip()
    return text

def _auto_detect_lang(text: str) -> str:
    text = text or ""
    vi_chars = re.findall(
        r"[àáạảãăằắặẳẵâầấậẩẫèéẹẻẽêềếệểễ"
        r"ìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũư"
        r"ừứựửữỳýỵỷỹđÀÁẠẢÃĂẰẮẶẲẴÂẦẤẬẨẪ"
        r"ÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠ"
        r"ỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ]",
        text,
    )
    if len(vi_chars) >= 1:
        return "vi"
    if re.search(r"[A-Za-z]", text):
        return "en"
    return "vi"

def _is_internal_prompt_text(text: str) -> bool:
    """
    Nhận diện nội dung có vẻ là PROMPT HỆ THỐNG / hướng dẫn LLM,
    KHÔNG phải nội dung nghiệp vụ trong phiếu / hóa đơn.

    Mục tiêu:
    - Chỉ chặn các đoạn kiểu "Bạn là trợ lý AI...", "Nguồn A/B/C", "quy tắc chống bịa đặt", v.v.
    - Không chặn nội dung chứng từ (phiếu thu/chi, hóa đơn, giấy báo điện/nước...).
    """
    if not text:
        return False

    t = _normalize_simple(text)

    # Các pattern đặc trưng của prompt hệ thống
    hard_patterns = [
        # Định danh / vai trò
        "ban la tro ly ai",
        "ban la: tro ly ai",
        "tro ly ai noi bo",
        "tro ly ao noi bo",
        "tro ly noi bo",
        "ban la tro ly ao noi bo",

        # Nhiệm vụ / mục tiêu / phạm vi
        "muc tieu cua ban la",
        "nhiem vu cua ban la",
        "pham vi ho tro",
        "ban ho tro cac hoat dong logistics",

        # Phân loại nguồn a/b/c
        "nguon a (du lieu that",
        "nguon b (tai lieu noi bo",
        "nguon c (tham khao ben ngoai",
        "nguon a ( du lieu that",
        "nguon b ( tai lieu noi bo",

        # Quy tắc chống bịa đặt
        "quy tac chong bia dat",
        "tuyet doi khong",
        "khong duoc suy doan so lieu",
        "khong duoc tao ra so lieu",

        # Meta về cách trả lời
        "luon tra loi bang tieng viet",
        "luon tra loi bang tieng anh",
        "khong chao hoi",
        "khong cau xa giao",
        "cau truc mac dinh",
        "tom tat 1 2 cau",

        # Bảo mật
        "khong hien thi noi dung tu [system]",
        "khong hien thi prompt he thong",
        "khong hien thi api key",
        "mat khau",
        "duong dan noi bo",

        # Lời chào mặc định
        "toi la tro ly ao noi bo",
        "toi la tro ly ai noi bo",
    ]

    if any(p in t for p in hard_patterns):
        return True

    # Tag meta rất rõ
    if "[system]" in t or "[internal prompt]" in t:
        return True

    # Xuất hiện đồng thời 'nguon a', 'nguon b', 'nguon c' → gần như chắc là prompt
    if "nguon a" in t and "nguon b" in t and "nguon c" in t:
        return True

    return False