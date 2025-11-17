# api_client.py
from __future__ import annotations
import requests, datetime as dt
from typing import Dict, Any, Optional, List, Tuple
from app.config.config_supabase import BASE_API_URL, API_KEY, DEFAULT_PAGE_SIZE, VN_TZ
import re as _re

import re as _re

_ORDER_CODE_INLINE_RE = _re.compile(
    r"\b(ORD[A-Z0-9\-]*|[A-Z]{2,5}[A-Z0-9\-]*\d+)\b",
    _re.IGNORECASE
)

def extract_order_code_from_text(text: str) -> str | None:
    if not text:
        return None
    m = _ORDER_CODE_INLINE_RE.search(text)
    return (m.group(1).upper() if m else None)

API_MAX_LIMIT = 500

def _headers() -> Dict[str, str]:
    return {"X-API-Key": API_KEY, "Accept": "application/json"}

def _clamp_limit(n: Optional[int]) -> int:
    try:
        n = int(n or DEFAULT_PAGE_SIZE)
    except Exception:
        n = DEFAULT_PAGE_SIZE
    return max(1, min(API_MAX_LIMIT, n))

def list_allowed_tables() -> List[str]:
    url = f"{BASE_API_URL}/api/meta/tables"
    resp = requests.get(url, headers=_headers(), timeout=20)
    resp.raise_for_status()
    data = resp.json()
    return data.get("allowed_tables") or []

def fetch_table_once(
    table: str,
    params: Optional[Dict[str, Any]] = None,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> Dict[str, Any]:
    url = f"{BASE_API_URL}/api/{table}"
    q = {"limit": _clamp_limit(limit), "offset": max(0, int(offset))}
    if params:
        q.update(params)
    resp = requests.get(url, headers=_headers(), params=q, timeout=30)
    if resp.status_code != 200:
        raise requests.HTTPError(f"POSTGREST {table}: {resp.status_code} {resp.text[:300]}")
    return resp.json()

def fetch_table_all(
    table: str,
    params: Optional[Dict[str, Any]] = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_pages: int = 200,
) -> List[Dict[str, Any]]:
    all_rows: List[Dict[str, Any]] = []
    offset = 0
    step = _clamp_limit(page_size)
    for _ in range(max_pages):
        data = fetch_table_once(table, params=params, limit=step, offset=offset)
        rows = data.get("data") or []
        all_rows.extend(rows)
        if len(rows) < step:
            break
        offset += step
    return all_rows

PAID_STATUSES = {"DA_THANH_TOAN", "DA_THANH_TOAN_SHIP"}

def fetch_payment_range(
    dt_from_iso: str, dt_to_iso: str, paid_only: bool = True, end_inclusive: bool = False
) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"gte__action_at": dt_from_iso, "order": "action_at", "desc": False}
    if end_inclusive:
        params["lte__action_at"] = dt_to_iso
    else:
        params["lt__action_at"] = dt_to_iso
    if paid_only:
        params["in__status"] = ",".join(sorted(PAID_STATUSES))
    return fetch_table_all("payment", params=params)

def sum_revenue_from_payments(payments: List[Dict[str, Any]]) -> float:
    total = 0.0
    for p in payments:
        st = (p.get("status") or "").upper()
        if st not in PAID_STATUSES:
            continue
        v = p.get("collected_amount", p.get("amount", 0))
        try:
            total += float(v or 0)
        except Exception:
            pass
    return total

def group_revenue_by_staff(payments: List[Dict[str, Any]]) -> Dict[int, float]:
    agg: Dict[int, float] = {}
    for p in payments:
        st = (p.get("status") or "").upper()
        if st not in PAID_STATUSES:
            continue
        sid = p.get("staff_id")
        if sid is None:
            continue
        v = p.get("collected_amount", p.get("amount", 0)) or 0
        try:
            agg[sid] = agg.get(sid, 0.0) + float(v)
        except Exception:
            pass
    return agg

