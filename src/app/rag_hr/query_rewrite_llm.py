# -*- coding: utf-8 -*-
import json
from app.config.config_HR import CASE_NORM_HR, USE_QR_LLM_HR, QR_LLM_MODEL_HR, QR_NUM_ALIASES_HR, PHRASE_BOOST_TIMES_HR, DEBUG_QE_HR
from .utils_hr import normalize_case
from .gemini_client_hr import init_gemini, ask_gemini

_PROMPT = """
    Bạn là bộ máy MỞ RỘNG TRUY VẤN cho lĩnh vực Nhân sự (HR) tiếng Việt.
    Mục tiêu: từ truy vấn người dùng, tạo ra một số cụm từ ĐỒNG NGHĨA/BIẾN THỂ NGẮN GỌN giúp tìm kiếm tài liệu tốt hơn.
    YÊU CẦU:
    - Trả về JSON với keys: canonical (string), aliases (array of strings).
    - aliases chỉ gồm CỤM DANH TỪ/THÀNH NGỮ NGẮN (≤ 4 từ), không giải thích, không câu dài.
    - Ưu tiên các biến thể phổ biến như: "sơ đồ tổ chức", "cơ cấu tổ chức", "org chart", ...
    - Không bịa tên riêng mới. Không thêm dấu câu thừa.
    """

def llm_expand_query(q: str) -> dict:
    nq = normalize_case(q, CASE_NORM_HR)
    if not USE_QR_LLM_HR:
        return {"lex_query": nq, "canonical": nq}

    genai = init_gemini()
    sys = "Bạn chỉ trả JSON như hướng dẫn. Không thêm chữ thừa ngoài JSON."
    user = f'input: "{q}"\nTrả JSON như yêu cầu ở trên.'
    raw = ask_gemini(genai, QR_LLM_MODEL_HR, sys + _PROMPT, user, json_mode=False).strip()

    try:
        data = json.loads(raw)
    except Exception:
        try:
            start = raw.find("{"); end = raw.rfind("}")
            data = json.loads(raw[start:end+1])
        except Exception:
            if DEBUG_QE_HR:
                print("[QR-LLM] Parse JSON fail, raw:", raw[:200])
            data = {"canonical": nq, "aliases": []}

    aliases = [normalize_case(x, CASE_NORM_HR) for x in (data.get("aliases") or [])]
    aliases = [a for a in aliases if a and a != nq]
    aliases = aliases[:max(1, QR_NUM_ALIASES_HR)]

    phrases = [f"\"{a}\"" for a in aliases]
    boosted = []
    for p in phrases:
        boosted.extend([p] * max(1, PHRASE_BOOST_TIMES_HR))

    lex_query = " ".join([nq] + boosted)
    canonical = normalize_case(data.get("canonical") or nq, CASE_NORM_HR)
    if DEBUG_QE_HR:
        print(f"[QR-LLM] canonical={canonical} | aliases={aliases}")
    return {"lex_query": lex_query, "canonical": canonical}
