# # -*- coding: utf-8 -*-
# from __future__ import annotations
# import os, re, unicodedata, datetime as dt
# from typing import Dict, Any, Optional, List, Tuple, Union
# import requests

# # =============== CẤU HÌNH ===============
# try:
#     from .config_supabase import BASE_API_URL, API_KEY, DEFAULT_PAGE_SIZE, VN_TZ
# except Exception:
#     BASE_API_URL = os.environ.get("BASE_API_URL", "https://sides-vacuum-tire-abc.trycloudflare.com").rstrip("/")
#     API_KEY = os.environ.get("API_KEY", "super-secret-xyz").strip()
#     DEFAULT_PAGE_SIZE = int(os.environ.get("DEFAULT_PAGE_SIZE", "200"))
#     try:
#         import pytz
#         VN_TZ = pytz.timezone(os.environ.get("VN_TZ","Asia/Ho_Chi_Minh"))
#     except Exception:
#         VN_TZ = dt.timezone(dt.timedelta(hours=7))

# # API phụ trợ warehouse trong kỳ (đã có sẵn ở dự án của bạn)
# try:
#     from api_adapter import fetch_warehouse_in_period
# except Exception:
#     # Fallback an toàn: trả về rỗng nếu chưa import được
#     def fetch_warehouse_in_period(dt_from_iso: str, dt_to_iso: str) -> List[Dict[str, Any]]:
#         return []

# API_MAX_LIMIT = 500
# PAID_STATUSES = {"DA_THANH_TOAN", "DA_THANH_TOAN_SHIP"}

# # =============== BẮT "THÁNG <m> (/năm)" ===============
# try:
#     from dateutil.relativedelta import relativedelta
# except Exception:
#     # fallback đơn giản nếu thiếu python-dateutil
#     class relativedelta:
#         def __init__(self, months=0):
#             self.months = months
#         def __radd__(self, d: dt.datetime):
#             y, m = d.year, d.month + self.months
#             while m > 12:
#                 m -= 12
#                 y += 1
#             while m < 1:
#                 m += 12
#                 y -= 1
#             return d.replace(year=y, month=m)
# # ====== Gemini polish (tùy chọn) ======
# USE_GEMINI_POLISH = os.environ.get("USE_GEMINI_POLISH", "0").strip() in {"1", "true", "TRUE"}
# GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# def _http_post_json(url: str, payload: Dict[str, Any], headers: Dict[str, str], timeout: int = 20) -> Optional[Dict[str, Any]]:
#     try:
#         r = requests.post(url, json=payload, headers=headers, timeout=timeout)
#         if r.status_code // 100 == 2:
#             return r.json()
#         return None
#     except Exception:
#         return None

# def polish_text_with_gemini(text: str) -> str:
#     """
#     Nếu có GEMINI_API_KEY và USE_GEMINI_POLISH=1 → gọi Gemini 1.5 flash để làm mượt câu trả lời tiếng Việt.
#     Nếu không có key, trả về nguyên văn (no-op).
#     """
#     if not USE_GEMINI_POLISH or not GEMINI_API_KEY or not text or len(text) < 40:
#         return text
#     try:
#         url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={GEMINI_API_KEY}"
#         payload = {
#             "contents": [{
#                 "parts": [{
#                     "text": (
#                         "Bạn là trình hiệu đính tiếng Việt cho báo cáo kỹ thuật/kho vận. "
#                         "Yêu cầu: ngắn gọn, mạch lạc, giữ nguyên số liệu/bảng Markdown.\n\n"
#                         f"---\n{text}\n---\n"
#                         "Hãy trả lại nội dung đã chỉnh giọng văn (đừng thêm phần thừa)."
#                     )
#                 }]
#             }],
#             "generationConfig": {
#                 "temperature": 0.2,
#                 "topK": 40,
#                 "topP": 0.9,
#                 "maxOutputTokens": 2048
#             }
#         }
#         headers = {"Content-Type": "application/json"}
#         resp = _http_post_json(url, payload, headers)
#         if not resp:
#             return text
#         # Lấy text đầu tiên
#         cands = (resp.get("candidates") or [])
#         parts = (((cands[0] or {}).get("content") or {}).get("parts") or [])
#         new_text = parts[0].get("text") if parts else ""
#         return new_text.strip() or text
#     except Exception:
#         return text

# def _emit(text: str):
#     """In ra sau khi polish bằng Gemini nếu bật cấu hình."""
#     print(polish_text_with_gemini(text))

# _MONTH_RANGE_RE = re.compile(
#     r"(?:thang|tháng)\s*(?P<m>\d{1,2})"
#     r"(?:\s*[/\-]\s*(?P<y1>\d{2,4}))?"
#     r"(?:\s*năm\s*(?P<y2>\d{4}))?",
#     re.IGNORECASE | re.UNICODE
# )

# def _normalize_year(y: int) -> int:
#     return y + 2000 if y < 100 else y

# def _month_bounds(year: int, month: int, tz) -> tuple[str, str]:
#     start = dt.datetime(year, month, 1, tzinfo=tz)
#     end = start + relativedelta(months=1)
#     return start.isoformat(), end.isoformat()

# def resolve_month_from_text(s: str, now: dt.datetime, tz) -> tuple[str, str] | None:
#     """
#     Ưu tiên: nếu user ghi 'tháng <m>' (có/không có năm), trả về [start, end) của tháng đó.
#     Nếu không match, trả về None để logic cũ xử lý 'tháng này'...
#     """
#     m = _MONTH_RANGE_RE.search(s or "")
#     if not m:
#         return None
#     month = int(m.group("m"))
#     y2 = m.group("y2")
#     y1 = m.group("y1")
#     year = _normalize_year(int(y2 or y1 or now.year))
#     if not (1 <= month <= 12):
#         return None
#     return _month_bounds(year, month, tz)

# # =============== HELPERS ===============
# def _headers() -> Dict[str, str]:
#     return {"X-API-Key": API_KEY, "Accept": "application/json"}

# def _clamp(n: Optional[int]) -> int:
#     try:
#         n = int(n or DEFAULT_PAGE_SIZE)
#     except Exception:
#         n = DEFAULT_PAGE_SIZE
#     return max(1, min(API_MAX_LIMIT, n))

# def _now() -> dt.datetime:
#     try:
#         return dt.datetime.now(VN_TZ)
#     except Exception:
#         return dt.datetime.now()

# def this_month_range_iso() -> Tuple[str,str]:
#     now = _now()
#     start = dt.datetime(now.year, now.month, 1, 0, 0, 0, tzinfo=now.tzinfo)
#     if now.month == 12:
#         end = dt.datetime(now.year+1, 1, 1, 0, 0, 0, tzinfo=now.tzinfo)
#     else:
#         end = dt.datetime(now.year, now.month+1, 1, 0, 0, 0, tzinfo=now.tzinfo)
#     return start.isoformat(), end.isoformat()

# def this_week_range_iso() -> Tuple[str,str]:
#     now = _now()
#     start = (now - dt.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
#     end = start + dt.timedelta(days=7)
#     return start.isoformat(), end.isoformat()

# def today_range_iso() -> Tuple[str,str]:
#     now = _now()
#     start = now.replace(hour=0, minute=0, second=0, microsecond=0)
#     end = start + dt.timedelta(days=1)
#     return start.isoformat(), end.isoformat()

# def _fold(s: str) -> str:
#     s = (s or "").strip()
#     t = unicodedata.normalize("NFD", s.lower())
#     return "".join(ch for ch in t if unicodedata.category(ch) != "Mn")

# _EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# _PHONE_FULL_RE = re.compile(r"^\+?\d{9,13}$")
# _ORDER_CODE_INLINE_RE = re.compile(r"\b(ORD[A-Z0-9\-]*|[A-Z]{2,5}[A-Z0-9\-]*\d+)\b", re.IGNORECASE)

# def extract_order_code_from_text(text: str) -> Optional[str]:
#     m = _ORDER_CODE_INLINE_RE.search(text or "")
#     return m.group(1).upper() if m else None

# # =============== API LAYER ===============
# def fetch_table_once(table: str, params: Optional[Dict[str, Any]] = None, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0) -> Dict[str, Any]:
#     url = f"{BASE_API_URL}/api/{table}"
#     q = {"limit": _clamp(limit), "offset": max(0, int(offset))}
#     if params:
#         q.update(params)
#     resp = requests.get(url, headers=_headers(), params=q, timeout=30)
#     if resp.status_code != 200:
#         raise requests.HTTPError(f"POSTGREST {table}: {resp.status_code} {resp.text[:240]}")
#     return resp.json()

# def fetch_table_all(table: str, params: Optional[Dict[str, Any]] = None, page_size: int = DEFAULT_PAGE_SIZE, max_pages: int = 200) -> List[Dict[str, Any]]:
#     out, offset, step = [], 0, _clamp(page_size)
#     for _ in range(max_pages):
#         data = fetch_table_once(table, params=params, limit=step, offset=offset)
#         rows = data.get("data") or []
#         out.extend(rows)
#         if len(rows) < step:
#             break
#         offset += step
#     return out

# # =============== AGG HELPERS ===============
# def _f(x):
#     try:
#         return float(x or 0)
#     except Exception:
#         return 0.0

# def fetch_payment_range(lo: str, hi: str, paid_only: bool = True, end_inclusive: bool = False) -> List[Dict[str, Any]]:
#     p = {"gte__action_at": lo, "order": "action_at", "desc": False}
#     p["lte__action_at" if end_inclusive else "lt__action_at"] = hi
#     if paid_only:
#         p["in__status"] = ",".join(sorted(PAID_STATUSES))
#     return fetch_table_all("payment", params=p)

# def sum_revenue_from_payments(payments: List[Dict[str, Any]]) -> float:
#     s = 0.0
#     for p in payments:
#         if (p.get("status") or "").upper() in PAID_STATUSES:
#             s += _f(p.get("collected_amount", p.get("amount", 0)))
#     return s

# def fetch_orders_range(lo: str, hi: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
#     p = {"gte__created_at": lo, "lt__created_at": hi}
#     if status:
#         p["eq__status"] = status
#     return fetch_table_all("orders", params=p)

# def fetch_routes_map() -> Dict[int, str]:
#     rows = fetch_table_all("route", {})
#     return {int(r["route_id"]): (r.get("name") or f"ROUTE#{r['route_id']}") for r in rows}

# def fetch_destinations_map() -> Dict[int, str]:
#     rows = fetch_table_all("destination", {})
#     return {int(r["destination_id"]): (r.get("destination_name") or f"DEST#{r['destination_id']}") for r in rows}

# def fetch_account_by_id(aid: int) -> Optional[Dict[str, Any]]:
#     rows = fetch_table_all("account", {"eq__account_id": int(aid)}, page_size=50)
#     return rows[0] if rows else None

# def fetch_staff_by_id(aid: int) -> Optional[Dict[str, Any]]:
#     rows = fetch_table_all("staff", {"eq__account_id": int(aid)}, page_size=50)
#     return rows[0] if rows else None

# def fetch_order_by_code(code: str) -> Optional[Dict[str, Any]]:
#     rows = fetch_table_all("orders", {"eq__order_code": code}, page_size=50)
#     if not rows and code.isdigit():
#         rows = fetch_table_all("orders", {"eq__order_id": int(code)}, page_size=50)
#     return rows[0] if rows else None

# def payments_by_order(oid: int) -> List[Dict[str, Any]]:
#     return fetch_table_all("payment", {"eq__order_id": int(oid)})

# def process_logs_by_order(oid: int) -> List[Dict[str, Any]]:
#     return fetch_table_all("order_process_log", {"eq__order_id": int(oid), "order":"timestamp", "desc":True})

# def order_snapshot_by_code(code: str) -> Optional[Dict[str, Any]]:
#     od = fetch_order_by_code(code)
#     if not od:
#         return None
#     oid = int(od["order_id"])
#     pays = payments_by_order(oid)
#     paid = sum(_f(p.get("collected_amount", p.get("amount", 0))) for p in pays if (p.get("status") or "").upper() in PAID_STATUSES)
#     pending = sum(_f(p.get("amount", 0)) for p in pays if (p.get("status") or "").upper() in {"CHO_THANH_TOAN","CHO_THANH_TOAN_SHIP"})
#     logs = process_logs_by_order(oid)
#     last_log = logs[0] if logs else None
#     routes = fetch_routes_map(); dests = fetch_destinations_map()
#     return {
#         "order_id": oid,
#         "order_code": od.get("order_code"),
#         "status": od.get("status"),
#         "created_at": od.get("created_at"),
#         "staff_id": od.get("staff_id"),
#         "staff_label": (fetch_staff_by_id(int(od.get("staff_id"))) or {}).get("staff_code") if od.get("staff_id") else None,
#         "staff_name": (fetch_account_by_id(int(od.get("staff_id"))) or {}).get("name") if od.get("staff_id") else None,
#         "customer_id": od.get("customer_id"),
#         "customer_name": (fetch_account_by_id(int(od.get("customer_id"))) or {}).get("name") if od.get("customer_id") else None,
#         "route_id": od.get("route_id"),
#         "route_name": routes.get(int(od.get("route_id")), f"ROUTE#{od.get('route_id')}") if od.get("route_id") else None,
#         "destination_id": od.get("destination_id"),
#         "destination_name": dests.get(int(od.get("destination_id")), f"DEST#{od.get('destination_id')}") if od.get("destination_id") else None,
#         "payments": {"count": len(pays), "paid_total": paid, "pending_total": pending},
#         "last_log": {"action": last_log.get("action"), "timestamp": last_log.get("timestamp"), "staff_id": last_log.get("staff_id")} if last_log else None
#     }

# def fetch_account_by_field(field: str, value: Union[str,int]) -> Optional[Dict[str, Any]]:
#     if field == "account_id":
#         rows = fetch_table_all("account", {"eq__account_id": int(value)}, page_size=50)
#     else:
#         rows = fetch_table_all("account", {f"eq__{field}": str(value)}, page_size=50)
#     return rows[0] if rows else None

# def fetch_feedback_by_orders(order_ids: List[int]) -> List[Dict[str, Any]]:
#     if not order_ids:
#         return []
#     out = []
#     for i in range(0, len(order_ids), 200):
#         chunk = order_ids[i:i+200]
#         out.extend(fetch_table_all("feedback", {"in__order_id": ",".join(map(str,chunk))}, page_size=500))
#     return out

# def fetch_order_process_logs(order_ids: List[int]) -> List[Dict[str, Any]]:
#     if not order_ids:
#         return []
#     out = []
#     for i in range(0, len(order_ids), 200):
#         chunk = order_ids[i:i+200]
#         out.extend(fetch_table_all("order_process_log", {"in__order_id": ",".join(map(str,chunk))}, page_size=500))
#     return out

# def agg_cashflow_daily(lo: str, hi: str) -> List[Tuple[str, float]]:
#     pays = fetch_payment_range(lo, hi, paid_only=True, end_inclusive=True)
#     buckets: Dict[str, float] = {}
#     for p in pays:
#         ts = p.get("action_at")
#         if not ts:
#             continue
#         d = ts[:10]
#         buckets[d] = buckets.get(d, 0.0) + _f(p.get("collected_amount", p.get("amount", 0)))
#     return sorted(buckets.items())

# def group_revenue_by_staff(pays: List[Dict[str, Any]]) -> Dict[int, float]:
#     agg: Dict[int, float] = {}
#     for p in pays:
#         if (p.get("status") or "").upper() not in PAID_STATUSES:
#             continue
#         sid = p.get("staff_id")
#         if sid is None:
#             continue
#         agg[int(sid)] = agg.get(int(sid), 0.0) + _f(p.get("collected_amount", p.get("amount", 0)))
#     return agg

# def agg_revenue_by_route(lo: str, hi: str) -> List[Tuple[str, float]]:
#     pays = fetch_payment_range(lo, hi, paid_only=True, end_inclusive=True)
#     oids = [int(p["order_id"]) for p in pays if p.get("order_id")]
#     if not oids:
#         return []
#     orders: Dict[int, Dict[str, Any]] = {}
#     for i in range(0, len(oids), 200):
#         ch = oids[i:i+200]
#         rows = fetch_table_all("orders", {"in__order_id": ",".join(map(str, ch))})
#         for r in rows:
#             orders[int(r["order_id"])] = r
#     route_map = fetch_routes_map()
#     agg: Dict[str, float] = {}
#     for p in pays:
#         oid = p.get("order_id")
#         if not oid or int(oid) not in orders:
#             continue
#         rid = orders[int(oid)].get("route_id")
#         name = route_map.get(int(rid), f"ROUTE#{rid}") if rid is not None else "UNKNOWN"
#         agg[name] = agg.get(name, 0.0) + _f(p.get("collected_amount", p.get("amount", 0)))
#     return sorted(agg.items(), key=lambda x: x[1], reverse=True)

# def agg_revenue_by_destination(lo: str, hi: str) -> List[Tuple[str, float]]:
#     pays = fetch_payment_range(lo, hi, paid_only=True, end_inclusive=True)
#     oids = [int(p["order_id"]) for p in pays if p.get("order_id")]
#     if not oids:
#         return []
#     orders: Dict[int, Dict[str, Any]] = {}
#     for i in range(0, len(oids), 200):
#         ch = oids[i:i+200]
#         rows = fetch_table_all("orders", {"in__order_id": ",".join(map(str, ch))})
#         for r in rows:
#             orders[int(r["order_id"])] = r
#     dest_map = fetch_destinations_map()
#     agg: Dict[str, float] = {}
#     for p in pays:
#         oid = p.get("order_id")
#         if not oid or int(oid) not in orders:
#             continue
#         did = orders[int(oid)].get("destination_id")
#         name = dest_map.get(int(did), f"DEST#{did}") if did is not None else "UNKNOWN"
#         agg[name] = agg.get(name, 0.0) + _f(p.get("collected_amount", p.get("amount", 0)))
#     return sorted(agg.items(), key=lambda x: x[1], reverse=True)

# def agg_aov_by_customer(lo: str, hi: str) -> List[Tuple[str, float, int]]:
#     orders = fetch_orders_range(lo, hi)
#     by: Dict[int, Tuple[float,int]] = {}
#     for o in orders:
#         cid = o.get("customer_id")
#         if cid is None:
#             continue
#         tot, cnt = by.get(int(cid), (0.0, 0))
#         by[int(cid)] = (tot + _f(o.get("final_price_order")), cnt+1)
#     out: List[Tuple[str,float,int]] = []
#     for cid,(tot,cnt) in by.items():
#         out.append((f"KH #{cid}", (tot/cnt if cnt else 0.0), cnt))
#     return sorted(out, key=lambda x: x[1], reverse=True)

# def agg_inventory_by_warehouse() -> List[Tuple[str,int]]:
#     rows = fetch_table_all("warehouse", {})
#     locs = fetch_table_all("warehouse_location", {})
#     locmap = {int(x["location_id"]): (x.get("name") or f"LOC#{x['location_id']}") for x in locs}
#     agg: Dict[str,int] = {}
#     for r in rows:
#         if (r.get("status") or "").upper() not in {"DA_NHAP_KHO","DANG_DOI_TRA"}:
#             continue
#         lid = r.get("location_id")
#         name = locmap.get(int(lid), f"LOC#{lid}") if lid is not None else "UNKNOWN"
#         agg[name] = agg.get(name, 0) + 1
#     return sorted(agg.items(), key=lambda x: x[1], reverse=True)

# def agg_flights_waiting_count(lo: str, hi: str) -> int:
#     rows = fetch_table_all("packing", {"gte__packed_date": lo, "lte__packed_date": hi, "eq__status":"CHO_BAY"})
#     return len(rows)

# # ======= NEW: KG theo tuyến có fallback route_id từ orders =======
# def agg_kg_by_route_in_period(dt_from_iso: str, dt_to_iso: str) -> List[Tuple[str, float]]:
#     """
#     Tính tổng kg theo tuyến trong [dt_from, dt_to) dựa trên warehouse.created_at.
#     Ưu tiên warehouse.route_id; nếu thiếu, fallback route_id từ orders qua order_id.
#     """
#     try:
#         wh_rows = fetch_warehouse_in_period(dt_from_iso, dt_to_iso)
#     except Exception:
#         wh_rows = []

#     # Thu thập order_id để join orders
#     oids = sorted({int(r["order_id"]) for r in wh_rows if r.get("order_id")})
#     orders_map: Dict[int, Dict[str, Any]] = {}
#     for i in range(0, len(oids), 200):
#         chunk = oids[i:i+200]
#         if not chunk:
#             continue
#         rows = fetch_table_all("orders", {"in__order_id": ",".join(map(str, chunk))})
#         for r in rows:
#             try:
#                 orders_map[int(r["order_id"])] = r
#             except Exception:
#                 pass

#     route_map = fetch_routes_map()
#     agg: Dict[str, float] = {}

#     for r in wh_rows:
#         try:
#             w = float(r.get("weight") or 0.0)
#         except Exception:
#             w = 0.0

#         rid = r.get("route_id")
#         if rid is None and r.get("order_id"):
#             od = orders_map.get(int(r["order_id"]))
#             if od:
#                 rid = od.get("route_id")

#         if rid is None:
#             name = "UNKNOWN"
#         else:
#             try:
#                 name = route_map.get(int(rid), f"ROUTE#{rid}")
#             except Exception:
#                 name = f"ROUTE#{rid}"

#         agg[name] = agg.get(name, 0.0) + w

#     # Sắp xếp theo kg giảm dần
#     return sorted(agg.items(), key=lambda x: x[1], reverse=True)

# # =============== INTENT ===============
# KEY_ORDERS_PURCHASED = ["don da mua", "don da mua hang", "da mua hang"]
# KEY_WAREHOUSE_INVENTORY = ["hang trong kho", "kho hien co", "ton kho"]
# KEY_FLIGHTS_WAITING = ["chuyen bay cho", "cho bay", "flight waiting"]
# # ====== MUA HỘ / KHO TQ / VẬN CHUYỂN / XỬ LÝ / BÁO CÁO ======
# MH_OVERVIEW_KEYS = [
#     "tong don mua ho hom nay", "tong don mua ho tuan nay", "tong don mua ho thang nay",
#     "tong so don mua ho hom nay", "tong so don mua ho tuan", "tong so don mua ho thang",
# ]
# MH_WAIT_TO_BUY_KEYS = ["bao nhieu don mua ho dang cho dat hang", "don cho dat hang", "don cho mua"]
# MH_PLACED_UNPAID_SELLER_KEYS = ["da dat nhung chua thanh toan cho seller", "chua thanh toan seller"]
# MH_WAIT_CN_WAREHOUSE_KEYS = ["ds don mua ho dang cho ve kho tq", "dang cho ve kho tq"]
# MH_ARRIVED_CN_WAIT_VN_KEYS = ["da ve kho tq cho van chuyen ve vn", "cho ve vn"]
# MH_PORT_CUSTOMS_KEYS = ["dang o cang", "dang o hai quan", "ket o hai quan"]
# MH_RT_STATUS_KEYS = ["trang thai tat ca don mua ho theo thoi gian thuc"]
# MH_SELLER_CANCEL_KEYS = ["don bi seller huy", "het hang seller"]
# MH_ISSUES_URGENT_KEYS = ["don mua ho co van de", "can xu ly gap"]

# # Seller/vendor mgmt
# SELLER_LIST_KEYS = ["ds shop thuong dat", "seller thuong dat hang"]
# SELLER_ONTIME_RATE_KEYS = ["ty le giao dung han cao", "shop giao dung han cao"]
# SELLER_NAME_INBOX_KEYS = ["shop", "seller"]  # sẽ parse tên sau
# SELLER_SLOW_CANCEL_KEYS = ["seller giao cham", "seller hay huy don"]
# SELLER_REPUTATION_KEYS = ["danh gia uy tin shop", "uy tin seller"]
# SELLER_AVG_TO_CN_KEYS = ["don tu shop mat bao lau ve kho", "thoi gian ve kho"]
# SELLER_BLACKLIST_KEYS = ["seller blacklist", "shop blacklist"]

# # CN warehouse
# CN_COUNT_KEYS = ["bao nhieu kien hang dang o kho tq"]
# CN_OF_ORDER_KEYS = ["hang cua don", "ve kho tq chua"]
# CN_PACKING_QUEUE_KEYS = ["ds hang cho dong goi o kho tq", "cho dong goi tq"]
# CN_OVERSTAY_KEYS = ["hang ton kho tq qua lau", "ton tq qua lau"]
# CN_STORAGE_COST_KEYS = ["chi phi luu kho tq thang nay"]
# CN_OVERLOAD_KEYS = ["kho tq qua tai", "qua tai kho tq"]
# CN_REAL_WEIGHT_KEYS = ["can nang thuc te hang ve kho tq", "kg thuc te kho tq"]

# # International shipping
# INTL_ON_THE_WAY_KEYS = ["dang tren duong tu tq ve vn", "dang tren duong ve vn"]
# INTL_LO_ETA_KEYS = ["lo hang", "du kien ve vn"]
# INTL_ORDER_IN_LO_KEYS = ["don nam trong lo hang nao"]
# INTL_STUCK_CUSTOMS_KEYS = ["bi ket o hai quan", "lo ket hai quan"]
# INTL_COST_MONTH_KEYS = ["chi phi van chuyen quoc te thang nay"]
# INTL_BEST_PARTNER_KEYS = ["doi tac van chuyen hieu qua nhat"]
# INTL_AVG_TIME_KEYS = ["thoi gian van chuyen trung binh tq vn"]
# INTL_TRACK_LO_KEYS = ["tracking lo hang", "dang o dau"]

# # Issues
# ISSUE_WRONG_SHORT_KEYS = ["giao thieu", "sai hang"]
# ISSUE_DAMAGED_KEYS = ["bi loi", "hu hong"]
# ISSUE_COMPLAINT_KEYS = ["khieu nai ve don", "khieu nai don"]
# ISSUE_REFUND_KEYS = ["can hoan tien", "hoan tien"]
# ISSUE_DISPUTE_KEYS = ["tranh chap", "tranh chap voi seller"]
# ISSUE_COMPENSATION_KEYS = ["boi thuong thiet hai"]
# ISSUE_RATE_KEYS = ["ty le don mua ho co van de"]