def sum_amount_by_payment_type(payments: List[Dict[str, Any]]) -> Dict[str, float]:
    agg: Dict[str, float] = {}
    for p in payments:
        ptype = (p.get("payment_type") or "").upper() or "UNKNOWN"
        v = p.get("collected_amount", p.get("amount", 0)) or 0
        try:
            agg[ptype] = agg.get(ptype, 0.0) + float(v)
        except Exception:
            pass
    return agg

def fetch_account_by_id(account_id: int) -> Optional[Dict[str, Any]]:
    rows = fetch_table_all("account", params={"eq__account_id": account_id}, page_size=50)
    return rows[0] if rows else None

def fetch_staff_by_id(staff_id: int) -> Optional[Dict[str, Any]]:
    rows = fetch_table_all("staff", params={"eq__account_id": staff_id}, page_size=50)
    return rows[0] if rows else None

def fetch_order_by_code(order_code: str) -> Optional[Dict[str, Any]]:
    oc = (order_code or "").strip()
    rows: List[Dict[str, Any]] = []
    if oc:
        rows = fetch_table_all("orders", params={"eq__order_code": oc}, page_size=50)
        if not rows and oc.isdigit():
            rows = fetch_table_all("orders", params={"eq__order_id": int(oc)}, page_size=50)
    return rows[0] if rows else None

def fetch_orders_range(
    dt_from_iso: str,
    dt_to_iso: str,
    status: Optional[str] = None,
    order_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"gte__created_at": dt_from_iso, "lt__created_at": dt_to_iso}
    if status:
        params["eq__status"] = status
    if order_type:
        params["eq__order_type"] = order_type
    return fetch_table_all("orders", params=params)

def group_orders_count_by_staff(orders: List[Dict[str, Any]]) -> Dict[int, int]:
    agg: Dict[int, int] = {}
    for o in orders:
        sid = o.get("staff_id")
        if sid is None:
            continue
        agg[sid] = agg.get(sid, 0) + 1
    return agg

def fetch_destinations_map() -> Dict[int, str]:
    rows = fetch_table_all("destination", params={}, page_size=500)
    return {int(r["destination_id"]): (r.get("destination_name") or f"DEST#{r['destination_id']}") for r in rows}

def fetch_routes_map() -> Dict[int, str]:
    rows = fetch_table_all("route", params={}, page_size=500)
    return {int(r["route_id"]): (r.get("name") or f"ROUTE#{r['route_id']}") for r in rows}

def fetch_feedback_by_orders(order_ids: List[int]) -> List[Dict[str, Any]]:
    if not order_ids:
        return []
    out: List[Dict[str, Any]] = []
    step = 200
    for i in range(0, len(order_ids), step):
        chunk = order_ids[i:i+step]
        params = {"in__order_id": ",".join(str(x) for x in chunk)}
        out.extend(fetch_table_all("feedback", params=params, page_size=500))
    return out

def fetch_order_process_logs(order_ids: List[int]) -> List[Dict[str, Any]]:
    if not order_ids:
        return []
    out: List[Dict[str, Any]] = []
    step = 200
    for i in range(0, len(order_ids), step):
        chunk = order_ids[i:i+step]
        params = {"in__order_id": ",".join(str(x) for x in chunk)}
        out.extend(fetch_table_all("order_process_log", params=params, page_size=500))
    return out

def fetch_warehouse_in_period(dt_from_iso: str, dt_to_iso: str) -> List[Dict[str, Any]]:
    return fetch_table_all("warehouse", params={"gte__created_at": dt_from_iso, "lt__created_at": dt_to_iso})

def fetch_packing_in_period(dt_from_iso: str, dt_to_iso: str) -> List[Dict[str, Any]]:
    return fetch_table_all("packing", params={"gte__packed_date": dt_from_iso, "lt__packed_date": dt_to_iso})

def agg_cashflow_daily(dt_from: str, dt_to: str) -> List[Tuple[str, float]]:
    pays = fetch_payment_range(dt_from, dt_to, paid_only=True, end_inclusive=True)
    buckets: Dict[str, float] = {}
    for p in pays:
        ts = p.get("action_at")
        if not ts:
            continue
        d = ts[:10]
        val = float(p.get("collected_amount", p.get("amount", 0)) or 0)
        buckets[d] = buckets.get(d, 0.0) + val
    return sorted(buckets.items())

