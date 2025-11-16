# -*- coding: utf-8 -*-
"""
Optional Gemini NLU module.
Set NLU_BACKEND=gemini and GEMINI_API_KEY to enable. Falls back to regex classify().
"""
import os, re, json

def classify_regex(text: str) -> tuple[str, dict]:
    s = (text or "").lower().strip()
    if any(k in s for k in ["doanh thu", "doanh số", "revenue", "doanhso"]):
        return "kpi_revenue", {}
    if any(k in s for k in ["đơn", "don", "mã", "ma "]):
        return "order_lookup", {}
    if any(k in s for k in ["thông tin","thong tin","profile","hồ sơ","ho so"]):
        return "person_profile", {}
    return "unknown", {}

def _gemini_available() -> bool:
    return (os.environ.get("NLU_BACKEND","").lower()=="gemini") and bool(os.environ.get("GEMINI_API_KEY"))

def classify(text: str) -> tuple[str, dict]:
    if not _gemini_available():
        return classify_regex(text)

    prompt = (
        "You are a Vietnamese NLU. Task: map the user text to one of intents: "
        "kpi_revenue | order_lookup | person_profile | unknown. "
        "Return a compact JSON: {\\\"intent\\\": \\\"<one>\\\", \\\"params\\\": {}}. "
        f"Text: \\\"{text}\\\""
    )

    try:
        # TODO: tích hợp SDK chính thức khi bạn sẵn sàng.
        from google import genai
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        resp = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        raw = resp.text
        raw = ""  # placeholder để không tạo phụ thuộc runtime
        j = json.loads(raw) if raw else {}
        intent = j.get("intent") or "unknown"
        params = j.get("params") or {}
        return intent, params
    except Exception:
        return classify_regex(text)
