import json
import time
from typing import Any, Dict, List, Optional
from app.Helpers.prompt_internal import sys_instr
from app.config.settings import ChatConfig, Chat_engine
from .history_ctx import _get_last_assistant_message
from .utils_text import _auto_detect_lang

LLM_SEM = ChatConfig.LLM_SEM
DB_CONF_THRESHOLD = Chat_engine.DB_CONF_THRESHOLD
REWRITE_DB_WITH_LLM = Chat_engine.REWRITE_DB_WITH_LLM

def _estimate_from_contents(contents, max_out_tokens=1024) -> int:
    words = 0
    for m in contents or []:
        for p in (m.get("parts") or []):
            if isinstance(p, dict) and p.get("text"):
                words += len(p["text"].split())
    return int(1.3 * words) + int(max_out_tokens or 512)


def _safe_gemini_generate(gclient, model, contents, config, retries=3, backoff=0.4):
    from app.Helpers.rate_limit import get_text_limiter

    limiter = get_text_limiter()
    max_out = (
        config.get("max_output_tokens")
        if isinstance(config, dict)
        else getattr(config, "max_output_tokens", 1024)
    )
    tokens_est = _estimate_from_contents(contents, max_out)
    last_err: Optional[Exception] = None

    for i in range(retries + 1):
        try:
            limiter.acquire(tokens_est)
            t0 = time.time()
            with LLM_SEM:
                resp = gclient.models.generate_content(
                    model=model, contents=contents, config=config
                )
            limiter.on_success()
            return (getattr(resp, "text", "") or ""), time.time() - t0
        except Exception as e:
            last_err = e
            s = str(e).lower()
            if ("429" in s or "quota" in s or "resource_exhausted" in s) and i < retries:
                limiter.on_429()
                time.sleep(backoff * (2 ** i))
                continue
            limiter.on_429()
            raise last_err


def _rewrite_last_answer_for_lang(
    gclient,
    GEMINI_MODEL,
    GEN_CFG,
    last_answer: str,
    target_lang: str = "en",
) -> str:
    last_answer = (last_answer or "").strip()
    if not last_answer:
        return ""
    target_lang = (target_lang or "en").lower()

    if target_lang.startswith("en"):
        instr = (
            "Rewrite the following answer in clear, natural English. "
            "Keep the meaning and important details, but you can shorten slightly if needed.\n"
            "Answer ONLY in English.\n"
        )
    else:
        instr = (
            "Viết lại câu trả lời sau bằng tiếng Việt rõ ràng, tự nhiên. "
            "Giữ nguyên ý chính và các chi tiết quan trọng, có thể rút gọn nhẹ nếu cần.\n"
            "Chỉ trả lời bằng tiếng Việt.\n"
        )

    prompt = f"""{instr}
    [ANSWER]
    {last_answer}
    """
    contents = [
        {
            "role": "user",
            "parts": [{"text": prompt}],
        }
    ]
    out, _ = _safe_gemini_generate(gclient, GEMINI_MODEL, contents, GEN_CFG)
    return (out or "").strip()


def _analyze_followup_and_lang(
    gclient,
    GEMINI_MODEL,
    GEN_CFG,
    user_text: str,
    history_msgs: List[Dict[str, str]],
    ctx: Dict[str, Any],
):
    user_text = (user_text or "").strip()
    if not user_text:
        return {"mode": "pass", "output": "", "set_lang": None}

    last_ans = _get_last_assistant_message(history_msgs)
    if not last_ans:
        return {"mode": "pass", "output": "", "set_lang": None}

    current_lang = (ctx or {}).get("lang") or "vi"
    lower_ut = user_text.lower()

    vi_to_en_patterns = [
        "viết bằng tiếng anh",
        "viết lại bằng tiếng anh",
        "viết tiếng anh",
        "dịch sang tiếng anh",
        "dịch đoạn trên sang tiếng anh",
        "dịch nội dung trên sang tiếng anh",
        "rewrite in english",
        "write in english",
        "answer in english",
        "translate to english",
    ]
    en_to_vi_patterns = [
        "viết bằng tiếng việt",
        "viết lại bằng tiếng việt",
        "dịch sang tiếng việt",
        "dịch đoạn trên sang tiếng việt",
        "dịch nội dung trên sang tiếng việt",
        "rewrite in vietnamese",
        "translate to vietnamese",
    ]

    if any(p in lower_ut for p in vi_to_en_patterns):
        out_text = _rewrite_last_answer_for_lang(
            gclient, GEMINI_MODEL, GEN_CFG, last_ans, target_lang="en"
        )
        return {
            "mode": "edit",
            "output": out_text,
            "set_lang": "en",
        }

    if any(p in lower_ut for p in en_to_vi_patterns):
        out_text = _rewrite_last_answer_for_lang(
            gclient, GEMINI_MODEL, GEN_CFG, last_ans, target_lang="vi"
        )
        return {
            "mode": "edit",
            "output": out_text,
            "set_lang": "vi",
        }

    prompt = f"""{sys_instr}
    [CURRENT_PREFERRED_LANG]
    {current_lang}
    [PREVIOUS_ANSWER]
    {last_ans}
    [USER_REQUEST]
    {user_text}
    """
    contents = [
        {
            "role": "user",
            "parts": [{"text": prompt}],
        }
    ]
    raw, _ = _safe_gemini_generate(gclient, GEMINI_MODEL, contents, GEN_CFG)
    raw = (raw or "").strip()

    try:
        data = json.loads(raw)
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}

    mode = (data.get("mode") or "pass").lower()
    output = (data.get("output") or "").strip()
    set_lang = data.get("set_lang", None)

    if set_lang is not None:
        if isinstance(set_lang, str):
            set_lang = set_lang.lower()
            if set_lang not in ("vi", "en"):
                set_lang = None
        else:
            set_lang = None

    if set_lang is None:
        detected = _auto_detect_lang(user_text)
        if detected in ("vi", "en") and detected != current_lang:
            set_lang = detected

    if mode != "edit" or not output:
        return {"mode": "pass", "output": "", "set_lang": set_lang}

    return {"mode": "edit", "output": output, "set_lang": set_lang}