def agg_revenue_by_route(dt_from: str, dt_to: str) -> List[Tuple[str, float]]:
    pays = fetch_payment_range(dt_from, dt_to, paid_only=True, end_inclusive=True)
    order_ids = [int(p["order_id"]) for p in pays if p.get("order_id")]
    if not order_ids:
        return []
    orders: Dict[int, Dict[str, Any]] = {}
    for i in range(0, len(order_ids), 200):
        ch = order_ids[i:i+200]
        rows = fetch_table_all("orders", params={"in__order_id": ",".join(map(str, ch))})
        for r in rows:
            orders[int(r["order_id"])] = r
    route_map = fetch_routes_map()
    agg: Dict[str, float] = {}
    for p in pays:
        oid = p.get("order_id")
        if not oid or int(oid) not in orders:
            continue
        route_id = orders[int(oid)].get("route_id")
        name = route_map.get(int(route_id), f"ROUTE#{route_id}") if route_id is not None else "UNKNOWN"
        val = float(p.get("collected_amount", p.get("amount", 0)) or 0)
        agg[name] = agg.get(name, 0.0) + val
    return sorted(agg.items(), key=lambda x: x[1], reverse=True)

def agg_revenue_by_destination(dt_from: str, dt_to: str) -> List[Tuple[str, float]]:
    pays = fetch_payment_range(dt_from, dt_to, paid_only=True, end_inclusive=True)
    order_ids = [int(p["order_id"]) for p in pays if p.get("order_id")]
    if not order_ids:
        return []
    orders: Dict[int, Dict[str, Any]] = {}
    for i in range(0, len(order_ids), 200):
        ch = order_ids[i:i+200]
        rows = fetch_table_all("orders", params={"in__order_id": ",".join(map(str, ch))})
        for r in rows:
            orders[int(r["order_id"])] = r
    dest_map = fetch_destinations_map()
    agg: Dict[str, float] = {}
    for p in pays:
        oid = p.get("order_id")
        if not oid or int(oid) not in orders:
            continue
        dest_id = orders[int(oid)].get("destination_id")
        name = dest_map.get(int(dest_id), f"DEST#{dest_id}") if dest_id is not None else "UNKNOWN"
        val = float(p.get("collected_amount", p.get("amount", 0)) or 0)
        agg[name] = agg.get(name, 0.0) + val
    return sorted(agg.items(), key=lambda x: x[1], reverse=True)

def agg_aov_by_customer(dt_from: str, dt_to: str) -> List[Tuple[str, float, int]]:
    orders = fetch_orders_range(dt_from, dt_to)
    by_cus: Dict[int, Tuple[float,int]] = {}
    for o in orders:
        cid = o.get("customer_id")
        if cid is None: 
            continue
        val = float(o.get("final_price_order") or 0.0)
        s = by_cus.get(int(cid), (0.0, 0))
        by_cus[int(cid)] = (s[0] + val, s[1] + 1)
    out: List[Tuple[str, float, int]] = []
    for cid,(tot,cnt) in by_cus.items():
        aov = (tot/cnt) if cnt else 0.0
        out.append((f"KH #{cid}", aov, cnt))
    return sorted(out, key=lambda x: x[1], reverse=True)

def agg_order_count_by_status(dt_from: str, dt_to: str, status: Optional[str]) -> int:
    rows = fetch_orders_range(dt_from, dt_to, status=status)
    return len(rows)

def agg_cancel_rate(dt_from: str, dt_to: str) -> Tuple[int,int,float]:
    all_orders = fetch_orders_range(dt_from, dt_to)
    total = len(all_orders)
    canceled = sum(1 for o in all_orders if (o.get("status") or "").upper()=="DA_HUY")
    rate = (canceled/total*100.0) if total else 0.0
    return total, canceled, rate