# # Reports
# REP_OVERVIEW_TODAY_KEYS = ["bao cao tong quan dich vu mua ho hom nay"]
# REP_BY_PLATFORM_KEYS = ["thong ke don mua ho theo san", "theo san tmdt"]
# REP_TOP_PRODUCT_KEYS = ["san pham duoc mua nhieu", "danh muc duoc mua nhieu"]
# REP_SEASONAL_TREND_KEYS = ["xu huong mua ho theo mua"]
# REP_AVG_HANDLE_TIME_KEYS = ["thoi gian xu ly don mua ho trung binh"]
# REP_SUCCESS_RATE_KEYS = ["ty le thanh cong cua dich vu mua ho"]
# REP_CHANNEL_COMPARE_KEYS = ["so sanh hieu qua cac kenh mua ho"]

# def classify_query(text: str) -> Tuple[str, Dict[str, Any], float]:
#     s = _fold(text)
#     m = _EMAIL_RE.search(text or "")
#     if m:
#         return ("profile_by", {"field":"email","value":m.group(0)}, 0.95)
#     if _PHONE_FULL_RE.fullmatch((text or "").strip()):
#         return ("profile_by", {"field":"phone","value":text.strip()}, 0.92)
#     code = extract_order_code_from_text(text or "")
#     if code:
#         return ("order_lookup", {"code": code}, 0.98)

#     if "doanh thu thang" in s or "tong doanh thu theo thang" in s or s.endswith("thang nay"):
#         return ("revenue_month", {}, 0.90)
#     if "doanh thu tuan" in s or s.endswith("tuan nay"):
#         return ("revenue_week", {}, 0.88)
#     if "doanh thu ngay" in s or "hom nay" in s or "hôm nay" in (text or "").lower():
#         return ("revenue_day", {}, 0.80)

#     if "cash flow" in s or "dong tien" in s:
#         return ("cashflow", {}, 0.85)
#     if "doanh thu theo tuyen" in s or "doanh thu theo tuyến" in (text or ""):
#         return ("revenue_by_route", {}, 0.85)
#     if "doanh thu theo diem den" in s:
#         return ("revenue_by_destination", {}, 0.80)
#     if "doanh thu theo nhan vien" in s or "nhan vien sale" in s:
#         return ("revenue_by_staff", {}, 0.90)
#     if "top 10 khach hang" in s:
#         return ("top_customers", {}, 0.90)
#     if "trung binh gia tri don hang" in s:
#         return ("aov_by_customer", {}, 0.85)
#     if "don cho mua" in s:
#         return ("orders_wait_buy", {}, 0.90)
#     if any(k in s for k in KEY_ORDERS_PURCHASED):
#         return ("orders_purchased", {}, 0.90)
#     if any(k in s for k in KEY_WAREHOUSE_INVENTORY):
#         return ("warehouse_inventory", {}, 0.85)
#     if any(k in s for k in KEY_FLIGHTS_WAITING):
#         return ("flights_waiting", {}, 0.85)

#     if "thong tin id" in s:
#         m = re.search(r"(\d+)", text or "")
#         if m:
#             return ("profile_by", {"field":"account_id","value":int(m.group(1))}, 0.85)
#     if "thong tin sdt" in s:
#         m = re.search(r"(\+?\d{9,13})", text or "")
#         if m:
#             return ("profile_by", {"field":"phone","value":m.group(1)}, 0.92)
#     if "thong tin email" in s:
#         m = _EMAIL_RE.search(text or "")
#         if m:
#             return ("profile_by", {"field":"email","value":m.group(0)}, 0.95)
    
#     # ==== MUA HỘ OVERVIEW ====
#     if any(k in s for k in MH_OVERVIEW_KEYS):
#         return ("mh_overview", {}, 0.90)
#     if any(k in s for k in MH_WAIT_TO_BUY_KEYS):
#         return ("mh_wait_to_buy", {}, 0.90)
#     if any(k in s for k in MH_PLACED_UNPAID_SELLER_KEYS):
#         return ("mh_placed_unpaid_seller", {}, 0.85)
#     if any(k in s for k in MH_WAIT_CN_WAREHOUSE_KEYS):
#         return ("mh_wait_cn_wh", {}, 0.85)
#     if any(k in s for k in MH_ARRIVED_CN_WAIT_VN_KEYS):
#         return ("mh_arrived_cn_wait_vn", {}, 0.85)
#     if any(k in s for k in MH_PORT_CUSTOMS_KEYS):
#         return ("mh_port_customs", {}, 0.85)
#     if any(k in s for k in MH_RT_STATUS_KEYS):
#         return ("mh_rt_status", {}, 0.85)
#     if any(k in s for k in MH_SELLER_CANCEL_KEYS):
#         return ("mh_seller_cancel", {}, 0.85)
#     if any(k in s for k in MH_ISSUES_URGENT_KEYS):
#         return ("mh_issues_urgent", {}, 0.85)

#     # ==== SELLER ====
#     if any(k in s for k in SELLER_LIST_KEYS):
#         return ("seller_list_freq", {}, 0.85)
#     if any(k in s for k in SELLER_ONTIME_RATE_KEYS):
#         return ("seller_ontime_top", {}, 0.85)
#     if any(k in s for k in SELLER_SLOW_CANCEL_KEYS):
#         return ("seller_slow_cancel", {}, 0.85)
#     if any(k in s for k in SELLER_REPUTATION_KEYS):
#         return ("seller_reputation", {}, 0.85)
#     if any(k in s for k in SELLER_AVG_TO_CN_KEYS):
#         return ("seller_avg_to_cn", {}, 0.85)
#     if any(k in s for k in SELLER_BLACKLIST_KEYS):
#         return ("seller_blacklist", {}, 0.85)

#     # ==== KHO TQ ====
#     if any(k in s for k in CN_COUNT_KEYS):
#         return ("cn_count", {}, 0.85)
#     if any(k in s for k in CN_OF_ORDER_KEYS):
#         return ("cn_of_order", {}, 0.85)
#     if any(k in s for k in CN_PACKING_QUEUE_KEYS):
#         return ("cn_packing_queue", {}, 0.85)
#     if any(k in s for k in CN_OVERSTAY_KEYS):
#         return ("cn_overstay", {}, 0.85)
#     if any(k in s for k in CN_STORAGE_COST_KEYS):
#         return ("cn_storage_cost", {}, 0.85)
#     if any(k in s for k in CN_OVERLOAD_KEYS):
#         return ("cn_overload", {}, 0.85)
#     if any(k in s for k in CN_REAL_WEIGHT_KEYS):
#         return ("cn_real_weight", {}, 0.85)

#     # ==== VẬN CHUYỂN Q.TẾ ====
#     if any(k in s for k in INTL_ON_THE_WAY_KEYS):
#         return ("intl_on_the_way", {}, 0.85)
#     if any(k in s for k in INTL_STUCK_CUSTOMS_KEYS):
#         return ("intl_stuck_customs", {}, 0.85)
#     if any(k in s for k in INTL_COST_MONTH_KEYS):
#         return ("intl_cost_month", {}, 0.85)
#     if any(k in s for k in INTL_BEST_PARTNER_KEYS):
#         return ("intl_best_partner", {}, 0.85)
#     if any(k in s for k in INTL_AVG_TIME_KEYS):
#         return ("intl_avg_time", {}, 0.85)

#     # ==== ISSUES ====
#     if any(k in s for k in ISSUE_WRONG_SHORT_KEYS):
#         return ("issue_wrong_short", {}, 0.85)
#     if any(k in s for k in ISSUE_DAMAGED_KEYS):
#         return ("issue_damaged", {}, 0.85)
#     if any(k in s for k in ISSUE_COMPLAINT_KEYS):
#         return ("issue_complaint", {}, 0.85)
#     if any(k in s for k in ISSUE_REFUND_KEYS):
#         return ("issue_refund", {}, 0.85)
#     if any(k in s for k in ISSUE_DISPUTE_KEYS):
#         return ("issue_dispute", {}, 0.85)
#     if any(k in s for k in ISSUE_COMPENSATION_KEYS):
#         return ("issue_compensation", {}, 0.85)
#     if any(k in s for k in ISSUE_RATE_KEYS):
#         return ("issue_rate", {}, 0.85)

#     # ==== REPORTS ====
#     if any(k in s for k in REP_OVERVIEW_TODAY_KEYS):
#         return ("rep_overview_today", {}, 0.85)
#     if any(k in s for k in REP_BY_PLATFORM_KEYS):
#         return ("rep_by_platform", {}, 0.85)
#     if any(k in s for k in REP_TOP_PRODUCT_KEYS):
#         return ("rep_top_product", {}, 0.85)
#     if any(k in s for k in REP_SEASONAL_TREND_KEYS):
#         return ("rep_seasonal_trend", {}, 0.85)
#     if any(k in s for k in REP_AVG_HANDLE_TIME_KEYS):
#         return ("rep_avg_handle_time", {}, 0.85)
#     if any(k in s for k in REP_SUCCESS_RATE_KEYS):
#         return ("rep_success_rate", {}, 0.85)
#     if any(k in s for k in REP_CHANNEL_COMPARE_KEYS):
#         return ("rep_channel_compare", {}, 0.85)

#     return ("unknown", {}, 0.40)

# # =============== FORMAT ===============
# def money_fmt(v: float) -> str:
#     try:
#         s = f"{int(round(v)):,.0f}".replace(",", ".")
#         return f"{s}₫"
#     except Exception:
#         return f"{v}₫"

# def _print_table(rows: List[Dict[str, Any]], headers: List[str]) -> str:
#     if not rows:
#         return "(khong co du lieu)"
#     w = {h: max(len(h), max(len(str(r.get(h,""))) for r in rows)) for h in headers}
#     line = "| " + " | ".join(h.ljust(w[h]) for h in headers) + " |"
#     sep  = "| " + " | ".join("-"*w[h] for h in headers) + " |"
#     out = [line, sep]
#     for r in rows:
#         out.append("| " + " | ".join(str(r.get(h,"")).ljust(w[h]) for h in headers) + " |")
#     return "\n".join(out)

# def format_snapshot(snap: Dict[str, Any]) -> str:
#     if not snap:
#         return "❌ Không tìm thấy đơn."
#     parts = []
#     parts.append(f"📦 Đơn: {snap.get('order_code')} (#{snap.get('order_id')})")
#     parts.append(f"   • Trạng thái: {snap.get('status')}")
#     parts.append(f"   • Thời gian tạo: {snap.get('created_at')}")
#     parts.append(f"   • Nhân viên phụ trách: {(snap.get('staff_name') or 'User')} ({snap.get('staff_id')}) — {snap.get('staff_label')}")
#     parts.append(f"   • Khách hàng: {(snap.get('customer_name') or '')} ({snap.get('customer_id')})")
#     parts.append(f"   • Tuyến: {snap.get('route_name')} (id={snap.get('route_id')})")
#     parts.append(f"   • Điểm đến: {snap.get('destination_name')} (id={snap.get('destination_id')})")
#     pay = snap.get("payments") or {}
#     parts.append(f"💰 Thanh toán: đã thu {money_fmt(pay.get('paid_total',0))} | còn chờ {money_fmt(pay.get('pending_total',0))} | giao dịch: {pay.get('count',0)}")
#     lg = snap.get("last_log")
#     if lg:
#         parts.append(f"📝 Log gần nhất: {lg.get('action')} @ {lg.get('timestamp')} (staff_id={lg.get('staff_id')})")
#     return "\n".join(parts)

# # =============== PROFILE ===============
# def person_full_profile(identifier_type: str, identifier_value: Union[str,int], recent_limit: int = 20) -> Optional[Dict[str, Any]]:
#     acct = fetch_account_by_field(identifier_type, identifier_value)
#     if not acct:
#         return None
#     account_id = int(acct['account_id'])
#     role = (acct.get('role') or '').upper()
#     profile: Dict[str, Any] = {
#         'account': acct, 'role': role, 'customer': None, 'staff': None,
#         'orders_recent': [], 'payments_recent': [],
#         'aggregates': {}, 'logs_recent': [], 'feedback_recent': [], 'warehouse_recent': []
#     }
#     cust_rows = fetch_table_all('customer', {'eq__account_id': account_id}, page_size=5)
#     if cust_rows:
#         profile['customer'] = cust_rows[0]
#     staff_rows = fetch_table_all('staff', {'eq__account_id': account_id}, page_size=5)
#     if staff_rows:
#         profile['staff'] = staff_rows[0]

#     orders = []
#     if profile['customer']:
#         cid = int(profile['customer']['account_id'])
#         orders.extend(fetch_table_all('orders', {'eq__customer_id': cid, 'order':'created_at','desc':True}, page_size=recent_limit))
#     if profile['staff']:
#         sid = int(profile['staff']['account_id'])
#         orders.extend(fetch_table_all('orders', {'eq__staff_id': sid, 'order':'created_at','desc':True}, page_size=recent_limit))
#     seen = {}; merged = []
#     for o in orders:
#         oid = int(o['order_id'])
#         if oid in seen:
#             continue
#         seen[oid]=1; merged.append(o)
#     profile['orders_recent'] = merged[:recent_limit]

#     pays = []
#     if profile['customer']:
#         cid = int(profile['customer']['account_id'])
#         pays = fetch_table_all('payment', {'eq__customer_id': cid, 'order':'action_at','desc':True}, page_size=recent_limit)
#     else:
#         oids = [int(o['order_id']) for o in profile['orders_recent']][:200]
#         if oids:
#             for i in range(0, len(oids), 100):
#                 ch = oids[i:i+100]
#                 pays.extend(fetch_table_all('payment', {'in__order_id': ','.join(map(str,ch)), 'order':'action_at','desc':True}, page_size=recent_limit))
#     pays = pays[:recent_limit]
#     profile['payments_recent'] = pays

#     total_paid = sum(_f(p.get('collected_amount', p.get('amount', 0))) for p in pays if (p.get('status') or '').upper() in PAID_STATUSES)
#     outstanding = sum(_f(p.get('amount',0)) for p in pays if (p.get('status') or '').upper() in {'CHO_THANH_TOAN','CHO_THANH_TOAN_SHIP'})
#     profile['aggregates'] = {'total_paid_recent': total_paid, 'outstanding_recent': outstanding, 'payments_count_recent': len(pays)}

#     oids = [int(o['order_id']) for o in profile['orders_recent']][:200]
#     logs = []
#     if oids:
#         for i in range(0, len(oids), 100):
#             ch = oids[i:i+100]
#             logs.extend(fetch_table_all('order_process_log', {'in__order_id': ','.join(map(str,ch)), 'order':'timestamp','desc':True}, page_size=recent_limit))
#     profile['logs_recent'] = logs[:recent_limit]

#     fbs = fetch_feedback_by_orders(oids) if oids else []
#     profile['feedback_recent'] = fbs[:recent_limit]

#     wh = []
#     if oids:
#         wh.extend(fetch_table_all('warehouse', {'in__order_id': ','.join(map(str,oids)), 'order':'created_at','desc':True}, page_size=recent_limit))
#     if profile['staff']:
#         wh.extend(fetch_table_all('warehouse', {'eq__staff_id': account_id, 'order':'created_at','desc':True}, page_size=recent_limit))
#     profile['warehouse_recent'] = wh[:recent_limit]

#     return profile


# # ===== Mua hộ: helpers phỏng đoán field/status (sửa theo schema thật) =====
# MH_ORDER_TYPE_FIELD = "order_type"     # TODO: nếu không có, để None → sẽ bỏ điều kiện
# MH_ORDER_TYPE_VALUE = "MUA_HO"         # TODO: thay bằng giá trị bạn dùng, hoặc None

# def _maybe_mh_params(base: Dict[str, Any]) -> Dict[str, Any]:
#     p = dict(base)
#     if MH_ORDER_TYPE_FIELD and MH_ORDER_TYPE_VALUE:
#         p[f"eq__{MH_ORDER_TYPE_FIELD}"] = MH_ORDER_TYPE_VALUE
#     return p

# def _count_orders(params: Dict[str, Any]) -> int:
#     rows = fetch_table_all("orders", params, page_size=200)
#     return len(rows)

# # ===== Kho TQ: suy luận theo 'country' hoặc 'location_name' =====
# def _is_cn_row(r: Dict[str, Any]) -> bool:
#     c = (r.get("country") or "").upper()
#     if c in {"CN", "CHN", "CHINA"}:
#         return True
#     name = (r.get("location_name") or r.get("name") or "").lower()
#     return ("tq" in name) or ("china" in name) or ("zhongguo" in name)

# # ======== HANDLERS: MUA HỘ OVERVIEW ========
# def h_mh_overview():
#     today_lo, today_hi = today_range_iso()
#     week_lo, week_hi = this_week_range_iso()
#     month_lo, month_hi = this_month_range_iso()

#     def _c(lo, hi):
#         return _count_orders(_maybe_mh_params({"gte__created_at": lo, "lt__created_at": hi}))

#     rows = [
#         {"window": f"{today_lo[:10]}→{today_hi[:10]}", "orders": _c(today_lo, today_hi)},
#         {"window": f"{week_lo[:10]}→{week_hi[:10]}", "orders": _c(week_lo, week_hi)},
#         {"window": f"{month_lo[:10]}→{month_hi[:10]}", "orders": _c(month_lo, month_hi)},
#     ]
#     tbl = _print_table(rows, ["window","orders"])
#     _emit(f"### Quản lý đơn mua hộ — Tổng số đơn\n{tbl}")

# def h_mh_wait_to_buy():
#     lo, hi = this_month_range_iso()
#     params = _maybe_mh_params({"gte__created_at": lo, "lt__created_at": hi, "eq__status": "CHO_MUA"})
#     rows = fetch_table_all("orders", params)
#     tbl = _print_table([{"order_code": r.get("order_code",""), "created_at": r.get("created_at","")} for r in rows], ["order_code","created_at"])
#     _emit(f"### Đơn mua hộ đang **chờ đặt hàng**\n{tbl}")

# def h_mh_placed_unpaid_seller():
#     lo, hi = this_month_range_iso()
#     # Phỏng đoán: thanh toán cho seller nằm ở payment.type = 'TO_SELLER' và status ∈ {CHO_THANH_TOAN...}
#     pay_rows = fetch_table_all("payment", {
#         "gte__action_at": lo, "lt__action_at": hi,
#         "eq__type": "TO_SELLER",  # TODO: đổi theo schema
#         "in__status": "CHO_THANH_TOAN,CHO_THANH_TOAN_SELLER"
#     })
#     # Lôi các order_id tương ứng
#     oids = sorted({int(p["order_id"]) for p in pay_rows if p.get("order_id")})
#     ord_map = {}
#     for i in range(0, len(oids), 200):
#         ch = oids[i:i+200]
#         ords = fetch_table_all("orders", _maybe_mh_params({"in__order_id": ",".join(map(str, ch))}))
#         for o in ords:
#             ord_map[int(o["order_id"])] = o
#     rows = [{"order_code": o.get("order_code",""), "status": o.get("status","")} for o in ord_map.values()]
#     tbl = _print_table(rows, ["order_code","status"])
#     _emit(f"### Đơn đã **đặt** nhưng **chưa thanh toán** cho seller\n{tbl}")

# def h_mh_wait_cn_wh():
#     lo, hi = this_month_range_iso()
#     wh = fetch_warehouse_in_period(lo, hi)
#     # Chọn các đơn mua hộ + chưa về VN (phỏng đoán status 'CHO_VAN_CHUYEN' ở CN)
#     oids = sorted({int(r["order_id"]) for r in wh if r.get("order_id") and _is_cn_row(r)})
#     out = []
#     for i in range(0, len(oids), 200):
#         ch = oids[i:i+200]
#         ords = fetch_table_all("orders", _maybe_mh_params({"in__order_id": ",".join(map(str, ch))}))
#         out.extend(ords)
#     rows = [{"order_code": o.get("order_code",""), "status": o.get("status","") } for o in out]
#     tbl = _print_table(rows, ["order_code","status"])
#     _emit(f"### Đơn mua hộ đang **chờ về kho TQ**\n{tbl}")

# def h_mh_arrived_cn_wait_vn():
#     lo, hi = this_month_range_iso()
#     # Giả định status đơn: ĐÃ VỀ KHO TQ & chờ vận chuyển: 'CHO_VE_VN' (sửa theo schema)
#     rows = fetch_table_all("orders", _maybe_mh_params({"gte__created_at": lo, "lt__created_at": hi, "eq__status": "CHO_VE_VN"}))
#     tbl = _print_table([{"order_code": r.get("order_code",""), "status": r.get("status","")} for r in rows], ["order_code","status"])
#     _emit(f"### Đã **về kho TQ**, chờ vận chuyển về VN\n{tbl}")

# def h_mh_port_customs():
#     lo, hi = this_month_range_iso()
#     # Giả định có bảng 'packing' hoặc 'flight' theo lô; status THONG_QUAN / DOCKED (sửa theo hệ của bạn)
#     rows = fetch_table_all("packing", {"gte__packed_date": lo, "lt__packed_date": hi, "in__status":"THONG_QUAN,DOCKED"})
#     tbl = _print_table([{"lo_id": r.get("packing_id",""), "status": r.get("status","")} for r in rows], ["lo_id","status"])
#     _emit(f"### Lô/đơn đang ở **cảng/hải quan**\n{tbl}")

# def h_mh_rt_status():
#     # “thời gian thực” sẽ phụ thuộc hạ tầng streaming; tạm trả snapshot theo giờ hiện tại
#     now = _now().isoformat(timespec="seconds")
#     rows = fetch_table_all("orders", _maybe_mh_params({"order":"updated_at","desc":True}))
#     rows = rows[:50]
#     tbl = _print_table([{"order_code": r.get("order_code",""), "status": r.get("status",""), "updated_at": r.get("updated_at","")} for r in rows], ["order_code","status","updated_at"])
#     _emit(f"### Trạng thái “gần thời gian thực” ({now})\n{tbl}")

# def h_mh_seller_cancel():
#     lo, hi = this_month_range_iso()
#     rows = fetch_table_all("orders", _maybe_mh_params({"gte__created_at": lo, "lt__created_at": hi, "in__status":"SELLER_HUY,HET_HANG"}))
#     tbl = _print_table([{"order_code": r.get("order_code",""), "status": r.get("status","")} for r in rows], ["order_code","status"])
#     _emit(f"### Đơn bị seller hủy / hết hàng\n{tbl}")

# def h_mh_issues_urgent():
#     lo, hi = this_month_range_iso()
#     # Phỏng đoán có bảng feedback/issue, hoặc flag trong orders
#     rows = fetch_table_all("feedback", {"gte__created_at": lo, "lt__created_at": hi, "in__issue_type":"GAP,URGENT"})
#     tbl = _print_table([{"order_id": r.get("order_id",""), "issue": r.get("issue_type",""), "note": r.get("note","")} for r in rows], ["order_id","issue","note"])
#     _emit(f"### Đơn mua hộ có **vấn đề khẩn cấp**\n{tbl}")

# # ======== SELLER ========
# def h_seller_list_freq():
#     # Tạm tính “thường xuyên” theo số lượng orders theo seller trong 90 ngày
#     now = _now(); start = (now - dt.timedelta(days=90)).isoformat()
#     orders = fetch_table_all("orders", _maybe_mh_params({"gte__created_at": start, "lt__created_at": now.isoformat()}))
#     agg: Dict[str,int] = {}
#     for o in orders:
#         seller = (o.get("seller_name") or "").strip()  # TODO: field seller
#         if not seller: continue
#         agg[seller] = agg.get(seller, 0) + 1
#     rows = [{"seller": k, "orders_90d": v} for k,v in sorted(agg.items(), key=lambda x: x[1], reverse=True)[:50]]
#     _emit("### Seller/Shop thường xuyên đặt hàng\n" + _print_table(rows, ["seller","orders_90d"]))

# def h_seller_ontime_top():
#     # Cần có field thời điểm đặt & về CN để tính on-time; placeholder theo field 'is_ontime'
#     rows = fetch_table_all("orders", _maybe_mh_params({"eq__is_ontime": True}))
#     agg: Dict[str, int] = {}
#     tot: Dict[str, int] = {}
#     for o in rows:
#         seller = (o.get("seller_name") or "").strip()
#         if not seller: continue
#         tot[seller] = tot.get(seller, 0) + 1
#         agg[seller] = agg.get(seller, 0) + 1
#     out = [{"seller": s, "ontime_rate": f"{(agg.get(s,0)/tot.get(s,1))*100:.1f}%"} for s in tot.keys()]
#     out.sort(key=lambda x: float(x["ontime_rate"].rstrip("%")), reverse=True)
#     _emit("### Seller có tỷ lệ giao đúng hạn cao (phỏng đoán)\n" + _print_table(out[:50], ["seller","ontime_rate"]))

# def h_seller_slow_cancel():
#     # Placeholder: dựa trên status
#     rows = fetch_table_all("orders", _maybe_mh_params({"in__status": "GIAO_CHAM,SELLER_HUY,HET_HANG"}))
#     agg: Dict[str,int] = {}
#     for o in rows:
#         seller = (o.get("seller_name") or "").strip()
#         if not seller: continue
#         agg[seller] = agg.get(seller, 0) + 1
#     out = [{"seller": k, "issues": v} for k,v in sorted(agg.items(), key=lambda x: x[1], reverse=True)[:50]]
#     _emit("### Seller hay giao chậm / hủy đơn\n" + _print_table(out, ["seller","issues"]))

