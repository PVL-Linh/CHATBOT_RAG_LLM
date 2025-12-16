from __future__ import annotations
from typing import Tuple, Optional, Dict, Any, List
import traceback
import re

from app.Model_LLM.Chat_Database.redis_ctx import (
    remember_time_window,
    remember_order_code,
    remember_intent,
    get_ctx,
)
from app.Model_LLM.Chat_Database.db_cli import (
    UNPAID_STATUSES,
    _f,
    _now,
    _print_table,
    agg_revenue_by_route,
    classify_query,
    cn_total_weight,
    extract_order_code_from_text,
    fetch_account_by_id,
    fetch_orders_range,
    fetch_payment_range,
    fetch_routes_map,
    fetch_table_all,
    fetch_warehouse_in_period,
    format_snapshot,
    group_revenue_by_staff,
    money_fmt,
    order_belongs_to_batch,
    order_snapshot_by_code,
    person_full_profile,
    resolve_month_from_text,
    seller_reputation,
    sum_revenue_from_payments,
    this_month_range_iso,
    this_week_range_iso,
    today_range_iso,
    fetch_account_routes,   # NEW: lấy route_id mà account phụ trách
)
from app.config.config_supabase import VN_TZ


# =========================
# RBAC / INTENTS
# =========================

ROLE_ADMIN = "ADMIN"
ROLE_MANAGER = "MANAGER"
ROLE_SALE = "SALE"
ROLE_LEAD_SALE = "LEAD_SALE"

# Intent DB chính từ NLU
DB_INTENTS = {
    "order_lookup",
    "profile_by",
    "revenue_month",
    "revenue_week",
    "revenue_day",
    "cashflow",
    "revenue_by_staff",
    "revenue_by_route",
    "revenue_by_destination",
    "top_customers",
    "aov_by_customer",
    "orders_wait_buy",
    "orders_purchased",
    "warehouse_inventory",
    "flights_waiting",
    "mh_total_today",
    "mh_total_week",
    "mh_total_month",
    "mh_wait_buy",
    "mh_ordered_not_paid_seller",
    "mh_wait_cn_wh",
    "mh_arrived_cn_wait_vn",
    "mh_at_port",
    "mh_realtime_status",
    "mh_seller_cancel_oos",
    "mh_urgent_issues",
    "seller_frequent",
    "seller_on_time_rate",
    "seller_inprogress_for_name",
    "seller_late_or_cancel",
    "seller_reputation",
    "seller_avg_to_cn",
    "seller_blacklist",
    "cn_count_items",
    "cn_order_arrived",
    "cn_wait_packing",
    "cn_overstay",
    "cn_storage_cost",
    "cn_overloaded",
    "cn_total_weight",
    "intl_in_transit",
    "intl_eta",
    "intl_order_batch",
    "intl_customs_stuck",
    "intl_cost",
    "intl_partner",
    "intl_avg_time",
    "intl_tracking",
    "paid_orders_owner",
}

# Intent rule-based cho SALE
MY_SALE_INTENTS = {
    "my_orders_month",
    "my_unpaid_orders_month",
    "my_orders_status_month",
}

TEAM_LEAD_INTENTS = {
    "team_orders_by_route_month",
    "team_unpaid_by_route_month",
    "team_revenue_by_staff_month",
    "team_staff_most_unpaid_month",
    "team_staff_most_paid_month",
}


def _fmt_table(rows: List[Dict[str, Any]], headers: List[str]) -> str:
    return _print_table(rows, headers)


def _safe(s: Optional[str]) -> str:
    return (s or "").strip()


# =========================
# Scope / RBAC helpers
# =========================