def agg_avg_fulfillment_time(dt_from: str, dt_to: str) -> Optional[float]:
    orders = fetch_orders_range(dt_from, dt_to)
    if not orders:
        return None
    order_ids = [int(o["order_id"]) for o in orders]
    logs = fetch_order_process_logs(order_ids)
    # tìm timestamp created_at, và log cuối = DA_GIAO
    delivered: List[float] = []
    by_oid = {int(o["order_id"]): o for o in orders}
    for o in orders:
        oid = int(o["order_id"])
        created = o.get("created_at")
        if not created:
            continue
        created_ts = dt.datetime.fromisoformat(created)
        # tìm log DA_GIAO của oid
        best = None
        for lg in logs:
            if lg.get("order_id") and int(lg["order_id"])==oid and (lg.get("action")=="DA_GIAO"):
                t = dt.datetime.fromisoformat(lg["timestamp"])
                if (best is None) or (t > best):
                    best = t
        if best:
            delta = (best - created_ts).total_seconds()
            if delta >= 0:
                delivered.append(delta)
    if not delivered:
        return None
    return sum(delivered)/len(delivered)

def agg_feedback_avg_by_customer(dt_from: str, dt_to: str) -> List[Tuple[str,float,int]]:
    orders = fetch_orders_range(dt_from, dt_to)
    if not orders:
        return []
    by_customer_orders: Dict[int, List[int]] = {}
    for o in orders:
        cid = o.get("customer_id")
        if cid is None: 
            continue
        by_customer_orders.setdefault(int(cid), []).append(int(o["order_id"]))
    out: List[Tuple[str,float,int]] = []
    for cid, oids in by_customer_orders.items():
        fbs = fetch_feedback_by_orders(oids)
        if not fbs:
            continue
        s, n = 0.0, 0
        for f in fbs:
            try:
                s += float(f.get("rating") or 0)
                n += 1
            except Exception:
                pass
        if n>0:
            out.append((f"KH #{cid}", s/n, n))
    return sorted(out, key=lambda x: x[1], reverse=True)

def agg_feedback_negative_customers(dt_from: str, dt_to: str, threshold: float=3.0) -> List[Tuple[str,float,int]]:
    rows = agg_feedback_avg_by_customer(dt_from, dt_to)
    return [(name, avg, cnt) for (name,avg,cnt) in rows if avg < threshold]

def agg_feedback_count(dt_from: str, dt_to: str) -> int:
    orders = fetch_orders_range(dt_from, dt_to)
    oids = [int(o["order_id"]) for o in orders]
    return len(fetch_feedback_by_orders(oids)) if oids else 0

def agg_repeat_customer_rate(dt_from: str, dt_to: str) -> Tuple[int,int,float]:
    orders = fetch_orders_range(dt_from, dt_to)
    by_cus: Dict[int,int] = {}
    for o in orders:
        cid = o.get("customer_id")
        if cid is None: 
            continue
        by_cus[int(cid)] = by_cus.get(int(cid), 0)+1
    total_customers = len(by_cus)
    repeat_customers = sum(1 for c in by_cus.values() if c>=2)
    rate = (repeat_customers/total_customers*100.0) if total_customers else 0.0
    return total_customers, repeat_customers, rate

def agg_outstanding_amount(dt_from: str, dt_to: str) -> float:
    params = {"gte__action_at": dt_from, "lte__action_at": dt_to, "in__status": "CHO_THANH_TOAN,CHO_THANH_TOAN_SHIP"}
    rows = fetch_table_all("payment", params=params)
    s = 0.0
    for r in rows:
        try:
            s += float(r.get("amount") or 0)
        except Exception:
            pass
    return s

def agg_ship_payment_report(dt_from: str, dt_to: str) -> Tuple[int,float]:
    params = {"gte__action_at": dt_from, "lte__action_at": dt_to, "in__status": "DA_THANH_TOAN_SHIP"}
    rows = fetch_table_all("payment", params=params)
    cnt, s = 0, 0.0
    for r in rows:
        cnt += 1
        s += float(r.get("collected_amount", r.get("amount", 0)) or 0)
    return cnt, s