# def h_seller_reputation():
#     # Placeholder: lấy điểm rating trung bình theo feedback
#     fb = fetch_table_all("feedback", {})
#     agg: Dict[str, List[float]] = {}
#     for r in fb:
#         seller = (r.get("seller_name") or "").strip()
#         if not seller: continue
#         score = _f(r.get("rating", 0))
#         agg.setdefault(seller, []).append(score)
#     rows = [{"seller": k, "avg_rating": f"{(sum(v)/len(v)):.2f}", "n": len(v)} for k,v in agg.items() if v]
#     rows.sort(key=lambda x: float(x["avg_rating"]), reverse=True)
#     _emit("### Đánh giá uy tín seller (phỏng đoán từ feedback)\n" + _print_table(rows[:50], ["seller","avg_rating","n"]))

# def h_seller_avg_to_cn():
#     # Placeholder: cần thời gian từ đặt → về CN
#     _emit("### Thời gian về kho CN trung bình theo seller\n(chưa đủ field thời điểm đặt/về, cần hoàn thiện mapping cột thực tế)")

# def h_seller_blacklist():
#     rows = fetch_table_all("seller_blacklist", {})  # TODO: nếu có bảng
#     tbl = _print_table([{"seller": r.get("seller",""), "reason": r.get("reason","") } for r in rows], ["seller","reason"])
#     _emit("### Seller bị blacklist\n" + (tbl or "(khong co du lieu)"))

# # ======== KHO TRUNG QUỐC ========
# def h_cn_count():
#     rows = fetch_table_all("warehouse", {})
#     cnt = sum(1 for r in rows if _is_cn_row(r))
#     _emit(f"### Kiện hàng đang ở kho TQ: **{cnt}**")

# def h_cn_of_order(s: str):
#     code = extract_order_code_from_text(s) or ""
#     od = order_snapshot_by_code(code) if code else None
#     if not od:
#         _emit("❌ Không tìm thấy đơn hoặc thiếu mã đơn."); return
#     oid = int(od["order_id"])
#     rows = fetch_table_all("warehouse", {"eq__order_id": oid, "order":"created_at","desc":True})
#     rows = [r for r in rows if _is_cn_row(r)]
#     tbl = _print_table([{"created_at": r.get("created_at",""), "status": r.get("status","")} for r in rows], ["created_at","status"])
#     _emit(f"### Hàng của đơn {od['order_code']} tại kho TQ\n" + (tbl or "(khong co du lieu)"))

# def h_cn_packing_queue():
#     rows = fetch_table_all("warehouse", {"eq__status":"CHO_DONG_GOI"})
#     rows = [r for r in rows if _is_cn_row(r)]
#     tbl = _print_table([{"order_id": r.get("order_id",""), "created_at": r.get("created_at","")} for r in rows], ["order_id","created_at"])
#     _emit("### Hàng chờ đóng gói ở kho TQ\n" + (tbl or "(khong co du lieu)"))

# def h_cn_overstay():
#     # Placeholder: quá 30 ngày ở CN
#     now = _now(); before = (now - dt.timedelta(days=30)).isoformat()
#     rows = fetch_table_all("warehouse", {"lt__created_at": before})
#     rows = [r for r in rows if _is_cn_row(r)]
#     _emit("### Hàng tồn kho TQ quá 30 ngày\n" + _print_table([{"order_id": r.get("order_id",""), "created_at": r.get("created_at","")} for r in rows], ["order_id","created_at"]))

# def h_cn_storage_cost():
#     # Placeholder: nếu có bảng cost_warehouse hoặc field fee
#     lo, hi = this_month_range_iso()
#     rows = fetch_table_all("warehouse_cost", {"gte__created_at": lo, "lt__created_at": hi})
#     total = sum(_f(r.get("amount")) for r in rows)
#     _emit(f"### Chi phí lưu kho TQ tháng này: {money_fmt(total)}")

# def h_cn_overload():
#     # Placeholder: phát hiện kho có >N kiện
#     rows = fetch_table_all("warehouse", {})
#     agg: Dict[str,int] = {}
#     for r in rows:
#         if not _is_cn_row(r): continue
#         name = (r.get("location_name") or "CN").strip()
#         agg[name] = agg.get(name, 0) + 1
#     ranked = sorted(agg.items(), key=lambda x: x[1], reverse=True)
#     _emit("### Kho TQ có nguy cơ quá tải\n" + _print_table([{"warehouse": k, "packages": v} for k,v in ranked], ["warehouse","packages"]))

# def h_cn_real_weight():
#     lo, hi = this_month_range_iso()
#     wh = fetch_warehouse_in_period(lo, hi)
#     w = sum(_f(r.get("weight")) for r in wh if _is_cn_row(r))
#     _emit(f"### Cân nặng thực tế hàng về kho TQ (tháng)\nTổng: **{w:.2f} kg**")

# # ======== VẬN CHUYỂN QUỐC TẾ ========
# def h_intl_on_the_way():
#     # Dựa vào packing/flight status “DANG_VAN_CHUYEN”
#     rows = fetch_table_all("packing", {"eq__status":"DANG_VAN_CHUYEN"})
#     tbl = _print_table([{"lo_id": r.get("packing_id",""), "eta_vn": r.get("eta_vn","")} for r in rows], ["lo_id","eta_vn"])
#     _emit("### Lô hàng đang trên đường TQ→VN\n" + (tbl or "(khong co du lieu)"))

# def h_intl_stuck_customs():
#     rows = fetch_table_all("packing", {"eq__status":"THONG_QUAN"})
#     tbl = _print_table([{"lo_id": r.get("packing_id",""), "updated_at": r.get("updated_at","")} for r in rows], ["lo_id","updated_at"])
#     _emit("### Lô đang thông quan/kẹt hải quan\n" + (tbl or "(khong co du lieu)"))

# def h_intl_cost_month():
#     lo, hi = this_month_range_iso()
#     rows = fetch_table_all("shipping_cost", {"gte__created_at": lo, "lt__created_at": hi})
#     total = sum(_f(r.get("amount")) for r in rows)
#     _emit(f"### Chi phí vận chuyển quốc tế tháng này: {money_fmt(total)}")

# def h_intl_best_partner():
#     # Placeholder: tổng chi phí/ thời gian giao theo đối tác
#     rows = fetch_table_all("packing", {})
#     agg: Dict[str, int] = {}
#     for r in rows:
#         partner = (r.get("partner") or "").strip()
#         if not partner: continue
#         agg[partner] = agg.get(partner, 0) + 1
#     tbl = _print_table([{"partner": k, "shipments": v} for k,v in sorted(agg.items(), key=lambda x: x[1], reverse=True)], ["partner","shipments"])
#     _emit("### Đối tác vận chuyển hiệu quả (phỏng đoán theo số chuyến)\n" + (tbl or "(khong co du lieu)"))

# def h_intl_avg_time():
#     # Placeholder: cần cột 'depart_cn_at' & 'arrive_vn_at'
#     _emit("### Thời gian vận chuyển trung bình TQ→VN\n(chưa đủ mốc thời gian trong DB để tính, cần mapping thực)")

# # ======== ISSUES ========
# def h_issue_wrong_short():
#     rows = fetch_table_all("feedback", {"eq__issue_type":"SAI_THIEU_HANG"})
#     _emit("### Đơn seller giao thiếu/sai hàng\n" + _print_table([{"order_id": r.get("order_id",""), "note": r.get("note","")} for r in rows], ["order_id","note"]))

# def h_issue_damaged():
#     rows = fetch_table_all("feedback", {"eq__issue_type":"HONG_HOAI"})
#     _emit("### Đơn hư hỏng trong vận chuyển\n" + _print_table([{"order_id": r.get("order_id",""), "note": r.get("note","")} for r in rows], ["order_id","note"]))

# def h_issue_complaint():
#     rows = fetch_table_all("feedback", {"eq__category":"COMPLAINT"})
#     _emit("### Khiếu nại đơn mua hộ\n" + _print_table([{"order_id": r.get("order_id",""), "note": r.get("note","")} for r in rows], ["order_id","note"]))

# def h_issue_refund():
#     rows = fetch_table_all("payment", {"eq__type":"REFUND", "in__status":"DA_THANH_TOAN,CHO_THANH_TOAN"})
#     _emit("### Đơn cần hoàn tiền cho khách\n" + _print_table([{"order_id": r.get("order_id",""), "amount": money_fmt(_f(r.get("amount")))} for r in rows], ["order_id","amount"]))

# def h_issue_dispute():
#     rows = fetch_table_all("feedback", {"eq__issue_type":"TRANH_CHAP"})
#     _emit("### Đơn đang tranh chấp với seller\n" + _print_table([{"order_id": r.get("order_id",""), "note": r.get("note","")} for r in rows], ["order_id","note"]))

# def h_issue_compensation():
#     rows = fetch_table_all("compensation", {})
#     _emit("### Xử lý đơn bồi thường thiệt hại\n" + _print_table([{"order_id": r.get("order_id",""), "amount": money_fmt(_f(r.get("amount")))} for r in rows], ["order_id","amount"]))

# def h_issue_rate():
#     # phỏng đoán: issues / tổng đơn tháng
#     lo, hi = this_month_range_iso()
#     total = _count_orders(_maybe_mh_params({"gte__created_at": lo, "lt__created_at": hi})) or 1
#     issues = fetch_table_all("feedback", {"gte__created_at": lo, "lt__created_at": hi})
#     rate = (len(issues) / total) * 100.0
#     _emit(f"### Tỷ lệ đơn mua hộ có vấn đề (tháng)\n**{rate:.2f}%**  ({len(issues)}/{total})")

# # ======== REPORTS ========
# def h_rep_overview_today():
#     lo, hi = today_range_iso()
#     cnt = _count_orders(_maybe_mh_params({"gte__created_at": lo, "lt__created_at": hi}))
#     _emit(f"### Báo cáo tổng quan dịch vụ mua hộ hôm nay\nTổng số đơn: **{cnt}**")

# def h_rep_by_platform():
#     lo, hi = this_month_range_iso()
#     rows = fetch_table_all("orders", _maybe_mh_params({"gte__created_at": lo, "lt__created_at": hi}))
#     agg: Dict[str,int] = {}
#     for r in rows:
#         plat = (r.get("platform") or "UNKNOWN").upper()  # TODO: field platform
#         agg[plat] = agg.get(plat, 0) + 1
#     _emit("### Thống kê đơn mua hộ theo sàn TMĐT (tháng)\n" + _print_table([{"platform": k, "orders": v} for k,v in agg.items()], ["platform","orders"]))

# def h_rep_top_product():
#     # Placeholder: cần bảng items của đơn
#     _emit("### Sản phẩm/danh mục được mua nhiều nhất\n(cần bảng order_items/category để thống kê)")

# def h_rep_seasonal_trend():
#     _emit("### Xu hướng mua hộ theo mùa\n(Cần dữ liệu nhiều tháng/quý để vẽ xu hướng)")

# def h_rep_avg_handle_time():
#     _emit("### Thời gian xử lý đơn mua hộ trung bình\n(Cần mốc thời gian các bước để tính SLA)")

# def h_rep_success_rate():
#     lo, hi = this_month_range_iso()
#     rows = fetch_table_all("orders", _maybe_mh_params({"gte__created_at": lo, "lt__created_at": hi}))
#     ok = sum(1 for r in rows if (r.get("status") or "").upper() in {"HOAN_TAT","DA_GIAO"})
#     rate = (ok / max(1, len(rows))) * 100.0
#     _emit(f"### Tỷ lệ thành công dịch vụ mua hộ (tháng)\n**{rate:.2f}%**  ({ok}/{len(rows)})")

# def h_rep_channel_compare():
#     _emit("### So sánh hiệu quả giữa các kênh mua hộ\n(Cần mapping kênh đặt/lead_source để tổng hợp)")

# # =============== CLI ===============
# BANNER = """
# Tiximax DB-CLI — hỏi gì đáp nấy (orders/payments/warehouse/packing/domestic/feedback…)
# Thoát: exit | quit | thoat
# """.strip()

# def main():
#     print(BANNER)
#     while True:
#         try:
#             s = input("\nBạn hỏi> ").strip()
#         except (EOFError, KeyboardInterrupt):
#             print("\nTạm biệt."); break
#         if not s:
#             continue
#         if _fold(s) in {"thoat","exit","quit"}:
#             print("Tạm biệt."); break

#         intent, params, conf = classify_query(s)

#         # Order lookup / fallback unknown → thử mã đơn
#         if intent in {"order_lookup","unknown"}:
#             code = extract_order_code_from_text(s)
#             if code:
#                 snap = order_snapshot_by_code(code)
#                 print(format_snapshot(snap))
#                 if snap is None:
#                     print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})")
#                 continue
#             if intent == "unknown":
#                 print("⚠️  Chưa nhận diện được ý định. Thử: 'doanh thu tháng này' / mã đơn 'OD2025…' / 'thông tin email a@b.com'")
#                 continue

#         # Profile by email/phone/id
#         if intent == "profile_by":
#             fld, val = params["field"], params["value"]
#             prof = person_full_profile(fld, val, recent_limit=20)
#             if not prof:
#                 print("❌ Không tìm thấy tài khoản."); continue
#             acct = prof["account"]
#             role = (acct.get("role") or "").upper()
#             print(f"👤 Account #{acct.get('account_id')} — {acct.get('name','N/A')}")
#             print(f"   • Email: {acct.get('email','N/A')} | Phone: {acct.get('phone','N/A')} | Username: {acct.get('username','N/A')}")
#             print(f"   • Role: {role or 'N/A'} | Status: {acct.get('status','N/A')}")
#             if prof.get("staff"):
#                 st = prof["staff"]
#                 print(f"🧑‍💼 Staff: code={st.get('staff_code','')} | location={st.get('location','')} | dept={st.get('department','')}")
#             ag = prof["aggregates"]
#             print(f"💰 Payments recent: paid={money_fmt(ag.get('total_paid_recent',0))} | outstanding={money_fmt(ag.get('outstanding_recent',0))} | count={ag.get('payments_count_recent',0)}")
#             ords = [{"order_code": o.get("order_code",""), "status": o.get("status","")} for o in prof["orders_recent"][:10]]
#             if ords:
#                 print("📦 Orders recent: " + ", ".join(f"{o['order_code']}({o['status']})" for o in ords))
#             print(f"🏬 Warehouse records recent: {len(prof['warehouse_recent'])}")
#             print(f"📝 Logs recent: {len(prof['logs_recent'])}")
#             print(f"⭐ Feedback recent: {len(prof['feedback_recent'])}")
#             continue

#         # Revenue (month/week/day) with paid/unpaid table; month → kg by route
#         if intent in {"revenue_month","revenue_week","revenue_day"}:
#             now = _now()
#             if intent == "revenue_month":
#                 forced = resolve_month_from_text(s, now, VN_TZ)  # ƯU TIÊN tháng user nhập
#                 if forced:
#                     lo, hi = forced
#                 else:
#                     lo, hi = this_month_range_iso()
#                 label = "tháng"
#             elif intent == "revenue_week":
#                 lo, hi = this_week_range_iso(); label = "tuần"
#             else:
#                 lo, hi = today_range_iso(); label = "ngày"

#             pays = fetch_payment_range(lo, hi, paid_only=True, end_inclusive=False)
#             total = sum_revenue_from_payments(pays)
#             print(f"💰 Doanh thu {lo} → {hi}: {money_fmt(total)} (giao dịch: {len(pays)})")

#             def _rows(dt_from_iso: str, dt_to_iso: str):
#                 paid = fetch_payment_range(dt_from_iso, dt_to_iso, paid_only=True, end_inclusive=False)
#                 up = fetch_table_all("payment", {
#                     "gte__action_at": dt_from_iso, "lt__action_at": dt_to_iso,
#                     "in__status":"CHO_THANH_TOAN,CHO_THANH_TOAN_SHIP"
#                 })
#                 return [{
#                     "window": f"{dt_from_iso[:10]}→{dt_to_iso[:10]}",
#                     "paid_orders": len(paid),
#                     "paid_amount": money_fmt(sum_revenue_from_payments(paid)),
#                     "unpaid_orders": len(up),
#                     "unpaid_amount": money_fmt(sum(_f(r.get('amount')) for r in up)),
#                 }]

#             print(f"\n▶ Theo {label}")
#             print(_print_table(_rows(lo, hi), ["window","paid_orders","paid_amount","unpaid_orders","unpaid_amount"]))

#             if intent == "revenue_month":
#                 kg_rows = agg_kg_by_route_in_period(lo, hi)
#                 print("\n▶ Số kg theo tuyến (theo warehouse.created_at trong tháng)")
#                 print(_print_table([{"route": k, "kg": round(v, 2)} for k, v in kg_rows], ["route","kg"]) if kg_rows else "(khong co du lieu)")

#             print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})")
#             continue
        
#         # Others
#         if intent == "cashflow":
#             lo, hi = this_month_range_iso()
#             pairs = agg_cashflow_daily(lo, hi)
#             print(_print_table([{"date": d, "collected": money_fmt(v)} for d,v in pairs], ["date","collected"]) or "(khong co du lieu)")
#             print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue

#         if intent == "revenue_by_staff":
#             lo, hi = this_month_range_iso()
#             pays = fetch_payment_range(lo, hi, paid_only=True, end_inclusive=False)
#             agg = group_revenue_by_staff(pays)
#             rows = []
#             for sid, amt in sorted(agg.items(), key=lambda x: x[1], reverse=True):
#                 acct = fetch_account_by_id(int(sid)) or {}
#                 rows.append({"staff_id": sid, "name": acct.get("name",""), "revenue": money_fmt(amt)})
#             print(_print_table(rows, ["staff_id","name","revenue"]) if rows else "(khong co du lieu)")
#             print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue

#         if intent == "revenue_by_route":
#             lo, hi = this_month_range_iso()
#             rows = [{"route": k, "revenue": money_fmt(v)} for k,v in agg_revenue_by_route(lo, hi)]
#             print(_print_table(rows, ["route","revenue"]) if rows else "(khong co du lieu)")
#             print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue

#         if intent == "revenue_by_destination":
#             lo, hi = this_month_range_iso()
#             rows = [{"destination": k, "revenue": money_fmt(v)} for k,v in agg_revenue_by_destination(lo, hi)]
#             print(_print_table(rows, ["destination","revenue"]) if rows else "(khong co du lieu)")
#             print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue

#         if intent == "top_customers":
#             lo, hi = this_month_range_iso()
#             pays = fetch_payment_range(lo, hi, paid_only=True, end_inclusive=False)
#             by: Dict[int,float] = {}
#             for p in pays:
#                 cid = p.get("customer_id")
#                 if cid is None:
#                     continue
#                 by[int(cid)] = by.get(int(cid), 0.0) + _f(p.get("collected_amount", p.get("amount", 0)))
#             rows = []
#             for cid, paid in sorted(by.items(), key=lambda x: x[1], reverse=True)[:10]:
#                 acct = fetch_account_by_id(int(cid)) or {}
#                 rows.append({"customer_id": cid, "name": f"{acct.get('name','')} ({cid})", "paid": money_fmt(paid)})
#             print(_print_table(rows, ["customer_id","name","paid"]) if rows else "(khong co du lieu)")
#             print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue

#         if intent == "aov_by_customer":
#             lo, hi = this_month_range_iso()
#             rows = [{"customer": k, "AOV": money_fmt(v), "orders": n} for (k,v,n) in agg_aov_by_customer(lo, hi)]
#             print(_print_table(rows, ["customer","AOV","orders"]) if rows else "(khong co du lieu)")
#             print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue

#         if intent == "orders_wait_buy":
#             lo, hi = this_month_range_iso()
#             rows = fetch_orders_range(lo, hi, status="CHO_MUA")
#             table = [{"order_code": r.get("order_code",""), "status": r.get("status",""), "created_at": r.get("created_at","")} for r in rows]
#             print(_print_table(table, ["order_code","status","created_at"]) if table else "(khong co du lieu)")
#             print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue

#         if intent == "orders_purchased":
#             lo, hi = this_month_range_iso()
#             rows = fetch_orders_range(lo, hi, status="DA_MUA_HANG")
#             if not rows:
#                 logs = fetch_table_all("order_process_log", {"gte__timestamp": lo, "lt__timestamp": hi, "eq__action":"DA_MUA_HANG"})
#                 oids = sorted({int(l["order_id"]) for l in logs if l.get("order_id")})
#                 rows = []
#                 for i in range(0, len(oids), 200):
#                     ch = oids[i:i+200]
#                     rows.extend(fetch_table_all("orders", {"in__order_id": ",".join(map(str, ch))}))
#             table = [{"order_code": r.get("order_code",""), "status": r.get("status",""), "created_at": r.get("created_at","")} for r in rows]
#             print(_print_table(table, ["order_code","status","created_at"]) if table else "(khong co du lieu)")
#             print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue

#         if intent == "warehouse_inventory":
#             rows = agg_inventory_by_warehouse()
#             print(_print_table([{"location": k, "packages": v} for k,v in rows], ["location","packages"]) if rows else "(khong co du lieu)")
#             print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue

#         if intent == "flights_waiting":
#             lo, hi = this_month_range_iso()
#             cnt = agg_flights_waiting_count(lo, hi)
#             print(f"✈️  Chuyến bay đang CHỜ: {cnt}")
#             print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
#                 # ====== MUA HỘ ======
#         if intent == "mh_overview":
#             h_mh_overview(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
#         if intent == "mh_wait_to_buy":
#             h_mh_wait_to_buy(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
#         if intent == "mh_placed_unpaid_seller":
#             h_mh_placed_unpaid_seller(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
#         if intent == "mh_wait_cn_wh":
#             h_mh_wait_cn_wh(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
#         if intent == "mh_arrived_cn_wait_vn":
#             h_mh_arrived_cn_wait_vn(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
#         if intent == "mh_port_customs":
#             h_mh_port_customs(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
#         if intent == "mh_rt_status":
#             h_mh_rt_status(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
#         if intent == "mh_seller_cancel":
#             h_mh_seller_cancel(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
#         if intent == "mh_issues_urgent":
#             h_mh_issues_urgent(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue

#         # ====== SELLER ======
#         if intent == "seller_list_freq":
#             h_seller_list_freq(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
#         if intent == "seller_ontime_top":
#             h_seller_ontime_top(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
#         if intent == "seller_slow_cancel":
#             h_seller_slow_cancel(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
#         if intent == "seller_reputation":
#             h_seller_reputation(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
#         if intent == "seller_avg_to_cn":
#             h_seller_avg_to_cn(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
#         if intent == "seller_blacklist":
#             h_seller_blacklist(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue

#         # ====== KHO TQ ======
#         if intent == "cn_count":
#             h_cn_count(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
#         if intent == "cn_of_order":
#             h_cn_of_order(s); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
#         if intent == "cn_packing_queue":
#             h_cn_packing_queue(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
#         if intent == "cn_overstay":
#             h_cn_overstay(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
#         if intent == "cn_storage_cost":
#             h_cn_storage_cost(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
#         if intent == "cn_overload":
#             h_cn_overload(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
#         if intent == "cn_real_weight":
#             h_cn_real_weight(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue

#         # ====== VẬN CHUYỂN Q.TẾ ======
#         if intent == "intl_on_the_way":
#             h_intl_on_the_way(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
#         if intent == "intl_stuck_customs":
#             h_intl_stuck_customs(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
#         if intent == "intl_cost_month":
#             h_intl_cost_month(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
#         if intent == "intl_best_partner":
#             h_intl_best_partner(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
#         if intent == "intl_avg_time":
#             h_intl_avg_time(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue

#         # ====== ISSUES ======
#         if intent == "issue_wrong_short":
#             h_issue_wrong_short(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
#         if intent == "issue_damaged":
#             h_issue_damaged(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
#         if intent == "issue_complaint":
#             h_issue_complaint(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
#         if intent == "issue_refund":
#             h_issue_refund(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
#         if intent == "issue_dispute":
#             h_issue_dispute(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
#         if intent == "issue_compensation":
#             h_issue_compensation(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
#         if intent == "issue_rate":
#             h_issue_rate(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue

#         # ====== REPORTS ======
#         if intent == "rep_overview_today":
#             h_rep_overview_today(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
#         if intent == "rep_by_platform":
#             h_rep_by_platform(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
#         if intent == "rep_top_product":
#             h_rep_top_product(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
#         if intent == "rep_seasonal_trend":
#             h_rep_seasonal_trend(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
#         if intent == "rep_avg_handle_time":
#             h_rep_avg_handle_time(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
#         if intent == "rep_success_rate":
#             h_rep_success_rate(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
#         if intent == "rep_channel_compare":
#             h_rep_channel_compare(); print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue

#         print("⚠️  Chưa nhận diện được ý định. Thử: 'doanh thu tháng này' / mã đơn 'OD2025…' / 'thông tin email a@b.com'")

# if __name__ == "__main__":
#     main()




# from __future__ import annotations
# import os, re, unicodedata, datetime as dt
# from typing import Dict, Any, Optional, List, Tuple, Union
# import requests

# # =========================
# # Cấu hình
# # =========================
# try:
#     from .config_supabase import BASE_API_URL, API_KEY, DEFAULT_PAGE_SIZE, VN_TZ
# except Exception:
#     BASE_API_URL = os.environ.get("BASE_API_URL", "https://damages-creature-webcast-intention.trycloudflare.com").rstrip("/")
#     API_KEY = os.environ.get("API_KEY", "super-secret-xyz").strip()
#     DEFAULT_PAGE_SIZE = int(os.environ.get("DEFAULT_PAGE_SIZE", "200"))
#     try:
#         import pytz
#         VN_TZ = pytz.timezone(os.environ.get("VN_TZ","Asia/Ho_Chi_Minh"))
#     except Exception:
#         VN_TZ = dt.timezone(dt.timedelta(hours=7))

# # Tùy chọn Gemini polish
# GEMINI_API_KEY = os.environ.get("GOOGLE_API_KEY", "").strip()
# GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash").strip()
# USE_GEMINI = bool(GEMINI_API_KEY)

