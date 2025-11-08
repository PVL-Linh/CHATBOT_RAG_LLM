# -*- coding: utf-8 -*-
from __future__ import annotations
import re, unicodedata, datetime as dt
from typing import Dict, Any, Optional, Tuple, List
import io, csv
# ====== Nếu bạn có VN_TZ trong config, import; nếu không, mặc định +07 ======
try:
    from src.app.config.config_supabase import VN_TZ
except Exception:
    VN_TZ = dt.timezone(dt.timedelta(hours=7))

# ============================================================================
# Helpers chuẩn hoá & regex
# ============================================================================
def _fold(s: str) -> str:
    s = (s or "").strip()
    t = unicodedata.normalize("NFD", s.lower())
    return "".join(ch for ch in t if unicodedata.category(ch) != "Mn")

NOW = lambda: dt.datetime.now(VN_TZ)
ORDER_CODE_RE = re.compile(
    r"\b("
    r"ORD[A-Z0-9\-]*"                
    r"|[A-Z]{2,5}[A-Z0-9\-]*\d+"
    r"|\d{6,}"                 
    r")\b",
    re.I,
)
def _looks_like_month_year(s: str) -> bool:
    f = _fold(s)
    return bool(re.search(r"(thang|t)\s*\d{1,2}\s*/\s*20\d{2}", f))

MONTH_VN_FULL_RE  = re.compile(r"(?:thang|tháng)\s*0?(\d{1,2})", re.I)
MONTH_VN_SHORT_RE = re.compile(r"(?:thg|t)\s*0?(\d{1,2})\b", re.I)
YEAR_RE           = re.compile(r"\b(20\d{2})\b")
QUARTER_RE        = re.compile(r"(?:quy|quý)\s*0?([1-4])\b", re.I)

def _is_this_month(raw: str) -> bool:
    f = _fold(raw)
    return ("thang nay" in f) or ("tháng này" in raw.lower()) or ("this month" in f)

def _is_this_quarter(raw: str) -> bool:
    f = _fold(raw)
    return ("quy nay" in f) or ("quý này" in raw.lower()) or ("this quarter" in f)

def _is_this_year(raw: str) -> bool:
    f = _fold(raw)
    return ("nam nay" in f) or ("năm nay" in raw.lower()) or ("this year" in f)

def _parse_month_year(raw: str) -> Tuple[Optional[int], Optional[int]]:
    now = NOW()
    m = MONTH_VN_FULL_RE.search(raw) or MONTH_VN_FULL_RE.search(_fold(raw)) \
        or MONTH_VN_SHORT_RE.search(raw) or MONTH_VN_SHORT_RE.search(_fold(raw))
    if not m:
        return None, None
    month = int(m.group(1))
    y = YEAR_RE.search(raw) or YEAR_RE.search(_fold(raw))
    year = int(y.group(1)) if y else now.year
    return month, year

def _parse_quarter_year(raw: str) -> Tuple[Optional[int], Optional[int]]:
    now = NOW()
    q = QUARTER_RE.search(raw) or QUARTER_RE.search(_fold(raw))
    if not q:
        return None, None
    quarter = int(q.group(1))
    y = YEAR_RE.search(raw) or YEAR_RE.search(_fold(raw))
    year = int(y.group(1)) if y else now.year
    return quarter, year

def _parse_period(raw: str) -> Dict[str, Any]:
    now = NOW()
    if _is_this_month(raw):
        return {"granularity": "month", "month": now.month, "year": now.year}
    if _is_this_quarter(raw):
        q = (now.month - 1)//3 + 1
        return {"granularity": "quarter", "quarter": q, "year": now.year}
    if _is_this_year(raw):
        return {"granularity": "year", "year": now.year}
    m, y = _parse_month_year(raw)
    if m:
        return {"granularity": "month", "month": m, "year": y or now.year}
    q, y = _parse_quarter_year(raw)
    if q:
        return {"granularity": "quarter", "quarter": q, "year": y or now.year}
    return {"granularity": "auto", "month": now.month, "year": now.year}