def _is_generic_current_file_query(
    user_text: str,
    gclient=None,
    GEMINI_MODEL=None,
    GEN_CFG=None,
) -> bool:
    """
    Dùng Gemini để detect các câu kiểu:
    - "file này", "file trên", "file vừa rồi"
    - "hóa đơn này", "ảnh trên", "2 file này", "các file này", "những file trên"
    => user đang nói chung chung về file hiện tại / các file vừa upload,
    KHÔNG nêu tên file cụ thể.
    """
    if not gclient or not user_text.strip():
        return False

    query = user_text.strip()[:1500]

    prompt = f"""Bạn là chuyên gia phân tích ngữ cảnh chat với trợ lý ảo có chức năng đọc file người dùng đã upload.

        NHIỆM VỤ:
        Quyết định xem câu hỏi của người dùng có phải kiểu nói CHUNG CHUNG về "file hiện tại" hoặc "những file vừa upload" hay không.

        ĐỊNH NGHĨA "CÂU HỎI CHUNG CHUNG VỀ FILE HIỆN TẠI":
        - User dùng các cụm như:
        + "file này", "file trên", "file vừa rồi", "file mới up", "file hiện tại"
        + hoặc "hóa đơn này", "hóa đơn trên", "ảnh này", "hình trên"
        + hoặc "2 file này", "3 file này", "các file này", "các file trên", "những file này", "những file trên"
        - KHÔNG nêu tên file cụ thể (không nói rõ như "file CV_PhanDuyBao_AIEngineer.pdf").

        VÍ DỤ → YES:
        - "file này là gì?"
        - "tóm tắt nội dung file trên"
        - "2 file này khác nhau gì?"
        - "ảnh trên là hóa đơn gì?"
        - "hóa đơn này tổng tiền bao nhiêu?"
        - "so sánh nội dung 2 file này giúp tôi"

        VÍ DỤ → NO:
        - "tóm tắt quy định nghỉ phép của công ty"
        - "cho tôi quy trình nhập kho"
        - "tổng hợp nội dung file BáoCaoThucTap.docx"
        - "tóm tắt nội dung file CV_PhanDuyBao_AIEngineer.pdf"
        - "cho tôi những tài liệu liên quan về công ty"

        Câu hỏi người dùng:
        {query}

        Nếu câu hỏi thuộc loại "chung chung về file hiện tại" như định nghĩa ở trên,
        hãy trả lời đúng 1 từ: YES
        Nếu không, trả lời đúng 1 từ: NO
        Không giải thích thêm.
        Trả lời:
        """

    try:
        contents = [{"role": "user", "parts": [{"text": prompt}]}]
        raw, _ = _safe_gemini_generate(gclient, GEMINI_MODEL, contents, GEN_CFG)
        result = (raw or "").strip().upper()
        return result == "YES" or result.startswith("YES")
    except Exception as e:
        print(f"[DEBUG] Lỗi detect generic current file query: {e}")
        # fallback an toàn
        return False

def _is_query_about_uploaded_file(
    user_text: str,
    lang: str = "vi",
    gclient=None,
    GEMINI_MODEL=None,
    GEN_CFG=None,
) -> bool:
    """
    Dùng Gemini để quyết định: người dùng có đang hỏi về file đã upload không?
    Trả lời YES/NO, không dùng pattern cứng.
    """
    if not gclient or not user_text.strip():
        return False

    query = user_text.strip()[:1500]
    prompt = f"""Bạn là chuyên gia phân tích ngữ cảnh chat.
    Có file đã được upload trong phiên này.
    Người dùng có đang hỏi cụ thể về nội dung của file đó không?
    Chỉ trả lời đúng 1 từ: YES hoặc NO. Không giải thích.
    Ví dụ:
    - "tóm tắt" → YES
    - "nội dung file trên" → YES
    - "cái này nói gì" → YES
    - "file này là gì" → YES
    - "quy trình nghỉ phép mới nhất?" → NO
    - "lương tháng này bao nhiêu?" → NO
    Câu hỏi người dùng: {query}
    Trả lời:"""
    try:
        contents = [{"role": "user", "parts": [{"text": prompt}]}]
        raw, _ = _safe_gemini_generate(gclient, GEMINI_MODEL, contents, GEN_CFG)
        result = (raw or "").strip().upper()
        return result == "YES" or result.startswith("YES")
    except Exception as e:
        print(f"[DEBUG] Lỗi detect file query: {e}")
        return False
    