# # =========================
# # Gemini helper (tùy chọn)
# # =========================
# def _gemini_rewrite(text: str) -> str:
#     """
#     Dùng Gemini để chỉnh văn phong/ngữ điệu, KHÔNG thêm bịa.
#     Nếu không có key/thư viện → trả lại text gốc.
#     """
#     if not USE_GEMINI or not text:
#         return text
#     try:
#         import google.generativeai as genai
#         genai.configure(api_key=GEMINI_API_KEY)
#         model = genai.GenerativeModel(GEMINI_MODEL)
#         sysrule = (
#             "Bạn là trợ lý tiếng Việt. Hãy chỉnh lại câu trả lời cho:\n"
#             "- ngắn gọn, mạch lạc, đúng số liệu\n"
#             "- không thêm/bịa thông tin ngoài nội dung đã có\n"
#             "- giữ nguyên bảng, số liệu, đơn vị (₫, kg, %)\n"
#             "- sửa lỗi chính tả/biểu đạt nhẹ nếu cần\n"
#         )
#         prompt = f"{sysrule}\n---\nNội dung cần chuẩn hoá:\n{text}\n---\nChỉ trả về nội dung đã chỉnh."
#         resp = model.generate_content(prompt)
#         out = (resp.text or "").strip()
#         return out if out else text
#     except Exception:
#         return text

# # =========================
# # Thời gian & tháng
# # =========================
# import re as _re
# try:
#     from dateutil.relativedelta import relativedelta
# except Exception:
#     class relativedelta:
#         def __init__(self, months=0):
#             self.months = months
#         def __radd__(self, d):
#             y, m = d.year, d.month + self.months
#             while m > 12: m -= 12; y += 1
#             while m < 1:  m += 12; y -= 1
#             return d.replace(year=y, month=m)

# _MONTH_RANGE_RE = _re.compile(
#     r"(?:thang|tháng)\s*(?P<m>\d{1,2})"
#     r"(?:\s*[/\-]\s*(?P<y1>\d{2,4}))?"
#     r"(?:\s*năm\s*(?P<y2>\d{4}))?",
#     _re.IGNORECASE | _re.UNICODE
# )

# def _normalize_year(y: int) -> int:
#     return y + 2000 if y < 100 else y

# def _month_bounds(year: int, month: int, tz) -> tuple[str, str]:
#     start = dt.datetime(year, month, 1, tzinfo=tz)
#     end = start + relativedelta(months=1)
#     return start.isoformat(), end.isoformat()

# def resolve_month_from_text(s: str, now, tz) -> tuple[str, str] | None:
#     m = _MONTH_RANGE_RE.search(s or "")
#     if not m: return None
#     month = int(m.group("m"))
#     y2 = m.group("y2"); y1 = m.group("y1")
#     year = _normalize_year(int(y2 or y1 or now.year))
#     if not (1 <= month <= 12): return None
#     return _month_bounds(year, month, tz)

# def _now():
#     try:
#         return dt.datetime.now(VN_TZ)
#     except Exception:
#         return dt.datetime.now()

# def this_month_range_iso() -> Tuple[str,str]:
#     now = _now()
#     start = dt.datetime(now.year, now.month, 1, 0, 0, 0, tzinfo=now.tzinfo)
#     end = (start + relativedelta(months=1))
#     return start.isoformat(), end.isoformat()

# def this_week_range_iso() -> Tuple[str,str]:
#     now = _now()
#     start = (now - dt.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
#     end = start + dt.timedelta(days=7)
#     return start.isoformat(), end.isoformat()

# def today_range_iso() -> Tuple[str,str]:
#     now = _now()
#     start = now.replace(hour=0, minute=0, second=0, microsecond=0)
#     end = start + dt.timedelta(days=1)
#     return start.isoformat(), end.isoformat()

# # =========================
# # Regex & helpers
# # =========================
# def _fold(s: str) -> str:
#     s = (s or "").strip()
#     t = unicodedata.normalize("NFD", s.lower())
#     return "".join(ch for ch in t if unicodedata.category(ch) != "Mn")

# _EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# _PHONE_FULL_RE = re.compile(r"^\+?\d{9,13}$")
# _ORDER_CODE_INLINE_RE = re.compile(r"\b(ORD[A-Z0-9\-]*|[A-Z]{2,5}[A-Z0-9\-]*\d+)\b", re.IGNORECASE)

# def extract_order_code_from_text(text: str) -> Optional[str]:
#     m = _ORDER_CODE_INLINE_RE.search(text or "")
#     return m.group(1).upper() if m else None

# # =========================
# # API layer
# # =========================
# API_MAX_LIMIT = 500
# PAID_STATUSES = {"DA_THANH_TOAN", "DA_THANH_TOAN_SHIP"}
# UNPAID_STATUSES = {"CHO_THANH_TOAN", "CHO_THANH_TOAN_SHIP"}

# def _headers() -> Dict[str, str]:
#     return {"X-API-Key": API_KEY, "Accept": "application/json"}

# def _clamp(n: Optional[int]) -> int:
#     try:
#         n = int(n or DEFAULT_PAGE_SIZE)
#     except Exception:
#         n = DEFAULT_PAGE_SIZE
#     return max(1, min(API_MAX_LIMIT, n))

# def fetch_table_once(table: str, params: Optional[Dict[str, Any]] = None, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0) -> Dict[str, Any]:
#     url = f"{BASE_API_URL}/api/{table}"
#     q = {"limit": _clamp(limit), "offset": max(0, int(offset))}
#     if params:
#         q.update(params)
#     resp = requests.get(url, headers=_headers(), params=q, timeout=30)
#     if resp.status_code != 200:
#         raise requests.HTTPError(f"POSTGREST {table}: {resp.status_code} {resp.text[:240]}")
#     return resp.json()

# def fetch_table_all(table: str, params: Optional[Dict[str, Any]] = None, page_size: int = DEFAULT_PAGE_SIZE, max_pages: int = 200) -> List[Dict[str, Any]]:
#     out, offset, step = [], 0, _clamp(page_size)
#     for _ in range(max_pages):
#         data = fetch_table_once(table, params=params, limit=step, offset=offset)
#         rows = data.get("data") or []
#         out.extend(rows)
#         if len(rows) < step:
#             break
#         offset += step
#     return out

# # =========================
# # Lookup helpers & aggregates
# # =========================
# def _f(x):
#     try: return float(x or 0)
#     except: return 0.0

# def fetch_payment_range(lo: str, hi: str, statuses: Optional[set]=None, end_inclusive: bool=False) -> List[Dict[str, Any]]:
#     p = {"gte__action_at": lo, "order": "action_at", "desc": False}
#     p["lte__action_at" if end_inclusive else "lt__action_at"] = hi
#     if statuses:
#         p["in__status"] = ",".join(sorted(statuses))
#     return fetch_table_all("payment", params=p)

# def sum_revenue_from_payments(payments: List[Dict[str, Any]]) -> float:
#     s = 0.0
#     for p in payments:
#         s += _f(p.get("collected_amount", p.get("amount", 0))) if (p.get("status") or "").upper() in PAID_STATUSES else 0.0
#     return s

# def fetch_orders_range(lo: str, hi: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
#     p = {"gte__created_at": lo, "lt__created_at": hi}
#     if status: p["eq__status"] = status
#     return fetch_table_all("orders", params=p)

# def fetch_routes_map() -> Dict[int, str]:
#     rows = fetch_table_all("route", {})
#     return {int(r["route_id"]): (r.get("name") or f"ROUTE#{r['route_id']}") for r in rows}

# def fetch_destinations_map() -> Dict[int, str]:
#     rows = fetch_table_all("destination", {})
#     return {int(r["destination_id"]): (r.get("destination_name") or f"DEST#{r['destination_id']}") for r in rows}

# def fetch_account_by_id(aid: int) -> Optional[Dict[str, Any]]:
#     rows = fetch_table_all("account", {"eq__account_id": int(aid)}, page_size=50)
#     return rows[0] if rows else None

# def fetch_staff_by_id(aid: int) -> Optional[Dict[str, Any]]:
#     rows = fetch_table_all("staff", {"eq__account_id": int(aid)}, page_size=50)
#     return rows[0] if rows else None

# def fetch_order_by_code(code: str) -> Optional[Dict[str, Any]]:
#     rows = fetch_table_all("orders", {"eq__order_code": code}, page_size=50)
#     if not rows and code.isdigit():
#         rows = fetch_table_all("orders", {"eq__order_id": int(code)}, page_size=50)
#     return rows[0] if rows else None

# def payments_by_order(oid: int) -> List[Dict[str, Any]]:
#     return fetch_table_all("payment", {"eq__order_id": int(oid)})

# def process_logs_by_order(oid: int) -> List[Dict[str, Any]]:
#     return fetch_table_all("order_process_log", {"eq__order_id": int(oid), "order":"timestamp", "desc":True})

# def order_snapshot_by_code(code: str) -> Optional[Dict[str, Any]]:
#     od = fetch_order_by_code(code)
#     if not od: return None
#     oid = int(od["order_id"])
#     pays = payments_by_order(oid)
#     paid = sum(_f(p.get("collected_amount", p.get("amount", 0))) for p in pays if (p.get("status") or "").upper() in PAID_STATUSES)
#     pending = sum(_f(p.get("amount", 0)) for p in pays if (p.get("status") or "").upper() in UNPAID_STATUSES)
#     logs = process_logs_by_order(oid)
#     last_log = logs[0] if logs else None
#     routes = fetch_routes_map(); dests = fetch_destinations_map()
#     return {
#         "order_id": oid,
#         "order_code": od.get("order_code"),
#         "status": od.get("status"),
#         "created_at": od.get("created_at"),
#         "staff_id": od.get("staff_id"),
#         "staff_label": (fetch_staff_by_id(int(od.get("staff_id"))) or {}).get("staff_code") if od.get("staff_id") else None,
#         "staff_name": (fetch_account_by_id(int(od.get("staff_id"))) or {}).get("name") if od.get("staff_id") else None,
#         "customer_id": od.get("customer_id"),
#         "customer_name": (fetch_account_by_id(int(od.get("customer_id"))) or {}).get("name") if od.get("customer_id") else None,
#         "route_id": od.get("route_id"),
#         "route_name": routes.get(int(od.get("route_id")), f"ROUTE#{od.get('route_id')}") if od.get("route_id") else None,
#         "destination_id": od.get("destination_id"),
#         "destination_name": dests.get(int(od.get("destination_id")), f"DEST#{od.get('destination_id')}") if od.get("destination_id") else None,
#         "payments": {"count": len(pays), "paid_total": paid, "pending_total": pending},
#         "last_log": {"action": last_log.get("action"), "timestamp": last_log.get("timestamp"), "staff_id": last_log.get("staff_id")} if last_log else None
#     }

# def fetch_account_by_field(field: str, value: Union[str,int]) -> Optional[Dict[str, Any]]:
#     if field == "account_id":
#         rows = fetch_table_all("account", {"eq__account_id": int(value)}, page_size=50)
#     else:
#         rows = fetch_table_all("account", {f"eq__{field}": str(value)}, page_size=50)
#     return rows[0] if rows else None

# def fetch_feedback_by_orders(order_ids: List[int]) -> List[Dict[str, Any]]:
#     if not order_ids: return []
#     out = []
#     for i in range(0, len(order_ids), 200):
#         chunk = order_ids[i:i+200]
#         out.extend(fetch_table_all("feedback", {"in__order_id": ",".join(map(str,chunk))}, page_size=500))
#     return out

# def fetch_order_process_logs(order_ids: List[int]) -> List[Dict[str, Any]]:
#     if not order_ids: return []
#     out = []
#     for i in range(0, len(order_ids), 200):
#         chunk = order_ids[i:i+200]
#         out.extend(fetch_table_all("order_process_log", {"in__order_id": ",".join(map(str,chunk))}, page_size=500))
#     return out

# def agg_cashflow_daily(lo: str, hi: str) -> List[Tuple[str, float]]:
#     pays = fetch_payment_range(lo, hi, statuses=PAID_STATUSES, end_inclusive=True)
#     buckets: Dict[str, float] = {}
#     for p in pays:
#         ts = p.get("action_at")
#         if not ts: continue
#         d = ts[:10]
#         buckets[d] = buckets.get(d, 0.0) + _f(p.get("collected_amount", p.get("amount", 0)))
#     return sorted(buckets.items())

# def group_revenue_by_staff(pays: List[Dict[str, Any]]) -> Dict[int, float]:
#     agg: Dict[int, float] = {}
#     for p in pays:
#         if (p.get("status") or "").upper() not in PAID_STATUSES: 
#             continue
#         sid = p.get("staff_id")
#         if sid is None: continue
#         agg[int(sid)] = agg.get(int(sid), 0.0) + _f(p.get("collected_amount", p.get("amount", 0)))
#     return agg

# def agg_revenue_by_route(lo: str, hi: str) -> List[Tuple[str, float]]:
#     pays = fetch_payment_range(lo, hi, statuses=PAID_STATUSES, end_inclusive=True)
#     oids = [int(p["order_id"]) for p in pays if p.get("order_id")]
#     if not oids: return []
#     orders: Dict[int, Dict[str, Any]] = {}
#     for i in range(0, len(oids), 200):
#         ch = oids[i:i+200]
#         rows = fetch_table_all("orders", {"in__order_id": ",".join(map(str, ch))})
#         for r in rows: orders[int(r["order_id"])] = r
#     route_map = fetch_routes_map()
#     agg: Dict[str, float] = {}
#     for p in pays:
#         oid = p.get("order_id")
#         if not oid or int(oid) not in orders: continue
#         rid = orders[int(oid)].get("route_id")
#         name = route_map.get(int(rid), f"ROUTE#{rid}") if rid is not None else "UNKNOWN"
#         agg[name] = agg.get(name, 0.0) + _f(p.get("collected_amount", p.get("amount", 0)))
#     return sorted(agg.items(), key=lambda x: x[1], reverse=True)

# def agg_revenue_by_destination(lo: str, hi: str) -> List[Tuple[str, float]]:
#     pays = fetch_payment_range(lo, hi, statuses=PAID_STATUSES, end_inclusive=True)
#     oids = [int(p["order_id"]) for p in pays if p.get("order_id")]
#     if not oids: return []
#     orders: Dict[int, Dict[str, Any]] = {}
#     for i in range(0, len(oids), 200):
#         ch = oids[i:i+200]
#         rows = fetch_table_all("orders", {"in__order_id": ",".join(map(str, ch))})
#         for r in rows: orders[int(r["order_id"])] = r
#     dest_map = fetch_destinations_map()
#     agg: Dict[str, float] = {}
#     for p in pays:
#         oid = p.get("order_id")
#         if not oid or int(oid) not in orders: continue
#         did = orders[int(oid)].get("destination_id")
#         name = dest_map.get(int(did), f"DEST#{did}") if did is not None else "UNKNOWN"
#         agg[name] = agg.get(name, 0.0) + _f(p.get("collected_amount", p.get("amount", 0)))
#     return sorted(agg.items(), key=lambda x: x[1], reverse=True)

# def agg_aov_by_customer(lo: str, hi: str) -> List[Tuple[str, float, int]]:
#     orders = fetch_orders_range(lo, hi)
#     by: Dict[int, Tuple[float,int]] = {}
#     for o in orders:
#         cid = o.get("customer_id")
#         if cid is None: continue
#         tot, cnt = by.get(int(cid), (0.0, 0))
#         by[int(cid)] = (tot + _f(o.get("final_price_order")), cnt+1)
#     out: List[Tuple[str,float,int]] = []
#     for cid,(tot,cnt) in by.items():
#         out.append((f"KH #{cid}", (tot/cnt if cnt else 0.0), cnt))
#     return sorted(out, key=lambda x: x[1], reverse=True)

# def agg_inventory_by_warehouse() -> List[Tuple[str,int]]:
#     rows = fetch_table_all("warehouse", {})
#     locs = fetch_table_all("warehouse_location", {})
#     locmap = {int(x["location_id"]): (x.get("name") or f"LOC#{x['location_id']}") for x in locs}
#     agg: Dict[str,int] = {}
#     for r in rows:
#         if (r.get("status") or "").upper() not in {"DA_NHAP_KHO","DANG_DOI_TRA"}: 
#             continue
#         lid = r.get("location_id")
#         name = locmap.get(int(lid), f"LOC#{lid}") if lid is not None else "UNKNOWN"
#         agg[name] = agg.get(name, 0) + 1
#     return sorted(agg.items(), key=lambda x: x[1], reverse=True)

# def agg_flights_waiting_count(lo: str, hi: str) -> int:
#     rows = fetch_table_all("packing", {"gte__packed_date": lo, "lte__packed_date": hi, "eq__status":"CHO_BAY"})
#     return len(rows)

# # =========================
# # Mua hộ — intent & helpers cơ bản
# # =========================
# # Mapping nhẹ các câu phổ biến → status/action hợp lý (an toàn)
# MUAHO_INTENTS = {
#     "bao_cao_mua_ho_today": [
#         "bao cao tong quan dich vu mua ho hom nay",
#         "bao cao tong quan dich vu mua ho hôm nay",
#         "tong so don mua ho hom nay",
#         "tong so don mua ho hôm nay",
#     ],
#     "don_cho_dat": [
#         "co bao nhieu don mua ho dang cho dat hang",
#         "dang cho dat hang",
#         "don cho mua"
#     ],
#     "don_da_dat_chua_tt_seller": [
#         "don nao da dat nhung chua thanh toan cho seller",
#         "da dat chua thanh toan seller"
#     ],
#     "don_cho_ve_kho_tq": [
#         "dang cho ve kho tq",
#         "don cho ve kho tq",
#         "don dang cho ve kho tq"
#     ],
# }

# # =========================
# # Intent
# # =========================
# KEY_ORDERS_PURCHASED = ["don da mua", "don da mua hang", "da mua hang"]
# KEY_WAREHOUSE_INVENTORY = ["hang trong kho", "kho hien co", "ton kho"]
# KEY_FLIGHTS_WAITING = ["chuyen bay cho", "cho bay", "flight waiting"]

# def classify_query(text: str) -> Tuple[str, Dict[str, Any], float]:
#     s = _fold(text)
#     # profile shortcuts
#     m = _EMAIL_RE.search(text or "")
#     if m: return ("profile_by", {"field":"email","value":m.group(0)}, 0.95)
#     if _PHONE_FULL_RE.fullmatch((text or "").strip()):
#         return ("profile_by", {"field":"phone","value":text.strip()}, 0.92)
#     code = extract_order_code_from_text(text or "")
#     if code: return ("order_lookup", {"code": code}, 0.98)

#     # tháng cụ thể: "tháng 9", "tháng 09/2025", ...
#     if "thang" in s or "tháng" in text.lower():
#         mb = resolve_month_from_text(text, _now(), VN_TZ)
#         if mb:
#             return ("revenue_month_explicit", {"lo": mb[0], "hi": mb[1]}, 0.93)

#     # revenue intents
#     if "doanh thu thang" in s or "tong doanh thu theo thang" in s or s.endswith("thang nay"):
#         return ("revenue_month", {}, 0.90)
#     if "doanh thu tuan" in s or s.endswith("tuan nay"):
#         return ("revenue_week", {}, 0.88)
#     if "doanh thu ngay" in s or "hom nay" in s or "hôm nay" in text.lower():
#         return ("revenue_day", {}, 0.80)

#     if "cash flow" in s or "dong tien" in s:
#         return ("cashflow", {}, 0.85)
#     if "doanh thu theo tuyen" in s or "doanh thu theo tuyến" in text:
#         return ("revenue_by_route", {}, 0.85)
#     if "doanh thu theo diem den" in s:
#         return ("revenue_by_destination", {}, 0.80)
#     if "doanh thu theo nhan vien" in s or "nhan vien sale" in s:
#         return ("revenue_by_staff", {}, 0.90)
#     if "top 10 khach hang" in s:
#         return ("top_customers", {}, 0.90)
#     if "trung binh gia tri don hang" in s:
#         return ("aov_by_customer", {}, 0.85)
#     if "don cho mua" in s:
#         return ("orders_wait_buy", {}, 0.90)
#     if any(k in s for k in KEY_ORDERS_PURCHASED):
#         return ("orders_purchased", {}, 0.90)
#     if any(k in s for k in KEY_WAREHOUSE_INVENTORY):
#         return ("warehouse_inventory", {}, 0.85)
#     if any(k in s for k in KEY_FLIGHTS_WAITING):
#         return ("flights_waiting", {}, 0.85)

#     # Mua hộ mapping cơ bản
#     for intent, keys in MUAHO_INTENTS.items():
#         if any(k in s for k in keys):
#             return (intent, {}, 0.90)

#     # explicit profile forms
#     if "thong tin id" in s:
#         m = re.search(r"(\d+)", text or "")
#         if m: return ("profile_by", {"field":"account_id","value":int(m.group(1))}, 0.85)
#     if "thong tin sdt" in s:
#         m = re.search(r"(\+?\d{9,13})", text or "")
#         if m: return ("profile_by", {"field":"phone","value":m.group(1)}, 0.92)
#     if "thong tin email" in s:
#         m = _EMAIL_RE.search(text or "")
#         if m: return ("profile_by", {"field":"email","value":m.group(0)}, 0.95)

#     return ("unknown", {}, 0.40)

# # =========================
# # Format & utilities
# # =========================
# def money_fmt(v: float) -> str:
#     try:
#         s = f"{int(round(v)):,.0f}".replace(",", ".")
#         return f"{s}₫"
#     except Exception:
#         return f"{v}₫"

# def _print_table(rows: List[Dict[str, Any]], headers: List[str]) -> str:
#     if not rows: return "(khong co du lieu)"
#     w = {h: max(len(h), max(len(str(r.get(h,""))) for r in rows)) for h in headers}
#     line = "| " + " ".join(h.ljust(w[h]) for h in headers) + " |"
#     sep  = "| " + " ".join("-"*w[h] for h in headers) + " |"
#     out = [line, sep]
#     for r in rows:
#         out.append("| " + " ".join(str(r.get(h,"")).ljust(w[h]) for h in headers) + " |")
#     return "\n".join(out)

# def format_snapshot(snap: Dict[str, Any]) -> str:
#     if not snap: return "❌ Không tìm thấy đơn."
#     parts = []
#     parts.append(f"📦 Đơn: {snap.get('order_code')} (#{snap.get('order_id')})")
#     parts.append(f"   • Trạng thái: {snap.get('status')}")
#     parts.append(f"   • Thời gian tạo: {snap.get('created_at')}")
#     parts.append(f"   • Nhân viên phụ trách: {(snap.get('staff_name') or 'User')} ({snap.get('staff_id')}) — {snap.get('staff_label')}")
#     parts.append(f"   • Khách hàng: {(snap.get('customer_name') or '')} ({snap.get('customer_id')})")
#     parts.append(f"   • Tuyến: {snap.get('route_name')} (id={snap.get('route_id')})")
#     parts.append(f"   • Điểm đến: {snap.get('destination_name')} (id={snap.get('destination_id')})")
#     pay = snap.get("payments") or {}
#     parts.append(f"💰 Thanh toán: đã thu {money_fmt(pay.get('paid_total',0))} | còn chờ {money_fmt(pay.get('pending_total',0))} | giao dịch: {pay.get('count',0)}")
#     lg = snap.get("last_log")
#     if lg:
#         parts.append(f"📝 Log gần nhất: {lg.get('action')} @ {lg.get('timestamp')} (staff_id={lg.get('staff_id')})")
#     return "\n".join(parts)

# _STATUS_FRIENDLY = {
#     "CHO_DONG_GOI": "Chờ đóng gói",
#     "CHO_VAN_CHUYEN_KHO": "Chờ vận chuyển kho",
#     "CHO_XAC_NHAN": "Chờ xác nhận",
#     "DANG_XU_LY": "Đang xử lý",
#     "DA_DU_HANG": "Đã đủ hàng",
#     "HOAN_TAT": "Hoàn tất",
#     "DA_GIAO": "Đã giao",
#     "DA_XUAT_KHO": "Đã xuất kho",
#     "CHO_GIAO": "Chờ giao",
# }

# def _status_friendly(s: str) -> str:
#     up = (s or "").upper()
#     return _STATUS_FRIENDLY.get(up, s)

# # =========================
# # Phần tính KG theo tuyến (join qua orders)
# # =========================
# def _kg_by_route_month(lo: str, hi: str) -> List[Dict[str, Any]]:
#     wh = fetch_table_all("warehouse", {"gte__created_at": lo, "lt__created_at": hi})
#     routes = fetch_routes_map()
#     oids = sorted({int(r["order_id"]) for r in wh if r.get("order_id") is not None})
#     order_map: Dict[int, Dict[str, Any]] = {}
#     for i in range(0, len(oids), 200):
#         ch = oids[i:i+200]
#         rows = fetch_table_all("orders", {"in__order_id": ",".join(map(str, ch))})
#         for od in rows:
#             order_map[int(od["order_id"])] = od
#     kg: Dict[str, float] = {}
#     for r in wh:
#         w = _f(r.get("weight"))
#         rid = r.get("route_id")
#         name = None
#         oid = r.get("order_id")
#         if oid is not None:
#             od = order_map.get(int(oid))
#             if od and od.get("route_id") is not None:
#                 rid = od.get("route_id")
#         if rid is not None:
#             name = routes.get(int(rid), f"ROUTE#{rid}")
#         else:
#             name = "UNKNOWN"
#         kg[name] = kg.get(name, 0.0) + w
#     rows = [{"route": k, "kg": round(v,2)} for k,v in sorted(kg.items())]
#     return rows

# # =========================
# # Summaries with fallback theo giao dịch
# # =========================
# def _summarize_payment_rows(rows: List[Dict[str, Any]], paid_flag: bool):
#     """
#     Trả về:
#       - total_orders: số đơn unique có payment (fallback = tổng tx nếu thiếu order_id)
#       - total_amount: tổng tiền (collected_amount nếu paid_flag else amount)
#       - breakdown_rows: list[{pay_status, orders, tx, amount}]
#     """
#     orders_set: Dict[int, int] = {}
#     total_amount = 0.0
#     by_status: Dict[str, Dict[str, Any]] = {}
#     amount_key = "collected_amount" if paid_flag else "amount"