def agg_payment_count_by_status(dt_from: str, dt_to: str, status_code: str) -> int:
    params = {"gte__action_at": dt_from, "lte__action_at": dt_to, "eq__status": status_code}
    rows = fetch_table_all("payment", params=params)
    return len(rows)

def list_orders_by_status(dt_from: str, dt_to: str, status: str) -> List[Dict[str, Any]]:
    return fetch_orders_range(dt_from, dt_to, status=status)

def list_wait_to_buy(dt_from: str, dt_to: str) -> List[Dict[str, Any]]:
    return fetch_orders_range(dt_from, dt_to, status="CHO_MUA")

def agg_inventory_by_warehouse() -> List[Tuple[str,int]]:
    rows = fetch_table_all("warehouse", params={})
    locs = fetch_table_all("warehouse_location", params={})
    locmap = {int(x["location_id"]): (x.get("name") or f"LOC#{x['location_id']}") for x in locs}
    agg: Dict[str,int] = {}
    for r in rows:
        st = (r.get("status") or "").upper()
        if st not in {"DA_NHAP_KHO","DANG_DOI_TRA"}: 
            continue
        lid = r.get("location_id")
        name = locmap.get(int(lid), f"LOC#{lid}") if lid is not None else "UNKNOWN"
        agg[name] = agg.get(name, 0)+1
    return sorted(agg.items(), key=lambda x: x[1], reverse=True)

def agg_avg_weight_in_stock() -> Optional[float]:
    rows = fetch_table_all("warehouse", params={})
    vals = [float(r.get("weight") or 0.0) for r in rows if (r.get("status") or "").upper() in {"DA_NHAP_KHO","DANG_DOI_TRA"}]
    return (sum(vals)/len(vals)) if vals else None

def agg_imported_vn_in_period(dt_from: str, dt_to: str) -> int:
    rows = fetch_table_all("packing", params={"gte__packed_date": dt_from, "lte__packed_date": dt_to, "eq__status": "DA_NHAP_KHO_VN"})
    cnt = 0
    for r in rows:
        lst = r.get("packing_list") or []
        try:
            cnt += len(lst)
        except Exception:
            pass
    return cnt

def agg_flights_waiting_count(dt_from: str, dt_to: str) -> int:
    rows = fetch_table_all("packing", params={"gte__packed_date": dt_from, "lte__packed_date": dt_to, "eq__status": "CHO_BAY"})
    return len(rows)

def agg_flight_completion_rate(dt_from: str, dt_to: str) -> Tuple[int,int,float]:
    waited = fetch_table_all("packing", params={"gte__packed_date": dt_from, "lte__packed_date": dt_to})
    total = len(waited)
    done = sum(1 for r in waited if (r.get("status") in {"DA_BAY","DA_NHAP_KHO_VN"}))
    rate = (done/total*100.0) if total else 0.0
    return total, done, rate

def agg_avg_transit_time_foreign_to_vn(dt_from: str, dt_to: str) -> Optional[float]:
    orders = fetch_orders_range(dt_from, dt_to)
    if not orders:
        return None
    oids = [int(o["order_id"]) for o in orders]
    logs = fetch_order_process_logs(oids)
    by_oid: Dict[int, Dict[str, dt.datetime]] = {}
    for lg in logs:
        oid = lg.get("order_id")
        if oid is None:
            continue
        t = lg.get("timestamp")
        if not t:
            continue
        act = (lg.get("action") or "").upper()
        dtm = dt.datetime.fromisoformat(t)
        obj = by_oid.setdefault(int(oid), {})
        if act == "DA_BAY":
            obj["fly"] = dtm
        if act == "DA_NHAP_KHO_VN":
            obj["vn"] = dtm
    secs: List[float] = []
    for obj in by_oid.values():
        if "fly" in obj and "vn" in obj and obj["vn"] >= obj["fly"]:
            secs.append((obj["vn"] - obj["fly"]).total_seconds())
    if not secs:
        return None
    return sum(secs)/len(secs)