def _parse_multi_periods(raw: str) -> Optional[List[Dict[str, Any]]]:
    if _looks_like_month_year(raw):
        return None

    if not re.search(r"[\/|]", raw):
        return None

    toks = [t.strip() for t in re.split(r"[\/|]", raw) if t.strip()]
    periods = [_parse_period(tk) for tk in toks]

    valid = [p for p in periods if (p.get("granularity") in ("month","quarter","year"))]

    return valid if len(valid) >= 2 else None

def _parse_topn(tf: str) -> Optional[int]:
    m = re.search(r"\btop\s*(\d{1,3})\b", tf)
    if m:
        try: return int(m.group(1))
        except: return None
    if "top10" in tf: return 10
    if "top5"  in tf: return 5
    if "top20" in tf: return 20
    if ("cao nhat" in tf) or ("nhiu nhat" in tf) or ("nhiều nhất" in tf):
        return 10
    return None

def _extract_order_code(raw: str) -> Optional[str]:
    m = ORDER_CODE_RE.search(raw or "")
    return m.group(1).upper() if m else None

def _has_any(tf: str, kws: List[str]) -> bool:
    return any(k in tf for k in kws)

KW_DOANHTHU = ["doanh thu"]
KW_SALE     = ["nhan vien sale","nhan vien ban hang","theo nhan vien","nhan vien","staff","sale"]
KW_ROUTE    = ["tuyen duong","tuyen","route"]
KW_DEST     = ["diem den","destination","quoc gia","quốc gia","nuoc den","nước đến","country"]
KW_CUSTOMER = ["khach hang","khách hàng","customer"]
KW_PRODUCT  = ["san pham","sản phẩm","product","product_type"]
KW_WARE     = ["kho","warehouse","kho vn","kho nn","tong kho","trong kho"]
KW_FLIGHT   = ["chuyen bay","chuyến bay","flight","bay"]
KW_PAYMENT  = ["thanh toan","payment","qr","tien mat","tiền mặt","chuyen khoan","chuyển khoản","thu duoc","thu được", "ship"]
KW_FEEDBACK = ["feedback","danh gia","đánh giá","phan hoi","phản hồi"]
KW_DOMESTIC = ["domestic","noi dia","nội địa"]
KW_SLA      = ["thoi gian trung binh","thời gian trung bình","sla","lead time","processing time","xu ly","xử lý","van chuyen","vận chuyển","transit"]

ORDER_STATUS_MAP = {
    "cho xac nhan": "CHO_XAC_NHAN",
    "đang chờ xác nhận": "CHO_XAC_NHAN",
    "da xac nhan": "DA_XAC_NHAN",
    "đã xác nhận": "DA_XAC_NHAN",
    "cho thanh toan": "CHO_THANH_TOAN",
    "đang chờ thanh toán": "CHO_THANH_TOAN",
    "da thanh toan": "DA_THANH_TOAN",
    "đã thanh toán": "DA_THANH_TOAN",
    "da thanh toan ship": "DA_THANH_TOAN_SHIP",
    "đã thanh toán ship": "DA_THANH_TOAN_SHIP",
    "cho giao": "CHO_GIAO",
    "đang chờ giao": "CHO_GIAO",
    "da giao": "DA_GIAO",
    "đã giao": "DA_GIAO",
    "da huy": "DA_HUY",
    "đã huỷ": "DA_HUY",
    "đã hủy": "DA_HUY",
}

def _extract_status(raw: str) -> Optional[str]:
    tf = _fold(raw)
    for vn, code in ORDER_STATUS_MAP.items():
        if _fold(vn) in tf:
            return code
    if "huy" in tf or "hủy" in raw.lower():
        return "DA_HUY"
    return None

def _extract_payment_type(tf: str) -> Optional[str]:
    if "qr" in tf: return "QR"
    if ("tien mat" in tf) or ("ti?n m?t" in tf) or ("tiền mặt" in tf): return "CASH"
    if ("chuyen khoan" in tf) or ("chuy?n kho?n" in tf) or ("chuyển khoản" in tf): return "BANK"
    return None