#     for r in rows:
#         st = (r.get("status") or "").upper()
#         oid = r.get("order_id")
#         amt = _f(r.get(amount_key, 0))
#         total_amount += amt
#         if st not in by_status:
#             by_status[st] = {"orders": set(), "tx": 0, "amount": 0.0}
#         by_status[st]["tx"] += 1
#         by_status[st]["amount"] += amt
#         if oid is not None:
#             by_status[st]["orders"].add(int(oid))
#             orders_set[int(oid)] = 1

#     total_orders = len(orders_set) if orders_set else sum(v["tx"] for v in by_status.values())

#     breakdown_rows = []
#     for st, v in sorted(by_status.items(), key=lambda x: x[0]):
#         orders_count = len(v["orders"]) if v["orders"] else v["tx"]
#         breakdown_rows.append({
#             "pay_status": st,
#             "orders": orders_count,
#             "tx": v["tx"],
#             "amount": money_fmt(v["amount"]),
#         })
#     return total_orders, total_amount, breakdown_rows

# # =========================
# # Hồ sơ người dùng tổng hợp
# # =========================
# def fetch_warehouse_in_period(lo: str, hi: str) -> List[Dict[str, Any]]:
#     return fetch_table_all("warehouse", {"gte__created_at": lo, "lt__created_at": hi})

# def person_full_profile(identifier_type: str, identifier_value: Union[str,int], recent_limit: int = 20) -> Optional[Dict[str, Any]]:
#     acct = fetch_account_by_field(identifier_type, identifier_value)
#     if not acct: return None
#     account_id = int(acct['account_id'])
#     role = (acct.get('role') or '').upper()
#     profile: Dict[str, Any] = {
#         'account': acct, 'role': role, 'customer': None, 'staff': None,
#         'orders_recent': [], 'payments_recent': [],
#         'aggregates': {}, 'logs_recent': [], 'feedback_recent': [], 'warehouse_recent': []
#     }
#     cust_rows = fetch_table_all('customer', {'eq__account_id': account_id}, page_size=5)
#     if cust_rows: profile['customer'] = cust_rows[0]
#     staff_rows = fetch_table_all('staff', {'eq__account_id': account_id}, page_size=5)
#     if staff_rows: profile['staff'] = staff_rows[0]

#     orders = []
#     if profile['customer']:
#         cid = int(profile['customer']['account_id'])
#         orders.extend(fetch_table_all('orders', {'eq__customer_id': cid, 'order':'created_at','desc':True}, page_size=recent_limit))
#     if profile['staff']:
#         sid = int(profile['staff']['account_id'])
#         orders.extend(fetch_table_all('orders', {'eq__staff_id': sid, 'order':'created_at','desc':True}, page_size=recent_limit))
#     seen = {}; merged = []
#     for o in orders:
#         oid = int(o['order_id'])
#         if oid in seen: continue
#         seen[oid]=1; merged.append(o)
#     profile['orders_recent'] = merged[:recent_limit]

#     pays = []
#     if profile['customer']:
#         cid = int(profile['customer']['account_id'])
#         pays = fetch_table_all('payment', {'eq__customer_id': cid, 'order':'action_at','desc':True}, page_size=recent_limit)
#     else:
#         oids = [int(o['order_id']) for o in profile['orders_recent']][:200]
#         if oids:
#             for i in range(0, len(oids), 100):
#                 ch = oids[i:i+100]
#                 pays.extend(fetch_table_all('payment', {'in__order_id': ','.join(map(str,ch)), 'order':'action_at','desc':True}, page_size=recent_limit))
#     pays = pays[:recent_limit]
#     profile['payments_recent'] = pays

#     total_paid = sum(_f(p.get('collected_amount', p.get('amount', 0))) for p in pays if (p.get('status') or '').upper() in PAID_STATUSES)
#     outstanding = sum(_f(p.get('amount',0)) for p in pays if (p.get('status') or '').upper() in UNPAID_STATUSES)
#     profile['aggregates'] = {'total_paid_recent': total_paid, 'outstanding_recent': outstanding, 'payments_count_recent': len(pays)}

#     oids = [int(o['order_id']) for o in profile['orders_recent']][:200]
#     logs = []
#     if oids:
#         for i in range(0, len(oids), 100):
#             ch = oids[i:i+100]
#             logs.extend(fetch_table_all('order_process_log', {'in__order_id': ','.join(map(str,ch)), 'order':'timestamp','desc':True}, page_size=recent_limit))
#     profile['logs_recent'] = logs[:recent_limit]

#     fbs = fetch_feedback_by_orders(oids) if oids else []
#     profile['feedback_recent'] = fbs[:recent_limit]

#     wh = []
#     if oids:
#         wh.extend(fetch_table_all('warehouse', {'in__order_id': ','.join(map(str,oids)), 'order':'created_at','desc':True}, page_size=recent_limit))
#     if profile['staff']:
#         wh.extend(fetch_table_all('warehouse', {'eq__staff_id': account_id, 'order':'created_at','desc':True}, page_size=recent_limit))
#     profile['warehouse_recent'] = wh[:recent_limit]
#     return profile

# # =========================
# # CLI
# # =========================
# BANNER = """
# Tiximax DB-CLI — hỏi gì đáp nấy (orders/payments/warehouse/packing/domestic/feedback…)
# Thoát: exit | quit | thoat
# """.strip()

# def _respond(text: str):
#     """In trả lời, có polish qua Gemini nếu bật."""
#     print(_gemini_rewrite(text))

# def main():
#     print(BANNER)
#     while True:
#         try:
#             s = input("\nBạn hỏi> ").strip()
#         except (EOFError, KeyboardInterrupt):
#             print("\nTạm biệt."); break
#         if not s: continue
#         if _fold(s) in {"thoat","exit","quit"}:
#             print("Tạm biệt."); break

#         intent, params, conf = classify_query(s)

#         # Order lookup / fallback unknown → thử mã đơn
#         if intent in {"order_lookup","unknown"}:
#             code = extract_order_code_from_text(s)
#             if code:
#                 snap = order_snapshot_by_code(code)
#                 _respond(format_snapshot(snap))
#                 if snap is None:
#                     _respond(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})")
#                 continue
#             if intent == "unknown":
#                 _respond("⚠️  Chưa nhận diện được ý định. Thử: 'doanh thu tháng này' / mã đơn 'OD2025…' / 'thông tin email a@b.com'")
#                 continue

#         # Profile by email/phone/id
#         if intent == "profile_by":
#             fld, val = params["field"], params["value"]
#             prof = person_full_profile(fld, val, recent_limit=20)
#             if not prof:
#                 _respond("❌ Không tìm thấy tài khoản.")
#                 continue
#             acct = prof["account"]
#             role = (acct.get("role") or "").upper()
#             lines = []
#             lines.append(f"👤 Account #{acct.get('account_id')} — {acct.get('name','N/A')}")
#             lines.append(f"   • Email: {acct.get('email','N/A')} | Phone: {acct.get('phone','N/A')} | Username: {acct.get('username','N/A')}")
#             lines.append(f"   • Role: {role or 'N/A'} | Status: {acct.get('status','N/A')}")
#             if prof.get("staff"):
#                 st = prof["staff"]
#                 lines.append(f"🧑‍💼 Staff: code={st.get('staff_code','')} | location={st.get('location','')} | dept={st.get('department','')}")
#             ag = prof["aggregates"]
#             lines.append(f"💰 Payments recent: paid={money_fmt(ag.get('total_paid_recent',0))} | outstanding={money_fmt(ag.get('outstanding_recent',0))} | count={ag.get('payments_count_recent',0)}")
#             ords = [{"order_code": o.get("order_code",""), "status": o.get("status","")} for o in prof["orders_recent"][:10]]
#             if ords:
#                 lines.append("📦 Orders recent: " + ", ".join(f"{o['order_code']}({o['status']})" for o in ords))
#             lines.append(f"🏬 Warehouse records recent: {len(prof['warehouse_recent'])}")
#             lines.append(f"📝 Logs recent: {len(prof['logs_recent'])}")
#             lines.append(f"⭐ Feedback recent: {len(prof['feedback_recent'])}")
#             _respond("\n".join(lines))
#             continue

#         # Revenue (explicit month from text)
#         if intent == "revenue_month_explicit":
#             lo, hi = params["lo"], params["hi"]
#             label = "tháng"
#         # Revenue (month/week/day) default ranges
#         if intent in {"revenue_month","revenue_week","revenue_day","revenue_month_explicit"}:
#             if intent == "revenue_month":
#                 lo, hi = this_month_range_iso(); label="tháng"
#             elif intent == "revenue_week":
#                 lo, hi = this_week_range_iso(); label="tuần"
#             elif intent == "revenue_day":
#                 lo, hi = today_range_iso(); label="ngày"

#             paid_rows   = fetch_payment_range(lo, hi, statuses=PAID_STATUSES, end_inclusive=False)
#             unpaid_rows = fetch_payment_range(lo, hi, statuses=UNPAID_STATUSES, end_inclusive=False)

#             total_paid = sum(_f(r.get("collected_amount", r.get("amount", 0))) for r in paid_rows)
#             title = f"💰 Doanh thu {lo} → {hi}: {money_fmt(total_paid)} (giao dịch: {len(paid_rows)})"

#             # Bảng theo kỳ (có thêm tx)
#             paid_order_ids   = {int(r["order_id"]) for r in paid_rows if r.get("order_id") is not None}
#             unpaid_order_ids = {int(r["order_id"]) for r in unpaid_rows if r.get("order_id") is not None}
#             month_rows = [{
#                 "window": f"{lo[:10]}→{hi[:10]}",
#                 "paid_orders": len(paid_order_ids),
#                 "paid_tx": len(paid_rows),
#                 "paid_amount": money_fmt(total_paid),
#                 "unpaid_orders": len(unpaid_order_ids),
#                 "unpaid_tx": len(unpaid_rows),
#                 "unpaid_amount": money_fmt(sum(_f(r.get("amount", 0)) for r in unpaid_rows)),
#             }]

#             # Tổng hợp & chi tiết thanh toán
#             p_orders, p_amt, p_break = _summarize_payment_rows(paid_rows, paid_flag=True)
#             u_orders, u_amt, u_break = _summarize_payment_rows(unpaid_rows, paid_flag=False)

#             parts = [title]
#             parts.append(f"\n▶ Theo {label}")
#             parts.append(_print_table(month_rows, ["window","paid_orders","paid_tx","paid_amount","unpaid_orders","unpaid_tx","unpaid_amount"]))

#             parts.append("\n▶ Tổng hợp thanh toán (tháng)")
#             parts.append(_print_table(
#                 [{"group":"PAID_STATUSES","orders":p_orders,"tx":len(paid_rows),"amount":money_fmt(p_amt)},
#                  {"group":"UNPAID_STATUSES","orders":u_orders,"tx":len(unpaid_rows),"amount":money_fmt(u_amt)}],
#                 ["group","orders","tx","amount"]
#             ))

#             parts.append("\n▶ Chi tiết thanh toán (tháng) — PAID_STATUSES")
#             parts.append(_print_table(p_break, ["pay_status","orders","tx","amount"]) if p_break else "(khong co du lieu)")

#             parts.append("\n▶ Chi tiết thanh toán (tháng) — UNPAID_STATUSES")
#             parts.append(_print_table(u_break, ["pay_status","orders","tx","amount"]) if u_break else "(khong co du lieu)")

#             # KG theo tuyến chỉ khi tháng
#             if label == "tháng":
#                 kg_rows = _kg_by_route_month(lo, hi)
#                 parts.append("\n▶ Số kg theo tuyến (theo warehouse.created_at trong tháng)")
#                 parts.append(_print_table(kg_rows, ["route","kg"]) if kg_rows else "(khong co du lieu)")

#                 # Trạng thái đơn (nghiệp vụ)
#                 orders_in_month = fetch_orders_range(lo, hi)
#                 state_count: Dict[str,int] = {}
#                 for o in orders_in_month:
#                     st = _status_friendly(o.get("status",""))
#                     state_count[st] = state_count.get(st,0) + 1
#                 st_rows = [{"status": k, "orders": v} for k,v in sorted(state_count.items(), key=lambda x: x[0])]
#                 if st_rows:
#                     parts.append("\n▶ Trạng thái đơn (tháng)")
#                     parts.append(_print_table(st_rows, ["status","orders"]))
#                     parts.append("ℹ️  Lưu ý: Đây là trạng thái NGHIỆP VỤ của đơn (orders.status), KHÁC với trạng thái thanh toán (payment.status).")

#             parts.append(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})")
#             _respond("\n".join(parts))
#             continue

#         # Others
#         if intent == "cashflow":
#             lo, hi = this_month_range_iso()
#             pairs = agg_cashflow_daily(lo, hi)
#             tbl = _print_table([{"date": d, "collected": money_fmt(v)} for d,v in pairs], ["date","collected"]) if pairs else "(khong co du lieu)"
#             _respond(tbl + f"\n\n(độ tin cậy nhận diện ý định: {conf:.2f})")
#             continue

#         if intent == "revenue_by_staff":
#             lo, hi = this_month_range_iso()
#             pays = fetch_payment_range(lo, hi, statuses=PAID_STATUSES, end_inclusive=False)
#             agg = group_revenue_by_staff(pays)
#             rows = []
#             for sid, amt in sorted(agg.items(), key=lambda x: x[1], reverse=True):
#                 acct = fetch_account_by_id(int(sid)) or {}
#                 rows.append({"staff_id": sid, "name": acct.get("name",""), "revenue": money_fmt(amt)})
#             out = _print_table(rows, ["staff_id","name","revenue"]) if rows else "(khong co du lieu)"
#             _respond(out + f"\n\n(độ tin cậy nhận diện ý định: {conf:.2f})")
#             continue

#         if intent == "revenue_by_route":
#             lo, hi = this_month_range_iso()
#             rows = [{"route": k, "revenue": money_fmt(v)} for k,v in agg_revenue_by_route(lo, hi)]
#             out = _print_table(rows, ["route","revenue"]) if rows else "(khong co du lieu)"
#             _respond(out + f"\n\n(độ tin cậy nhận diện ý định: {conf:.2f})")
#             continue

#         if intent == "revenue_by_destination":
#             lo, hi = this_month_range_iso()
#             rows = [{"destination": k, "revenue": money_fmt(v)} for k,v in agg_revenue_by_destination(lo, hi)]
#             out = _print_table(rows, ["destination","revenue"]) if rows else "(khong co du lieu)"
#             _respond(out + f"\n\n(độ tin cậy nhận diện ý định: {conf:.2f})")
#             continue

#         if intent == "top_customers":
#             lo, hi = this_month_range_iso()
#             pays = fetch_payment_range(lo, hi, statuses=PAID_STATUSES, end_inclusive=False)
#             by: Dict[int,float] = {}
#             for p in pays:
#                 cid = p.get("customer_id")
#                 if cid is None: continue
#                 by[int(cid)] = by.get(int(cid), 0.0) + _f(p.get("collected_amount", p.get("amount", 0)))
#             rows = []
#             for cid, paid in sorted(by.items(), key=lambda x: x[1], reverse=True)[:10]:
#                 acct = fetch_account_by_id(int(cid)) or {}
#                 rows.append({"customer_id": cid, "name": f"{acct.get('name','')} ({cid})", "paid": money_fmt(paid)})
#             out = _print_table(rows, ["customer_id","name","paid"]) if rows else "(khong co du lieu)"
#             _respond(out + f"\n\n(độ tin cậy nhận diện ý định: {conf:.2f})")
#             continue

#         if intent == "aov_by_customer":
#             lo, hi = this_month_range_iso()
#             rows = [{"customer": k, "AOV": money_fmt(v), "orders": n} for (k,v,n) in agg_aov_by_customer(lo, hi)]
#             out = _print_table(rows, ["customer","AOV","orders"]) if rows else "(khong co du lieu)"
#             _respond(out + f"\n\n(độ tin cậy nhận diện ý định: {conf:.2f})")
#             continue

#         if intent == "orders_wait_buy":
#             lo, hi = this_month_range_iso()
#             rows = fetch_orders_range(lo, hi, status="CHO_MUA")
#             table = [{"order_code": r.get("order_code",""), "status": r.get("status",""), "created_at": r.get("created_at","")} for r in rows]
#             out = _print_table(table, ["order_code","status","created_at"]) if table else "(khong co du lieu)"
#             _respond(out + f"\n\n(độ tin cậy nhận diện ý định: {conf:.2f})")
#             continue

#         if intent == "orders_purchased":
#             lo, hi = this_month_range_iso()
#             rows = fetch_orders_range(lo, hi, status="DA_MUA_HANG")
#             if not rows:
#                 logs = fetch_table_all("order_process_log", {"gte__timestamp": lo, "lt__timestamp": hi, "eq__action":"DA_MUA_HANG"})
#                 oids = sorted({int(l["order_id"]) for l in logs if l.get("order_id")})
#                 rows = []
#                 for i in range(0, len(oids), 200):
#                     ch = oids[i:i+200]
#                     rows.extend(fetch_table_all("orders", {"in__order_id": ",".join(map(str, ch))}))
#             table = [{"order_code": r.get("order_code",""), "status": r.get("status",""), "created_at": r.get("created_at","")} for r in rows]
#             out = _print_table(table, ["order_code","status","created_at"]) if table else "(khong co du lieu)"
#             _respond(out + f"\n\n(độ tin cậy nhận diện ý định: {conf:.2f})")
#             continue

#         if intent == "warehouse_inventory":
#             rows = agg_inventory_by_warehouse()
#             out = _print_table([{"location": k, "packages": v} for k,v in rows], ["location","packages"]) if rows else "(khong co du lieu)"
#             _respond(out + f"\n\n(độ tin cậy nhận diện ý định: {conf:.2f})")
#             continue

#         if intent == "flights_waiting":
#             lo, hi = this_month_range_iso()
#             cnt = agg_flights_waiting_count(lo, hi)
#             _respond(f"✈️  Chuyến bay đang CHỜ: {cnt}\n\n(độ tin cậy nhận diện ý định: {conf:.2f})")
#             continue

#         # ===== Mua hộ cơ bản =====
#         if intent == "bao_cao_mua_ho_today":
#             lo, hi = today_range_iso()
#             paid_rows   = fetch_payment_range(lo, hi, statuses=PAID_STATUSES)
#             unpaid_rows = fetch_payment_range(lo, hi, statuses=UNPAID_STATUSES)
#             total_paid = sum(_f(r.get("collected_amount", r.get("amount", 0))) for r in paid_rows)
#             rows = [{
#                 "window": f"{lo[:10]}→{hi[:10]}",
#                 "paid_orders": len({int(r["order_id"]) for r in paid_rows if r.get("order_id") is not None}),
#                 "paid_tx": len(paid_rows),
#                 "paid_amount": money_fmt(total_paid),
#                 "unpaid_orders": len({int(r["order_id"]) for r in unpaid_rows if r.get("order_id") is not None}),
#                 "unpaid_tx": len(unpaid_rows),
#                 "unpaid_amount": money_fmt(sum(_f(r.get("amount", 0)) for r in unpaid_rows)),
#             }]
#             out = "📊 Tổng quan hôm nay — Đơn: {}\n".format(
#                 len({int(r["order_id"]) for r in paid_rows+unpaid_rows if r.get("order_id") is not None})
#             )
#             out += _print_table(rows, ["window","paid_orders","paid_tx","paid_amount","unpaid_orders","unpaid_tx","unpaid_amount"])
#             _respond(out + f"\n\n(độ tin cậy nhận diện ý định: {conf:.2f})")
#             continue

#         if intent == "don_cho_dat":
#             lo, hi = this_month_range_iso()
#             # Chờ đặt = CHO_MUA
#             rows = fetch_orders_range(lo, hi, status="CHO_MUA")
#             table = [{"order_code": r.get("order_code",""), "status": _status_friendly(r.get("status","")), "created_at": r.get("created_at","")} for r in rows]
#             hdr = ["order_code","status","created_at"]
#             _respond((_print_table(table, hdr) if table else "(khong co du lieu)") + f"\n\n(độ tin cậy nhận diện ý định: {conf:.2f})")
#             continue

#         if intent == "don_da_dat_chua_tt_seller":
#             lo, hi = this_month_range_iso()
#             # Không có cột “thanh toán cho seller”, dùng heuristic: đã đặt hàng (log/action=DA_DAT_HANG) nhưng payment.status ∈ UNPAID_STATUSES
#             logs = fetch_table_all("order_process_log", {"gte__timestamp": lo, "lt__timestamp": hi, "eq__action":"DA_DAT_HANG"})
#             oids = sorted({int(l["order_id"]) for l in logs if l.get("order_id")})
#             rows = []
#             if oids:
#                 # Lấy payment UNPAID cho các đơn này
#                 for i in range(0, len(oids), 200):
#                     ch = oids[i:i+200]
#                     pays = fetch_table_all("payment", {"in__order_id": ",".join(map(str, ch)), "in__status": ",".join(sorted(UNPAID_STATUSES))})
#                     up_oids = sorted({int(p["order_id"]) for p in pays if p.get("order_id")})
#                     if up_oids:
#                         ords = fetch_table_all("orders", {"in__order_id": ",".join(map(str, up_oids))})
#                         rows.extend(ords)
#             table = [{"order_code": r.get("order_code",""), "status": _status_friendly(r.get("status","")), "created_at": r.get("created_at","")} for r in rows]
#             _respond((_print_table(table, ["order_code","status","created_at"]) if table else "(khong co du lieu)") + f"\n\n(độ tin cậy nhận diện ý định: {conf:.2f})")
#             continue

#         if intent == "don_cho_ve_kho_tq":
#             lo, hi = this_month_range_iso()
#             # Heuristic: các trạng thái thể hiện đang đi đường/đợi về kho TQ
#             candidates = fetch_orders_range(lo, hi)  # lọc toàn bộ trong tháng
#             filt = []
#             for r in candidates:
#                 st = (r.get("status") or "").upper()
#                 if st in {"CHO_VAN_CHUYEN_KHO","DANG_XU_LY","CHO_DONG_GOI","DA_DU_HANG"}:
#                     filt.append(r)
#             table = [{"order_code": r.get("order_code",""), "status": _status_friendly(r.get("status","")), "created_at": r.get("created_at","")} for r in filt]
#             _respond((_print_table(table, ["order_code","status","created_at"]) if table else "(khong co du lieu)") + f"\n\n(độ tin cậy nhận diện ý định: {conf:.2f})")
#             continue

#         _respond("⚠️  Chưa nhận diện được ý định. Thử: 'doanh thu tháng này' / mã đơn 'OD2025…' / 'thông tin email a@b.com'")

# if __name__ == "__main__":
#     main()

# -*- coding: utf-8 -*-
"""
Tiximax DB-CLI — 1 file hoàn chỉnh
- KPI Ngày/Tuần/Tháng: bảng paid/unpaid theo payment.status; chi tiết nhóm PAID_STATUSES/UNPAID_STATUSES
- Số kg theo tuyến (tháng) từ warehouse (theo created_at)
- Trạng thái đơn (orders.status) trong tháng (phân biệt với payment.status)
- Tra cứu mã đơn (order snapshot), hồ sơ tài khoản theo email/phone/id
- Mua hộ tổng thể, Seller analytics, Kho TQ, Vận chuyển quốc tế
- Hook gemini_rewrite() để "mềm" câu chữ mà không đổi số liệu

API pattern: /api/<table>?eq__field=...&in__field=a,b&gte__action_at=...&lt__action_at=...
"""

from __future__ import annotations
import os, re, unicodedata, datetime as dt
from typing import Dict, Any, Optional, List, Tuple, Union
import requests

# =========================
# Cấu hình
# =========================
try:
    from .config_supabase import BASE_API_URL, API_KEY, DEFAULT_PAGE_SIZE, VN_TZ
except Exception:
    BASE_API_URL = os.environ.get("BASE_API_URL", "https://ordering-sound-myers-buried.trycloudflare.com").rstrip("/")
    API_KEY = os.environ.get("API_KEY", "super-secret-xyz").strip()
    DEFAULT_PAGE_SIZE = int(os.environ.get("DEFAULT_PAGE_SIZE", "200"))
    try:
        import pytz
        VN_TZ = pytz.timezone(os.environ.get("VN_TZ", "Asia/Ho_Chi_Minh"))
    except Exception:
        VN_TZ = dt.timezone(dt.timedelta(hours=7))

# =========================
# Hằng số & tập trạng thái
# =========================
API_MAX_LIMIT = 500

# Thanh toán
PAID_STATUSES = {"DA_THANH_TOAN", "DA_THANH_TOAN_SHIP"}
UNPAID_STATUSES = {"CHO_THANH_TOAN", "CHO_THANH_TOAN_SHIP"}

# Đơn mua hộ
ORDER_TYPE_MUA_HO = "MUA_HO"
ORDER_STATUSES_WAIT_BUY = {"CHO_MUA"}  # “đang chờ đặt hàng”
ORDER_STATUSES_INPROGRESS = {
    "CHO_XAC_NHAN","DA_XAC_NHAN","CHO_THANH_TOAN","CHO_MUA","CHO_THANH_TOAN_DAU_GIA",
    "CHO_NHAP_KHO_NN","CHO_DONG_GOI","DANG_XU_LY","DA_DU_HANG","CHO_THANH_TOAN_SHIP",
    "CHO_VAN_CHUYEN_KHO","CHO_GIAO"
}
ORDER_STATUSES_DONE_OR_CANCEL = {"DA_GIAO","DA_HUY"}

# Kho quốc gia
COUNTRY_CN_HINTS = {"cn", "china", "trung quoc", "trung quốc", "zh"}
COUNTRY_VN_HINTS = {"vn", "viet nam", "vietnam", "việt nam"}

DEFAULT_SHIP_SLA_DAYS = 14
UNSUPPORTED_NOTE = "⚠️ Chưa đủ trường dữ liệu trong schema để tính chỉ số này."

