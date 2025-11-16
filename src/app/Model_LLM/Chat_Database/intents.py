
import re
from typing import Dict, Any, Tuple

MONTH_REGEX = re.compile(r"tháng\s*(\d{1,2})(?:\s*/\s*(20\d{2}))?", re.IGNORECASE)

def classify(user_text: str) -> Tuple[str, Dict[str, Any]]:
    s = (user_text or "").strip().lower()

    if "doanh thu" in s and ("tháng này" in s or "thang nay" in s):
        return "revenue_this_month", {}
    if "doanh thu" in s and ("tháng trước" in s or "thang truoc" in s):
        return "revenue_prev_month", {}
    if "doanh thu" in s and "theo ngày" in s and ("tháng này" in s or "thang nay" in s):
        return "revenue_by_day_this_month", {}

    if "doanh thu" in s and "tháng" in s:
        m = MONTH_REGEX.search(s)
        if m:
            month = int(m.group(1))
            year = int(m.group(2)) if m.group(2) else None
            return "revenue_monthN", {"month": month, "year": year}

    if "top nhân viên" in s and "doanh thu" in s:
        return "top_staff_by_revenue_this_month", {}

    if "doanh thu theo tuyến" in s:
        return "revenue_by_route_this_month", {}

    if "doanh thu theo điểm đến" in s or "doanh thu theo destination" in s:
        return "revenue_by_destination_this_month", {}

    if "số đơn" in s and "trạng thái" in s and ("tháng này" in s or "thang nay" in s):
        return "orders_count_by_status_this_month", {}

    if "hàng tồn kho theo trạng thái" in s:
        return "warehouse_inventory_by_status", {}

    if "trọng lượng trung bình" in s and ("hàng tồn" in s or "kho" in s):
        return "avg_weight_in_stock", {}

    # tra cứu đơn theo mã (OD..., ORD..., VN-..., etc.); để CLI có thể bắt khi có mã trong câu
    if "đơn" in s or "don" in s or "mã" in s or "ma " in s:
        return "order_lookup", {}

    if any(k in s for k in ["thông tin","thong tin","profile","hồ sơ","ho so"]):
        return "person_profile", {}

    return "unknown", {}