def _extract_scope(principal: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Chuẩn hoá phạm vi (scope) từ principal.
    """
    p = principal or {}

    raw_role = (p.get("role") or "").strip().upper().replace(" ", "_")

    # Chuẩn hoá role logic
    if raw_role in {"ADMIN", "SUPERADMIN", "SUPER_ADMIN"}:
        role = ROLE_ADMIN
    elif raw_role in {"MANAGER", "MANAGER_SALES", "MANAGER_MARKETING"}:
        role = ROLE_MANAGER
    elif raw_role in {"LEAD_SALE", "LEADSALE", "TEAM_LEAD_SALE"}:
        role = ROLE_LEAD_SALE
    elif raw_role in {"SALE", "SALES", "STAFF_SALE"}:
        role = ROLE_SALE
    else:
        role = raw_role or ""

    # account_id (từ bảng account)
    account_id = p.get("account_id") or p.get("id")

    # id nhân viên sale (nếu có staff_id riêng)
    sale_owner_id = (
        p.get("staff_id")
        or p.get("sale_owner_id")
        or account_id
    )

    try:
        sale_owner_id_int = int(sale_owner_id) if sale_owner_id is not None else None
    except Exception:
        sale_owner_id_int = None

    # route_ids cho LEAD_SALE (dựa vào bảng account_route)
    route_ids: List[int] = []
    if account_id:
        try:
            route_ids = fetch_account_routes(int(account_id))
        except Exception as e:
            print(f"[db_router._extract_scope] fetch_account_routes error: {e}")
            route_ids = []

    scope = {
        "role": role,
        "sale_owner_id": sale_owner_id_int,
        "route_ids": route_ids,
    }

    print(f"[db_router._extract_scope] principal={p} -> scope={scope}")
    return scope


def _filter_payments_by_scope(
    pays: List[Dict[str, Any]], scope: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    RBAC trên payment:

    - ADMIN / MANAGER: full.
    - SALE           : payment có staff_id == sale_owner_id.
    - LEAD_SALE      : nếu payment có route_id -> chỉ các route_id trong scope['route_ids'].
                       nếu không có route_id -> tạm thời không filter (tuỳ bạn chỉnh thêm).
    """
    role = scope.get("role")
    sale_owner_id = scope.get("sale_owner_id")
    route_ids = set(scope.get("route_ids") or [])

    if role in {ROLE_ADMIN, ROLE_MANAGER}:
        return pays

    out: List[Dict[str, Any]] = []

    for p in pays:
        try:
            sid = p.get("staff_id")
            rid = p.get("route_id")

            sid_int = int(sid) if sid is not None else None
            rid_int = int(rid) if rid is not None else None
        except Exception:
            continue

        if role == ROLE_SALE:
            if sale_owner_id is not None and sid_int == sale_owner_id:
                out.append(p)

        elif role == ROLE_LEAD_SALE:
            if rid_int is not None:
                if rid_int in route_ids:
                    out.append(p)
            else:
                out.append(p)
        else:
            out.append(p)

    return out


def _filter_orders_by_scope(
    orders: List[Dict[str, Any]], scope: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    RBAC trên orders:

    - ADMIN / MANAGER: full.
    - SALE           : staff_id == sale_owner_id.
    - LEAD_SALE      : route_id thuộc các tuyến mà account lead phụ trách (account_route).
    """
    role = scope.get("role")
    sale_owner_id = scope.get("sale_owner_id")
    route_ids = set(scope.get("route_ids") or [])

    if role in {ROLE_ADMIN, ROLE_MANAGER}:
        return orders

    out: List[Dict[str, Any]] = []

    for o in orders:
        try:
            sid = o.get("staff_id")
            rid = o.get("route_id")

            sid_int = int(sid) if sid is not None else None
            rid_int = int(rid) if rid is not None else None
        except Exception:
            continue

        if role == ROLE_SALE:
            if sale_owner_id is not None and sid_int == sale_owner_id:
                out.append(o)

        elif role == ROLE_LEAD_SALE:
            if rid_int is not None and rid_int in route_ids:
                out.append(o)

        else:
            out.append(o)

    return out


def _can_view_order(order_or_snap: Dict[str, Any], scope: Dict[str, Any]) -> bool:
    """
    Kiểm tra quyền xem 1 đơn cụ thể:
    - ADMIN / MANAGER: luôn được xem.
    - SALE           : chỉ xem được nếu staff_id của đơn == sale_owner_id.
    - LEAD_SALE      : chỉ xem được nếu route_id của đơn thuộc tuyến lead phụ trách.
    - role khác / không rõ: tạm cho phép.
    """
    role = scope.get("role")
    if role in {ROLE_ADMIN, ROLE_MANAGER} or not role:
        return True

    sale_owner_id = scope.get("sale_owner_id")
    route_ids = set(scope.get("route_ids") or [])

    try:
        sid = order_or_snap.get("staff_id")
        rid = order_or_snap.get("route_id")

        sid_int = int(sid) if sid is not None else None
        rid_int = int(rid) if rid is not None else None
    except Exception:
        sid_int = None
        rid_int = None

    if role == ROLE_SALE:
        if sale_owner_id is not None and sid_int == sale_owner_id:
            return True
        return False

    if role == ROLE_LEAD_SALE:
        if rid_int is not None and rid_int in route_ids:
            return True
        return False

    return True  # default permissive


# =========================
# Rule-based intent cho SALE
# =========================

_MY_ORDER_RE = re.compile(r"\b(đơn|đơn hàng)\b", re.IGNORECASE)
_MY_ME_RE = re.compile(r"\b(của tôi|tôi phụ trách|tôi đang phụ trách)\b", re.IGNORECASE)
_MY_UNPAID_RE = re.compile(r"\b(chưa thanh toán|chưa trả|chưa thu tiền)\b", re.IGNORECASE)
_MY_STATUS_RE = re.compile(r"\b(trạng thái|tình trạng)\b", re.IGNORECASE)
_ROUTE_RE = re.compile(r"\btuyến\b", re.IGNORECASE)
_TEAM_RE = re.compile(r"\bteam tôi\b|\bteam cua tôi\b|\bteam của tôi\b", re.IGNORECASE)
_UNPAID_RE = re.compile(r"chưa thanh toán|chưa trả|chưa thu tiền", re.IGNORECASE)
_REVENUE_RE = re.compile(r"doanh thu", re.IGNORECASE)
_STAFF_RE = re.compile(r"nhân viên|sale", re.IGNORECASE)
_MOST_UNPAID_RE = re.compile(r"nhiều đơn chưa thanh toán nhất", re.IGNORECASE)
_PAID_RE = re.compile(r"đã thanh toán|đã thu tiền|đã trả hết", re.IGNORECASE)
_MOST_PAID_RE = re.compile(r"nhiều đơn đã thanh toán nhất", re.IGNORECASE)


def _detect_sale_my_orders_intent(
    text: str, scope: Dict[str, Any]
) -> Optional[str]:
    """
    Nếu role = SALE và câu hỏi có dạng:
      - "Danh sách các đơn của tôi trong tháng này"
      - "Những đơn của tôi chưa thanh toán trong tháng này"
      - "Trạng thái các đơn tôi đang phụ trách trong tháng này"
    thì trả về intent nội bộ tương ứng trong MY_SALE_INTENTS.
    """
    role = scope.get("role")
    if role != ROLE_SALE:
        return None

    t = (text or "").lower()

    if not (_MY_ORDER_RE.search(t) and _MY_ME_RE.search(t)):
        return None

    # Ưu tiên: chưa thanh toán
    if _MY_UNPAID_RE.search(t):
        return "my_unpaid_orders_month"

    # Kế tiếp: trạng thái
    if _MY_STATUS_RE.search(t):
        return "my_orders_status_month"

    # Mặc định: danh sách đơn
    return "my_orders_month"


# =========================
# Rule-based intent cho LEAD_SALE
# =========================

_ROUTE_RE = re.compile(r"\btuyến\b", re.IGNORECASE)


def _detect_lead_team_intent(
    text: str,
    scope: Dict[str, Any],
) -> Optional[str]:
    role = scope.get("role")
    if role != ROLE_LEAD_SALE:
        return None

    t = (text or "").lower()

    # Nhân viên nào trong team tôi có nhiều đơn chưa thanh toán nhất
    if _MOST_UNPAID_RE.search(t):
        return "team_staff_most_unpaid_month"

    # Nhân viên nào trong team tôi có nhiều đơn đã thanh toán nhất
    if _MOST_PAID_RE.search(t) or (_PAID_RE.search(t) and "nhiều đơn" in t):
        return "team_staff_most_paid_month"

    # Những đơn chưa thanh toán theo tuyến của team tôi trong tháng này
    if _UNPAID_RE.search(t) and _ROUTE_RE.search(t):
        return "team_unpaid_by_route_month"

    # Doanh thu theo nhân viên trong team tôi tháng này
    if _REVENUE_RE.search(t) and _STAFF_RE.search(t):
        return "team_revenue_by_staff_month"

    # Danh sách các đơn theo tuyến của team tôi trong tháng này
    if _ROUTE_RE.search(t) and (_TEAM_RE.search(t) or "theo tuyến" in t):
        return "team_orders_by_route_month"

    return None

def _auto_context_intent(
    text: str, session_id: str
) -> Tuple[Optional[str], Dict[str, Any], float]:
    """
    Auto-context dùng Redis:
    - Nếu user hỏi kiểu "của ai?" ngay sau một câu doanh thu,
      thì map sang intent 'paid_orders_owner' và reuse time_window cũ.

    Tránh lỗi kiểu dữ liệu: last_intent có thể là string hoặc dict.
    """
    t = (text or "").lower().strip()

    try:
        ctx = get_ctx(session_id) or {}
    except Exception:
        ctx = {}

    if isinstance(ctx, str):
        # phòng trường hợp ctx bị lưu là chuỗi JSON chưa parse
        try:
            import json as _json
            ctx = _json.loads(ctx)
        except Exception:
            ctx = {}

    # ---- Đọc last_intent an toàn ----
    raw_last_int = ctx.get("last_intent")

    if isinstance(raw_last_int, dict):
        last_int = (
            raw_last_int.get("name")
            or raw_last_int.get("intent")
            or ""
        ).lower()
    else:
        last_int = str(raw_last_int or "").lower()

    # ---- Đọc time_window an toàn ----
    raw_tw = (
        ctx.get("last_time_window")
        or ctx.get("time_window")
        or {}
    )
    if not isinstance(raw_tw, dict):
        raw_tw = {}

    # Pattern kiểu: "2 đơn đã thanh toán của ai", "đã thanh toán này của ai", "của ai?"
    if (
        re.search(r"của ai\b", t)
        or re.search(r"nhân viên nào\b", t)
        or "thuộc ai" in t
    ):
        # Chỉ auto-context nếu trước đó là câu doanh thu/thanh toán
        if last_int in {"revenue_month", "revenue_week", "revenue_day"}:
            # params rỗng, hàm 'paid_orders_owner' sẽ dùng lại time_window từ Redis
            return "paid_orders_owner", {}, 0.93

    return None, {}, 0.0


# =========================
# Core: handle_db_message
# =========================
def handle_db_message(
    user_text: str,
    session_id: str,
    principal: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    try:
        # 1) Classify bình thường
        intent, params, conf = classify_query(user_text)

        # 2) Nếu không match intent DB -> thử Auto-Context từ Redis
        if intent not in DB_INTENTS:
            ctx_intent, ctx_params, ctx_conf = _auto_context_intent(
                user_text, session_id
            )
            if ctx_intent and ctx_intent in DB_INTENTS:
                intent, params, conf = ctx_intent, ctx_params, ctx_conf

        # 3) Nếu vẫn không phải intent DB -> trả về cho RAG xử lý
        if intent not in DB_INTENTS:
            return (False, "", {})

        remember_intent(session_id, intent, conf)
        scope = _extract_scope(principal)

        # ==== 0. Rule-based override cho SALE ====
        sale_my_intent = _detect_sale_my_orders_intent(user_text, scope)
        if sale_my_intent in MY_SALE_INTENTS:
            return _handle_sale_my_orders(
                sale_my_intent, user_text, session_id, conf, scope
            )

        # ==== 0b. Rule-based override cho LEAD_SALE ====
        lead_intent = _detect_lead_team_intent(user_text, scope)
        if lead_intent in TEAM_LEAD_INTENTS:
            return _handle_lead_team_intent(
                lead_intent, user_text, session_id, conf, scope
            )
        
        # 1) Tra đơn / mã đơn
        if intent in {"order_lookup", "unknown"}:
            code = extract_order_code_from_text(user_text)
            if code:
                remember_order_code(session_id, code)
                snap = order_snapshot_by_code(code)
                if not snap:
                    return (
                        True,
                        f"❌ Không tìm thấy đơn với mã {code}.",
                        {
                            "intent": intent,
                            "confidence": conf,
                            "not_found": True,
                            "scope": scope,
                        },
                    )

                # RBAC: kiểm tra quyền xem đơn
                if not _can_view_order(snap, scope):
                    return (
                        True,
                        "⛔ Bạn không có quyền xem đơn này (thuộc nhân viên/tuyến khác).",
                        {
                            "intent": intent,
                            "confidence": conf,
                            "forbidden": True,
                            "scope": scope,
                        },
                    )

                return (
                    True,
                    format_snapshot(snap),
                    {"intent": intent, "confidence": conf, "scope": scope},
                )

            # ❗ Không có mã đơn → cho RAG xử lý (ví dụ: "đơn xin tạm ứng", "mẫu đơn xin tạm ứng")
            return (
                False,
                "",
                {
                    "intent": intent,
                    "confidence": conf,
                    "scope": scope,
                    "reason": "no_order_code_in_text",
                },
            )

        # 2) Hồ sơ tài khoản
        if intent == "profile_by":
            fld, val = params.get("field"), params.get("value")
            prof = person_full_profile(fld, val, recent_limit=20)
            if not prof:
                return (
                    True,
                    "❌ Không tìm thấy tài khoản.",
                    {"intent": intent, "confidence": conf, "scope": scope},
                )
            acct = prof["account"]
            role = (acct.get("role") or "").upper()
            rows_orders = [
                {"order_code": o.get("order_code", ""), "status": o.get("status", "")}
                for o in prof["orders_recent"][:10]
            ]
            blocks: List[str] = []
            blocks.append(
                f"👤 Account #{acct.get('account_id')} — {acct.get('name','N/A')}"
            )
            blocks.append(
                f"   • Email: {acct.get('email','N/A')} | Phone: {acct.get('phone','N/A')} "
                f"| Username: {acct.get('username','N/A')}"
            )
            blocks.append(
                f"   • Role: {role or 'N/A'} | Status: {acct.get('status','N/A')}"
            )
            ag = prof["aggregates"]
            blocks.append(
                f"💰 Payments recent: paid={money_fmt(ag.get('total_paid_recent',0))} | "
                f"outstanding={money_fmt(ag.get('outstanding_recent',0))} | "
                f"count={ag.get('payments_count_recent',0)}"
            )
            if rows_orders:
                blocks.append(
                    "📦 Orders recent:\n"
                    + _fmt_table(rows_orders, ["order_code", "status"])
                )
            blocks.append(
                f"🏬 Warehouse recent: {len(prof['warehouse_recent'])} | "
                f"📝 Logs: {len(prof['logs_recent'])} | ⭐ Feedback: {len(prof['feedback_recent'])}"
            )
            return (
                True,
                "\n".join(blocks),
                {"intent": intent, "confidence": conf, "scope": scope},
            )

        # 3) Doanh thu / thời gian (tháng / tuần / ngày)
        if intent in {"revenue_month", "revenue_week", "revenue_day"}:
            # Xác định khung thời gian
            if intent == "revenue_month":
                parsed = resolve_month_from_text(user_text, _now(), VN_TZ)
                lo, hi = parsed if parsed else this_month_range_iso()
                label = "tháng"
            elif intent == "revenue_week":
                lo, hi = this_week_range_iso()
                label = "tuần"
            else:
                lo, hi = today_range_iso()
                label = "ngày"

            remember_time_window(session_id, lo, hi)

            # Lấy dữ liệu payment
            pays_paid = fetch_payment_range(
                lo, hi, paid_only=True, end_inclusive=False
            )
            pays_unpaid = fetch_table_all(
                "payment",
                {
                    "gte__action_at": lo,
                    "lt__action_at": hi,
                    "in__status": ",".join(sorted(UNPAID_STATUSES)),
                },
            )

            # RBAC: SALE / LEAD_SALE bị giới hạn
            pays_paid = _filter_payments_by_scope(pays_paid, scope)
            pays_unpaid = _filter_payments_by_scope(pays_unpaid, scope)

            role = scope.get("role")

            # Nếu là SALE / LEAD_SALE mà hoàn toàn không có giao dịch trong kỳ
            if role in {ROLE_SALE, ROLE_LEAD_SALE} and not pays_paid and not pays_unpaid:
                msg_role = "nhân viên kinh doanh" if role == ROLE_SALE else "lead sale"
                msg = (
                    f"Tài khoản của bạn ({msg_role}) hiện không có dữ liệu doanh thu "
                    f"trong khoảng thời gian từ {lo[:10]} đến {hi[:10]} "
                    f"hoặc không được phép xem tổng doanh thu của toàn công ty.\n\n"
                    "Bạn có thể thử các câu hỏi khác phù hợp với quyền hạn, ví dụ:\n"
                    "- \"Danh sách các đơn của tôi trong tháng này\"\n"
                    "- \"Những đơn của tôi chưa thanh toán trong tháng này\"\n"
                    "- \"Trạng thái các đơn tôi đang phụ trách trong tháng này\""
                )
                if role == ROLE_LEAD_SALE:
                    msg += (
                        "\n- \"Danh sách số đơn theo tuyến của team tôi trong tháng này\""
                    )
                return (
                    True,
                    msg,
                    {
                        "intent": intent,
                        "confidence": conf,
                        "time_window": {"lo": lo, "hi": hi},
                        "scope": scope,
                        "no_data_for_scope": True,
                    },
                )

            total = sum_revenue_from_payments(pays_paid)

            # Helper định dạng ngày dd/mm/yyyy
            def _dmy(iso: str) -> str:
                try:
                    y, m, d = iso[:10].split("-")
                    return f"{d}/{m}/{y}"
                except Exception:
                    return iso[:10]

            # Bảng tổng quan
            rows_total = [
                {
                    "window": f"{lo[:10]}→{hi[:10]}",
                    "paid_orders": len(pays_paid),
                    "paid_amount": money_fmt(sum_revenue_from_payments(pays_paid)),
                    "unpaid_orders": len(pays_unpaid),
                    "unpaid_amount": money_fmt(
                        sum(_f(r.get("amount")) for r in pays_unpaid)
                    ),
                }
            ]

            # Tóm tắt
            d1, d2 = _dmy(lo), _dmy(hi)
            summary_header = f"Tổng doanh thu {label} này"
            summary_para = (
                f"{summary_header}\n\n"
                f"Tổng doanh thu từ {d1} đến {d2} là {money_fmt(total)} "
                f"với {len(pays_paid)} giao dịch, chi tiết như sau:\n\n"
                "Tổng quan doanh thu:\n\n"
                + _print_table(
                    rows_total,
                    [
                        "window",
                        "paid_orders",
                        "paid_amount",
                        "unpaid_orders",
                        "unpaid_amount",
                    ],
                )
            )

            # Head + tổng
            head = (
                f"💰 Doanh thu {lo} → {hi}: {money_fmt(total)} "
                f"(giao dịch: {len(pays_paid)})"
            )
            body_total = "\n▶ Tổng\n" + _print_table(
                rows_total,
                [
                    "window",
                    "paid_orders",
                    "paid_amount",
                    "unpaid_orders",
                    "unpaid_amount",
                ],
            )

            # Tổng hợp PAID/UNPAID theo status
            def _agg_by_status(rows, paid: bool):
                by, cnt = {}, {}
                for r in rows:
                    st = (r.get("status") or "").upper()
                    v = _f(r.get("collected_amount" if paid else "amount"))
                    by[st] = by.get(st, 0.0) + v
                    cnt[st] = cnt.get(st, 0) + 1
                return [
                    {
                        "pay_status": k,
                        "orders": cnt.get(k, 0),
                        "amount": money_fmt(by.get(k, 0.0)),
                    }
                    for k in sorted((cnt.keys() | by.keys()))
                ]

            det_paid = _agg_by_status(pays_paid, True)
            det_unpd = _agg_by_status(pays_unpaid, False)

            paid_tbl = (
                _print_table(det_paid, ["pay_status", "orders", "amount"])
                if det_paid
                else "(khong co du lieu)"
            )
            unpd_tbl = (
                _print_table(det_unpd, ["pay_status", "orders", "amount"])
                if det_unpd
                else "(khong co du lieu)"
            )

            sections: List[str] = [
                summary_para,
                head,
                body_total,
                "▶ Tổng hợp thanh toán (" + label + ")\n"
                + _print_table(
                    [
                        {
                            "group": "PAID_STATUSES",
                            "orders": len(pays_paid),
                            "amount": money_fmt(
                                sum_revenue_from_payments(pays_paid)
                            ),
                        },
                        {
                            "group": "UNPAID_STATUSES",
                            "orders": len(pays_unpaid),
                            "amount": money_fmt(
                                sum(_f(r.get("amount")) for r in pays_unpaid)
                            ),
                        },
                    ],
                    ["group", "orders", "amount"],
                ),
                "▶ Chi tiết thanh toán (" + label + ") — PAID_STATUSES\n" + paid_tbl,
                "▶ Chi tiết thanh toán (" + label + ") — UNPAID_STATUSES\n" + unpd_tbl,
            ]

            if intent == "revenue_month":
                wh = fetch_warehouse_in_period(lo, hi)
                routes = fetch_routes_map()
                kg: Dict[str, float] = {}

                for r in wh:
                    w = _f(r.get("weight"))
                    if not w:
                        continue

                    rid = r.get("route_id")
                    route_label: str

                    if rid is None:
                        # cố gắng lấy tên tuyến nếu có sẵn trong record
                        route_label = (
                            (r.get("route_name") or r.get("route") or "").strip()
                            or "CHUA_GAN_TUYEN"
                        )
                    else:
                        try:
                            rid_int = int(rid)
                        except Exception:
                            rid_int = None

                        if rid_int is not None and rid_int in routes:
                            route_label = routes[rid_int]
                        elif rid is not None:
                            route_label = f"ROUTE#{rid}"
                        else:
                            route_label = "CHUA_GAN_TUYEN"

                    kg[route_label] = kg.get(route_label, 0.0) + w

                # Chuẩn hoá rows + đổi nhãn CHUA_GAN_TUYEN -> Chưa gán tuyến
                rows_kg = [
                    {
                        "route": ("Chưa gán tuyến" if k == "CHUA_GAN_TUYEN" else k),
                        "kg": round(v, 2),
                    }
                    for k, v in sorted(kg.items())
                    if v > 0
                ]

                if not rows_kg:
                    # Không có dữ liệu kho
                    sections.append(
                        "\n▶ Số kg theo tuyến (theo warehouse.created_at trong tháng)\n"
                        "(khong co du lieu)"
                    )
                elif len(rows_kg) == 1 and rows_kg[0]["route"] == "Chưa gán tuyến":
                    # Chỉ toàn phiếu chưa gán tuyến -> giải thích thay vì in bảng vô nghĩa
                    sections.append(
                        "\n▶ Số kg theo tuyến (theo warehouse.created_at trong tháng)\n"
                        "Hiện tại các phiếu nhập kho trong tháng chưa được gán tuyến cụ thể, "
                        "nên không thể thống kê chi tiết theo từng tuyến. "
                        f"Tổng khối lượng ghi nhận: {rows_kg[0]['kg']} kg (chưa gán tuyến)."
                    )
                else:
                    sections.append(
                        "\n▶ Số kg theo tuyến (theo warehouse.created_at trong tháng)\n"
                        + _print_table(rows_kg, ["route", "kg"])
                    )

                # ===== Trạng thái đơn (orders.status) =====
                ords = fetch_orders_range(lo, hi)
                agg_stat: Dict[str, int] = {}
                for o in ords:
                    st = (o.get("status") or "UNKNOWN").upper()
                    agg_stat[st] = agg_stat.get(st, 0) + 1
                stat_rows = [
                    {"status": k.replace("_", " ").title(), "orders": v}
                    for k, v in sorted(agg_stat.items())
                ]
                sections.append(
                    "\n▶ Trạng thái đơn (tháng)\n"
                    + (_print_table(stat_rows, ["status", "orders"]) if stat_rows else "(khong co du lieu)")
                )
                sections.append(
                    "ℹ️  Lưu ý: Đây là trạng thái NGHIỆP VỤ của đơn (orders.status), "
                    "KHÁC với trạng thái thanh toán (payment.status)."
                )


            txt = "\n".join(sections)
            return (
                True,
                txt,
                {
                    "intent": intent,
                    "confidence": conf,
                    "time_window": {"lo": lo, "hi": hi},
                    "scope": scope,
                },
            )
        # 4) Các intent khác — dùng dispatcher gọn
        return _dispatch_misc(intent, params, session_id, conf, user_text, scope)
    
    except Exception as e:
        tb = traceback.format_exc(limit=2)
        return (
            True,
            f"⚠️ Lỗi DB branch: {e}\n{tb}",
            {"error": "db_branch_failed"},
        )


# =========================
# HANDLER RIÊNG CHO SALE: "các đơn của tôi ..."
# =========================

def _handle_sale_my_orders(
    sale_intent: str,
    user_text: str,
    session_id: str,
    conf: float,
    scope: Dict[str, Any],
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Xử lý 3 intent nội bộ:
      - my_orders_month
      - my_unpaid_orders_month
      - my_orders_status_month
    Tất cả đều hiểu là "trong tháng này".
    """
    role = scope.get("role")
    if role != ROLE_SALE:
        # fallback: không phải SALE thì không áp rule này
        return (
            True,
            "⛔ Intent này chỉ áp dụng cho nhân viên sale.",
            {"intent": sale_intent, "confidence": conf, "scope": scope},
        )

    lo, hi = this_month_range_iso()
    remember_time_window(session_id, lo, hi)

    # 1) Danh sách các đơn của tôi trong tháng này
    if sale_intent == "my_orders_month":
        orders = fetch_orders_range(lo, hi)
        orders = _filter_orders_by_scope(orders, scope)

        if not orders:
            return (
                True,
                "Trong tháng này bạn chưa có đơn hàng nào được ghi nhận trong hệ thống.",
                {
                    "intent": sale_intent,
                    "confidence": conf,
                    "time_window": {"lo": lo, "hi": hi},
                    "scope": scope,
                },
            )

        # Giới hạn hiển thị
        orders = sorted(
            orders,
            key=lambda o: o.get("created_at", "") or o.get("order_created_at", ""),
            reverse=True,
        )[:50]

        rows: List[Dict[str, Any]] = []
        for o in orders:
            rows.append(
                {
                    "order_code": o.get("order_code", o.get("code", "")),
                    "status": o.get("status", ""),
                    "created_at": (o.get("created_at") or o.get("order_created_at") or "")[:19],
                }
            )

        txt = (
            f"📋 Danh sách các đơn hàng bạn phụ trách trong tháng này ({lo[:10]} → {hi[:10]}):\n"
            + _print_table(rows, ["order_code", "status", "created_at"])
        )
        return (
            True,
            txt,
            {
                "intent": sale_intent,
                "confidence": conf,
                "time_window": {"lo": lo, "hi": hi},
                "scope": scope,
            },
        )

    # 2) Những đơn của tôi chưa thanh toán trong tháng này
    if sale_intent == "my_unpaid_orders_month":
        pays_unpaid = fetch_table_all(
            "payment",
            {
                "gte__action_at": lo,
                "lt__action_at": hi,
                "in__status": ",".join(sorted(UNPAID_STATUSES)),
            },
        )
        pays_unpaid = _filter_payments_by_scope(pays_unpaid, scope)

        if not pays_unpaid:
            return (
                True,
                "Trong tháng này bạn không có đơn hàng nào ở trạng thái CHƯA THANH TOÁN.",
                {
                    "intent": sale_intent,
                    "confidence": conf,
                    "time_window": {"lo": lo, "hi": hi},
                    "scope": scope,
                },
            )

        # Giới hạn hiển thị
        pays_unpaid = sorted(
            pays_unpaid,
            key=lambda p: p.get("action_at", ""),
            reverse=True,
        )[:50]

        rows: List[Dict[str, Any]] = []
        for p in pays_unpaid:
            rows.append(
                {
                    "order_code": p.get("order_code", ""),
                    "status": p.get("status", ""),
                    "amount": money_fmt(_f(p.get("amount"))),
                    "action_at": (p.get("action_at") or "")[:19],
                }
            )

        txt = (
            f"📋 Những đơn hàng của bạn CHƯA THANH TOÁN trong tháng này "
            f"({lo[:10]} → {hi[:10]}):\n"
            + _print_table(rows, ["order_code", "status", "amount", "action_at"])
        )
        return (
            True,
            txt,
            {
                "intent": sale_intent,
                "confidence": conf,
                "time_window": {"lo": lo, "hi": hi},
                "scope": scope,
            },
        )

    # 3) Trạng thái các đơn tôi đang phụ trách trong tháng này
    if sale_intent == "my_orders_status_month":
        orders = fetch_orders_range(lo, hi)
        orders = _filter_orders_by_scope(orders, scope)

        if not orders:
            return (
                True,
                "Trong tháng này bạn chưa có đơn hàng nào được ghi nhận trong hệ thống.",
                {
                    "intent": sale_intent,
                    "confidence": conf,
                    "time_window": {"lo": lo, "hi": hi},
                    "scope": scope,
                },
            )

        # Tổng hợp theo trạng thái
        agg_stat: Dict[str, int] = {}
        for o in orders:
            st = (o.get("status") or "UNKNOWN").upper()
            agg_stat[st] = agg_stat.get(st, 0) + 1

        stat_rows = [
            {"status": k.replace("_", " ").title(), "orders": v}
            for k, v in sorted(agg_stat.items())
        ]

        txt = (
            f"📊 Trạng thái các đơn hàng bạn đang phụ trách trong tháng này "
            f"({lo[:10]} → {hi[:10]}):\n"
            + _print_table(stat_rows, ["status", "orders"])
        )
        return (
            True,
            txt,
            {
                "intent": sale_intent,
                "confidence": conf,
                "time_window": {"lo": lo, "hi": hi},
                "scope": scope,
            },
        )

    # fallback (không nên vào)
    return (
        True,
        f"✅ Intent SALE nội bộ: {sale_intent} (conf={conf:.2f}).",
        {"intent": sale_intent, "confidence": conf, "scope": scope},
    )


# =========================
# HANDLER RIÊNG CHO LEAD_SALE: "đơn theo tuyến team tôi ..."
# =========================

def _handle_lead_team_intent(
    team_intent: str,
    user_text: str,
    session_id: str,
    conf: float,
    scope: Dict[str, Any],
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Xử lý các intent nội bộ cho LEAD_SALE:

      - team_orders_by_route_month:
          Số đơn theo tuyến trong tháng này (chỉ các tuyến lead phụ trách)

      - team_unpaid_by_route_month:
          Các đơn CHƯA THANH TOÁN theo tuyến trong tháng này (team lead)

      - team_revenue_by_staff_month:
          Doanh thu theo nhân viên trong team (trên các tuyến lead phụ trách)

      - team_staff_most_unpaid_month:
          Nhân viên trong team có nhiều đơn CHƯA THANH TOÁN nhất
    """
    role = scope.get("role")
    if role != ROLE_LEAD_SALE:
        return (
            True,
            "⛔ Intent này chỉ áp dụng cho lead sale.",
            {"intent": team_intent, "confidence": conf, "scope": scope},
        )

    lo, hi = this_month_range_iso()
    remember_time_window(session_id, lo, hi)

    # ===== 1) Số đơn theo tuyến của team trong tháng =====
    if team_intent == "team_orders_by_route_month":
        orders = fetch_orders_range(lo, hi)
        orders = _filter_orders_by_scope(orders, scope)

        if not orders:
            return (
                True,
                "Trong tháng này không có đơn hàng nào thuộc các tuyến bạn phụ trách.",
                {
                    "intent": team_intent,
                    "confidence": conf,
                    "time_window": {"lo": lo, "hi": hi},
                    "scope": scope,
                },
            )

        routes = fetch_routes_map()
        agg: Dict[str, int] = {}
        for o in orders:
            rid = o.get("route_id")
            try:
                rid_int = int(rid) if rid is not None else None
            except Exception:
                rid_int = None

            if rid_int is not None:
                rname = routes.get(rid_int, f"ROUTE#{rid_int}")
            else:
                rname = "UNKNOWN"

            agg[rname] = agg.get(rname, 0) + 1

        rows = [
            {"route": k, "orders": v}
            for k, v in sorted(agg.items(), key=lambda x: x[0])
        ]

        txt = (
            f"Dưới đây là thống kê số lượng đơn hàng theo tuyến của team bạn trong tháng "
            f"({lo[:10]} - {hi[:10]}):\n\n"
            + _print_table(rows, ["route", "orders"])
        )

        return (
            True,
            txt,
            {
                "intent": team_intent,
                "confidence": conf,
                "time_window": {"lo": lo, "hi": hi},
                "scope": scope,
            },
        )

    # ===== 2) Đơn CHƯA THANH TOÁN theo tuyến của team trong tháng =====
    if team_intent == "team_unpaid_by_route_month":
        pays_unpaid = fetch_table_all(
            "payment",
            {
                "gte__action_at": lo,
                "lt__action_at": hi,
                "in__status": ",".join(sorted(UNPAID_STATUSES)),
            },
        )
        pays_unpaid = _filter_payments_by_scope(pays_unpaid, scope)

        if not pays_unpaid:
            return (
                True,
                "Trong tháng này không có đơn CHƯA THANH TOÁN nào thuộc các tuyến bạn phụ trách.",
                {
                    "intent": team_intent,
                    "confidence": conf,
                    "time_window": {"lo": lo, "hi": hi},
                    "scope": scope,
                },
            )

        routes = fetch_routes_map()
        agg_cnt: Dict[str, int] = {}
        agg_amount: Dict[str, float] = {}

        for p in pays_unpaid:
            rid = p.get("route_id")
            try:
                rid_int = int(rid) if rid is not None else None
            except Exception:
                rid_int = None

            if rid_int is not None:
                rname = routes.get(rid_int, f"ROUTE#{rid_int}")
            else:
                rname = "UNKNOWN"

            amt = _f(p.get("amount"))
            agg_cnt[rname] = agg_cnt.get(rname, 0) + 1
            agg_amount[rname] = agg_amount.get(rname, 0.0) + amt

        rows = [
            {
                "route": k,
                "unpaid_orders": agg_cnt.get(k, 0),
                "unpaid_amount": money_fmt(agg_amount.get(k, 0.0)),
            }
            for k in sorted(agg_cnt.keys())
        ]

        txt = (
            f"Dưới đây là thống kê các đơn CHƯA THANH TOÁN theo tuyến của team bạn trong tháng "
            f"({lo[:10]} - {hi[:10]}):\n\n"
            + _print_table(rows, ["route", "unpaid_orders", "unpaid_amount"])
        )

        return (
            True,
            txt,
            {
                "intent": team_intent,
                "confidence": conf,
                "time_window": {"lo": lo, "hi": hi},
                "scope": scope,
            },
        )

    # ===== 3) Doanh thu theo nhân viên trong team tháng này =====
    if team_intent == "team_revenue_by_staff_month":
        pays = fetch_payment_range(lo, hi, paid_only=True, end_inclusive=False)
        pays = _filter_payments_by_scope(pays, scope)

        if not pays:
            return (
                True,
                "Trong tháng này team bạn chưa ghi nhận doanh thu nào trên các tuyến bạn phụ trách.",
                {
                    "intent": team_intent,
                    "confidence": conf,
                    "time_window": {"lo": lo, "hi": hi},
                    "scope": scope,
                },
            )

        agg = group_revenue_by_staff(pays)
        rows: List[Dict[str, Any]] = []

        for sid, amt in sorted(agg.items(), key=lambda x: x[1], reverse=True):
            try:
                sid_int = int(sid)
            except Exception:
                sid_int = sid
            acct = fetch_account_by_id(sid_int) or {}
            rows.append(
                {
                    "staff_id": sid,
                    "name": acct.get("name", ""),
                    "revenue": money_fmt(amt),
                }
            )

        txt = (
            f"Doanh thu theo nhân viên trong team bạn trong tháng này "
            f"({lo[:10]} - {hi[:10]}):\n\n"
            + _print_table(rows, ["staff_id", "name", "revenue"])
        )

        return (
            True,
            txt,
            {
                "intent": team_intent,
                "confidence": conf,
                "time_window": {"lo": lo, "hi": hi},
                "scope": scope,
            },
        )

    # ===== 4) Nhân viên nào trong team có nhiều đơn CHƯA THANH TOÁN nhất =====
    if team_intent == "team_staff_most_unpaid_month":
        pays_unpaid = fetch_table_all(
            "payment",
            {
                "gte__action_at": lo,
                "lt__action_at": hi,
                "in__status": ",".join(sorted(UNPAID_STATUSES)),
            },
        )
        pays_unpaid = _filter_payments_by_scope(pays_unpaid, scope)

        if not pays_unpaid:
            return (
                True,
                "Trong tháng này team bạn không có đơn hàng nào ở trạng thái CHƯA THANH TOÁN.",
                {
                    "intent": team_intent,
                    "confidence": conf,
                    "time_window": {"lo": lo, "hi": hi},
                    "scope": scope,
                },
            )

        # Gom theo staff_id
        cnt: Dict[int, int] = {}
        amt: Dict[int, float] = {}

        for p in pays_unpaid:
            sid = p.get("staff_id")
            try:
                sid_int = int(sid) if sid is not None else None
            except Exception:
                continue
            if sid_int is None:
                continue

            cnt[sid_int] = cnt.get(sid_int, 0) + 1
            amt[sid_int] = amt.get(sid_int, 0.0) + _f(p.get("amount"))

        if not cnt:
            return (
                True,
                "Không tìm thấy nhân viên nào trong team có đơn CHƯA THANH TOÁN trong tháng này.",
                {
                    "intent": team_intent,
                    "confidence": conf,
                    "time_window": {"lo": lo, "hi": hi},
                    "scope": scope,
                },
            )

        # Tìm staff có nhiều đơn chưa thanh toán nhất
        top_sid, top_count = max(cnt.items(), key=lambda x: x[1])
        top_amount = amt.get(top_sid, 0.0)
        top_acct = fetch_account_by_id(top_sid) or {}
        top_name = top_acct.get("name", f"staff #{top_sid}")

        # Bảng tổng hợp
        rows: List[Dict[str, Any]] = []
        for sid_int, c in sorted(cnt.items(), key=lambda x: x[1], reverse=True):
            acct = fetch_account_by_id(sid_int) or {}
            rows.append(
                {
                    "staff_id": sid_int,
                    "name": acct.get("name", ""),
                    "unpaid_orders": c,
                    "unpaid_amount": money_fmt(amt.get(sid_int, 0.0)),
                }
            )

        txt = (
            f"Trong tháng này ({lo[:10]} - {hi[:10]}), nhân viên trong team bạn có "
            f"nhiều đơn CHƯA THANH TOÁN nhất là **{top_name} (ID {top_sid})** "
            f"với **{top_count} đơn**, tổng giá trị khoảng **{money_fmt(top_amount)}**.\n\n"
            "Thống kê chi tiết các nhân viên trong team có đơn chưa thanh toán:\n\n"
            + _print_table(rows, ["staff_id", "name", "unpaid_orders", "unpaid_amount"])
        )

        return (
            True,
            txt,
            {
                "intent": team_intent,
                "confidence": conf,
                "time_window": {"lo": lo, "hi": hi},
                "scope": scope,
            },
        )

        # ===== 5) Nhân viên nào trong team có nhiều đơn ĐÃ THANH TOÁN nhất =====
    if team_intent == "team_staff_most_paid_month":
        # Lấy payment đã thanh toán trong tháng, trong phạm vi route của lead
        pays_paid = fetch_payment_range(lo, hi, paid_only=True, end_inclusive=False)
        pays_paid = _filter_payments_by_scope(pays_paid, scope)

        if not pays_paid:
            return (
                True,
                "Trong tháng này team bạn chưa có đơn hàng nào ở trạng thái ĐÃ THANH TOÁN trong phạm vi các tuyến bạn phụ trách.",
                {
                    "intent": team_intent,
                    "confidence": conf,
                    "time_window": {"lo": lo, "hi": hi},
                    "scope": scope,
                },
            )

        # Gom theo staff_id: số đơn ĐÃ THANH TOÁN + tổng doanh thu
        cnt: Dict[int, int] = {}
        amt: Dict[int, float] = {}

        for p in pays_paid:
            sid = p.get("staff_id")
            try:
                sid_int = int(sid) if sid is not None else None
            except Exception:
                continue
            if sid_int is None:
                continue

            cnt[sid_int] = cnt.get(sid_int, 0) + 1
            # với payment đã thanh toán, ưu tiên collected_amount
            value = _f(p.get("collected_amount")) or _f(p.get("amount"))
            amt[sid_int] = amt.get(sid_int, 0.0) + value

        if not cnt:
            return (
                True,
                "Không tìm thấy nhân viên nào trong team có đơn ĐÃ THANH TOÁN trong tháng này.",
                {
                    "intent": team_intent,
                    "confidence": conf,
                    "time_window": {"lo": lo, "hi": hi},
                    "scope": scope,
                },
            )

        # Tìm staff có nhiều đơn đã thanh toán nhất
        top_sid, top_count = max(cnt.items(), key=lambda x: x[1])
        top_amount = amt.get(top_sid, 0.0)
        top_acct = fetch_account_by_id(top_sid) or {}
        top_name = top_acct.get("name", f"staff #{top_sid}")

        # Bảng tổng hợp cho toàn team
        rows: List[Dict[str, Any]] = []
        for sid_int, c in sorted(cnt.items(), key=lambda x: x[1], reverse=True):
            acct = fetch_account_by_id(sid_int) or {}
            rows.append(
                {
                    "staff_id": sid_int,
                    "name": acct.get("name", ""),
                    "paid_orders": c,
                    "paid_amount": money_fmt(amt.get(sid_int, 0.0)),
                }
            )

        txt = (
            f"Trong tháng này ({lo[:10]} - {hi[:10]}), nhân viên trong team bạn có "
            f"nhiều đơn ĐÃ THANH TOÁN nhất là **{top_name} (ID {top_sid})** "
            f"với **{top_count} đơn**, tổng doanh thu khoảng **{money_fmt(top_amount)}**.\n\n"
            "Thống kê chi tiết các nhân viên trong team có đơn đã thanh toán:\n\n"
            + _print_table(rows, ["staff_id", "name", "paid_orders", "paid_amount"])
        )

        return (
            True,
            txt,
            {
                "intent": team_intent,
                "confidence": conf,
                "time_window": {"lo": lo, "hi": hi},
                "scope": scope,
            },
        )


    # ===== fallback =====
    return (
        True,
        f"✅ Intent LEAD_SALE nội bộ: {team_intent} (conf={conf:.2f}).",
        {"intent": team_intent, "confidence": conf, "scope": scope},
    )



# =========================
# Dispatcher cho các intent còn lại (mẫu + có thể mở rộng)
# =========================

def _dispatch_misc(
    intent: str,
    params: Dict[str, Any],
    session_id: str,
    conf: float,
    user_text: str,
    scope: Dict[str, Any],
):
    # === Doanh thu theo nhân viên (tôn trọng scope) ===
    if intent == "revenue_by_staff":
        lo, hi = this_month_range_iso()
        remember_time_window(session_id, lo, hi)
        pays = fetch_payment_range(lo, hi, paid_only=True, end_inclusive=False)

        # RBAC: SALE / LEAD_SALE bị filter
        pays = _filter_payments_by_scope(pays, scope)

        agg = group_revenue_by_staff(pays)
        rows: List[Dict[str, Any]] = []
        for sid, amt in sorted(agg.items(), key=lambda x: x[1], reverse=True):
            acct = fetch_account_by_id(int(sid)) or {}
            rows.append(
                {
                    "staff_id": sid,
                    "name": acct.get("name", ""),
                    "revenue": money_fmt(amt),
                }
            )
        txt = "▶ Doanh thu theo nhân viên (tháng)\n" + (
            _print_table(rows, ["staff_id", "name", "revenue"])
            if rows
            else "(khong co du lieu)"
        )
        return (
            True,
            txt,
            {
                "intent": intent,
                "confidence": conf,
                "time_window": {"lo": lo, "hi": hi},
                "scope": scope,
            },
        )

    # === Doanh thu theo tuyến (ADMIN/MANAGER; LEAD_SALE sẽ dùng intent riêng) ===
    if intent == "revenue_by_route":
        lo, hi = this_month_range_iso()
        remember_time_window(session_id, lo, hi)
        rows = [
            {"route": k, "revenue": money_fmt(v)}
            for k, v in agg_revenue_by_route(lo, hi)
        ]
        txt = "▶ Doanh thu theo tuyến (tháng)\n" + (
            _print_table(rows, ["route", "revenue"])
            if rows
            else "(khong co du lieu)"
        )
        return (
            True,
            txt,
            {
                "intent": intent,
                "confidence": conf,
                "time_window": {"lo": lo, "hi": hi},
                "scope": scope,
            },
        )

    # === Liên kết đơn với lô ===
    if intent == "intl_order_batch":
        code = params.get("code") or extract_order_code_from_text(user_text)
        if code:
            remember_order_code(session_id, code)
        pk = order_belongs_to_batch(code) if code else None
        return (
            True,
            f"📦 Đơn {code}: thuộc lô {pk or '(không tìm thấy)'}",
            {"intent": intent, "confidence": conf, "scope": scope},
        )

    # === Kho TQ: tổng cân nặng tháng ===
    if intent == "cn_total_weight":
        lo, hi = this_month_range_iso()
        remember_time_window(session_id, lo, hi)
        kg = cn_total_weight(lo, hi)
        return (
            True,
            f"⚖️ Tổng cân nặng hàng về kho TQ (tháng): {kg:.2f} kg",
            {
                "intent": intent,
                "confidence": conf,
                "time_window": {"lo": lo, "hi": hi},
                "scope": scope,
            },
        )

    # === Seller uy tín ===
    if intent == "seller_reputation":
        lo, hi = this_month_range_iso()
        remember_time_window(session_id, lo, hi)
        shop = (params.get("shop") or "").lower()
        r = seller_reputation(shop, lo, hi)
        rows = [r]
        txt = (
            f"▶ Đánh giá uy tín shop '{shop}'\n"
            + _print_table(
                rows,
                ["shop", "on_time_rate", "cancel_rate", "avg_rating", "orders"],
            )
        )
        return (
            True,
            txt,
            {
                "intent": intent,
                "confidence": conf,
                "time_window": {"lo": lo, "hi": hi},
                "scope": scope,
            },
        )
    if intent == "paid_orders_owner":
        # Ưu tiên dùng time_window đã lưu trong Redis (khi user vừa hỏi "doanh thu tháng này")
        from app.Model_LLM.Chat_Database.redis_ctx import get_ctx  # nếu chưa import trên đầu file

        try:
            ctx = get_ctx(session_id) or {}
        except Exception:
            ctx = {}

        raw_tw = ctx.get("last_time_window") or ctx.get("time_window") or {}
        if not isinstance(raw_tw, dict):
            raw_tw = {}

        lo = raw_tw.get("lo")
        hi = raw_tw.get("hi")

        # Nếu Redis không có time_window, fallback về tháng này
        if not lo or not hi:
            lo, hi = this_month_range_iso()

        remember_time_window(session_id, lo, hi)

        # Lấy tất cả payment đã thanh toán trong khoảng thời gian
        pays = fetch_payment_range(lo, hi, paid_only=True, end_inclusive=False)
        # RBAC: SALE / LEAD_SALE chỉ thấy phần của mình / team (scope đã xử lý trong _filter_payments_by_scope)
        pays = _filter_payments_by_scope(pays, scope)

        if not pays:
            txt = (
                "Hiện tại không tìm thấy đơn nào đã thanh toán trong khoảng thời gian "
                f"từ {lo[:10]} đến {hi[:10]} dưới quyền xem của bạn."
            )
            return (
                True,
                txt,
                {
                    "intent": intent,
                    "confidence": conf,
                    "time_window": {"lo": lo, "hi": hi},
                    "scope": scope,
                },
            )

        # Gộp theo (staff_id, staff_name, customer)
        agg: Dict[tuple, Dict[str, Any]] = {}
        for p in pays:
            # tuỳ cấu trúc payment: dùng staff_id trên payment hoặc map từ orders
            staff_id = p.get("staff_id")
            # map staff_id -> account để lấy tên
            acct = fetch_account_by_id(int(staff_id)) if staff_id is not None else {}
            staff_name = acct.get("name", "N/A")

            # cố gắng lấy thông tin khách từ payment hoặc order snapshot
            customer = p.get("customer_name") or p.get("customer") or "N/A"

            key = (staff_id, staff_name, customer)
            if key not in agg:
                agg[key] = {
                    "staff_id": staff_id,
                    "staff_name": staff_name,
                    "customer": customer,
                    "orders": 0,
                    "amount": 0.0,
                }

            agg[key]["orders"] += 1
            agg[key]["amount"] += _f(
                p.get("collected_amount", p.get("amount", 0))
            )

        rows: List[Dict[str, Any]] = []
        for (sid, sname, cust), v in sorted(
            agg.items(), key=lambda x: x[1]["amount"], reverse=True
        ):
            rows.append(
                {
                    "staff_id": sid,
                    "staff_name": sname,
                    "customer": cust,
                    "orders": v["orders"],
                    "amount": money_fmt(v["amount"]),
                }
            )

        header = (
            f"Dưới đây là phân bổ các đơn đã thanh toán trong khoảng thời gian "
            f"từ {lo[:10]} đến {hi[:10]} mà bạn có quyền xem:\n"
        )
        tbl = _print_table(
            rows,
            ["staff_id", "staff_name", "customer", "orders", "amount"],
        )
        txt = header + "\n" + tbl

        return (
            True,
            txt,
            {
                "intent": intent,
                "confidence": conf,
                "time_window": {"lo": lo, "hi": hi},
                "scope": scope,
            },
        )
    # === Mặc định: intent DB đã bắt nhưng chưa map riêng ===
    return (
        True,
        f"✅ Intent DB: {intent} (conf={conf:.2f}) — hãy bổ sung mapping riêng nếu muốn định dạng chi tiết hơn.",
        {"intent": intent, "confidence": conf, "scope": scope},
    )