# Regex
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE_FULL_RE = re.compile(r"^\+?\d{9,13}$")
_ORDER_CODE_INLINE_RE = re.compile(r"\b(ORD[A-Z0-9\-]*|[A-Z]{2,5}[A-Z0-9\-]*\d+)\b", re.IGNORECASE)
_RE_SHOP_NAME = re.compile(r"(?:shop|seller)\s+([^\?]+)", re.IGNORECASE | re.UNICODE)

# “tháng 9”, “tháng 9/2025”, “tháng 09-2024”, “tháng 9 năm 2024”
try:
    from dateutil.relativedelta import relativedelta
except Exception:
    class relativedelta:  # fallback đơn giản
        def __init__(self, months=0): self.months = months
        def __radd__(self, d):
            y, m = d.year, d.month + self.months
            while m > 12: m -= 12; y += 1
            while m < 1:  m += 12; y -= 1
            return d.replace(year=y, month=m)
_MONTH_RANGE_RE = re.compile(
    r"(?:thang|tháng)\s*(?P<m>\d{1,2})"
    r"(?:\s*[/\-]\s*(?P<y1>\d{2,4}))?"
    r"(?:\s*năm\s*(?P<y2>\d{4}))?",
    re.IGNORECASE | re.UNICODE
)

# =========================
# Helpers chung
# =========================
def _headers() -> Dict[str, str]:
    return {"X-API-Key": API_KEY, "Accept": "application/json"}

def _clamp(n: Optional[int]) -> int:
    try: n = int(n or DEFAULT_PAGE_SIZE)
    except Exception: n = DEFAULT_PAGE_SIZE
    return max(1, min(API_MAX_LIMIT, n))

def _now():
    try: return dt.datetime.now(VN_TZ)
    except Exception: return dt.datetime.now()

def _fold(s: str) -> str:
    s = (s or "").strip()
    t = unicodedata.normalize("NFD", s.lower())
    return "".join(ch for ch in t if unicodedata.category(ch) != "Mn")

def _f(x):
    try: return float(x or 0)
    except: return 0.0

def money_fmt(v: float) -> str:
    try:
        s = f"{int(round(v)):,.0f}".replace(",", ".")
        return f"{s}₫"
    except Exception:
        return f"{v}₫"

def _print_table(rows: List[Dict[str, Any]], headers: List[str]) -> str:
    if not rows: return "(khong co du lieu)"
    w = {h: max(len(h), max(len(str(r.get(h,""))) for r in rows)) for h in headers}
    line = "| " + " | ".join(h.ljust(w[h]) for h in headers) + " |"
    sep  = "| " + " | ".join("-"*w[h] for h in headers) + " |"
    out = [line, sep]
    for r in rows:
        out.append("| " + " | ".join(str(r.get(h,"")).ljust(w[h]) for h in headers) + " |")
    return "\n".join(out)

def gemini_rewrite(text: str) -> str:
    """
    Hook làm 'mềm' câu chữ, KHÔNG thay số liệu. 
    Hiện tại chỉ pass-through. 
    Nếu bạn có MCP/Gemini, thay thân hàm này để gọi rewrite.
    """
    return text

def extract_order_code_from_text(text: str) -> Optional[str]:
    m = _ORDER_CODE_INLINE_RE.search(text or "")
    return m.group(1).upper() if m else None

# =========================
# Thời gian
# =========================
def this_month_range_iso() -> Tuple[str,str]:
    now = _now()
    start = dt.datetime(now.year, now.month, 1, 0, 0, 0, tzinfo=now.tzinfo)
    end = start + relativedelta(months=1)
    return start.isoformat(), end.isoformat()

