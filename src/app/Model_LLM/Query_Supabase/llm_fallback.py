import re, unicodedata, datetime as dt
from typing import Dict, Any, Optional, Tuple
from app.config.config_supabase import VN_TZ

# Map status/type tiếng Việt → mã hệ thống
ORDER_STATUSES = {
    "chờ thanh toán": "CHO_THANH_TOAN",
    "chờ thanh toán ship": "CHO_THANH_TOAN_SHIP",
    "đã thanh toán": "DA_THANH_TOAN",
    "đã thanh toán ship": "DA_THANH_TOAN_SHIP",
    "chờ giao": "CHO_GIAO",
    "đã giao": "DA_GIAO",
}
ORDER_TYPES = {
    "mua hộ": "MUA_HO",
    "ký gửi": "KY_GUI",
    "đấu giá": "DAU_GIA",
    "thanh toán hộ": "THANH_TOAN_HO",
}

ORDER_CODE_RE = re.compile(r"\b(ORD[A-Z0-9]+|[A-Z0-9]{6,})\b", re.I)
MONTH_RE = re.compile(r"(?:tháng|thang)\s*(\d{1,2})", re.I)
YEAR_RE  = re.compile(r"\b(20\d{2})\b")

def _fold(s: str) -> str:
    t = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(ch for ch in t if unicodedata.category(ch) != "Mn")

def _match_status(text_folded: str) -> Optional[str]:
    for vn_label, code in ORDER_STATUSES.items():
        if _fold(vn_label) in text_folded:
            return code
    return None

def _match_order_type(text_folded: str) -> Optional[str]:
    for vn_label, code in ORDER_TYPES.items():
        if _fold(vn_label) in text_folded:
            return code
    return None

def normalize_query(text: str) -> Dict[str, Any]:
    """
    Trả về {intent, norm}
    Hỗ trợ:
      - "doanh thu hôm nay", "doanh thu tháng 9 (2025)"
      - "nhân viên top doanh thu"
      - "trạng thái đơn ORDXYZ..."
      - "mã ORDNHL1N thể loại chờ thanh toán" (→ lọc orders theo code + status/type)
    """
    tf = _fold(text)
    now = dt.datetime.now(VN_TZ)

    # 1) Doanh thu hôm nay
    if "doanh thu" in tf and ("hom nay" in tf or "hôm nay" in text.lower()):
        return {"intent": "GET_REVENUE_TOTAL", "norm": {"type": "today"}}

    # 2) Doanh thu tháng X [YYYY]
    if "doanh thu" in tf and ("thang" in tf or "tháng" in text.lower()):
        m = MONTH_RE.search(text) or MONTH_RE.search(tf)
        if m:
            month = int(m.group(1))
            y = YEAR_RE.search(text) or YEAR_RE.search(tf)
            year = int(y.group(1)) if y else now.year
            return {"intent": "GET_REVENUE_TOTAL", "norm": {"type": "month", "year": year, "month": month}}

    # 3) Top nhân viên theo doanh thu (đơn giản)
    if ("nhan vien" in tf or "nhân viên" in text.lower()) and ("top" in tf or "cao nhat" in tf):
        # Cho demo: dùng khoảng tháng hiện tại, bạn có thể mở rộng logic
        start = dt.datetime(now.year, now.month, 1, tzinfo=VN_TZ).isoformat()
        end   = (dt.datetime(now.year, now.month, 1, tzinfo=VN_TZ) + dt.timedelta(days=40)).isoformat()
        return {"intent": "GET_REVENUE_BY_STAFF", "norm": {"from": start, "to": end}}

    # 4) Hỏi trạng thái đơn
    if "trang thai" in tf or "trạng thái" in text.lower():
        m = ORDER_CODE_RE.search(text)
        if m:
            return {"intent": "GET_ORDER_STATUS", "norm": {"order_code": m.group(0)}}

    # 5) Câu kiểu: "mã ORDNHL1N thể loại chờ thanh toán" hoặc có type/status
    if text.strip().lower().startswith(("mã ", "ma ")):
        m = ORDER_CODE_RE.search(text)
        st = _match_status(tf)
        ot = _match_order_type(tf)
        return {"intent": "FILTER_ORDERS",
                "norm": {"order_code": m.group(0) if m else None,
                         "status": st,
                         "order_type": ot}}

    # 6) Smalltalk / chưa xác định
    return {"intent": "SMALLTALK", "norm": {}}