def _extract_route_pair(raw: str) -> Optional[Dict[str, str]]:
    """
    Bắt các cụm 'indo - việt nam', 'japan→vn', 'JP -> VN', 'us > vn'...
    Return {'from': 'indo', 'to': 'viet nam'} dạng chữ thường (folded giữ dấu cách).
    """
    s = raw.strip()
    m = re.search(r"([a-zA-ZÀ-ỹ\s]+)\s*(?:-|→|->|>|to|đến|->)\s*([a-zA-ZÀ-ỹ\s]+)", s, flags=re.I)
    if not m:
        f = _fold(s)
        m = re.search(r"([a-z\s]+)\s*(?:\-|->|>|to|den|d?n|→)\s*([a-z\s]+)", f, flags=re.I)
        if not m:
            return None
        return {"from": m.group(1).strip(), "to": m.group(2).strip()}
    return {"from": m.group(1).strip(), "to": m.group(2).strip()}

def _has_order_word(raw: str, tf: str) -> bool:
    l = raw.lower()
    return any([
        "don" in tf, "don hang" in tf, "s? don" in tf, "so don" in tf, "đơn" in l, "đơn hàng" in l
    ])
def _mk_table(columns, rows):
    return {"columns": columns, "rows": rows}

def _mk_csv_bytes(columns, rows) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k) if isinstance(r, dict) else r[i] for i,k in enumerate(columns)} if not isinstance(r, dict) else r)
    return buf.getvalue().encode("utf-8-sig")