def this_week_range_iso() -> Tuple[str,str]:
    now = _now()
    start = (now - dt.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + dt.timedelta(days=7)
    return start.isoformat(), end.isoformat()

def today_range_iso() -> Tuple[str,str]:
    now = _now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + dt.timedelta(days=1)
    return start.isoformat(), end.isoformat()

def _normalize_year(y: int) -> int:
    return y + 2000 if y < 100 else y

def _month_bounds(year: int, month: int, tz) -> Tuple[str, str]:
    start = dt.datetime(year, month, 1, tzinfo=tz)
    end = start + relativedelta(months=1)
    return start.isoformat(), end.isoformat()

def resolve_month_from_text(s: str, now, tz) -> Optional[Tuple[str,str]]:
    m = _MONTH_RANGE_RE.search(s or "")
    if not m: return None
    mo = int(m.group("m")); y2 = m.group("y2"); y1 = m.group("y1")
    year = _normalize_year(int(y2 or y1 or now.year))
    if not (1 <= mo <= 12): return None
    return _month_bounds(year, mo, tz)

# =========================
# API layer
# =========================
def fetch_table_once(table: str, params: Optional[Dict[str, Any]] = None, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0) -> Dict[str, Any]:
    url = f"{BASE_API_URL}/api/{table}"
    q = {"limit": _clamp(limit), "offset": max(0, int(offset))}
    if params: q.update(params)
    resp = requests.get(url, headers=_headers(), params=q, timeout=30)
    if resp.status_code != 200:
        raise requests.HTTPError(f"POSTGREST {table}: {resp.status_code} {resp.text[:240]}")
    return resp.json()

def fetch_table_all(table: str, params: Optional[Dict[str, Any]] = None, page_size: int = DEFAULT_PAGE_SIZE, max_pages: int = 200) -> List[Dict[str, Any]]:
    out, offset, step = [], 0, _clamp(page_size)
    for _ in range(max_pages):
        data = fetch_table_once(table, params=params, limit=step, offset=offset)
        rows = data.get("data") or []
        out.extend(rows)
        if len(rows) < step: break
        offset += step
    return out

# =========================
# Lookups & snapshot
# =========================
def fetch_routes_map() -> Dict[int, str]:
    rows = fetch_table_all("route", {})
    return {int(r["route_id"]): (r.get("name") or f"ROUTE#{r['route_id']}") for r in rows}

def fetch_destinations_map() -> Dict[int, str]:
    rows = fetch_table_all("destination", {})
    return {int(r["destination_id"]): (r.get("destination_name") or f"DEST#{r['destination_id']}") for r in rows}

def fetch_account_by_id(aid: int) -> Optional[Dict[str, Any]]:
    rows = fetch_table_all("account", {"eq__account_id": int(aid)}, page_size=50)
    return rows[0] if rows else None

def fetch_staff_by_id(aid: int) -> Optional[Dict[str, Any]]:
    rows = fetch_table_all("staff", {"eq__account_id": int(aid)}, page_size=50)
    return rows[0] if rows else None

def fetch_order_by_code(code: str) -> Optional[Dict[str, Any]]:
    rows = fetch_table_all("orders", {"eq__order_code": code}, page_size=50)
    if not rows and code.isdigit():
        rows = fetch_table_all("orders", {"eq__order_id": int(code)}, page_size=50)
    return rows[0] if rows else None

def payments_by_order(oid: int) -> List[Dict[str, Any]]:
    return fetch_table_all("payment", {"eq__order_id": int(oid)})

def process_logs_by_order(oid: int) -> List[Dict[str, Any]]:
    return fetch_table_all("order_process_log", {"eq__order_id": int(oid), "order":"timestamp", "desc":True})

def order_snapshot_by_code(code: str) -> Optional[Dict[str, Any]]:
    od = fetch_order_by_code(code)
    if not od: return None
    oid = int(od["order_id"])
    pays = payments_by_order(oid)
    paid = sum(_f(p.get("collected_amount", p.get("amount", 0))) for p in pays if (p.get("status") or "").upper() in PAID_STATUSES)
    pending = sum(_f(p.get("amount", 0)) for p in pays if (p.get("status") or "").upper() in UNPAID_STATUSES)
    logs = process_logs_by_order(oid)
    last_log = logs[0] if logs else None
    routes = fetch_routes_map(); dests = fetch_destinations_map()
    return {
        "order_id": oid,
        "order_code": od.get("order_code"),
        "status": od.get("status"),
        "created_at": od.get("created_at"),
        "staff_id": od.get("staff_id"),
        "staff_label": (fetch_staff_by_id(int(od.get("staff_id"))) or {}).get("staff_code") if od.get("staff_id") else None,
        "staff_name": (fetch_account_by_id(int(od.get("staff_id"))) or {}).get("name") if od.get("staff_id") else None,
        "customer_id": od.get("customer_id"),
        "customer_name": (fetch_account_by_id(int(od.get("customer_id"))) or {}).get("name") if od.get("customer_id") else None,
        "route_id": od.get("route_id"),
        "route_name": routes.get(int(od.get("route_id")), f"ROUTE#{od.get('route_id')}") if od.get("route_id") else None,
        "destination_id": od.get("destination_id"),
        "destination_name": dests.get(int(od.get("destination_id")), f"DEST#{od.get('destination_id')}") if od.get("destination_id") else None,
        "payments": {"count": len(pays), "paid_total": paid, "pending_total": pending},
        "last_log": {"action": last_log.get("action"), "timestamp": last_log.get("timestamp"), "staff_id": last_log.get("staff_id")} if last_log else None
    }

def format_snapshot(snap: Dict[str, Any]) -> str:
    if not snap: return "❌ Không tìm thấy đơn."
    parts = []
    parts.append(f"📦 Đơn: {snap.get('order_code')} (#{snap.get('order_id')})")
    parts.append(f"   • Trạng thái: {snap.get('status')}")
    parts.append(f"   • Thời gian tạo: {snap.get('created_at')}")
    parts.append(f"   • Nhân viên phụ trách: {(snap.get('staff_name') or 'User')} ({snap.get('staff_id')}) — {snap.get('staff_label')}")
    parts.append(f"   • Khách hàng: {(snap.get('customer_name') or '')} ({snap.get('customer_id')})")
    parts.append(f"   • Tuyến: {snap.get('route_name')} (id={snap.get('route_id')})")
    parts.append(f"   • Điểm đến: {snap.get('destination_name')} (id={snap.get('destination_id')})")
    pay = snap.get("payments") or {}
    parts.append(f"💰 Thanh toán: đã thu {money_fmt(pay.get('paid_total',0))} | còn chờ {money_fmt(pay.get('pending_total',0))} | giao dịch: {pay.get('count',0)}")
    lg = snap.get("last_log")
    if lg:
        parts.append(f"📝 Log gần nhất: {lg.get('action')} @ {lg.get('timestamp')} (staff_id={lg.get('staff_id')})")
    return "\n".join(parts)

def fetch_account_by_field(field: str, value: Union[str,int]) -> Optional[Dict[str, Any]]:
    if field == "account_id":
        rows = fetch_table_all("account", {"eq__account_id": int(value)}, page_size=50)
    else:
        rows = fetch_table_all("account", {f"eq__{field}": str(value)}, page_size=50)
    return rows[0] if rows else None

def fetch_feedback_by_orders(order_ids: List[int]) -> List[Dict[str, Any]]:
    if not order_ids: return []
    out = []
    for i in range(0, len(order_ids), 200):
        chunk = order_ids[i:i+200]
        out.extend(fetch_table_all("feedback", {"in__order_id": ",".join(map(str,chunk))}, page_size=500))
    return out

def fetch_order_process_logs(order_ids: List[int]) -> List[Dict[str, Any]]:
    if not order_ids: return []
    out = []
    for i in range(0, len(order_ids), 200):
        chunk = order_ids[i:i+200]
        out.extend(fetch_table_all("order_process_log", {"in__order_id": ",".join(map(str,chunk))}, page_size=500))
    return out

# =========================
# Revenue & Aggregations
# =========================
def fetch_payment_range(lo: str, hi: str, paid_only: bool = True, end_inclusive: bool = False) -> List[Dict[str, Any]]:
    p = {"gte__action_at": lo, "order": "action_at", "desc": False}
    p["lte__action_at" if end_inclusive else "lt__action_at"] = hi
    if paid_only:
        p["in__status"] = ",".join(sorted(PAID_STATUSES))
    return fetch_table_all("payment", params=p)

def sum_revenue_from_payments(payments: List[Dict[str, Any]]) -> float:
    s = 0.0
    for p in payments:
        if (p.get("status") or "").upper() in PAID_STATUSES:
            s += _f(p.get("collected_amount", p.get("amount", 0)))
    return s

def fetch_orders_range(lo: str, hi: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
    p = {"gte__created_at": lo, "lt__created_at": hi}
    if status: p["eq__status"] = status
    return fetch_table_all("orders", params=p)

def group_revenue_by_staff(pays: List[Dict[str, Any]]) -> Dict[int, float]:
    agg: Dict[int, float] = {}
    for p in pays:
        if (p.get("status") or "").upper() not in PAID_STATUSES: 
            continue
        sid = p.get("staff_id")
        if sid is None: continue
        agg[int(sid)] = agg.get(int(sid), 0.0) + _f(p.get("collected_amount", p.get("amount", 0)))
    return agg

def agg_revenue_by_route(lo: str, hi: str) -> List[Tuple[str, float]]:
    pays = fetch_payment_range(lo, hi, paid_only=True, end_inclusive=True)
    oids = [int(p["order_id"]) for p in pays if p.get("order_id")]
    if not oids: return []
    orders: Dict[int, Dict[str, Any]] = {}
    for i in range(0, len(oids), 200):
        ch = oids[i:i+200]
        rows = fetch_table_all("orders", {"in__order_id": ",".join(map(str, ch))})
        for r in rows: orders[int(r["order_id"])] = r
    route_map = fetch_routes_map()
    agg: Dict[str, float] = {}
    for p in pays:
        oid = p.get("order_id"); 
        if not oid or int(oid) not in orders: continue
        rid = orders[int(oid)].get("route_id")
        name = route_map.get(int(rid), f"ROUTE#{rid}") if rid is not None else "UNKNOWN"
        agg[name] = agg.get(name, 0.0) + _f(p.get("collected_amount", p.get("amount", 0)))
    return sorted(agg.items(), key=lambda x: x[1], reverse=True)

def agg_revenue_by_destination(lo: str, hi: str) -> List[Tuple[str, float]]:
    pays = fetch_payment_range(lo, hi, paid_only=True, end_inclusive=True)
    oids = [int(p["order_id"]) for p in pays if p.get("order_id")]
    if not oids: return []
    orders: Dict[int, Dict[str, Any]] = {}
    for i in range(0, len(oids), 200):
        ch = oids[i:i+200]
        rows = fetch_table_all("orders", {"in__order_id": ",".join(map(str, ch))})
        for r in rows: orders[int(r["order_id"])] = r
    dest_map = fetch_destinations_map()
    agg: Dict[str, float] = {}
    for p in pays:
        oid = p.get("order_id"); 
        if not oid or int(oid) not in orders: continue
        did = orders[int(oid)].get("destination_id")
        name = dest_map.get(int(did), f"DEST#{did}") if did is not None else "UNKNOWN"
        agg[name] = agg.get(name, 0.0) + _f(p.get("collected_amount", p.get("amount", 0)))
    return sorted(agg.items(), key=lambda x: x[1], reverse=True)

def agg_aov_by_customer(lo: str, hi: str) -> List[Tuple[str, float, int]]:
    orders = fetch_orders_range(lo, hi)
    by: Dict[int, Tuple[float,int]] = {}
    for o in orders:
        cid = o.get("customer_id")
        if cid is None: continue
        tot, cnt = by.get(int(cid), (0.0, 0))
        by[int(cid)] = (tot + _f(o.get("final_price_order")), cnt+1)
    out: List[Tuple[str,float,int]] = []
    for cid,(tot,cnt) in by.items():
        out.append((f"KH #{cid}", (tot/cnt if cnt else 0.0), cnt))
    return sorted(out, key=lambda x: x[1], reverse=True)

# =========================
# Kho/route helper
# =========================
def fetch_warehouse_in_period(lo: str, hi: str) -> List[Dict[str,Any]]:
    return fetch_table_all("warehouse", {"gte__created_at": lo, "lt__created_at": hi})

# =========================
# CN/VN country helpers & seller helpers
# =========================
def _loc_country_name_by_id(location_id: Optional[int]) -> Optional[str]:
    if location_id is None: 
        return None
    loc = fetch_table_all("warehouse_location", {"eq__location_id": int(location_id)}, page_size=1)
    if not loc: 
        return None
    return (loc[0].get("country") or "").strip()

def _is_country_cn(country: Optional[str]) -> bool:
    if not country: return False
    s = _fold(country); return any(h in s for h in COUNTRY_CN_HINTS)

def _is_country_vn(country: Optional[str]) -> bool:
    if not country: return False
    s = _fold(country); return any(h in s for h in COUNTRY_VN_HINTS)

def _extract_shop_from_link_or_field(ol: Dict[str,Any]) -> str:
    web = (ol.get("website") or "").strip()
    if web: return web.lower()
    link = (ol.get("product_link") or "").strip().lower()
    if not link: return "unknown"
    m = re.search(r"https?://([^/]+)/?", link)
    if m:
        host = re.sub(r"^(www\.|m\.)", "", m.group(1))
        return host
    return "unknown"

def _parse_int_days_from_text(s: Optional[str]) -> Optional[int]:
    if not s: return None
    low_high = re.findall(r"(\d+)\s*[-~–]\s*(\d+)", s)
    if low_high:
        try: a,b = map(int, low_high[0]); return max(a,b)
        except: pass
    single = re.findall(r"(\d+)\s*(?:d|day|days|ngay|ngày)", _fold(s))
    if single:
        try: return int(single[0])
        except: return None
    nums = re.findall(r"\d+", s)
    if nums:
        try: return int(max(nums, key=int))
        except: pass
    return None

def _route_sla_days(route_id: Optional[int]) -> int:
    if route_id is None: return DEFAULT_SHIP_SLA_DAYS
    rows = fetch_table_all("route", {"eq__route_id": int(route_id)}, page_size=1)
    if not rows: return DEFAULT_SHIP_SLA_DAYS
    raw = rows[0].get("ship_time")
    days = _parse_int_days_from_text(raw)
    return days or DEFAULT_SHIP_SLA_DAYS

# =========================
# Mua hộ — API & tính toán
# =========================
def filter_orders_mua_ho(lo: str, hi: str) -> List[Dict[str,Any]]:
    return fetch_table_all("orders", {"gte__created_at": lo, "lt__created_at": hi, "eq__order_type": ORDER_TYPE_MUA_HO})

def mua_ho_realtime_status(lo: str, hi: str) -> List[Dict[str,Any]]:
    rows = filter_orders_mua_ho(lo, hi)
    agg: Dict[str,int] = {}
    for r in rows:
        st = (r.get("status") or "UNKNOWN").upper()
        agg[st] = agg.get(st, 0) + 1
    return [{"status": k.replace("_"," ").title(), "orders": v} for k,v in sorted(agg.items(), key=lambda x:x[0])]

def mua_ho_today_week_month_counts(kind: str) -> Tuple[str,str,int]:
    if kind=="day": lo,hi = today_range_iso()
    elif kind=="week": lo,hi = this_week_range_iso()
    else: lo,hi = this_month_range_iso()
    rows = filter_orders_mua_ho(lo, hi)
    return lo, hi, len(rows)

def mua_ho_wait_to_buy(lo: str, hi: str) -> List[Dict[str, Any]]:
    rows = filter_orders_mua_ho(lo, hi)
    return [r for r in rows if (r.get("status") or "").upper() in ORDER_STATUSES_WAIT_BUY]

def orders_waiting_cn_wh(lo: str, hi: str, hint: Optional[str]=None) -> List[Dict[str,Any]]:
    # Đơn đang chờ về kho TQ: gần nghĩa "CHO_NHAP_KHO_NN"
    rows = filter_orders_mua_ho(lo, hi)
    return [r for r in rows if (r.get("status") or "").upper()=="CHO_NHAP_KHO_NN"]

def orders_arrived_cn_wait_ship_vn(lo: str, hi: str) -> List[Dict[str,Any]]:
    # Đã về kho TQ (có warehouse ở CN) nhưng đang chờ chuyển về VN => trạng thái "CHO_VAN_CHUYEN_KHO" hoặc chưa pack
    rows = filter_orders_mua_ho(lo, hi)
    oids = [int(r["order_id"]) for r in rows]
    if not oids: return []
    wh = []
    for i in range(0, len(oids), 300):
        ch = oids[i:i+300]
        wh.extend(fetch_table_all("warehouse", {"in__order_id": ",".join(map(str,ch))}))
    cn_oids = {int(w["order_id"]) for w in wh if _is_country_cn(_loc_country_name_by_id(w.get("location_id")))}
    out = []
    for r in rows:
        st = (r.get("status") or "").upper()
        if int(r["order_id"]) in cn_oids and (st in {"CHO_VAN_CHUYEN_KHO","CHO_DONG_GOI","DA_DONG_GOI"} or True):
            out.append(r)
    return out

def orders_at_port_customs(lo: str, hi: str) -> List[Dict[str,Any]]:
    # Ước lượng: lô DA_BAY nhưng chưa có warehouse VN ⇒ có thể đang ở cảng/hải quan
    packs = fetch_table_all("packing", {"gte__packed_date": lo, "lt__packed_date": hi, "eq__status": "DA_BAY"})
    if not packs: return []
    pids = [int(p["packing_id"]) for p in packs]
    wh = []
    for i in range(0, len(pids), 300):
        ch = pids[i:i+300]
        wh.extend(fetch_table_all("warehouse", {"in__packing_id": ",".join(map(str,ch))}))
    vn_pids = {int(w["packing_id"]) for w in wh if w.get("packing_id") and _is_country_vn(_loc_country_name_by_id(w.get("location_id")))}
    in_port = [p for p in packs if int(p["packing_id"]) not in vn_pids]
    # Liệt kê đơn thuộc các lô này:
    pack_ids = {int(p["packing_id"]) for p in in_port}
    items = [w for w in wh if w.get("packing_id") and int(w["packing_id"]) in pack_ids]
    # map order
    oids = sorted({int(x["order_id"]) for x in items if x.get("order_id")})
    outs = []
    for i in range(0, len(oids), 200):
        ch = oids[i:i+200]
        outs.extend(fetch_table_all("orders", {"in__order_id": ",".join(map(str,ch))}))
    return outs

def mua_ho_cancel_by_seller_or_out_of_stock(lo: str, hi: str) -> List[Dict[str,Any]]:
    ords = filter_orders_mua_ho(lo, hi)
    oids = [int(o["order_id"]) for o in ords if (o.get("status") or "").upper()=="DA_HUY"]
    if not oids: return []
    ols = []
    for i in range(0, len(oids), 200):
        ch = oids[i:i+200]
        ols.extend(fetch_table_all("order_links", {"in__order_id": ",".join(map(str,ch))}))
    bad_oids = set()
    for x in ols:
        st = (x.get("status") or "").upper()
        note = (x.get("note") or "").lower()
        if st=="DA_HUY" or "het hang" in note or "hết hàng" in note or "seller huy" in note:
            bad_oids.add(int(x["order_id"]))
    out = [o for o in ords if int(o["order_id"]) in bad_oids]
    return out

def mua_ho_urgent_issues(lo: str, hi: str) -> List[Dict[str,Any]]:
    rows = filter_orders_mua_ho(lo, hi)
    oids = [int(r["order_id"]) for r in rows]
    if not oids: return []
    fbs = fetch_feedback_by_orders(oids)
    bad_by_fb = {int(f["order_id"]) for f in fbs if int(f.get("rating", 5)) <= 2}
    bad_by_status = {int(r["order_id"]) for r in rows if (r.get("status") or "").upper()=="DA_HUY"}
    bad = bad_by_fb.union(bad_by_status)
    return [r for r in rows if int(r["order_id"]) in bad]

# “Đã đặt nhưng chưa thanh toán seller” — không có bảng payment_seller ⇒ dùng heuristic:
# có purchases nhưng orders.status vẫn trước “DA_NHAP_KHO_NN” & không có payment khách hàng ở PAID_STATUSES
def orders_ordered_not_paid_seller(lo: str, hi: str) -> List[Dict[str,Any]]:
    rows = filter_orders_mua_ho(lo, hi)
    if not rows: return []
    oids = [int(r["order_id"]) for r in rows]
    pur = []
    for i in range(0, len(oids), 300):
        ch = oids[i:i+300]
        pur.extend(fetch_table_all("purchases", {"in__order_id": ",".join(map(str,ch))}))
    has_purchase = {int(p["order_id"]) for p in pur}
    pays = []
    for i in range(0, len(oids), 300):
        ch = oids[i:i+300]
        pays.extend(fetch_table_all("payment", {"in__order_id": ",".join(map(str,ch))}))
    paid_oids = {int(p["order_id"]) for p in pays if (p.get("status") or "").upper() in PAID_STATUSES and p.get("order_id")}
    out = []
    for r in rows:
        oid = int(r["order_id"])
        st = (r.get("status") or "").upper()
        if oid in has_purchase and oid not in paid_oids and st in {"DA_XAC_NHAN","CHO_NHAP_KHO_NN","CHO_DONG_GOI","CHO_THANH_TOAN_DAU_GIA","CHO_MUA"}:
            out.append(r)
    return out

# =========================
# Seller analytics
# =========================
def sellers_frequent(lo: str, hi: str, topn: int = 20) -> List[Dict[str,Any]]:
    ords = filter_orders_mua_ho(lo, hi)
    oids = [int(o["order_id"]) for o in ords]
    if not oids: return []
    ols = []
    for i in range(0, len(oids), 300):
        ch = oids[i:i+300]
        ols.extend(fetch_table_all("order_links", {"in__order_id": ",".join(map(str,ch))}))
    by: Dict[str,int] = {}
    for ol in ols:
        shop = _extract_shop_from_link_or_field(ol)
        by[shop] = by.get(shop, 0) + 1
    rows = [{"shop": k, "orders": v} for k,v in sorted(by.items(), key=lambda x:x[1], reverse=True)[:topn]]
    return rows

def seller_on_time_stats(lo: str, hi: str) -> List[Dict[str,Any]]:
    ords = filter_orders_mua_ho(lo, hi)
    if not ords: return []
    oids = [int(o["order_id"]) for o in ords]
    pur = []
    for i in range(0, len(oids), 300):
        ch = oids[i:i+300]
        pur.extend(fetch_table_all("purchases", {"in__order_id": ",".join(map(str,ch))}))
    pur_by_oid: Dict[int, dt.datetime] = {}
    for p in pur:
        ts = p.get("purchase_time")
        if not ts: continue
        try: pur_by_oid[int(p["order_id"])] = dt.datetime.fromisoformat(ts)
        except: pass

    wh = []
    for i in range(0, len(oids), 300):
        ch = oids[i:i+300]
        wh.extend(fetch_table_all("warehouse", {"in__order_id": ",".join(map(str,ch))}))
    cn_first_by_oid: Dict[int, dt.datetime] = {}
    for w in sorted(wh, key=lambda x: x.get("created_at","")):
        try:
            oid = int(w["order_id"])
            if oid in cn_first_by_oid: continue
            if _is_country_cn(_loc_country_name_by_id(w.get("location_id"))):
                cn_first_by_oid[oid] = dt.datetime.fromisoformat(w.get("created_at"))
        except: pass

    ols = []
    for i in range(0, len(oids), 300):
        ch = oids[i:i+300]
        ols.extend(fetch_table_all("order_links", {"in__order_id": ",".join(map(str,ch))}))
    shop_by_oid: Dict[int,str] = {}
    for ol in ols:
        shop_by_oid[int(ol["order_id"])] = _extract_shop_from_link_or_field(ol)

    by: Dict[str, Dict[str,int]] = {}
    for o in ords:
        oid = int(o["order_id"])
        shop = shop_by_oid.get(oid, "unknown")
        if shop not in by: by[shop] = {"total":0,"on":0}
        by[shop]["total"] += 1
        ptime = pur_by_oid.get(oid); ctime = cn_first_by_oid.get(oid)
        if not ptime or not ctime: continue
        sla = _route_sla_days(o.get("route_id"))
        if (ctime - ptime).days <= sla:
            by[shop]["on"] += 1

    rows = []
    for shop,stat in by.items():
        if stat["total"] == 0: continue
        rate = stat["on"] / stat["total"]
        rows.append({"shop": shop, "on_time_rate": f"{rate:.0%}", "orders": stat["total"]})
    rows.sort(key=lambda x: (-float(x["on_time_rate"].rstrip("%")), -x["orders"]))
    return rows

def seller_orders_inprogress(shop_name: str, lo: str, hi: str) -> List[Dict[str,Any]]:
    ords = filter_orders_mua_ho(lo, hi)
    if not ords: return []
    oids = [int(o["order_id"]) for o in ords]
    ols = []
    for i in range(0, len(oids), 300):
        ch = oids[i:i+300]
        ols.extend(fetch_table_all("order_links", {"in__order_id": ",".join(map(str,ch))}))
    shop_oids = {int(ol["order_id"]) for ol in ols if shop_name.lower() in _extract_shop_from_link_or_field(ol)}
    out = [o for o in ords if int(o["order_id"]) in shop_oids and (o.get("status") or "").upper() in ORDER_STATUSES_INPROGRESS]
    return out

def seller_late_or_cancel_stats(lo: str, hi: str, topn: int = 20) -> List[Dict[str,Any]]:
    ords = filter_orders_mua_ho(lo, hi)
    if not ords: return []
    oids = [int(o["order_id"]) for o in ords]

    pur = []
    for i in range(0, len(oids), 300):
        ch = oids[i:i+300]
        pur.extend(fetch_table_all("purchases", {"in__order_id": ",".join(map(str,ch))}))
    pur_by_oid: Dict[int, dt.datetime] = {}
    for p in pur:
        ts = p.get("purchase_time")
        if not ts: continue
        try: pur_by_oid[int(p["order_id"])] = dt.datetime.fromisoformat(ts)
        except: pass

    wh = []
    for i in range(0, len(oids), 300):
        ch = oids[i:i+300]
        wh.extend(fetch_table_all("warehouse", {"in__order_id": ",".join(map(str,ch))}))
    cn_first_by_oid: Dict[int, dt.datetime] = {}
    for w in sorted(wh, key=lambda x: x.get("created_at","")):
        try:
            oid = int(w["order_id"])
            if oid in cn_first_by_oid: continue
            if _is_country_cn(_loc_country_name_by_id(w.get("location_id"))):
                cn_first_by_oid[oid] = dt.datetime.fromisoformat(w.get("created_at"))
        except: pass

    ols = []
    for i in range(0, len(oids), 300):
        ch = oids[i:i+300]
        ols.extend(fetch_table_all("order_links", {"in__order_id": ",".join(map(str,ch))}))
    by: Dict[str, Dict[str,int]] = {}  # shop -> {'total','late','cancel'}
    shop_of_oid: Dict[int,str] = {}
    for ol in ols:
        shop = _extract_shop_from_link_or_field(ol)
        shop_of_oid[int(ol["order_id"])] = shop
        d = by.setdefault(shop, {"total":0,"late":0,"cancel":0})
        d["total"] += 1
        if (ol.get("status","").upper() == "DA_HUY"):
            d["cancel"] += 1

    route_cache: Dict[int,int] = {}
    for o in ords:
        oid = int(o["order_id"])
        shop = shop_of_oid.get(oid, "unknown")
        ptime = pur_by_oid.get(oid); ctime = cn_first_by_oid.get(oid)
        if not ptime or not ctime: 
            continue
        rid = o.get("route_id")
        sla = route_cache.get(int(rid), None) if rid is not None else None
        if sla is None:
            sla = _route_sla_days(rid)
            if rid is not None:
                route_cache[int(rid)] = sla
        if (ctime - ptime).days > sla:
            by.setdefault(shop, {"total":0,"late":0,"cancel":0})
            by[shop]["late"] += 1

    rows = []
    for shop, d in by.items():
        total = max(1, d["total"])
        late_rate = d["late"]/total
        cancel_rate = d["cancel"]/total
        rows.append({
            "shop": shop,
            "late_rate": f"{late_rate:.0%}",
            "cancel_rate": f"{cancel_rate:.0%}",
            "orders": d["total"]
        })
    rows.sort(key=lambda x: (-float(x["late_rate"].rstrip("%")), -x["orders"]))
    return rows[:topn]

def seller_reputation(shop_name: str, lo: str, hi: str) -> Dict[str,Any]:
    ords = filter_orders_mua_ho(lo, hi)
    if not ords: return {"shop": shop_name, "on_time_rate":"N/A", "cancel_rate":"N/A", "avg_rating":"N/A", "orders":0}
    oids = [int(o["order_id"]) for o in ords]
    ols = []
    for i in range(0, len(oids), 300):
        ch = oids[i:i+300]
        ols.extend(fetch_table_all("order_links", {"in__order_id": ",".join(map(str,ch))}))
    target_oids = {int(ol["order_id"]) for ol in ols if shop_name.lower() in _extract_shop_from_link_or_field(ol)}
    if not target_oids:
        return {"shop": shop_name, "on_time_rate":"N/A", "cancel_rate":"N/A", "avg_rating":"N/A", "orders":0}

    fbs = fetch_feedback_by_orders(list(target_oids))
    ratings = [int(f.get("rating", 0)) for f in fbs if f.get("rating") is not None]
    avg_rating = f"{(sum(ratings)/len(ratings)):.2f}" if ratings else "N/A"

    all_stats = seller_late_or_cancel_stats(lo, hi, topn=9999)
    by_name = {r["shop"]: r for r in all_stats}
    row = by_name.get(shop_name.lower()) or by_name.get(shop_name) or {}
    if row:
        # on_time_rate = 100% - late_rate
        try:
            late = float(row["late_rate"].rstrip("%"))
            on_time = f"{int(round(100 - late))}%"
        except:
            on_time = "N/A"
        cancel_rate = row.get("cancel_rate","N/A")
    else:
        on_time = "N/A"; cancel_rate = "N/A"

    return {"shop": shop_name, "on_time_rate": on_time, "cancel_rate": cancel_rate, "avg_rating": avg_rating, "orders": len(target_oids)}

def seller_avg_days_to_cn(shop_name: str, lo: str, hi: str) -> Optional[float]:
    ords = filter_orders_mua_ho(lo, hi)
    if not ords: return None
    oids = [int(o["order_id"]) for o in ords]
    ols = []
    for i in range(0, len(oids), 300):
        ch = oids[i:i+300]
        ols.extend(fetch_table_all("order_links", {"in__order_id": ",".join(map(str,ch))}))
    target_oids = {int(ol["order_id"]) for ol in ols if shop_name.lower() in _extract_shop_from_link_or_field(ol)}
    if not target_oids: return None

    pur = []
    for i in range(0, len(oids), 300):
        ch = oids[i:i+300]
        pur.extend(fetch_table_all("purchases", {"in__order_id": ",".join(map(str,ch))}))
    pur_by_oid: Dict[int, dt.datetime] = {}
    for p in pur:
        ts = p.get("purchase_time")
        if not ts: continue
        try: pur_by_oid[int(p["order_id"])] = dt.datetime.fromisoformat(ts)
        except: pass

    wh = []
    for i in range(0, len(oids), 300):
        ch = oids[i:i+300]
        wh.extend(fetch_table_all("warehouse", {"in__order_id": ",".join(map(str,ch))}))
    cn_first_by_oid: Dict[int, dt.datetime] = {}
    for w in sorted(wh, key=lambda x: x.get("created_at","")):
        try:
            oid = int(w["order_id"])
            if oid in cn_first_by_oid: continue
            if _is_country_cn(_loc_country_name_by_id(w.get("location_id"))):
                cn_first_by_oid[oid] = dt.datetime.fromisoformat(w.get("created_at"))
        except: pass

    deltas = []
    for oid in target_oids:
        if oid in pur_by_oid and oid in cn_first_by_oid:
            deltas.append( (cn_first_by_oid[oid] - pur_by_oid[oid]).days )
    if not deltas: return None
    return sum(deltas)/len(deltas)

def sellers_blacklist_candidates(lo: str, hi: str, cancel_threshold: float = 0.3, min_orders: int = 5) -> List[Dict[str,Any]]:
    stats = seller_late_or_cancel_stats(lo, hi, topn=9999)
    out = []
    for r in stats:
        total = r["orders"]
        c_rate = float(r["cancel_rate"].rstrip("%"))/100.0 if isinstance(r["cancel_rate"], str) and r["cancel_rate"].endswith("%") else 0.0
        if total >= min_orders and c_rate >= cancel_threshold:
            r2 = dict(r); r2["reason"] = f"Cancel rate ≥ {int(cancel_threshold*100)}% và đơn ≥ {min_orders}"
            out.append(r2)
    return out

# =========================
# Kho Trung Quốc
# =========================
def cn_warehouse_counts(lo: str, hi: str) -> int:
    rows = fetch_table_all("warehouse", {"gte__created_at": lo, "lt__created_at": hi})
    cnt = 0
    for w in rows:
        st = (w.get("status") or "").upper()
        if st not in {"DA_NHAP_KHO","DANG_DOI_TRA"}: 
            continue
        country = _loc_country_name_by_id(w.get("location_id"))
        if _is_country_cn(country):
            cnt += 1
    return cnt

def has_order_arrived_cn(order_code: str) -> bool:
    od = fetch_order_by_code(order_code)
    if not od: return False
    owh = fetch_table_all("warehouse", {"eq__order_id": int(od["order_id"])})
    for w in owh:
        if _is_country_cn(_loc_country_name_by_id(w.get("location_id"))):
            return True
    return False

def cn_wait_packing_list(lo: str, hi: str) -> List[Dict[str,Any]]:
    rows = fetch_table_all("warehouse", {"gte__created_at": lo, "lt__created_at": hi})
    out = []
    for w in rows:
        if _is_country_cn(_loc_country_name_by_id(w.get("location_id"))) and not w.get("packing_id"):
            out.append(w)
    return out

def cn_overstay_items(lo: str, hi: str, days: int = 14) -> List[Dict[str,Any]]:
    now = _now()
    rows = fetch_table_all("warehouse", {"lt__created_at": hi})
    out = []
    for w in rows:
        if not _is_country_cn(_loc_country_name_by_id(w.get("location_id"))):
            continue
        try:
            created = dt.datetime.fromisoformat(w.get("created_at"))
            if (now - created).days >= days:
                out.append(w)
        except: pass
    return out

def cn_total_weight(lo: str, hi: str) -> float:
    rows = fetch_table_all("warehouse", {"gte__created_at": lo, "lt__created_at": hi})
    s = 0.0
    for w in rows:
        if _is_country_cn(_loc_country_name_by_id(w.get("location_id"))):
            s += _f(w.get("weight", 0))
    return s

# =========================
# Vận chuyển quốc tế
# =========================
def intl_in_transit_batches(lo: str, hi: str) -> List[Dict[str,Any]]:
    rows = []
    rows.extend(fetch_table_all("packing", {"gte__packed_date": lo, "lt__packed_date": hi, "eq__status":"DA_BAY"}))
    # nếu muốn tính cả CHO_BAY thì mở rộng thêm:
    # rows.extend(fetch_table_all("packing", {"gte__packed_date": lo, "lt__packed_date": hi, "eq__status":"CHO_BAY"}))
    return rows

def order_belongs_to_batch(order_code: str) -> Optional[str]:
    od = fetch_order_by_code(order_code)
    if not od: return None
    wh = fetch_table_all("warehouse", {"eq__order_id": int(od["order_id"])})
    for w in wh:
        if w.get("packing_id"):
            pk = fetch_table_all("packing", {"eq__packing_id": int(w["packing_id"])}, page_size=1)
            if pk: 
                return pk[0].get("packing_code")
    return None

def tracking_batch(packing_code: str) -> Optional[Dict[str,Any]]:
    pk = fetch_table_all("packing", {"eq__packing_code": packing_code}, page_size=1)
    if not pk: return None
    p = pk[0]
    return {"packing_code": p.get("packing_code"), "status": p.get("status"), "packed_date": p.get("packed_date")}

def avg_transit_days_cn_to_vn(lo: str, hi: str) -> Optional[float]:
    packs = fetch_table_all("packing", {"gte__packed_date": lo, "lt__packed_date": hi, "eq__status":"DA_BAY"})
    if not packs: return None
    pids = [int(p["packing_id"]) for p in packs]
    wh = []
    for i in range(0, len(pids), 300):
        ch = pids[i:i+300]
        wh.extend(fetch_table_all("warehouse", {"in__packing_id": ",".join(map(str,ch))}))
    vn_first: Dict[int, dt.datetime] = {}
    for w in sorted(wh, key=lambda x: x.get("created_at","")):
        try:
            pid = int(w["packing_id"] or 0)
            if not pid or pid in vn_first: 
                continue
            if _is_country_vn(_loc_country_name_by_id(w.get("location_id"))):
                vn_first[pid] = dt.datetime.fromisoformat(w.get("created_at"))
        except: pass
    deltas = []
    for p in packs:
        pid = int(p["packing_id"])
        if pid in vn_first:
            try:
                t1 = dt.datetime.fromisoformat(p["packed_date"])
                deltas.append( (vn_first[pid] - t1).days )
            except: pass
    if not deltas: return None
    return sum(deltas)/len(deltas)

# =========================
# Hồ sơ tài khoản tổng hợp
# =========================
def person_full_profile(identifier_type: str, identifier_value: Union[str,int], recent_limit: int = 20) -> Optional[Dict[str, Any]]:
    acct = fetch_account_by_field(identifier_type, identifier_value)
    if not acct: return None
    account_id = int(acct['account_id'])
    role = (acct.get('role') or '').upper()
    profile: Dict[str, Any] = {
        'account': acct, 'role': role, 'customer': None, 'staff': None,
        'orders_recent': [], 'payments_recent': [],
        'aggregates': {}, 'logs_recent': [], 'feedback_recent': [], 'warehouse_recent': []
    }
    cust_rows = fetch_table_all('customer', {'eq__account_id': account_id}, page_size=5)
    if cust_rows: profile['customer'] = cust_rows[0]
    staff_rows = fetch_table_all('staff', {'eq__account_id': account_id}, page_size=5)
    if staff_rows: profile['staff'] = staff_rows[0]

    orders = []
    if profile['customer']:
        cid = int(profile['customer']['account_id'])
        orders.extend(fetch_table_all('orders', {'eq__customer_id': cid, 'order':'created_at','desc':True}, page_size=recent_limit))
    if profile['staff']:
        sid = int(profile['staff']['account_id'])
        orders.extend(fetch_table_all('orders', {'eq__staff_id': sid, 'order':'created_at','desc':True}, page_size=recent_limit))
    seen = {}; merged = []
    for o in orders:
        oid = int(o['order_id'])
        if oid in seen: continue
        seen[oid]=1; merged.append(o)
    profile['orders_recent'] = merged[:recent_limit]

    pays = []
    if profile['customer']:
        cid = int(profile['customer']['account_id'])
        pays = fetch_table_all('payment', {'eq__customer_id': cid, 'order':'action_at','desc':True}, page_size=recent_limit)
    else:
        oids = [int(o['order_id']) for o in profile['orders_recent']][:200]
        if oids:
            for i in range(0, len(oids), 100):
                ch = oids[i:i+100]
                pays.extend(fetch_table_all('payment', {'in__order_id': ','.join(map(str,ch)), 'order':'action_at','desc':True}, page_size=recent_limit))
    pays = pays[:recent_limit]
    profile['payments_recent'] = pays

    total_paid = sum(_f(p.get('collected_amount', p.get('amount', 0))) for p in pays if (p.get('status') or '').upper() in PAID_STATUSES)
    outstanding = sum(_f(p.get('amount',0)) for p in pays if (p.get('status') or '').upper() in UNPAID_STATUSES)
    profile['aggregates'] = {'total_paid_recent': total_paid, 'outstanding_recent': outstanding, 'payments_count_recent': len(pays)}

    oids = [int(o['order_id']) for o in profile['orders_recent']][:200]
    logs = []
    if oids:
        for i in range(0, len(oids), 100):
            ch = oids[i:i+100]
            logs.extend(fetch_table_all('order_process_log', {'in__order_id': ','.join(map(str,ch)), 'order':'timestamp','desc':True}, page_size=recent_limit))
    profile['logs_recent'] = logs[:recent_limit]

    fbs = fetch_feedback_by_orders(oids) if oids else []
    profile['feedback_recent'] = fbs[:recent_limit]

    wh = []
    if oids:
        wh.extend(fetch_table_all('warehouse', {'in__order_id': ','.join(map(str,oids)), 'order':'created_at','desc':True}, page_size=recent_limit))
    if profile['staff']:
        wh.extend(fetch_table_all('warehouse', {'eq__staff_id': account_id, 'order':'created_at','desc':True}, page_size=recent_limit))
    profile['warehouse_recent'] = wh[:recent_limit]

    return profile

# =========================
# Intent nhận diện
# =========================
def classify_query(text: str) -> Tuple[str, Dict[str, Any], float]:
    s = _fold(text)
    m = _EMAIL_RE.search(text or "")
    if m: return ("profile_by", {"field":"email","value":m.group(0)}, 0.95)
    if _PHONE_FULL_RE.fullmatch((text or "").strip()):
        return ("profile_by", {"field":"phone","value":text.strip()}, 0.92)
    code = extract_order_code_from_text(text or "")
    if code: return ("order_lookup", {"code": code}, 0.98)

    # Revenue ranges
    if "doanh thu thang" in s or s.endswith("thang nay"):
        return ("revenue_month", {}, 0.90)
    if "doanh thu tuan" in s or s.endswith("tuan nay"):
        return ("revenue_week", {}, 0.88)
    if "doanh thu ngay" in s or "hom nay" in s or "hôm nay" in text.lower():
        return ("revenue_day", {}, 0.80)

    # Others classic
    if "cash flow" in s or "dong tien" in s:
        return ("cashflow", {}, 0.85)
    if "doanh thu theo tuyen" in s or "doanh thu theo tuyến" in text:
        return ("revenue_by_route", {}, 0.85)
    if "doanh thu theo diem den" in s:
        return ("revenue_by_destination", {}, 0.80)
    if "doanh thu theo nhan vien" in s or "nhan vien sale" in s:
        return ("revenue_by_staff", {}, 0.90)
    if "top 10 khach hang" in s:
        return ("top_customers", {}, 0.90)
    if "trung binh gia tri don hang" in s:
        return ("aov_by_customer", {}, 0.85)
    if "don cho mua" in s:
        return ("orders_wait_buy", {}, 0.90)
    if "don da mua" in s or "da mua hang" in s:
        return ("orders_purchased", {}, 0.90)
    if "hang trong kho" in s or "kho hien co" in s or "ton kho" in s:
        return ("warehouse_inventory", {}, 0.85)
    if "chuyen bay cho" in s or "cho bay" in s:
        return ("flights_waiting", {}, 0.85)

    if "thong tin id" in s:
        m = re.search(r"(\d+)", text or "")
        if m: return ("profile_by", {"field":"account_id","value":int(m.group(1))}, 0.85)
    if "thong tin sdt" in s:
        m = re.search(r"(\+?\d{9,13})", text or "")
        if m: return ("profile_by", {"field":"phone","value":m.group(1)}, 0.92)
    if "thong tin email" in s:
        m = _EMAIL_RE.search(text or "")
        if m: return ("profile_by", {"field":"email","value":m.group(0)}, 0.95)

    # ======= Mua hộ tổng thể =======
    if "tong so don mua ho hom nay" in s or "tổng số đơn mua hộ hôm nay" in text.lower(): return ("mh_total_today", {}, 0.92)
    if "tong so don mua ho tuan nay" in s or "tổng số đơn mua hộ tuần này" in text.lower(): return ("mh_total_week", {}, 0.92)
    if "tong so don mua ho thang nay" in s or "tổng số đơn mua hộ tháng này" in text.lower(): return ("mh_total_month", {}, 0.92)
    if "dang cho dat hang" in s or "đang chờ đặt hàng" in text.lower(): return ("mh_wait_buy", {}, 0.92)
    if ("da dat" in s and "chua thanh toan" in s) or ("đã đặt" in text.lower() and "chưa thanh toán" in text.lower()): return ("mh_ordered_not_paid_seller", {}, 0.92)
    if "dang cho ve kho tq" in s or "đang chờ về kho tq" in text.lower(): return ("mh_wait_cn_wh", {"hint": "CN"}, 0.90)
    if "da ve kho tq" in s and ("cho van chuyen" in s or "chờ vận chuyển" in text.lower()): return ("mh_arrived_cn_wait_vn", {}, 0.90)
    if "cang" in s or "hai quan" in s or "hải quan" in text.lower(): return ("mh_at_port", {}, 0.88)
    if "trang thai tat ca don mua ho" in s or "trạng thái tất cả đơn mua hộ" in text.lower(): return ("mh_realtime_status", {}, 0.90)
    if "bi seller huy" in s or "hết hàng" in text.lower() or "het hang" in s: return ("mh_seller_cancel_oos", {}, 0.88)
    if "van de can xu ly gap" in s or "cần xử lý gấp" in text.lower(): return ("mh_urgent_issues", {}, 0.88)

    # ======= Seller =======
    if "danh sach shop thuong xuyen" in s or "danh sách shop thường xuyên" in text.lower() or "danh sach shop" in s: return ("seller_frequent", {}, 0.90)
    if "ti le giao hang dung han" in s or "tỷ lệ giao hàng đúng hạn" in text.lower(): return ("seller_on_time_rate", {}, 0.90)
    if "shop" in s or "seller" in s:
        mshop = _RE_SHOP_NAME.search(text or "")
        if mshop and ("dang xu ly" in s or "đang xử lý" in text.lower()): return ("seller_inprogress_for_name", {"shop": mshop.group(1).strip()}, 0.92)
        if mshop and ("uy tin" in s or "uy tín" in text.lower()): return ("seller_reputation", {"shop": mshop.group(1).strip()}, 0.90)
        if mshop and ("mat bao lau ve kho" in s or "mất bao lâu về kho" in text.lower()): return ("seller_avg_to_cn", {"shop": mshop.group(1).strip()}, 0.90)
    if "seller hay giao cham" in s or "giao chậm" in text.lower() or "huy don" in s or "hủy đơn" in text.lower(): return ("seller_late_or_cancel", {}, 0.90)
    if "blacklist" in s: return ("seller_blacklist", {}, 0.88)

    # ======= Kho Trung Quốc =======
    if "bao nhieu kien hang dang o kho tq" in s or "bao nhieu kien hang dang o kho trung quoc" in s or "bao nhiêu kiện hàng đang ở kho tq" in text.lower(): return ("cn_count_items", {}, 0.90)
    if "hang cua don" in s and ("ve kho tq chua" in s or "về kho tq chưa" in text.lower()):
        code = extract_order_code_from_text(text or "")
        if code: return ("cn_order_arrived", {"code": code}, 0.92)
    if "cho dong goi o kho tq" in s or "chờ đóng gói ở kho tq" in text.lower(): return ("cn_wait_packing", {}, 0.90)
    if "ton kho tq qua lau" in s or "tồn kho tq quá lâu" in text.lower(): return ("cn_overstay", {}, 0.88)
    if "chi phi luu kho tq" in s or "chi phí lưu kho tq" in text.lower(): return ("cn_storage_cost", {}, 0.80)
    if "kho tq qua tai" in s or "kho tq nào đang quá tải" in text.lower(): return ("cn_overloaded", {}, 0.80)
    if "can nang thuc te hang ve kho tq" in s or "cân nặng thực tế hàng về kho tq" in text.lower(): return ("cn_total_weight", {}, 0.90)

    # ======= Vận chuyển quốc tế =======
    if "bao nhieu lo hang dang tren duong" in s or "đang trên đường từ tq về vn" in text.lower(): return ("intl_in_transit", {}, 0.90)
    if "lo hang" in s and ("du kien ve" in s or "dự kiến về" in text.lower()): return ("intl_eta", {}, 0.80)
    if "don" in s and "nam trong lo hang nao" in s:
        code = extract_order_code_from_text(text or "")
        if code: return ("intl_order_batch", {"code": code}, 0.90)
    if "ket hai quan" in s or "kẹt ở hải quan" in text.lower(): return ("intl_customs_stuck", {}, 0.80)
    if "chi phi van chuyen quoc te" in s: return ("intl_cost", {}, 0.80)
    if "doi tac van chuyen hieu qua" in s or "đối tác vận chuyển nào hiệu quả" in text.lower(): return ("intl_partner", {}, 0.80)
    if "thoi gian van chuyen trung binh" in s or "thời gian vận chuyển trung bình" in text.lower(): return ("intl_avg_time", {}, 0.90)
    if "tracking lo hang" in s or "tracking lô hàng" in text.lower():
        m = re.search(r"(?:packing|lo|lô)\s*([A-Za-z0-9\-]+)", text or "", re.IGNORECASE)
        if m: return ("intl_tracking", {"packing_code": m.group(1)}, 0.90)

    return ("unknown", {}, 0.40)

# =========================
# CLI main
# =========================
BANNER = """
Tiximax DB-CLI — hỏi gì đáp nấy (orders/payments/warehouse/packing/domestic/feedback…)
Thoát: exit | quit | thoat
""".strip()

def main():
    print(BANNER)
    while True:
        try:
            s = input("\nBạn hỏi> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nTạm biệt."); break
        if not s: continue
        if _fold(s) in {"thoat","exit","quit"}:
            print("Tạm biệt."); break

        intent, params, conf = classify_query(s)

        # Order lookup / fallback unknown → thử mã đơn
        if intent in {"order_lookup","unknown"}:
            code = extract_order_code_from_text(s)
            if code:
                snap = order_snapshot_by_code(code)
                print(format_snapshot(snap))
                if snap is None:
                    print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})")
                continue
            if intent == "unknown":
                print("⚠️  Chưa nhận diện được ý định. Thử: 'doanh thu tháng này' / mã đơn 'OD2025…' / 'thông tin email a@b.com'")
                continue

        # Profile by email/phone/id
        if intent == "profile_by":
            fld, val = params["field"], params["value"]
            prof = person_full_profile(fld, val, recent_limit=20)
            if not prof:
                print("❌ Không tìm thấy tài khoản."); continue
            acct = prof["account"]
            role = (acct.get("role") or "").upper()
            print(f"👤 Account #{acct.get('account_id')} — {acct.get('name','N/A')}")
            print(f"   • Email: {acct.get('email','N/A')} | Phone: {acct.get('phone','N/A')} | Username: {acct.get('username','N/A')}")
            print(f"   • Role: {role or 'N/A'} | Status: {acct.get('status','N/A')}")
            if prof.get("staff"):
                st = prof["staff"]
                print(f"🧑‍💼 Staff: code={st.get('staff_code','')} | location={st.get('location','')} | dept={st.get('department','')}")
            ag = prof["aggregates"]
            print(f"💰 Payments recent: paid={money_fmt(ag.get('total_paid_recent',0))} | outstanding={money_fmt(ag.get('outstanding_recent',0))} | count={ag.get('payments_count_recent',0)}")
            ords = [{"order_code": o.get("order_code",""), "status": o.get("status","")} for o in prof["orders_recent"][:10]]
            if ords:
                print("📦 Orders recent: " + ", ".join(f"{o['order_code']}({o['status']})" for o in ords))
            print(f"🏬 Warehouse records recent: {len(prof['warehouse_recent'])}")
            print(f"📝 Logs recent: {len(prof['logs_recent'])}")
            print(f"⭐ Feedback recent: {len(prof['feedback_recent'])}")
            continue

        # Revenue Day/Week/Month
        if intent in {"revenue_month","revenue_week","revenue_day"}:
            label = "tháng" if intent=="revenue_month" else ("tuần" if intent=="revenue_week" else "ngày")
            if intent=="revenue_month":
                # Thử parse “tháng 9/2025 ...”
                parsed = resolve_month_from_text(s, _now(), VN_TZ)
                if parsed: lo,hi = parsed
                else: lo, hi = this_month_range_iso()
            elif intent=="revenue_week":
                lo, hi = this_week_range_iso()
            else:
                lo, hi = today_range_iso()

            pays_paid = fetch_payment_range(lo, hi, paid_only=True, end_inclusive=False)
            pays_unpaid = fetch_table_all("payment", {"gte__action_at": lo, "lt__action_at": hi, "in__status": ",".join(sorted(UNPAID_STATUSES))})
            total = sum_revenue_from_payments(pays_paid)
            print(f"💰 Doanh thu {lo} → {hi}: {money_fmt(total)} (giao dịch: {len(pays_paid)})")

            # Bảng tổng
            rows_total = [{
                "window": f"{lo[:10]}→{hi[:10]}",
                "paid_orders": len(pays_paid),
                "paid_amount": money_fmt(sum_revenue_from_payments(pays_paid)),
                "unpaid_orders": len(pays_unpaid),
                "unpaid_amount": money_fmt(sum(_f(r.get('amount')) for r in pays_unpaid)),
            }]
            print(f"\n▶ Theo {label}")
            print(_print_table(rows_total, ["window","paid_orders","paid_amount","unpaid_orders","unpaid_amount"]))

            # Tổng hợp PAID/UNPAID
            grp = [
                {"group":"PAID_STATUSES",   "orders": len(pays_paid),   "amount": money_fmt(sum_revenue_from_payments(pays_paid))},
                {"group":"UNPAID_STATUSES", "orders": len(pays_unpaid), "amount": money_fmt(sum(_f(r.get('amount')) for r in pays_unpaid))},
            ]
            print(f"\n▶ Tổng hợp thanh toán ({label})")
            print(_print_table(grp, ["group","orders","amount"]))

            # Chi tiết theo từng status
            def _agg_by_status(rows: List[Dict[str,Any]], paid: bool) -> List[Dict[str,Any]]:
                by: Dict[str, float] = {}
                cnt: Dict[str, int] = {}
                for r in rows:
                    st = (r.get("status") or "").upper()
                    v = _f(r.get("collected_amount" if paid else "amount"))
                    by[st] = by.get(st, 0.0) + v
                    cnt[st] = cnt.get(st, 0) + 1
                out = [{"pay_status": k, "orders": cnt.get(k,0), "amount": money_fmt(by.get(k,0.0))} for k in sorted((cnt.keys() | by.keys()))]
                return out

            det_paid = _agg_by_status(pays_paid, True)
            det_unpd = _agg_by_status(pays_unpaid, False)

            print(f"\n▶ Chi tiết thanh toán ({label}) — PAID_STATUSES")
            print(_print_table(det_paid, ["pay_status","orders","amount"]) if det_paid else "(khong co du lieu)")
            print(f"\n▶ Chi tiết thanh toán ({label}) — UNPAID_STATUSES")
            print(_print_table(det_unpd, ["pay_status","orders","amount"]) if det_unpd else "(khong co du lieu)")

            # Theo tuyến (chỉ tháng)
            if intent=="revenue_month":
                wh = fetch_warehouse_in_period(lo, hi)
                routes = fetch_routes_map()
                kg = {}
                for r in wh:
                    rid = r.get("route_id"); w = _f(r.get("weight"))
                    name = routes.get(int(rid), f"ROUTE#{rid}") if rid is not None else "UNKNOWN"
                    kg[name] = kg.get(name, 0.0) + w
                rows = [{"route": k, "kg": round(v,2)} for k,v in sorted(kg.items())]
                print("\n▶ Số kg theo tuyến (theo warehouse.created_at trong tháng)")
                print(_print_table(rows, ["route","kg"]) if rows else "(khong co du lieu)")

                # Trạng thái đơn (orders.status)
                ords = fetch_orders_range(lo, hi)
                agg: Dict[str,int] = {}
                for o in ords:
                    st = (o.get("status") or "UNKNOWN").upper()
                    agg[st] = agg.get(st,0)+1
                stat_rows = [{"status": k.replace("_"," ").title(), "orders": v} for k,v in sorted(agg.items())]
                print("\n▶ Trạng thái đơn (tháng)")
                print(_print_table(stat_rows, ["status","orders"]) if stat_rows else "(khong co du lieu)")
                print("ℹ️  Lưu ý: Đây là trạng thái NGHIỆP VỤ của đơn (orders.status), KHÁC với trạng thái thanh toán (payment.status).")

            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})")
            continue

        # KPI khác
        if intent == "cashflow":
            lo, hi = this_month_range_iso()
            pays = fetch_payment_range(lo, hi, paid_only=True, end_inclusive=True)
            buckets: Dict[str, float] = {}
            for p in pays:
                ts = p.get("action_at"); 
                if not ts: continue
                d = ts[:10]
                buckets[d] = buckets.get(d, 0.0) + _f(p.get("collected_amount", p.get("amount", 0)))
            pairs = sorted(buckets.items())
            print(_print_table([{"date": d, "collected": money_fmt(v)} for d,v in pairs], ["date","collected"]) or "(khong co du lieu)")
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue

        if intent == "revenue_by_staff":
            lo, hi = this_month_range_iso()
            pays = fetch_payment_range(lo, hi, paid_only=True, end_inclusive=False)
            agg = group_revenue_by_staff(pays)
            rows = []
            for sid, amt in sorted(agg.items(), key=lambda x: x[1], reverse=True):
                acct = fetch_account_by_id(int(sid)) or {}
                rows.append({"staff_id": sid, "name": acct.get("name",""), "revenue": money_fmt(amt)})
            print(_print_table(rows, ["staff_id","name","revenue"]) if rows else "(khong co du lieu)")
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue

        if intent == "revenue_by_route":
            lo, hi = this_month_range_iso()
            rows = [{"route": k, "revenue": money_fmt(v)} for k,v in agg_revenue_by_route(lo, hi)]
            print(_print_table(rows, ["route","revenue"]) if rows else "(khong co du lieu)")
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue

        if intent == "revenue_by_destination":
            lo, hi = this_month_range_iso()
            rows = [{"destination": k, "revenue": money_fmt(v)} for k,v in agg_revenue_by_destination(lo, hi)]
            print(_print_table(rows, ["destination","revenue"]) if rows else "(khong co du lieu)")
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue

        if intent == "top_customers":
            lo, hi = this_month_range_iso()
            pays = fetch_payment_range(lo, hi, paid_only=True, end_inclusive=False)
            by: Dict[int,float] = {}
            for p in pays:
                cid = p.get("customer_id")
                if cid is None: continue
                by[int(cid)] = by.get(int(cid), 0.0) + _f(p.get("collected_amount", p.get("amount", 0)))
            rows = []
            for cid, paid in sorted(by.items(), key=lambda x: x[1], reverse=True)[:10]:
                acct = fetch_account_by_id(int(cid)) or {}
                rows.append({"customer_id": cid, "name": f"{acct.get('name','')} ({cid})", "paid": money_fmt(paid)})
            print(_print_table(rows, ["customer_id","name","paid"]) if rows else "(khong co du lieu)")
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue

        if intent == "aov_by_customer":
            lo, hi = this_month_range_iso()
            rows = [{"customer": k, "AOV": money_fmt(v), "orders": n} for (k,v,n) in agg_aov_by_customer(lo, hi)]
            print(_print_table(rows, ["customer","AOV","orders"]) if rows else "(khong co du lieu)")
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue

        if intent == "orders_wait_buy":
            lo, hi = this_month_range_iso()
            rows = fetch_orders_range(lo, hi, status="CHO_MUA")
            table = [{"order_code": r.get("order_code",""), "status": r.get("status",""), "created_at": r.get("created_at","")} for r in rows]
            print(_print_table(table, ["order_code","status","created_at"]) if table else "(khong co du lieu)")
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue

        if intent == "orders_purchased":
            lo, hi = this_month_range_iso()
            rows = fetch_orders_range(lo, hi, status="DA_MUA_HANG")
            if not rows:
                logs = fetch_table_all("order_process_log", {"gte__timestamp": lo, "lt__timestamp": hi, "eq__action":"DA_MUA_HANG"})
                oids = sorted({int(l["order_id"]) for l in logs if l.get("order_id")})
                rows = []
                for i in range(0, len(oids), 200):
                    ch = oids[i:i+200]
                    rows.extend(fetch_table_all("orders", {"in__order_id": ",".join(map(str, ch))}))
            table = [{"order_code": r.get("order_code",""), "status": r.get("status",""), "created_at": r.get("created_at","")} for r in rows]
            print(_print_table(table, ["order_code","status","created_at"]) if table else "(khong co du lieu)")
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue

        if intent == "warehouse_inventory":
            rows = fetch_table_all("warehouse", {})
            locs = fetch_table_all("warehouse_location", {})
            locmap = {int(x["location_id"]): (x.get("name") or f"LOC#{x['location_id']}") for x in locs}
            agg: Dict[str,int] = {}
            for r in rows:
                if (r.get("status") or "").upper() not in {"DA_NHAP_KHO","DANG_DOI_TRA"}: 
                    continue
                lid = r.get("location_id")
                name = locmap.get(int(lid), f"LOC#{lid}") if lid is not None else "UNKNOWN"
                agg[name] = agg.get(name, 0) + 1
            print(_print_table([{"location": k, "packages": v} for k,v in sorted(agg.items(), key=lambda x: x[1], reverse=True)], ["location","packages"]) if agg else "(khong co du lieu)")
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue

        if intent == "flights_waiting":
            lo, hi = this_month_range_iso()
            rows = fetch_table_all("packing", {"gte__packed_date": lo, "lte__packed_date": hi, "eq__status":"CHO_BAY"})
            print(f"✈️  Chuyến bay đang CHỜ: {len(rows)}")
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue

        # ======= NEW: Mua hộ tổng thể =======
        if intent == "mh_total_today":
            lo,hi,c = mua_ho_today_week_month_counts("day")
            print(gemini_rewrite(f"📊 Tổng số đơn mua hộ hôm nay ({lo[:10]}→{hi[:10]}): {c}"))
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
        if intent == "mh_total_week":
            lo,hi,c = mua_ho_today_week_month_counts("week")
            print(gemini_rewrite(f"📊 Tổng số đơn mua hộ tuần này ({lo[:10]}→{hi[:10]}): {c}"))
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
        if intent == "mh_total_month":
            lo,hi,c = mua_ho_today_week_month_counts("month")
            print(gemini_rewrite(f"📊 Tổng số đơn mua hộ tháng này ({lo[:10]}→{hi[:10]}): {c}"))
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
        if intent == "mh_wait_buy":
            lo, hi = this_month_range_iso()
            rows = mua_ho_wait_to_buy(lo, hi)
            tbl = [{"order_code": r.get("order_code",""), "status": r.get("status",""), "created_at": r.get("created_at","")} for r in rows]
            print(gemini_rewrite("▶ Đơn mua hộ đang chờ đặt hàng\n" + (_print_table(tbl, ["order_code","status","created_at"]) if tbl else "(khong co du lieu)")))
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
        if intent == "mh_ordered_not_paid_seller":
            lo, hi = this_month_range_iso()
            rows = orders_ordered_not_paid_seller(lo, hi)
            tbl = [{"order_code": r.get("order_code",""), "status": r.get("status",""), "created_at": r.get("created_at","")} for r in rows]
            print(gemini_rewrite("▶ Đã đặt nhưng chưa thanh toán seller (ước lượng)\n" + (_print_table(tbl, ["order_code","status","created_at"]) if tbl else "(khong co du lieu)")))
            print("ℹ️ Heuristic do schema chưa có bảng thanh toán cho seller.")
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
        if intent == "mh_wait_cn_wh":
            lo, hi = this_month_range_iso()
            rows = orders_waiting_cn_wh(lo, hi, params.get("hint"))
            tbl = [{"order_code": r.get("order_code",""), "status": r.get("status",""), "created_at": r.get("created_at","")} for r in rows]
            print(gemini_rewrite("▶ Đơn mua hộ đang chờ về kho TQ\n" + (_print_table(tbl, ["order_code","status","created_at"]) if tbl else "(khong co du lieu)")))
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
        if intent == "mh_arrived_cn_wait_vn":
            lo, hi = this_month_range_iso()
            rows = orders_arrived_cn_wait_ship_vn(lo, hi)
            tbl = [{"order_code": r.get("order_code",""), "status": r.get("status",""), "created_at": r.get("created_at","")} for r in rows]
            print(gemini_rewrite("▶ Đã về kho TQ — chờ vận chuyển về VN\n" + (_print_table(tbl, ["order_code","status","created_at"]) if tbl else "(khong co du lieu)")))
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
        if intent == "mh_at_port":
            lo, hi = this_month_range_iso()
            rows = orders_at_port_customs(lo, hi)
            tbl = [{"order_code": r.get("order_code",""), "status": r.get("status",""), "created_at": r.get("created_at","")} for r in rows]
            print(gemini_rewrite("▶ Đơn/lô ở cảng / hải quan (ước lượng)\n" + (_print_table(tbl, ["order_code","status","created_at"]) if tbl else "(khong co du lieu)")))
            print("ℹ️ Ước lượng qua packing.DA_BAY nhưng chưa ghi nhận nhập kho VN.")
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
        if intent == "mh_realtime_status":
            lo, hi = this_month_range_iso()
            rows = mua_ho_realtime_status(lo, hi)
            print(gemini_rewrite("▶ Trạng thái tất cả đơn mua hộ (tháng)\n" + (_print_table(rows, ["status","orders"]) if rows else "(khong co du lieu)")))
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
        if intent == "mh_seller_cancel_oos":
            lo, hi = this_month_range_iso()
            rows = mua_ho_cancel_by_seller_or_out_of_stock(lo, hi)
            tbl = [{"order_code": r.get("order_code",""), "status": r.get("status",""), "created_at": r.get("created_at","")} for r in rows]
            print(gemini_rewrite("▶ Đơn bị seller hủy / hết hàng\n" + (_print_table(tbl, ["order_code","status","created_at"]) if tbl else "(khong co du lieu)")))
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
        if intent == "mh_urgent_issues":
            lo, hi = this_month_range_iso()
            rows = mua_ho_urgent_issues(lo, hi)
            tbl = [{"order_code": r.get("order_code",""), "status": r.get("status","")} for r in rows]
            print(gemini_rewrite("▶ Đơn mua hộ có vấn đề cần xử lý gấp (feedback≤2 hoặc đã hủy)\n" + (_print_table(tbl, ["order_code","status"]) if tbl else "(khong co du lieu)")))
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue

        # ======= Seller =======
        if intent == "seller_frequent":
            lo, hi = this_month_range_iso()
            rows = sellers_frequent(lo, hi, topn=30)
            print(gemini_rewrite("▶ Danh sách shop/seller thường xuyên đặt hàng (tháng)\n" + (_print_table(rows, ["shop","orders"]) if rows else "(khong co du lieu)")))
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
        if intent == "seller_on_time_rate":
            lo, hi = this_month_range_iso()
            rows = seller_on_time_stats(lo, hi)
            print(gemini_rewrite("▶ Tỷ lệ giao hàng đúng hạn theo shop (ước lượng SLA theo route)\n" + (_print_table(rows, ["shop","on_time_rate","orders"]) if rows else "(khong co du lieu)")))
            print("ℹ️ On-time ≈ (purchase_time → CN) ≤ ship_time(route) hoặc mặc định 14 ngày.")
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
        if intent == "seller_inprogress_for_name":
            lo, hi = this_month_range_iso()
            shop = params.get("shop","").lower()
            rows = seller_orders_inprogress(shop, lo, hi)
            tbl = [{"order_code": r.get("order_code",""), "status": r.get("status",""), "created_at": r.get("created_at","")} for r in rows]
            print(gemini_rewrite(f"▶ Đơn đang xử lý của shop '{shop}'\n" + (_print_table(tbl, ["order_code","status","created_at"]) if tbl else "(khong co du lieu)")))
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
        if intent == "seller_late_or_cancel":
            lo, hi = this_month_range_iso()
            rows = seller_late_or_cancel_stats(lo, hi, topn=30)
            print(gemini_rewrite("▶ Seller giao chậm / hủy đơn (tỷ lệ)\n" + (_print_table(rows, ["shop","late_rate","cancel_rate","orders"]) if rows else "(khong co du lieu)")))
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
        if intent == "seller_reputation":
            lo, hi = this_month_range_iso()
            shop = params.get("shop","").lower()
            r = seller_reputation(shop, lo, hi)
            rows = [r]
            print(gemini_rewrite(f"▶ Đánh giá uy tín shop '{shop}'\n" + (_print_table(rows, ["shop","on_time_rate","cancel_rate","avg_rating","orders"]) if rows else "(khong co du lieu)")))
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
        if intent == "seller_avg_to_cn":
            lo, hi = this_month_range_iso()
            shop = params.get("shop","").lower()
            days = seller_avg_days_to_cn(shop, lo, hi)
            if days is None:
                print(gemini_rewrite(f"▶ Trung bình mất bao lâu về kho TQ (shop '{shop}'): (không đủ dữ liệu)"))
            else:
                print(gemini_rewrite(f"▶ Trung bình mua → về kho TQ (shop '{shop}'): ~{days:.1f} ngày"))
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
        if intent == "seller_blacklist":
            lo, hi = this_month_range_iso()
            rows = sellers_blacklist_candidates(lo, hi)
            print(gemini_rewrite("▶ Shop blacklist đề xuất (cancel rate cao)\n" + (_print_table(rows, ["shop","cancel_rate","late_rate","orders","reason"]) if rows else "(khong co du lieu)")))
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue

        # ======= Kho Trung Quốc =======
        if intent == "cn_count_items":
            lo, hi = this_month_range_iso()
            cnt = cn_warehouse_counts(lo, hi)
            print(gemini_rewrite(f"📦 Kiện hàng đang ở kho TQ (tháng): {cnt}"))
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
        if intent == "cn_order_arrived":
            code = params.get("code")
            ok = has_order_arrived_cn(code)
            print(gemini_rewrite(f"📦 Đơn {code}: " + ("ĐÃ về kho TQ" if ok else "CHƯA có bản ghi về kho TQ")))
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
        if intent == "cn_wait_packing":
            lo, hi = this_month_range_iso()
            rows = cn_wait_packing_list(lo, hi)
            tbl = [{"order_id": r.get("order_id",""), "tracking_code": r.get("tracking_code",""), "created_at": r.get("created_at","")} for r in rows]
            print(gemini_rewrite("▶ Hàng chờ đóng gói ở kho TQ\n" + (_print_table(tbl, ["order_id","tracking_code","created_at"]) if tbl else "(khong co du lieu)")))
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
        if intent == "cn_overstay":
            lo, hi = this_month_range_iso()
            rows = cn_overstay_items(lo, hi, days=14)
            tbl = [{"order_id": r.get("order_id",""), "tracking_code": r.get("tracking_code",""), "created_at": r.get("created_at","")} for r in rows]
            print(gemini_rewrite("▶ Hàng tồn kho TQ quá 14 ngày\n" + (_print_table(tbl, ["order_id","tracking_code","created_at"]) if tbl else "(khong co du lieu)")))
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
        if intent == "cn_storage_cost":
            print(UNSUPPORTED_NOTE)
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
        if intent == "cn_overloaded":
            print("ℹ️ Cần ngưỡng công suất kho (config) để đánh giá 'quá tải'. Hiện chưa có.")
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
        if intent == "cn_total_weight":
            lo, hi = this_month_range_iso()
            kg = cn_total_weight(lo, hi)
            print(gemini_rewrite(f"⚖️ Tổng cân nặng hàng về kho TQ (tháng): {kg:.2f} kg"))
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue

        # ======= Vận chuyển quốc tế =======
        if intent == "intl_in_transit":
            lo, hi = this_month_range_iso()
            rows = intl_in_transit_batches(lo, hi)
            tbl = [{"packing_code": r.get("packing_code",""), "status": r.get("status",""), "packed_date": r.get("packed_date","")} for r in rows]
            print(gemini_rewrite("▶ Lô đang trên đường TQ→VN\n" + (_print_table(tbl, ["packing_code","status","packed_date"]) if tbl else "(khong co du lieu)")))
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
        if intent == "intl_eta":
            print("ℹ️ Hiện không có ETA trong schema route/packing — chưa thể tính chính xác.")
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
        if intent == "intl_order_batch":
            code = params.get("code")
            pk = order_belongs_to_batch(code)
            print(gemini_rewrite(f"📦 Đơn {code} thuộc lô: {pk or '(không tìm thấy)'}"))
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
        if intent == "intl_customs_stuck":
            print("ℹ️ Không có cờ 'kẹt hải quan' rõ trong packing/domestic — cần thêm nguồn dữ liệu.")
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
        if intent in {"intl_cost","intl_partner"}:
            print(UNSUPPORTED_NOTE)
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
        if intent == "intl_avg_time":
            lo, hi = this_month_range_iso()
            days = avg_transit_days_cn_to_vn(lo, hi)
            if days is None:
                print(gemini_rewrite("▶ Thời gian vận chuyển trung bình TQ→VN: (không đủ dữ liệu)"))
            else:
                print(gemini_rewrite(f"▶ Thời gian vận chuyển trung bình TQ→VN: ~{days:.1f} ngày"))
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue
        if intent == "intl_tracking":
            pk = tracking_batch(params.get("packing_code",""))
            if not pk:
                print(gemini_rewrite("▶ Tracking lô hàng: (không tìm thấy)"))
            else:
                print(gemini_rewrite("▶ Tracking lô hàng\n" + _print_table([pk], ["packing_code","status","packed_date"])))
            print(f"\n(độ tin cậy nhận diện ý định: {conf:.2f})"); continue

        # Fallback
        print("⚠️  Chưa nhận diện được ý định. Thử: 'doanh thu tháng này' / mã đơn 'OD2025…' / 'thông tin email a@b.com'")

# if __name__ == "__main__":
#     main()
