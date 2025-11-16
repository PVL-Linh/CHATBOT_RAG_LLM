# services.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import datetime as dt, json
from typing import Dict, Any, List, Tuple, Optional
import api_client as ac
from app.config.config_supabase import VN_TZ, CURRENCY
from .intents import _detect_relative_period_key, normalize_query
from api_client import (
    fetch_payment_range, sum_revenue_from_payments, group_revenue_by_staff,
    fetch_staff_by_id, fetch_account_by_id, fetch_orders_range, fetch_order_by_code, group_orders_count_by_staff,
    agg_cashflow_daily, agg_revenue_by_route, agg_revenue_by_destination, agg_aov_by_customer,
    agg_order_count_by_status, agg_cancel_rate, agg_avg_fulfillment_time, agg_feedback_avg_by_customer,
    agg_feedback_negative_customers, agg_feedback_count, agg_repeat_customer_rate, agg_outstanding_amount,
    agg_ship_payment_report, agg_payment_count_by_status, list_orders_by_status, list_wait_to_buy,
    agg_inventory_by_warehouse, agg_avg_weight_in_stock, agg_imported_vn_in_period, agg_flights_waiting_count,
    agg_flight_completion_rate, agg_avg_transit_time_foreign_to_vn, sum_amount_by_payment_type
)
from app.Model_LLM.Query_Supabase.sql3 import init_db
import inspect, re
from api_client import group_orders_count_by_staff


def _resolve_order_codes_for_payments(pays: list[dict]) -> dict[str, list[str]]:
    if not pays:
        return {}
    # thu thập id → code
    order_ids = []
    for p in pays:
        oid = p.get("order_id") or p.get("orderId") or p.get("oid")
        if oid is not None:
            try: order_ids.append(int(oid))
            except: pass
    order_ids = list({i for i in order_ids if isinstance(i, int)})

    id2code = {}
    if order_ids:
        try:
            if hasattr(ac, "map_order_ids_to_codes"):
                id2code = {int(k): str(v) for k, v in (ac.map_order_ids_to_codes(order_ids) or {}).items() if v}
            elif hasattr(ac, "fetch_orders_by_ids"):
                rows = ac.fetch_orders_by_ids(order_ids) or []
                for r in rows:
                    oid = r.get("id")
                    code = r.get("order_code") or r.get("code") or r.get("order_no")
                    if oid is not None and code:
                        id2code[int(oid)] = str(code)
        except Exception:
            id2code = {}

    out: dict[str, list[str]] = {}
    for p in pays:
        # ngày
        dt_raw = p.get("paid_at") or p.get("created_at") or p.get("date")
        day = None
        try:
            d = dt.datetime.fromisoformat(str(dt_raw)); day = f"{d.year:04d}-{d.month:02d}-{d.day:02d}"
        except Exception:
            if isinstance(dt_raw, str) and len(dt_raw) >= 10 and dt_raw[4] == "-" and dt_raw[7] == "-":
                day = dt_raw[:10]
        if not day:
            continue

        # code ưu tiên: field → map id → regex note
        code = p.get("order_code") or p.get("orderNo") or p.get("code")
        if not code:
            oid = p.get("order_id") or p.get("orderId") or p.get("oid")
            try:
                if oid is not None and int(oid) in id2code:
                    code = id2code[int(oid)]
            except Exception:
                pass
        if not code:
            try:
                if hasattr(ac, "extract_order_code_from_text"):
                    code = ac.extract_order_code_from_text(p.get("description") or p.get("note") or "")
                else:
                    import re as _re
                    _FALLBACK_RE = _re.compile(r"\b(ORD[A-Z0-9\-]*|[A-Z]{2,5}[A-Z0-9\-]*\d+)\b", _re.IGNORECASE)
                    m = _FALLBACK_RE.search((p.get("description") or p.get("note") or "") or "")
                    code = (m.group(1).upper() if m else None)
            except Exception:
                code = None

        if code:
            out.setdefault(day, [])
            if code.upper() not in out[day]:
                out[day].append(code.upper())

    return out


def _call_group_orders_count_by_staff(dt_from: str, dt_to: str):
    """
    Trả về mapping {staff_id:int -> count:int} bất kể chữ ký api_client.group_orders_count_by_staff là gì.
    Thử theo thứ tự: (dt_from, dt_to) → {"dt_from","dt_to"} → (dt_from, dt_to) tuple → keyword start/end → date_from/date_to → ().
    """
    try:
        sig = inspect.signature(group_orders_count_by_staff)
        n = len(sig.parameters)
    except Exception:
        n = 2  # mặc định

    # thử nhiều biến thể
    for call in (
        lambda: group_orders_count_by_staff(dt_from, dt_to),
        lambda: group_orders_count_by_staff({"dt_from": dt_from, "dt_to": dt_to}),
        lambda: group_orders_count_by_staff((dt_from, dt_to)),
        lambda: group_orders_count_by_staff(start=dt_from, end=dt_to),
        lambda: group_orders_count_by_staff(date_from=dt_from, date_to=dt_to),
        lambda: group_orders_count_by_staff(dt_from),             # một tham số
        lambda: group_orders_count_by_staff(),                    # không tham số
    ):
        try:
            res = call()
            if res is not None:
                return res
        except TypeError:
            continue
        except Exception:
            continue
    return None

def _normalize_staff_count(res) -> dict[int, int]:
    """
    Chuẩn hoá kết quả về dict {staff_id:int: count:int}.
    Hỗ trợ: dict thô, list[dict], list[tuple], v.v.
    """
    out = {}
    if isinstance(res, dict):
        for k, v in res.items():
            try:
                out[int(k)] = int(v)
            except Exception:
                pass
        return out
    if isinstance(res, (list, tuple)):
        for it in res:
            if isinstance(it, dict):
                sid = it.get("staff_id") or it.get("staff") or it.get("id")
                cnt = it.get("count") or it.get("orders") or it.get("total") or it.get("num") or 0
                if sid is not None:
                    try:
                        out[int(sid)] = int(cnt)
                    except Exception:
                        pass
            elif isinstance(it, (list, tuple)) and len(it) >= 2:
                try:
                    out[int(it[0])] = int(it[1])
                except Exception:
                    pass
    return out

# ========================= time helpers =========================
def _first_of_month(y: int, m: int) -> dt.datetime:
    return dt.datetime(y, m, 1, 0, 0, 0, tzinfo=VN_TZ)

def _month_range_exclusive(y: int, m: int) -> Tuple[str, str]:
    s = _first_of_month(y, m)
    e = _first_of_month(y + 1, 1) if m == 12 else _first_of_month(y, m + 1)
    return s.isoformat(), e.isoformat()

def _month_range_inclusive(y: int, m: int) -> Tuple[str, str]:
    s, e_ex = _month_range_exclusive(y, m)
    e = (dt.datetime.fromisoformat(e_ex) - dt.timedelta(microseconds=1)).isoformat()
    return s, e

def _quarter_range(y: int, q: int, inclusive=True) -> Tuple[str, str]:
    start_month = (q - 1) * 3 + 1
    s = dt.datetime(y, start_month, 1, tzinfo=VN_TZ)
    if q == 4:
        e_ex = dt.datetime(y + 1, 1, 1, tzinfo=VN_TZ)
    else:
        e_ex = dt.datetime(y, start_month + 3, 1, tzinfo=VN_TZ)
    if inclusive:
        e = (e_ex - dt.timedelta(microseconds=1))
        return s.isoformat(), e.isoformat()
    return s.isoformat(), e_ex.isoformat()

def _year_range(y: int, inclusive=True) -> Tuple[str, str]:
    s = dt.datetime(y, 1, 1, tzinfo=VN_TZ)
    e_ex = dt.datetime(y + 1, 1, 1, tzinfo=VN_TZ)
    if inclusive:
        e = (e_ex - dt.timedelta(microseconds=1))
        return s.isoformat(), e.isoformat()
    return s.isoformat(), e_ex.isoformat()