def normalize_query(text: str) -> Dict[str, Any]:
    """
    Trả về {intent, norm}
    Bao phủ phần lớn các câu trong danh sách của bạn; có thể nối trực tiếp với services.py.
    """
    raw = (text or "").strip()
    tf  = _fold(raw)
    now = NOW()

    code_only = _extract_order_code(raw)
    if code_only and raw.strip().upper() == code_only:
        return {"intent": "GET_ORDER_STATUS_BY_CODE", "norm": {"order_code": code_only}}
    
    if any(k in tf for k in [
        "cua ai","thuoc ai","cua ai?","thuoc ai?","owner la ai","owner la",
        "cua nhan vien nao","cua ai "
    ]):
        code = _extract_order_code(raw)
        return {"intent": "GET_ORDER_OWNER", "norm": {"order_code": code}}

    if ("trang thai" in tf) or ("status" in tf) or ("trạng thái" in raw.lower()):
        code = _extract_order_code(raw)
        if code:
            return {"intent": "GET_ORDER_STATUS_BY_CODE", "norm": {"order_code": code}}

    if _has_any(tf, KW_DOANHTHU):
        if _has_any(tf, KW_SALE):
            p = _parse_period(raw)
            return {"intent": "GET_REVENUE_BY_SALE", "norm": {"period": p}}
        if _has_any(tf, KW_ROUTE):
            p = _parse_period(raw)
            rp = _extract_route_pair(raw)
            return {"intent": "GET_REVENUE_BY_ROUTE", "norm": {"period": p, "route_pair": rp}}
        if _has_any(tf, KW_DEST):
            p = _parse_period(raw)
            return {"intent": "GET_REVENUE_BY_DESTINATION", "norm": {"period": p}}
        if ("bieu do" in tf) or ("bi?u d?" in tf) or ("biểu đồ" in raw.lower()):
            p = _parse_period(raw)
            dim = "route" if _has_any(tf, KW_ROUTE) else ("destination" if _has_any(tf, KW_DEST) else "date")
            return {"intent": "CHART_REVENUE_BY_DIM", "norm": {"period": p, "dimension": dim}}
        if ("du doan" in tf) or ("d? doan" in tf) or ("dự đoán" in raw.lower()):
            p = _parse_period(raw)
            return {"intent": "FORECAST_REVENUE_SEASONAL", "norm": {"period": p}}
        p = _parse_period(raw)
        multi = _parse_multi_periods(raw)
        if multi and len(multi) >= 2:
            return {"intent": "GET_REVENUE_MULTI", "norm": {"periods": multi}}
        return {"intent": "GET_REVENUE_TOTAL_BY_PERIOD", "norm": {"period": p}}

    if ("top" in tf) or ("cao nhat" in tf) or ("nhiu nhat" in tf) or ("nhiều nhất" in raw.lower()):
        if ("so don" in tf) or ("s? don" in tf) or ("số đơn" in raw.lower()):
            p = _parse_period(raw)
            tn = _parse_topn(tf) or 10
            return {"intent": "GET_TOP_STAFF_BY_ORDERS", "norm": {"period": p, "topn": tn}}

        topn = _parse_topn(tf) or 10
        if _has_any(tf, KW_CUSTOMER) and ("chi tieu" in tf or "chi tiêu" in raw.lower() or "spend" in tf or "tieu" in tf):
            p = _parse_period(raw)
            return {"intent": "GET_TOP_CUSTOMERS_BY_SPEND", "norm": {"period": p, "topn": topn}}
        if _has_any(tf, ["nhan vien","nhân viên","staff","sale"]):
            p = _parse_period(raw)
            return {"intent": "GET_TOP_STAFF_PERFORMANCE", "norm": {"period": p, "topn": topn}}
        p = _parse_period(raw)
        return {"intent": "GET_TOP_STAFF_BY_ORDERS", "norm": {"period": p, "topn": topn}}

    if (re.search(r"\bdanh\s*s[aá]ch\b", _fold(raw)) or "list" in _fold(raw)) and _has_order_word(raw, _fold(raw)):
        st2 = _extract_status(raw)
        p = _parse_period(raw)
        return {"intent": "LIST_ORDERS_BY_STATUS", "norm": {"period": p, "status": st2}}
    if (("tong so don" in tf) or ("t?ng s? don" in tf) or ("tong don" in tf) or ("t?ng ??n" in tf)
        or ( _has_order_word(raw, tf) and (_is_this_month(raw) or _is_this_quarter(raw) or _is_this_year(raw)
             or MONTH_VN_FULL_RE.search(raw) or MONTH_VN_SHORT_RE.search(raw) or QUARTER_RE.search(raw) or YEAR_RE.search(raw))
       )):
        p = _parse_period(raw)
        return {"intent": "GET_ORDER_COUNT_BY_PERIOD", "norm": {"period": p}}

    st = _extract_status(raw)
    if st and _has_order_word(raw, tf):
        p = _parse_period(raw)
        if any(k in tf for k in [
            "bao nhieu", "bao nhiêu", "tong so", "t?ng s?", "tong don", "t?ng ??n",
            "so luong", "s? l??ng", "dem", "đếm"
        ]):
            return {"intent": "GET_ORDER_COUNT_BY_STATUS", "norm": {"period": p, "status": st}}
        return {"intent": "LIST_ORDERS_BY_STATUS", "norm": {"period": p, "status": st}}

    if (("ty le" in tf) or ("t? le" in tf) or ("tỷ lệ" in raw.lower())) and (("huy" in tf) or ("hủy" in raw.lower())):
        p = _parse_period(raw)
        return {"intent": "GET_CASH_FLOW_DAILY", "norm": {"period": p}}

    if ("danh sach" in tf or "list" in tf) and _has_order_word(raw, tf):
        st2 = _extract_status(raw)
        p = _parse_period(raw)
        return {"intent": "LIST_ORDERS_BY_STATUS", "norm": {"period": p, "status": st2}}

    if (("lich su" in tf) or ("l?ch s?" in tf) or ("lịch sử" in raw.lower())) and (("process" in tf) or ("xu ly" in tf) or ("xử lý" in raw.lower())):
        p = _parse_period(raw)
        return {"intent": "ORDER_PROCESS_HISTORY", "norm": {"period": p}}

    if _has_any(tf, KW_SLA) and (("tu dat den giao" in tf) or ("t? d?t ??n giao" in tf) or ("từ đặt đến giao" in raw.lower())):
        p = _parse_period(raw)
        return {"intent": "AVG_FULFILLMENT_TIME", "norm": {"period": p}}

    if ("cham xu ly" in tf) or ("ch?m x? l?" in tf) or ("chậm xử lý" in raw.lower()):
        p = _parse_period(raw)
        return {"intent": "SLOW_ORDERS_COUNT", "norm": {"period": p}}

    if (("thong ke" in tf) or ("th?ng k?" in tf) or ("thống kê" in raw.lower())) and (("trang thai" in tf) or ("trạng thái" in raw.lower())) and _has_order_word(raw, tf):
        p = _parse_period(raw)
        return {"intent": "DASHBOARD_ORDER_STATUS", "norm": {"period": p}}

    if _has_any(tf, KW_FEEDBACK) and _has_any(tf, KW_CUSTOMER) and (("trung binh" in tf) or ("trung b?nh" in tf) or ("trung bình" in raw.lower())):
        p = _parse_period(raw)
        return {"intent": "AVG_RATING_BY_CUSTOMER", "norm": {"period": p}}

    m_thr = re.search(r"(?:rating|danh gia|đánh giá)\s*[<≤]\s*(\d(?:\.\d+)?)", raw, flags=re.I)
    if m_thr:
        try:
            thr = float(m_thr.group(1))
            p = _parse_period(raw)
            return {"intent": "NEGATIVE_FEEDBACK_CUSTOMERS", "norm": {"period": p, "threshold": thr}}
        except:
            pass

    if _has_any(tf, KW_FEEDBACK) and (_is_this_month(raw) or MONTH_VN_FULL_RE.search(raw) or MONTH_VN_SHORT_RE.search(raw) or ("thang" in tf) or ("tháng" in raw.lower())):
        p = _parse_period(raw)
        return {"intent": "FEEDBACK_COUNT_MONTH", "norm": {"period": p}}

    if _has_any(tf, KW_FEEDBACK) and (("thoi gian trung binh" in tf) or ("thời gian trung bình" in raw.lower())):
        p = _parse_period(raw)
        return {"intent": "AVG_RESPONSE_TIME", "norm": {"period": p}}

    if (("ty le" in tf) or ("tỷ lệ" in raw.lower())) and (("khach hang quay lai" in tf) or ("khách hàng quay lại" in raw.lower()) or ("repeat" in tf)):
        p = _parse_period(raw)
        return {"intent": "REPEAT_CUSTOMER_RATE", "norm": {"period": p}}

    if _has_any(tf, KW_FEEDBACK) and (("tong hop" in tf) or ("t?ng h?p" in tf) or ("tổng hợp" in raw.lower())):
        p = _parse_period(raw)
        return {"intent": "FEEDBACK_OVERVIEW", "norm": {"period": p}}

    if (("trung binh gia tri don hang" in tf) or ("trung b?nh gi? tr? ??n h?ng" in tf) or ("trung bình giá trị đơn hàng" in raw.lower())) and _has_any(tf, KW_CUSTOMER):
        p = _parse_period(raw)
        return {"intent": "AOV_BY_CUSTOMER", "norm": {"period": p}}

    if (("tong tien" in tf) or ("t?ng ti?n" in tf) or ("tong thu" in tf) or ("t?ng thu" in tf) or ("thu duoc" in tf) or ("thu được" in tf)) and _has_any(tf, KW_PAYMENT):
        p = _parse_period(raw)
        return {"intent": "TOTAL_COLLECTED_IN_PERIOD", "norm": {"period": p}}

    if (("tong tien" in tf) or ("t?ng ti?n" in tf)) and (("con no" in tf) or ("còn nợ" in raw.lower()) or ("chua thanh toan" in tf) or ("chưa thanh toán" in raw.lower())):
        p = _parse_period(raw)
        return {"intent": "TOTAL_OUTSTANDING_IN_PERIOD", "norm": {"period": p}}

    if (("tong tien" in tf) or ("t?ng ti?n" in tf)) and (_has_any(tf, KW_PAYMENT) or ("theo tung loai" in tf) or ("theo tung loai thanh toan" in tf)):
        p = _parse_period(raw)
        pm = _extract_payment_type(tf)
        return {"intent": "TOTAL_BY_PAYMENT_METHOD", "norm": {"period": p, "payment_type": pm}}

    if "thanh toan ship" in tf:
        p = _parse_period(raw)
        return {"intent": "SHIP_PAYMENT_REPORT", "norm": {"period": p}}

    if (("so luong thanh toan" in tf) or ("s? l??ng thanh toan" in tf)) and (("loi" in tf) or ("l?i" in tf) or ("dang cho" in tf) or ("đang chờ" in raw.lower()) or ("cho thanh toan" in tf)):
        p = _parse_period(raw)
        status = "CHO_THANH_TOAN" if (("dang cho" in tf) or ("đang chờ" in raw.lower()) or ("cho thanh toan" in tf)) else "LOI"
        return {"intent": "PAYMENT_COUNT_BY_STATUS", "norm": {"period": p, "status": status}}

    if ("tong chi phi mua hang" in tf) or ("t?ng chi ph? mua h?ng" in tf) or ("tổng chi phí mua hàng" in raw.lower()):
        p = _parse_period(raw)
        if _has_any(tf, KW_ROUTE) or _has_any(tf, ["quoc gia","quốc gia","country"]):
            dim = "route" if _has_any(tf, KW_ROUTE) else "country"
            rp = _extract_route_pair(raw) if dim == "route" else None
            return {"intent": "PURCHASE_COST_BY_DIMENSION", "norm": {"period": p, "dimension": dim, "route_pair": rp}}
        return {"intent": "PURCHASE_COST_BY_MONTH", "norm": {"period": p}}

    if (("so sanh" in tf) or ("so sánh" in raw.lower())) and _has_any(tf, ["doanh thu"]) and _has_any(tf, ["chi phi","chi phí","cost"]):
        p = _parse_period(raw)
        return {"intent": "COMPARE_REVENUE_COST_OVER_TIME", "norm": {"period": p}}

    if _has_any(tf, ["dong tien","cash flow","cashflow","d?ng ti?n"]):
        p = _parse_period(raw)
        return {"intent": "GET_CASH_FLOW_DAILY", "norm": {"period": p}}

    if (("tong tien" in tf) or ("t?ng ti?n" in tf) or ("thu duoc" in tf) or ("thu được" in tf)) and _has_any(tf, KW_SALE):
        p = _parse_period(raw)
        return {"intent": "TOTAL_COLLECTED_BY_SALE", "norm": {"period": p}}

    if (("dang cho mua" in tf) or ("đang chờ mua" in raw.lower()) or ("cho mua" in tf)):
        p = _parse_period(raw)
        return {"intent": "LIST_WAIT_TO_BUY", "norm": {"period": p}}

    if _has_any(tf, ["nhan vien mua hang","nhân viên mua hàng","purchaser"]) and (("nhieu don nhat" in tf) or ("nhiều đơn nhất" in raw.lower())):
        p = _parse_period(raw)
        return {"intent": "TOP_PURCHASERS_BY_ORDER_COUNT", "norm": {"period": p, "topn": 10}}

    if _has_any(tf, KW_PRODUCT) and (("phi mua hang cao nhat" in tf) or ("phí mua hàng cao nhất" in raw.lower())):
        p = _parse_period(raw)
        return {"intent": "PRODUCT_HIGHEST_PURCHASE_FEE", "norm": {"period": p}}

    if (("mua thanh cong" in tf) or ("mua thành công" in raw.lower())) and (("ty le" in tf) or ("tỷ lệ" in raw.lower())):
        p = _parse_period(raw)
        return {"intent": "PURCHASE_SUCCESS_RATE", "norm": {"period": p}}

    if (("thoi gian trung binh hoan tat don mua" in tf) or ("thời gian trung bình hoàn tất đơn mua" in raw.lower())):
        p = _parse_period(raw)
        return {"intent": "AVG_PURCHASE_COMPLETION_TIME", "norm": {"period": p}}

    if (("thong ke so don da hoan tat mua hang" in tf) or ("thống kê số đơn đã hoàn tất mua hàng" in raw.lower())):
        p = _parse_period(raw)
        return {"intent": "PURCHASE_COMPLETED_ORDERS_COUNT", "norm": {"period": p}}

    if _has_any(tf, KW_PRODUCT) and (("thuong xuyen loi" in tf) or ("thường xuyên lỗi" in raw.lower()) or ("bi huy" in tf) or ("bị hủy" in raw.lower())):
        p = _parse_period(raw)
        return {"intent": "PRODUCT_LINK_FAILURES", "norm": {"period": p}}

    if (("tong so kien hang" in tf) or ("t?ng s? ki?n h?ng" in tf) or ("tổng số kiện hàng" in raw.lower())) and (_has_any(tf, KW_WARE) or ("trong tung kho" in tf) or ("trong từng kho" in raw.lower())):
        p = _parse_period(raw)
        return {"intent": "INVENTORY_PARCELS_BY_WAREHOUSE", "norm": {"period": p}}

    if (("trong luong trung binh" in tf) or ("trọng lượng trung bình" in raw.lower())) and _has_any(tf, KW_WARE):
        p = _parse_period(raw)
        return {"intent": "AVG_WEIGHT_IN_STOCK", "norm": {"period": p}}

    if (("tong hang nhap kho trong thang" in tf) or ("tổng hàng nhập kho trong tháng" in raw.lower())):
        p = _parse_period(raw)
        return {"intent": "TOTAL_IMPORTED_THIS_MONTH", "norm": {"period": p}}

    if (("cho tra lai" in tf) or ("chờ trả lại" in raw.lower())):
        p = _parse_period(raw)
        return {"intent": "RETURN_PENDING_COUNT", "norm": {"period": p}}

    if (("dang cho dong goi" in tf) or ("đang chờ đóng gói" in raw.lower())):
        p = _parse_period(raw)
        return {"intent": "LIST_PACKING_PENDING", "norm": {"period": p}}

    if (("xu ly nhieu nhat" in tf) or ("xử lý nhiều nhất" in raw.lower())) and _has_any(tf, KW_WARE):
        p = _parse_period(raw)
        return {"intent": "WAREHOUSE_STAFF_ACTIVITY_TOP", "norm": {"period": p, "topn": 10}}

    if (("roi kho nuoc ngoai" in tf) or ("rời kho nước ngoài" in raw.lower())):
        p = _parse_period(raw)
        return {"intent": "FOREIGN_WAREHOUSE_DEPARTED_STATS", "norm": {"period": p}}

    if (("tong so kien hang" in tf) or ("tổng số kiện hàng" in raw.lower())) and (("dia diem" in tf) or ("location" in tf)):
        p = _parse_period(raw)
        return {"intent": "PARCELS_PER_LOCATION", "norm": {"period": p}}

    if (("lich su di chuyen hang" in tf) or ("lịch sử di chuyển hàng" in raw.lower())) and _has_any(tf, KW_DOMESTIC):
        p = _parse_period(raw)
        return {"intent": "DOMESTIC_MOVEMENT_HISTORY", "norm": {"period": p}}

    if (("da nhap kho vn" in tf) or ("đã nhập kho vn" in raw.lower()) or ("nhap kho vn" in tf)):
        p = _parse_period(raw)
        return {"intent": "IMPORTED_VN_THIS_PERIOD", "norm": {"period": p}}

    if _has_any(tf, KW_FLIGHT) and (("dang cho bay" in tf) or ("đang chờ bay" in raw.lower())):
        p = _parse_period(raw)
        return {"intent": "FLIGHT_WAITING_COUNT", "norm": {"period": p}}

    if _has_any(tf, KW_FLIGHT) and (("ty le hoan tat" in tf) or ("tỷ lệ hoàn tất" in raw.lower())):
        p = _parse_period(raw)
        return {"intent": "FLIGHT_COMPLETION_RATE", "norm": {"period": p}}

    if (("thong ke theo trang thai" in tf) or ("thống kê theo trạng thái" in raw.lower())) and _has_any(tf, KW_FLIGHT):
        p = _parse_period(raw)
        return {"intent": "FLIGHT_STATUS_STATS", "norm": {"period": p}}

    if (("tong so kien hang" in tf) or ("tổng số kiện hàng" in raw.lower())) and _has_any(tf, KW_FLIGHT):
        p = _parse_period(raw)
        return {"intent": "PARCELS_PER_FLIGHT", "norm": {"period": p}}

    if (("tren duong van chuyen" in tf) or ("trên đường vận chuyển" in raw.lower())):
        p = _parse_period(raw)
        return {"intent": "IN_TRANSIT_PARCELS_COUNT", "norm": {"period": p}}

    if (("da giao thanh cong" in tf) or ("đã giao thành công" in raw.lower())) and (_is_this_month(raw) or MONTH_VN_FULL_RE.search(raw) or MONTH_VN_SHORT_RE.search(raw) or ("trong thang" in tf) or ("trong tháng" in raw.lower())):
        p = _parse_period(raw)
        return {"intent": "DELIVERED_SUCCESS_THIS_PERIOD", "norm": {"period": p}}

    if (("tre chuyen" in tf) or ("tr? chuy?n" in tf) or ("trễ chuyến" in raw.lower()) or ("loi van chuyen" in tf) or ("lỗi vận chuyển" in raw.lower())):
        p = _parse_period(raw)
        return {"intent": "LATE_OR_ERROR_SHIPMENTS_COUNT", "norm": {"period": p}}

    if _has_any(tf, KW_SLA) and (("tu kho nuoc ngoai den vn" in tf) or ("từ kho nước ngoài đến vn" in raw.lower())):
        p = _parse_period(raw)
        return {"intent": "AVG_TRANSIT_TIME_FOREIGN_TO_VN", "norm": {"period": p}}

    if (("tong so don hang duoc van chuyen boi tung nhan vien" in tf) or ("tổng số đơn hàng được vận chuyển bởi từng nhân viên" in raw.lower())):
        p = _parse_period(raw)
        return {"intent": "ORDERS_TRANSPORTED_BY_STAFF", "norm": {"period": p}}

    if ("tong so tai khoan dang hoat dong" in tf) or ("tổng số tài khoản đang hoạt động" in raw.lower()):
        return {"intent": "ACTIVE_ACCOUNTS_COUNT", "norm": {}}

    if ("phan bo vai tro" in tf) or ("phân bổ vai trò" in raw.lower()):
        return {"intent": "ACCOUNT_ROLE_DISTRIBUTION", "norm": {}}

    if (("so luong nhan vien hoat dong" in tf) or ("số lượng nhân viên hoạt động" in raw.lower())) and _has_any(tf, KW_WARE):
        return {"intent": "ACTIVE_STAFF_BY_WAREHOUSE", "norm": {}}

    if (("tong quan he thong" in tf) or ("tổng quan hệ thống" in raw.lower())):
        p = _parse_period(raw)
        return {"intent": "SYSTEM_OVERVIEW", "norm": {"period": p}}

    if (("so luong khach hang moi" in tf) or ("số lượng khách hàng mới" in raw.lower())):
        p = _parse_period(raw)
        return {"intent": "NEW_CUSTOMERS_THIS_PERIOD", "norm": {"period": p}}

    if (("bieu do" in tf) or ("bi?u d?" in tf) or ("biểu đồ" in raw.lower())) and _has_any(tf, KW_DOANHTHU) and (_has_any(tf, KW_ROUTE) or _has_any(tf, KW_SALE) or _has_any(tf, KW_DEST)):
        p = _parse_period(raw)
        if _has_any(tf, KW_ROUTE): dim = "route"
        elif _has_any(tf, KW_DEST): dim = "destination"
        else: dim = "staff"
        rp = _extract_route_pair(raw) if dim == "route" else None
        return {"intent": "CHART_REVENUE_BY_DIM", "norm": {"period": p, "dimension": dim, "route_pair": rp}}

    if (("phan tich hanh vi" in tf) or ("phân tích hành vi" in raw.lower())) and _has_any(tf, KW_CUSTOMER):
        p = _parse_period(raw)
        return {"intent": "CUSTOMER_BEHAVIOR_ANALYSIS", "norm": {"period": p}}
    if ("vip" in tf) and _has_any(tf, KW_CUSTOMER):
        p = _parse_period(raw)
        return {"intent": "VIP_CUSTOMER_ANALYSIS", "norm": {"period": p}}
    if (("phan tich san pham" in tf) or ("phân tích sản phẩm" in raw.lower())) and (_has_any(tf, KW_PRODUCT) or ("product_type" in tf)):
        p = _parse_period(raw)
        return {"intent": "PRODUCT_TYPE_COMPLETION_ANALYSIS", "norm": {"period": p}}

    p = _parse_period(raw)
    if p.get("granularity") in ("month","quarter","year"):
        return {"intent": "FOLLOWUP_SET_PERIOD", "norm": p}

    return {
        "intent": "SMALLTALK",
        "norm": {}
    }