def _period_to_range(period: Dict[str, Any], inclusive_for_month: bool = True) -> Tuple[str, str]:
    gran = (period or {}).get("granularity") or "auto"
    now = dt.datetime.now(VN_TZ)
    if gran == "month":
        y = int(period.get("year") or now.year)
        m = int(period.get("month") or now.month)
        return _month_range_inclusive(y, m) if inclusive_for_month else _month_range_exclusive(y, m)
    if gran == "quarter":
        y = int(period.get("year") or now.year)
        q = int(period.get("quarter") or ((now.month - 1)//3 + 1))
        return _quarter_range(y, q, inclusive=True)
    if gran == "year":
        y = int(period.get("year") or now.year)
        return _year_range(y, inclusive=True)
    return _month_range_inclusive(now.year, now.month)

def _fmt_money(v: float) -> str:
    return f"{v:,.0f}₫" if CURRENCY == "VND" else f"{v:,.2f} {CURRENCY}"

def _fmt_period_label(period: Dict[str, Any]) -> str:
    gran = (period or {}).get("granularity") or "auto"
    if gran == "month": return f"tháng {int(period.get('month'))}/{int(period.get('year'))}"
    if gran == "quarter": return f"quý {int(period.get('quarter'))}/{int(period.get('year'))}"
    if gran == "year": return f"năm {int(period.get('year'))}"
    now = dt.datetime.now(VN_TZ); return f"tháng {now.month}/{now.year}"

# ========================= session KV (SQLite) =========================
def _kv_imports():
    from app.Model_LLM.Query_Supabase.sql3 import (
        save_message, set_last_order_code, get_last_order_code,
        set_last_period, get_last_period, set_last_topic, get_last_topic,
        set_last_top, get_last_top
    )
    return {
        "save_message": save_message,
        "set_last_order_code": set_last_order_code,
        "get_last_order_code": get_last_order_code,
        "set_last_period": set_last_period,
        "get_last_period": get_last_period,
        "set_last_topic": set_last_topic,
        "get_last_topic": get_last_topic,
        "set_last_top": set_last_top,
        "get_last_top": get_last_top,
    }

# ========================= generic helpers =========================
def _ok_reply(text: str, table: Optional[dict]=None, chart: Optional[dict]=None, meta: Optional[dict]=None) -> Dict[str, Any]:
    out = {"reply": text}
    if table: out["table"] = table
    if chart: out["chart"] = chart
    if meta:  out["meta"]  = meta
    return out


# ========================= handlers (mới) =========================
def handle_cashflow_daily(period: Dict[str, Any]) -> Dict[str, Any]:
    dt_from, dt_to = _period_to_range(period, inclusive_for_month=True)
    series = agg_cashflow_daily(dt_from, dt_to)
    if not series:
        return _ok_reply(f"Không có dòng tiền trong {_fmt_period_label(period)}.")
    # chart + csv
    chart = {"kind": "line", "x": [d for d,_ in series], "y": [v for _,v in series], "title": "Cash flow theo ngày"}
    table = {"filename": "cashflow_daily.csv", "data": {"columns": ["date","amount"], "rows": series}}
    total = sum(v for _,v in series)
    return _ok_reply(f"💵 Dòng tiền {_fmt_period_label(period)}: **{_fmt_money(total)}**.", table, chart)

def handle_revenue_by_route(period: Dict[str, Any]) -> Dict[str, Any]:
    dt_from, dt_to = _period_to_range(period, inclusive_for_month=True)
    rows = agg_revenue_by_route(dt_from, dt_to)
    if not rows:
        return _ok_reply(f"Không có doanh thu theo tuyến trong {_fmt_period_label(period)}.")
    lines = [f"- {k}: {_fmt_money(v)}" for k,v in rows]
    table = {"filename": "revenue_by_route.csv", "data": {"columns": ["route","revenue"], "rows": rows}}
    return _ok_reply("🚚 **Doanh thu theo tuyến**:\n" + "\n".join(lines), table, None)

def handle_revenue_by_destination(period: Dict[str, Any]) -> Dict[str, Any]:
    dt_from, dt_to = _period_to_range(period, inclusive_for_month=True)
    rows = agg_revenue_by_destination(dt_from, dt_to)
    if not rows:
        return _ok_reply(f"Không có doanh thu theo điểm đến trong {_fmt_period_label(period)}.")
    lines = [f"- {k}: {_fmt_money(v)}" for k,v in rows]
    table = {"filename": "revenue_by_destination.csv", "data": {"columns": ["destination","revenue"], "rows": rows}}
    return _ok_reply("🎯 **Doanh thu theo điểm đến**:\n" + "\n".join(lines), table, None)

def handle_aov_by_customer(period: Dict[str, Any]) -> Dict[str, Any]:
    dt_from, dt_to = _period_to_range(period, inclusive_for_month=True)
    rows = agg_aov_by_customer(dt_from, dt_to)
    if not rows:
        return _ok_reply(f"Không có dữ liệu để tính AOV trong {_fmt_period_label(period)}.")
    # rows: (name, aov, count)
    top = rows[:10]
    lines = [f"- {name}: AOV {_fmt_money(aov)} · {cnt} đơn" for name,aov,cnt in top]
    table = {"filename": "aov_by_customer.csv", "data": {"columns": ["customer","aov","orders"], "rows": rows}}
    return _ok_reply("📦 **AOV theo khách hàng (Top 10)**:\n" + "\n".join(lines), table, None)

def _status_vn_label(code: str) -> str:
    m = {
        "CHO_XAC_NHAN": "chờ xác nhận",
        "DA_XAC_NHAN": "đã xác nhận",
        "CHO_THANH_TOAN": "chờ thanh toán",
        "DA_THANH_TOAN": "đã thanh toán",
        "DA_THANH_TOAN_SHIP": "đã thanh toán ship",
        "CHO_GIAO": "chờ giao",
        "DA_GIAO": "đã giao",
        "DA_HUY": "đã hủy",
    }
    return m.get((code or "").upper(), code or "")

def handle_order_count_by_status(period: Dict[str, Any], status: str) -> Dict[str, Any]:
    dt_from, dt_to = _period_to_range(period, inclusive_for_month=False)
    label_vn = _status_vn_label(status)

    rows = None
    # 1) Ưu tiên API trả sẵn danh sách theo trạng thái (nếu có)
    try:
        rows = list_orders_by_status(dt_from, dt_to, status)  # list[dict] có order_code/created_at/updated_at
    except Exception:
        rows = None

    # 2) Fallback: tự lọc từ toàn bộ orders nếu API trên không có/không chuẩn
    if rows is None:
        try:
            all_orders = fetch_orders_range(dt_from, dt_to) or []
            rows = [od for od in all_orders if (od.get("status") or "").upper() == (status or "").upper()]
        except Exception:
            rows = []

    total = len(rows)

    # Nhóm theo ngày + gom mã
    from collections import defaultdict
    import datetime as _dt

    def _to_date(s: str) -> str:
        try:
            d = _dt.datetime.fromisoformat(s); return f"{d.year:04d}-{d.month:02d}-{d.day:02d}"
        except Exception:
            if len(s) == 10 and s[4] == '-' and s[7] == '-':  # đã YYYY-MM-DD
                return s
            return ""

    daily_count = defaultdict(int)
    daily_codes = defaultdict(list)

    for od in rows:
        ts = od.get("created_at") or od.get("updated_at") or ""
        day = _to_date(ts)
        if not day:
            continue
        daily_count[day] += 1
        code = (od.get("order_code") or "").strip()
        if code:
            daily_codes[day].append(code)

    series3 = []
    for d in sorted(daily_count.keys()):
        codes_csv = ", ".join(sorted(set(daily_codes[d]))) if daily_codes.get(d) else ""
        series3.append((d, int(daily_count[d]), codes_csv))

    # Compose reply
    if series3:
        lines = "\n".join(
            f"- {d}: {c} đơn" + (f" · mã: {codes}" if codes else "")
            for d, c, codes in series3
        )
        breakdown = f"\n\nPhân rã theo ngày ({len(series3)} dòng):\n{lines}"
        table = {
            "filename": f"orders_{status.lower()}_daily.csv",
            "data": {"columns": ["date", "count", "order_codes"], "rows": series3}
        }
    else:
        breakdown = ""
        table = None

    label = _fmt_period_label(period)
    reply = (
        f"📊 **Số đơn {label_vn or status} {label}**: **{total}**\n"
        f"Khoảng: `{dt_from}` → `{dt_to}`{breakdown}"
    )
    # Có daily → tránh Gemini chỉnh sửa dãy dữ liệu
    return _ok_reply(reply, table, None, meta={"no_summarize": bool(series3)})



def handle_cancel_rate(period: Dict[str, Any]) -> Dict[str, Any]:
    dt_from, dt_to = _period_to_range(period, inclusive_for_month=False)
    total, canceled, rate = agg_cancel_rate(dt_from, dt_to)
    return _ok_reply(f"❌ Tỷ lệ hủy: **{rate:.2f}%** ({canceled}/{total}).")

def handle_avg_fulfillment_time(period: Dict[str, Any]) -> Dict[str, Any]:
    dt_from, dt_to = _period_to_range(period, inclusive_for_month=True)
    sec = agg_avg_fulfillment_time(dt_from, dt_to)
    if sec is None:
        return _ok_reply(f"Không đủ log để tính thời gian xử lý đặt→giao trong {_fmt_period_label(period)}.")
    hours = sec/3600.0
    return _ok_reply(f"⏱️ Thời gian trung bình đặt→giao: **{hours:.2f} giờ**.")

def handle_feedback_metrics(period: Dict[str, Any]) -> Dict[str, Any]:
    dt_from, dt_to = _period_to_range(period, inclusive_for_month=True)
    rows = agg_feedback_avg_by_customer(dt_from, dt_to)
    if not rows:
        return _ok_reply(f"Không có feedback trong {_fmt_period_label(period)}.")
    top = rows[:10]
    lines = [f"- {name}: {avg:.2f}⭐ · {cnt} FB" for name,avg,cnt in top]
    table = {"filename": "feedback_avg_by_customer.csv", "data": {"columns": ["customer","avg_rating","feedback_count"], "rows": rows}}
    return _ok_reply("⭐ **Điểm trung bình theo khách hàng (Top 10)**:\n" + "\n".join(lines), table, None)

def handle_feedback_negative(period: Dict[str, Any], thr: float) -> Dict[str, Any]:
    dt_from, dt_to = _period_to_range(period, inclusive_for_month=True)
    rows = agg_feedback_negative_customers(dt_from, dt_to, thr)
    if not rows:
        return _ok_reply(f"Không có khách hàng rating < {thr} trong {_fmt_period_label(period)}.")
    lines = [f"- {name}: {avg:.2f}⭐ · {cnt} FB" for name,avg,cnt in rows[:20]]
    table = {"filename": "negative_feedback_customers.csv", "data": {"columns": ["customer","avg_rating","feedback_count"], "rows": rows}}
    return _ok_reply(f"⚠️ **KH phản hồi tiêu cực (rating < {thr})**:\n" + "\n".join(lines), table, None)

def handle_feedback_count(period: Dict[str, Any]) -> Dict[str, Any]:
    dt_from, dt_to = _period_to_range(period, inclusive_for_month=True)
    cnt = agg_feedback_count(dt_from, dt_to)
    return _ok_reply(f"🗳️ Tổng feedback {_fmt_period_label(period)}: **{cnt}**.")

def handle_repeat_customer_rate(period: Dict[str, Any]) -> Dict[str, Any]:
    dt_from, dt_to = _period_to_range(period, inclusive_for_month=True)
    total, repeat, rate = agg_repeat_customer_rate(dt_from, dt_to)
    return _ok_reply(f"🔁 Repeat customers: **{rate:.2f}%** ({repeat}/{total}).")

def handle_outstanding(period: Dict[str, Any]) -> Dict[str, Any]:
    dt_from, dt_to = _period_to_range(period, inclusive_for_month=True)
    val = agg_outstanding_amount(dt_from, dt_to)
    return _ok_reply(f"📌 Tổng tiền còn nợ {_fmt_period_label(period)}: **{_fmt_money(val)}**.")

def handle_ship_payment_report(period: Dict[str, Any]) -> Dict[str, Any]:
    dt_from, dt_to = _period_to_range(period, inclusive_for_month=True)
    cnt, val = agg_ship_payment_report(dt_from, dt_to)
    return _ok_reply(f"🚛 Thanh toán ship {_fmt_period_label(period)}: **{cnt} giao dịch**, **{_fmt_money(val)}**.")

def handle_payment_count_status(period: Dict[str, Any], status_code: str) -> Dict[str, Any]:
    dt_from, dt_to = _period_to_range(period, inclusive_for_month=True)
    cnt = agg_payment_count_by_status(dt_from, dt_to, status_code)
    return _ok_reply(f"🧾 Số thanh toán trạng thái **{status_code}**: **{cnt}**.")

def handle_list_orders_by_status(period: Dict[str, Any], status: str) -> Dict[str, Any]:
    want_period = bool(period and period.get("granularity") in ("month","quarter","year"))
    if want_period:
        dt_from, dt_to = _period_to_range(period, inclusive_for_month=True)
        rows = list_orders_by_status(dt_from, dt_to, status)
        if not rows:
            try:
                rows = list_orders_by_status(dt_from, dt_to, status, field="updated_at")
            except Exception:
                pass
    else:
        try:
            rows = list_orders_by_status(None, None, status)
        except TypeError:
            now = dt.datetime.now(VN_TZ)
            dt_to = now.isoformat()
            dt_from = (now - dt.timedelta(days=90)).isoformat()
            rows = list_orders_by_status(dt_from, dt_to, status)

    if not rows:
        return _ok_reply(f"Không có đơn trạng thái **{_status_vn_label(status) or status}**.")

    # Enrich Owner
    table_rows = []
    for r in rows:
        sid = r.get("staff_id") or r.get("account_id") or r.get("created_by") or r.get("owner_id")
        name, scode = _resolve_owner(int(sid)) if sid is not None else (None, None)
        table_rows.append([
            r.get("order_code"), r.get("status"), r.get("order_type"),
            (name or ""), (scode or ""), r.get("created_at"), r.get("updated_at")
        ])

    # Thêm 3–5 mã đầu vào phần text để “nhìn là thấy”
    head = []
    for rr in table_rows[:5]:
        head.append(f"- {rr[0]} · {rr[1]} · {(rr[2] or '')}")

    table = {
        "filename": f"orders_{status.lower()}.csv",
        "data": {"columns": ["order_code","status","order_type","owner_name","owner_code","created_at","updated_at"],
                 "rows": table_rows}
    }
    st_name = _status_vn_label(status) or status
    body = f"📋 **Danh sách đơn {st_name}** ({len(rows)} bản ghi).\n"
    if head:
        body += "\nVí dụ mã (5 dòng đầu):\n" + "\n".join(head)
    return _ok_reply(body, table, None)


# --- NEW: Đếm số đơn theo kỳ + phân rã theo ngày ---
def handle_order_count_by_period(period: Dict[str, Any]) -> Dict[str, Any]:
    """
    Trả về:
      - Tổng số đơn trong kỳ
      - Phân rã theo ngày (YYYY-MM-DD: N đơn)
      - CSV kèm cột order_codes (danh sách mã đơn theo ngày, phân tách bằng dấu phẩy)
    Nguồn dữ liệu: fetch_orders_range(dt_from, dt_to)
    """
    dt_from, dt_to = _period_to_range(period, inclusive_for_month=False)

    try:
        orders = fetch_orders_range(dt_from, dt_to) or []  # list[dict]
    except Exception:
        orders = []

    total = len(orders)

    # Nhóm theo ngày (ưu tiên created_at, fallback updated_at)
    from collections import defaultdict
    import datetime as _dt

    def _to_date_yyyy_mm_dd(s: str) -> str:
        # Chuẩn về YYYY-MM-DD
        try:
            d = _dt.datetime.fromisoformat(s)
            return f"{d.year:04d}-{d.month:02d}-{d.day:02d}"
        except Exception:
            # nếu đã ở dạng YYYY-MM-DD thì để nguyên
            if len(s) == 10 and s[4] == '-' and s[7] == '-':
                return s
            return s or ""

    daily_count = defaultdict(int)
    daily_codes = defaultdict(list)

    for od in orders:
        ts = od.get("created_at") or od.get("updated_at") or ""
        day = _to_date_yyyy_mm_dd(ts)
        if not day:
            continue
        daily_count[day] += 1
        code = (od.get("order_code") or "").strip()
        if code:
            daily_codes[day].append(code)

    # series: [(date, count, codes_csv)] sắp xếp theo ngày tăng dần
    all_days = sorted(daily_count.keys())
    series3 = []
    for d in all_days:
        codes_csv = ", ".join(sorted(set(daily_codes[d]))) if daily_codes.get(d) else ""
        series3.append((d, int(daily_count[d]), codes_csv))

    # Chuẩn bị text phân rã (chỉ 1 block "Phân rã theo ngày")
    if series3:
        daily_lines = "\n".join(
            f"- {d}: {c} đơn" + (f" · mã: {codes}" if codes else "")
            for d, c, codes in series3
        )
        breakdown = f"\n\nPhân rã theo ngày ({len(series3)} dòng):\n{daily_lines}"
        table = {
            "filename": "orders_count_daily.csv",
            "data": {"columns": ["date", "count", "order_codes"], "rows": series3}
        }
    else:
        breakdown = ""
        table = None

    label = _fmt_period_label(period)
    reply = (
        f"📊 **Tổng số đơn {label}**: **{total}**\n"
        f"Khoảng: `{dt_from}` → `{dt_to}`{breakdown}"
    )

    # Có phân rã → báo app không tóm tắt để tránh làm hỏng dữ liệu dòng
    return _ok_reply(reply, table, None, meta={"no_summarize": bool(series3)})

def handle_list_wait_to_buy(period: Dict[str, Any]) -> Dict[str, Any]:
    dt_from, dt_to = _period_to_range(period, inclusive_for_month=False)
    rows = list_wait_to_buy(dt_from, dt_to)
    if not rows:
        return _ok_reply("Không có đơn **CHO_MUA**.")
    table_rows = [[r.get("order_code"), r.get("status"), r.get("created_at")] for r in rows]
    table = {"filename": "orders_cho_mua.csv", "data": {"columns":["order_code","status","created_at"], "rows": table_rows}}
    return _ok_reply(f"🛒 Đơn **chờ mua**: {len(rows)}.", table, None)

def handle_inventory_by_warehouse() -> Dict[str, Any]:
    rows = agg_inventory_by_warehouse()
    if not rows:
        return _ok_reply("Kho đang rỗng.")
    lines = [f"- {k}: {v} kiện" for k,v in rows]
    table = {"filename": "inventory_by_warehouse.csv", "data": {"columns": ["warehouse","parcels"], "rows": rows}}
    return _ok_reply("🏬 **Tồn kho theo kho**:\n" + "\n".join(lines), table, None)

def handle_avg_weight_in_stock() -> Dict[str, Any]:
    val = agg_avg_weight_in_stock()
    if val is None:
        return _ok_reply("Không có dữ liệu trọng lượng tồn.")
    return _ok_reply(f"⚖️ Trọng lượng trung bình hàng trong kho: **{val:.2f} kg**.")

def handle_imported_vn(period: Dict[str, Any]) -> Dict[str, Any]:
    dt_from, dt_to = _period_to_range(period, inclusive_for_month=True)
    rows = None; status_used = None
    for st_code in ("DA_NHAP_KHO_VN", "DA_NHAP_KHO"):
        try:
            rows = list_orders_by_status(dt_from, dt_to, st_code)
            if rows:
                status_used = st_code
                break
        except Exception:
            rows = None

    if not rows:
        cnt = agg_imported_vn_in_period(dt_from, dt_to)
        return _ok_reply(f"📦 Kiện **đã nhập kho VN** {_fmt_period_label(period)}: **{cnt}**.")

    table_rows, codes = [], []
    for r in rows:
        code = r.get("order_code") or r.get("code") or r.get("order_no")
        if code: codes.append(str(code).upper())
        table_rows.append([
            code, r.get("status"), r.get("order_type"),
            r.get("created_at"), r.get("updated_at")
        ])
    show = codes[:15]; tail = " …" if len(codes) > 15 else ""
    line_codes = f"\nMã đơn: {', '.join(show)}{tail}" if show else ""

    table = {"filename":"orders_imported_vn.csv",
             "data":{"columns":["order_code","status","order_type","created_at","updated_at"],"rows":table_rows}}
    return _ok_reply(f"📦 Đơn **đã nhập kho VN** ({len(rows)} bản ghi).{line_codes}", table, None)


def handle_flights_waiting(period: Dict[str, Any]) -> Dict[str, Any]:
    dt_from, dt_to = _period_to_range(period, inclusive_for_month=True)
    cnt = agg_flights_waiting_count(dt_from, dt_to)
    return _ok_reply(f"✈️ Số chuyến đang **chờ bay**: **{cnt}**.")

def handle_flight_completion(period: Dict[str, Any]) -> Dict[str, Any]:
    dt_from, dt_to = _period_to_range(period, inclusive_for_month=True)
    total, done, rate = agg_flight_completion_rate(dt_from, dt_to)
    return _ok_reply(f"✈️ Tỷ lệ hoàn tất chuyến bay: **{rate:.2f}%** ({done}/{total}).")

def handle_avg_transit_foreign_to_vn(period: Dict[str, Any]) -> Dict[str, Any]:
    dt_from, dt_to = _period_to_range(period, inclusive_for_month=True)
    sec = agg_avg_transit_time_foreign_to_vn(dt_from, dt_to)
    if sec is None:
        return _ok_reply("Không đủ log để tính thời gian bay→nhập kho VN.")
    hours = sec/3600.0
    return _ok_reply(f"🕒 Trung bình vận chuyển từ kho NN → VN: **{hours:.2f} giờ**.")

def _start_of_day(d: dt.datetime) -> dt.datetime:
    return d.replace(hour=0, minute=0, second=0, microsecond=0)

def _end_of_day(d: dt.datetime) -> dt.datetime:
    return d.replace(hour=23, minute=59, second=59, microsecond=999999)

def _monday_of_week(d: dt.datetime) -> dt.datetime:
    return _start_of_day(d - dt.timedelta(days=d.weekday()))  # Mon=0

def resolve_period_key(period_key: str) -> tuple[str, str, str]:
    """
    Trả về (dt_from_iso, dt_to_iso, label_vn)
    - last_1d  : 24 giờ gần nhất
    - last_7d  : 7 ngày gần nhất
    - today    : hôm nay (00:00–23:59)
    - this_week: tuần này (T2–CN)
    """
    now = dt.datetime.now(VN_TZ)
    pk = (period_key or "").lower().strip()
    if pk == "last_1d":
        dt_to = now; dt_from = now - dt.timedelta(days=1)
        return dt_from.isoformat(), dt_to.isoformat(), "24 giờ qua"
    if pk == "last_7d":
        dt_to = now; dt_from = now - dt.timedelta(days=7)
        return dt_from.isoformat(), dt_to.isoformat(), "7 ngày qua"
    if pk == "today":
        s, e = _start_of_day(now), _end_of_day(now)
        return s.isoformat(), e.isoformat(), "hôm nay"
    if pk == "this_week":
        s = _monday_of_week(now); e = _end_of_day(s + dt.timedelta(days=6))
        return s.isoformat(), e.isoformat(), "tuần này"
    # fallback
    s, e = _start_of_day(now), _end_of_day(now)
    return s.isoformat(), e.isoformat(), "hôm nay"
def handle_revenue_total_by_range(dt_from: str, dt_to: str, label_vn: str = "") -> Dict[str, Any]:
    pays = fetch_payment_range(dt_from, dt_to, paid_only=True, end_inclusive=True)
    total = sum_revenue_from_payments(pays)
    series = agg_cashflow_daily(dt_from, dt_to) or []
    day2codes = _resolve_order_codes_for_payments(pays)

    def _ddmmyyyy(s: str) -> str:
        try:
            d = dt.datetime.fromisoformat(s); return f"{d.day:02d}/{d.month:02d}/{d.year}"
        except Exception:
            if len(s) == 10 and s[4] == '-' and s[7] == '-':
                y, m, d = s.split('-'); return f"{int(d):02d}/{int(m):02d}/{int(y)}"
            return s

    chart = table = None
    lines_txt = ""
    if series:
        chart = {"kind":"line","x":[d for d,_ in series],"y":[v for _,v in series],
                 "title": f"Doanh thu theo ngày – {label_vn or (dt_from+'→'+dt_to)}"}
        table = {"filename":"revenue_daily.csv","data":{"columns":["date","amount"],"rows":series}}
        detail = []
        for d, v in series:
            codes = day2codes.get(d, [])
            if codes:
                show = codes[:5]; tail = " …" if len(codes) > 5 else ""
                detail.append(f"- {_ddmmyyyy(d)}: {_fmt_money(v)}  ({', '.join(show)}{tail})")
            else:
                detail.append(f"- {_ddmmyyyy(d)}: {_fmt_money(v)}")
        lines_txt = "\nPhân rã theo ngày ({} dòng):\n".format(len(series)) + "\n".join(detail)

    reply = f"💰 **Tổng doanh thu {label_vn or ''}**: **{_fmt_money(total)}**\nKhoảng thời gian: {_ddmmyyyy(dt_from)} → {_ddmmyyyy(dt_to)}{lines_txt}"
    return _ok_reply(reply, table, chart, meta={"no_summarize": True})


# ========================= legacy revenue / top =========================
def _today_range() -> Tuple[str, str]:
    now = dt.datetime.now(VN_TZ)
    s = dt.datetime(now.year, now.month, now.day, tzinfo=VN_TZ)
    e = s + dt.timedelta(days=1)
    return s.isoformat(), e.isoformat()

def handle_revenue_total_by_period(period: Dict[str, Any]) -> Dict[str, Any]:
    dt_from, dt_to = _period_to_range(period, inclusive_for_month=True)
    pays = fetch_payment_range(dt_from, dt_to, paid_only=True, end_inclusive=True)
    total = sum_revenue_from_payments(pays)
    label = _fmt_period_label(period)

    series = agg_cashflow_daily(dt_from, dt_to) or []
    day2codes = _resolve_order_codes_for_payments(pays)

    # range dd/mm/yyyy
    try:
        _s = dt.datetime.fromisoformat(dt_from); _e = dt.datetime.fromisoformat(dt_to)
        vn_range = f"{_s.day:02d}/{_s.month:02d}/{_s.year} → {_e.day:02d}/{_e.month:02d}/{_e.year}"
    except Exception:
        vn_range = f"{dt_from} → {dt_to}"

    def _ddmmyyyy(s: str) -> str:
        try:
            d = dt.datetime.fromisoformat(s); return f"{d.day:02d}/{d.month:02d}/{d.year}"
        except Exception:
            if len(s) == 10 and s[4] == '-' and s[7] == '-':
                y, m, d = s.split('-'); return f"{int(d):02d}/{int(m):02d}/{int(y)}"
            return s

    lines_txt = ""
    chart = table = None
    if series:
        chart = {"kind":"line","x":[d for d,_ in series],"y":[v for _,v in series],"title":f"Doanh thu theo ngày – {label}"}
        table = {"filename":"revenue_daily.csv","data":{"columns":["date","amount"],"rows":series}}
        detail_lines = []
        for d, v in series:
            codes = day2codes.get(d, [])
            if codes:
                show = codes[:5]; tail = " …" if len(codes) > 5 else ""
                detail_lines.append(f"- {_ddmmyyyy(d)}: {_fmt_money(v)}  ({', '.join(show)}{tail})")
            else:
                detail_lines.append(f"- {_ddmmyyyy(d)}: {_fmt_money(v)}")
        lines_txt = "\nPhân rã theo ngày ({} dòng):\n".format(len(series)) + "\n".join(detail_lines)

    reply = f"💰 **Tổng doanh thu {label}**: **{_fmt_money(total)}**\nKhoảng thời gian: {vn_range}{lines_txt}"
    meta = {"no_summarize": True}
    return _ok_reply(reply, table, chart, meta=meta)



def _resolve_owner(staff_id: Optional[int]) -> Tuple[Optional[str], Optional[str]]:
    if staff_id is None:
        return None, None
    try:
        acc = fetch_account_by_id(int(staff_id)) or {}
        stf = fetch_staff_by_id(int(staff_id)) or {}
        name = acc.get("name") or stf.get("name")
        scode = stf.get("staff_code")
        return name, scode
    except Exception:
        return None, None

# =============== sửa: handle_revenue_by_staff để lưu last_top ===============
def handle_revenue_by_staff(period: Dict[str, Any], *, session_id: Optional[str]=None, db_path: Optional[str]=None) -> Dict[str, Any]:
    dt_from, dt_to = _period_to_range(period, inclusive_for_month=True)
    pays = fetch_payment_range(dt_from, dt_to, paid_only=True, end_inclusive=True)
    agg = group_revenue_by_staff(pays)
    if not agg:
        return _ok_reply(f"Không có doanh thu theo nhân viên trong {_fmt_period_label(period)}.")

    rows = []  # (name, revenue, staff_code)
    items_for_ctx = []
    for sid, val in sorted(agg.items(), key=lambda x: x[1], reverse=True):
        acc = fetch_account_by_id(int(sid)) or {}
        stf = fetch_staff_by_id(int(sid)) or {}
        name = acc.get("name") or stf.get("name") or f"STAFF#{sid}"
        scode = (stf.get("staff_code") or "").strip() or "-"
        rows.append((name, float(val), scode))
        items_for_ctx.append({"name": name, "staff_code": scode, "value": float(val)})

    if session_id and db_path:
        from app.Model_LLM.Query_Supabase.sql3 import set_last_top
        set_last_top(session_id, {"items": items_for_ctx, "meta": {
            "label": "Doanh thu theo nhân viên",
            "period": _fmt_period_label(period)
        }}, db_path)

    lines = [f"- {n} ({sc}): {_fmt_money(v)}" for n, v, sc in rows]
    table = {"filename": "revenue_by_staff.csv", "data": {"columns": ["staff","revenue","staff_code"], "rows": rows}}
    return _ok_reply("👤 **Doanh thu theo nhân viên**:\n" + "\n".join(lines), table, None)

def handle_top_staff_by_orders(period: Dict[str, Any], topn: int, *, session_id: Optional[str]=None, db_path: Optional[str]=None) -> Dict[str, Any]:
    dt_from, dt_to = _period_to_range(period, inclusive_for_month=False)

    # 1) Thử API gốc (đã có wrapper _call_group_orders_count_by_staff + _normalize_staff_count)
    raw = _call_group_orders_count_by_staff(dt_from, dt_to)
    agg = _normalize_staff_count(raw)

    # 2) Fallback: tự group từ orders nếu agg rỗng/None
    if not agg:
        try:
            orders = fetch_orders_range(dt_from, dt_to)  # list[dict]
            tmp = {}
            for od in orders or []:
                # chỉ tính các trạng thái là đơn hợp lệ (tùy nhu cầu)
                sid = od.get("staff_id") or od.get("account_id") or od.get("created_by") or od.get("owner_id")
                if sid is None: 
                    continue
                tmp[int(sid)] = tmp.get(int(sid), 0) + 1
            agg = tmp
        except Exception:
            agg = {}

    if not agg:
        return _ok_reply(f"Không có dữ liệu **số đơn** theo nhân viên trong {_fmt_period_label(period)}.")

    pairs = sorted(agg.items(), key=lambda x: x[1], reverse=True)[:max(1, int(topn))]
    rows, items_for_ctx = [], []
    for sid, cnt in pairs:
        name, scode = _resolve_owner(int(sid))
        name = name or f"STAFF#{sid}"
        scode = scode or "-"
        rows.append((name, int(cnt), scode))
        items_for_ctx.append({"name": name, "staff_code": scode, "count": int(cnt)})

    if session_id and db_path:
        from app.Model_LLM.Query_Supabase.sql3 import set_last_top
        set_last_top(session_id, {"items": items_for_ctx, "meta": {
            "label": f"Top theo số đơn ({_fmt_period_label(period)})",
            "period": _fmt_period_label(period)
        }}, db_path)

    lines = [f"- {n} ({sc}): **{c} đơn**" for n, c, sc in rows]
    table = {"filename": "top_staff_by_orders.csv", "data": {"columns": ["staff","orders","staff_code"], "rows": rows}}
    return _ok_reply(f"🏆 **Top {len(rows)} nhân viên theo số đơn**:\n" + "\n".join(lines), table, None)


# ========================= Entry point =========================
def handle_message(user_text: str, session_id: str, db_path: str) -> Dict[str, Any]:
    KV = _kv_imports()
    set_last_order_code = KV["set_last_order_code"]
    get_last_order_code = KV["get_last_order_code"]
    set_last_period     = KV["set_last_period"]
    get_last_period     = KV["get_last_period"]
    set_last_topic      = KV["set_last_topic"]
    get_last_topic      = KV["get_last_topic"]
    set_last_top        = KV["set_last_top"]
    get_last_top        = KV["get_last_top"]


    try:
        init_db(db_path)
    except Exception:
        pass

    _rel_pk = _detect_relative_period_key(user_text)
    if _rel_pk:
        set_last_topic(session_id, "metric", db_path)
        dt_from, dt_to, label_vn = resolve_period_key(_rel_pk)
        try:
            set_last_period(session_id, dt_from, dt_to, db_path, last_intent="GET_REVENUE_TOTAL_BY_PERIOD")
        except Exception:
            pass
        print(f"[DEBUG] relative_guard hit: period_key={_rel_pk}  {dt_from} -> {dt_to}")
        return handle_revenue_total_by_range(dt_from, dt_to, label_vn)
    
    parsed = normalize_query(user_text)
    print("DEBUG_INTENT:", normalize_query(user_text))
    intent = parsed["intent"]
    norm = parsed["norm"]

    if intent == "GET_ORDER_COUNT_BY_PERIOD":
        set_last_topic(session_id, "metric", db_path)
        return handle_order_count_by_period(norm.get("period") or {})
    
    if intent == "GET_TOP_CUSTOMERS_BY_SPEND":
        set_last_topic(session_id, "metric", db_path)
        return handle_top_customers_by_spend(norm.get("period") or {}, int(norm.get("topn") or 10))

    if intent == "GET_REVENUE_MULTI":
        set_last_topic(session_id, "metric", db_path)
        return handle_revenue_multi(norm.get("periods") or [])

    if intent == "IMPORTED_VN_THIS_PERIOD":
        set_last_topic(session_id, "metric", db_path)
        return handle_imported_vn(norm.get("period") or {})

    # ===== SMALLTALK =====
    if intent == "SMALLTALK":
        set_last_topic(session_id, "none", db_path)
        return {"intent": intent, "reply": "Mình hỗ trợ: doanh thu, số đơn (lọc trạng thái/thể loại), Top theo số đơn, tra mã đơn + follow-up 'của ai' / 'tên gì'."}

    # ===== FOLLOWUP_SET_PERIOD =====
    if intent == "FOLLOWUP_SET_PERIOD":
        dt_from, dt_to = _period_to_range(norm, inclusive_for_month=False)
        set_last_period(session_id, dt_from, dt_to, db_path, last_intent=intent)
        set_last_topic(session_id, "metric", db_path)
        label = _fmt_period_label(norm)
        return {"intent": intent, "reply": f"✔️ Đã đặt khoảng thời gian mặc định: **{label}** (`{dt_from}` → `{dt_to}`). Bạn có thể hỏi tiếp: top theo số đơn, tổng đơn, doanh thu..."}

    # ===== ORDER STATUS BY CODE =====
    if intent in ("GET_ORDER_STATUS_BY_CODE","GET_ORDER_STATUS"):
        code = (norm.get("order_code") or "").strip() or get_last_order_code(session_id, db_path) or ""
        if not code:
            return {"intent": intent, "reply": "Gửi giúp mình **mã đơn** (VD ORDI7KQ1) để kiểm tra trạng thái nhé."}

        od = fetch_order_by_code(code)
        if not od:
            return {"intent": intent, "reply": f"Không tìm thấy đơn “{code}”."}

        set_last_order_code(session_id, code, db_path)
        set_last_topic(session_id, "order", db_path)

        stt   = od.get("status") or "(không có cột status)"
        otype = od.get("order_type")
        staff_id = od.get("staff_id") or od.get("account_id") or od.get("created_by") or od.get("owner_id")

        owner_txt = None
        if staff_id is not None:
            try:
                acc = fetch_account_by_id(int(staff_id)) or {}
                stf = fetch_staff_by_id(int(staff_id)) or {}
            except Exception:
                acc, stf = {}, {}
            name = acc.get("name") or stf.get("name")
            scode = stf.get("staff_code")
            if name:
                owner_txt = name + (f" · {scode}" if scode else "")
            elif scode:
                owner_txt = scode

        reply = f"**{code}** → Trạng thái: **{stt}**"
        if otype: reply += f" · Thể loại: **{otype}**"
        if owner_txt: reply += f" · Owner: **{owner_txt}**"

        return {"intent": intent, "reply": reply}


    # ===== GET_ORDER_OWNER =====
    if intent == "GET_ORDER_OWNER":
        code = (norm.get("order_code") or "").strip()
        if not code and get_last_topic(session_id, db_path) == "order":
            code = get_last_order_code(session_id, db_path) or ""

        if not code:
            last_top = get_last_top(session_id, db_path)
            if last_top and last_top.get("items"):
                first = last_top["items"][0]
                name = first.get("name") or "(không tên)"
                scode = first.get("staff_code") or "-"
                cnt = first.get("count") or 0
                meta = last_top.get("meta") or {}
                label = meta.get("label") or ""
                return {"intent": intent, "reply": f"**{name}** ({scode}) đang đứng đầu {label} — **{cnt} đơn**."}

            # Không có mã đơn, cũng không có bảng xếp hạng gần nhất
            return {"intent": intent,
                    "reply": "‘**Của ai**’ áp dụng cho **một đơn cụ thể** hoặc **bảng xếp hạng gần nhất**.\n"
                                "• Gõ mã: `OD202500008`\n"
                                "• Hoặc hỏi: *top 5 nhân viên theo số đơn tháng 11* rồi hỏi tiếp ‘của ai?’"}


    # ===== REVENUE TOTAL BY PERIOD =====
    # if intent == "GET_REVENUE_TOTAL_BY_PERIOD":
    #     set_last_topic(session_id, "metric", db_path)
    #     period = norm.get("period") or {}
    #     res = handle_revenue_total_by_period(period)  # <-- gọi handler đã build series/table/meta
    #     # lưu last_period cho follow-up
    #     dt_from, dt_to = _period_to_range(period, inclusive_for_month=True)
    #     set_last_period(session_id, dt_from, dt_to, db_path, last_intent=intent)
    #     res["intent"] = intent
    #     return res

    if intent == "GET_REVENUE_TOTAL_BY_PERIOD":
        set_last_topic(session_id, "metric", db_path)
        period_key = (norm.get("period_key") or "").strip().lower()
        if period_key:
            dt_from, dt_to, label_vn = resolve_period_key(period_key)
            try:
                set_last_period(session_id, dt_from, dt_to, db_path, last_intent=intent)
            except Exception:
                pass
            return handle_revenue_total_by_range(dt_from, dt_to, label_vn)
        # Fallback tháng/quý/năm:
        period = norm.get("period") or {}
        res = handle_revenue_total_by_period(period)
        try:
            _f, _t = _period_to_range(period, inclusive_for_month=True)
            set_last_period(session_id, _f, _t, db_path, last_intent=intent)
        except Exception:
            pass
        res["intent"] = intent
        return res

    # ===== REVENUE BY STAFF =====
    if intent == "GET_REVENUE_BY_SALE":
        set_last_topic(session_id, "metric", db_path)
        period = norm.get("period") or {}
        return handle_revenue_by_staff(period, session_id=session_id, db_path=db_path)

    # 2) Top theo SỐ ĐƠN (chấp nhận 2 tên intent để tương thích)
    if intent in ("GET_TOP_STAFF_BY_ORDERS","GET_TOP_STAFF_PERFORMANCE"):
        set_last_topic(session_id, "metric", db_path)
        period = norm.get("period") or {}
        topn = int(norm.get("topn") or 10)
        return handle_top_staff_by_orders(period, topn, session_id=session_id, db_path=db_path)

    # ===== REVENUE BY ROUTE / DESTINATION =====
    if intent == "GET_REVENUE_BY_ROUTE":
        set_last_topic(session_id, "metric", db_path)
        return handle_revenue_by_route(norm.get("period") or {})
    if intent == "GET_REVENUE_BY_DESTINATION":
        set_last_topic(session_id, "metric", db_path)
        return handle_revenue_by_destination(norm.get("period") or {})

    # ===== AOV BY CUSTOMER =====
    if intent == "AOV_BY_CUSTOMER":
        set_last_topic(session_id, "metric", db_path)
        return handle_aov_by_customer(norm.get("period") or {})

    # ===== ORDER COUNT / STATUS =====
    if intent == "GET_ORDER_COUNT_BY_STATUS":
        set_last_topic(session_id, "metric", db_path)
        return handle_order_count_by_status(norm.get("period") or {}, norm.get("status") or "DA_XAC_NHAN")

    if intent == "CANCEL_RATE":
        set_last_topic(session_id, "metric", db_path)
        return handle_cancel_rate(norm.get("period") or {})

    # ===== SLA / THỜI GIAN =====
    if intent == "AVG_FULFILLMENT_TIME":
        set_last_topic(session_id, "metric", db_path)
        return handle_avg_fulfillment_time(norm.get("period") or {})
    if intent == "AVG_RESPONSE_TIME":
        set_last_topic(session_id, "metric", db_path)
        # Với schema hiện tại chưa có mốc 'XAC_NHAN_DON' rõ ràng → có thể map thêm sau
        return {"intent": intent, "reply": "Metric 'AVG_RESPONSE_TIME' sẽ dùng log xác nhận đơn; mình sẽ nối khi có mốc log chuẩn."}

    # ===== FEEDBACK =====
    if intent == "AVG_RATING_BY_CUSTOMER":
        set_last_topic(session_id, "metric", db_path)
        return handle_feedback_metrics(norm.get("period") or {})
    if intent == "NEGATIVE_FEEDBACK_CUSTOMERS":
        set_last_topic(session_id, "metric", db_path)
        thr = float(norm.get("threshold", 3.0))
        return handle_feedback_negative(norm.get("period") or {}, thr)
    if intent == "FEEDBACK_COUNT_MONTH":
        set_last_topic(session_id, "metric", db_path)
        return handle_feedback_count(norm.get("period") or {})
    if intent == "REPEAT_CUSTOMER_RATE":
        set_last_topic(session_id, "metric", db_path)
        return handle_repeat_customer_rate(norm.get("period") or {})

    # ===== PAYMENTS / CASHFLOW =====
    if intent == "TOTAL_COLLECTED_IN_PERIOD":
        set_last_topic(session_id, "metric", db_path)
        per = norm.get("period") or {}
        dt_from, dt_to = _period_to_range(per, inclusive_for_month=True)
        pays = fetch_payment_range(dt_from, dt_to, paid_only=True, end_inclusive=True)
        total = sum_revenue_from_payments(pays)
        return {"intent": intent, "reply": f"💵 Tổng tiền đã thu { _fmt_period_label(per) }: **{_fmt_money(total)}** ({dt_from} → {dt_to})."}
    if intent == "TOTAL_BY_PAYMENT_METHOD":
        set_last_topic(session_id, "metric", db_path)
        per = norm.get("period") or {}
        dt_from, dt_to = _period_to_range(per, inclusive_for_month=True)
        pays = fetch_payment_range(dt_from, dt_to, paid_only=True, end_inclusive=True)
        agg = sum_amount_by_payment_type(pays)
        if not agg:
            return {"intent": intent, "reply": f"Không có thanh toán trong {_fmt_period_label(per)}."}
        rows = sorted(agg.items(), key=lambda x: x[1], reverse=True)
        lines = [f"- {k}: {_fmt_money(v)}" for k,v in rows]
        table = {"filename": "total_by_payment_type.csv", "data": {"columns":["payment_type","amount"], "rows": rows}}
        return {"intent": intent, "reply": "**Tổng tiền theo loại thanh toán**:\n" + "\n".join(lines), "table": table}
    if intent == "CASH_FLOW_DAILY":
        set_last_topic(session_id, "metric", db_path)
        return handle_cashflow_daily(norm.get("period") or {})
    if intent == "TOTAL_OUTSTANDING_IN_PERIOD":
        set_last_topic(session_id, "metric", db_path)
        return handle_outstanding(norm.get("period") or {})
    if intent == "SHIP_PAYMENT_REPORT":
        set_last_topic(session_id, "metric", db_path)
        return handle_ship_payment_report(norm.get("period") or {})
    if intent == "PAYMENT_COUNT_BY_STATUS":
        set_last_topic(session_id, "metric", db_path)
        per = norm.get("period") or {}
        st = norm.get("status", "CHO_THANH_TOAN")
        return handle_payment_count_status(per, st)

    # ===== LIST ORDERS =====
    if intent == "LIST_ORDERS_BY_STATUS":
        set_last_topic(session_id, "metric", db_path)
        return handle_list_orders_by_status(norm.get("period") or {}, norm.get("status") or "CHO_XAC_NHAN")
    if intent == "LIST_WAIT_TO_BUY":
        set_last_topic(session_id, "metric", db_path)
        return handle_list_wait_to_buy(norm.get("period") or {})

    # ===== KHO / PACKING =====
    if intent == "INVENTORY_PARCELS_BY_WAREHOUSE":
        set_last_topic(session_id, "metric", db_path)
        return handle_inventory_by_warehouse()
    if intent == "AVG_WEIGHT_IN_STOCK":
        set_last_topic(session_id, "metric", db_path)
        return handle_avg_weight_in_stock()
    if intent == "IMPORTED_VN_THIS_PERIOD":
        set_last_topic(session_id, "metric", db_path)
        return handle_imported_vn(norm.get("period") or {})

    # ===== FLIGHT =====
    if intent == "FLIGHT_WAITING_COUNT":
        set_last_topic(session_id, "metric", db_path)
        return handle_flights_waiting(norm.get("period") or {})
    if intent == "FLIGHT_COMPLETION_RATE":
        set_last_topic(session_id, "metric", db_path)
        return handle_flight_completion(norm.get("period") or {})
    if intent == "AVG_TRANSIT_TIME_FOREIGN_TO_VN":
        set_last_topic(session_id, "metric", db_path)
        return handle_avg_transit_foreign_to_vn(norm.get("period") or {})

    # ===== FALLBACK: xác nhận intent (không in JSON) =====
    per = None
    if isinstance(norm, dict):
        per = norm.get("period")
    if per:
        dt_from, dt_to = _period_to_range(per, inclusive_for_month=False)
        set_last_period(session_id, dt_from, dt_to, db_path, last_intent=intent)
        set_last_topic(session_id, "metric", db_path)
    return {"intent": intent, "reply": f"✅ Đã nhận intent **{intent}** — yêu cầu đã được ghi nhận để nối dữ liệu thật."}

def handle_top_customers_by_spend(period: Dict[str, Any], topn: int = 10) -> Dict[str, Any]:
    dt_from, dt_to = _period_to_range(period, inclusive_for_month=True)
    rows = None
    try:
        if hasattr(ac, "agg_top_customers_by_spend"):
            rows = ac.agg_top_customers_by_spend(dt_from, dt_to, topn)  # list[(name, amount, orders)]
    except Exception:
        rows = None

    if not rows:
        try:
            pays = fetch_payment_range(dt_from, dt_to, paid_only=True, end_inclusive=True)
            agg, cnt = {}, {}
            for p in pays or []:
                cname = p.get("customer_name") or p.get("customer") or f"KH#{p.get('customer_id') or 'NA'}"
                val = float(p.get("amount") or 0.0)
                agg[cname] = agg.get(cname, 0.0) + val
                cnt[cname] = cnt.get(cname, 0) + 1
            rows = sorted([(k, v, cnt.get(k, 0)) for k, v in agg.items()], key=lambda x: x[1], reverse=True)[:topn]
        except Exception:
            rows = []

    if not rows:
        return _ok_reply(f"Không có dữ liệu **Top khách hàng theo chi tiêu** trong {_fmt_period_label(period)}.")

    lines = [f"- {name}: {_fmt_money(amount)} · {n} đơn" for name, amount, n in rows]
    table = {"filename":"top_customers_by_spend.csv","data":{"columns":["customer","spend","orders"],"rows":rows}}
    return _ok_reply(f"🏅 **Top {len(rows)} khách hàng chi tiêu cao nhất**:\n" + "\n".join(lines), table, None)

def handle_revenue_multi(periods: List[Dict[str, Any]]) -> Dict[str, Any]:
    lines, table_rows = [], []
    for p in periods or []:
        dt_from, dt_to = _period_to_range(p, inclusive_for_month=True)
        pays = fetch_payment_range(dt_from, dt_to, paid_only=True, end_inclusive=True)
        total = sum_revenue_from_payments(pays)
        label = _fmt_period_label(p)
        lines.append(f"- {label}: {_fmt_money(total)}")
        table_rows.append([label, dt_from, dt_to, float(total)])
    table = {"filename":"revenue_multi.csv",
             "data":{"columns":["period","from","to","amount"],"rows":table_rows}}
    reply = "💰 **Doanh thu nhiều kỳ**:\n" + "\n".join(lines)
    meta = {"no_summarize": True}
    return _ok_reply(reply, table, None, meta=meta)

    # =========================== main ===========================
    # --- NEW HANDLER: Doanh thu theo route ---
    if intent == "GET_REVENUE_BY_ROUTE":
        set_last_topic(session_id, "metric", db_path)
        period = norm.get("period") or {}
        dt_from, dt_to = _period_to_range(period, inclusive_for_month=True)
        from api_client import revenue_by_route
        m = revenue_by_route(dt_from, dt_to)  # {route_id: revenue}
        if not m:
            return {"intent": intent, "reply": f"Không có dữ liệu theo tuyến ({_fmt_period_label(period)})."}
        lines = [f"- Route #{rid}: **{val:,.0f}₫**" for rid, val in sorted(m.items(), key=lambda x: x[1], reverse=True)]
        return {"intent": intent, "reply": "🛣️ **Doanh thu theo tuyến**:\n" + "\n".join(lines)}

    # --- NEW HANDLER: Doanh thu theo destination ---
    if intent == "GET_REVENUE_BY_DESTINATION":
        set_last_topic(session_id, "metric", db_path)
        period = norm.get("period") or {}
        dt_from, dt_to = _period_to_range(period, inclusive_for_month=True)
        from api_client import revenue_by_destination
        m = revenue_by_destination(dt_from, dt_to)
        if not m:
            return {"intent": intent, "reply": f"Không có dữ liệu theo điểm đến ({_fmt_period_label(period)})."}
        lines = [f"- Destination #{did}: **{val:,.0f}₫**" for did, val in sorted(m.items(), key=lambda x: x[1], reverse=True)]
        return {"intent": intent, "reply": "📍 **Doanh thu theo điểm đến**:\n" + "\n".join(lines)}

    # --- NEW HANDLER: Tổng thu theo sale ---
    if intent == "TOTAL_COLLECTED_BY_SALE":
        set_last_topic(session_id, "metric", db_path)
        period = norm.get("period") or {}
        dt_from, dt_to = _period_to_range(period, inclusive_for_month=True)
        from api_client import total_collected_by_sale
        m = total_collected_by_sale(dt_from, dt_to)  # {staff_id: total}
        if not m:
            return {"intent": intent, "reply": f"Không có doanh thu theo nhân viên ({_fmt_period_label(period)})."}
        lines = []
        for sid, val in sorted(m.items(), key=lambda x: x[1], reverse=True):
            acc = fetch_account_by_id_safe(sid) or {}
            stf = fetch_staff_by_id_safe(sid) or {}
            name = acc.get("name") or stf.get("name") or f"Staff #{sid}"
            scode = stf.get("staff_code") or "-"
            lines.append(f"- {name} ({scode}): **{val:,.0f}₫**")
        return {"intent": intent, "reply": "👤 **Tổng tiền theo nhân viên sale**:\n" + "\n".join(lines)}

    # --- NEW HANDLER: AOV theo khách hàng ---
    if intent == "AOV_BY_CUSTOMER":
        set_last_topic(session_id, "metric", db_path)
        period = norm.get("period") or {}
        dt_from, dt_to = _period_to_range(period, inclusive_for_month=False)
        from api_client import aov_by_customer
        m = aov_by_customer(dt_from, dt_to)  # {customer_id: aov}
        if not m:
            return {"intent": intent, "reply": f"Không có dữ liệu AOV ({_fmt_period_label(period)})."}
        lines = [f"- KH #{cid}: **{val:,.0f}₫/đơn**" for cid, val in sorted(m.items(), key=lambda x: x[1], reverse=True)[:10]]
        return {"intent": intent, "reply": "📦 **AOV theo khách hàng**:\n" + "\n".join(lines)}

    # --- NEW HANDLER: Order count by status / cancel rate ---
    if intent == "GET_ORDER_COUNT_BY_STATUS":
        set_last_topic(session_id, "metric", db_path)
        period = norm.get("period") or {}
        status = norm.get("status")
        dt_from, dt_to = _period_to_range(period, inclusive_for_month=False)
        from api_client import order_count_by_status
        res = order_count_by_status(dt_from, dt_to, status=status)
        if isinstance(res, int):
            return {"intent": intent, "reply": f"**{res}** đơn với trạng thái **{status}** ({_fmt_period_label(period)})."}
        lines = [f"- {k or '(NULL)'}: **{v}**" for k, v in sorted(res.items(), key=lambda x: x[1], reverse=True)]
        return {"intent": intent, "reply": "📊 **Số đơn theo trạng thái**:\n" + "\n".join(lines)}

    if intent == "GET_CANCEL_RATE":
        set_last_topic(session_id, "metric", db_path)
        period = norm.get("period") or {}
        dt_from, dt_to = _period_to_range(period, inclusive_for_month=False)
        from api_client import cancel_rate
        canceled, total, rate = cancel_rate(dt_from, dt_to)
        return {"intent": intent, "reply": f"❌ **Tỷ lệ hủy**: **{rate:.2f}%** ({canceled}/{total}) — {_fmt_period_label(period)}"}

    # --- NEW HANDLER: Feedback TB theo KH ---
    if intent == "AVG_RATING_BY_CUSTOMER":
        set_last_topic(session_id, "metric", db_path)
        period = norm.get("period") or {}
        dt_from, dt_to = _period_to_range(period, inclusive_for_month=False)
        from api_client import avg_rating_by_customer
        m = avg_rating_by_customer(dt_from, dt_to)
        if not m:
            return {"intent": intent, "reply": f"Không có feedback trong {_fmt_period_label(period)}."}
        lines = [f"- KH #{cid}: **{val:.2f}**" for cid, val in sorted(m.items(), key=lambda x: x[1], reverse=True)]
        return {"intent": intent, "reply": "⭐ **Điểm đánh giá TB theo KH**:\n" + "\n".join(lines)}

    # --- NEW HANDLER: Kho – tồn theo kho ---
    if intent == "INVENTORY_PARCELS_BY_WAREHOUSE":
        set_last_topic(session_id, "metric", db_path)
        from api_client import inventory_parcels_by_warehouse
        m = inventory_parcels_by_warehouse()
        if not m:
            return {"intent": intent, "reply": "Không có kiện hàng trong kho."}
        lines = [f"- Location #{lid}: **{cnt}** kiện" for lid, cnt in sorted(m.items(), key=lambda x: x[1], reverse=True)]
        return {"intent": intent, "reply": "🏬 **Kiện hàng theo kho**:\n" + "\n".join(lines)}
