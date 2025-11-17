# # app/services/db_router.py
# # -*- coding: utf-8 -*-
# from __future__ import annotations
# from typing import Tuple, Optional, Dict, Any, List
# import traceback

# # Tái dùng toàn bộ hàm từ db_cli
# from app.Model_LLM.Chat_Database import db_cli as DB
# from app.Model_LLM.Chat_Database.redis_ctx import remember_time_window, remember_order_code, remember_intent

# # Danh sách intent do DB xử lý
# DB_INTENTS = {
#     "order_lookup","profile_by",
#     "revenue_month","revenue_week","revenue_day",
#     "cashflow","revenue_by_staff","revenue_by_route","revenue_by_destination",
#     "top_customers","aov_by_customer",
#     "orders_wait_buy","orders_purchased","warehouse_inventory","flights_waiting",
#     "mh_total_today","mh_total_week","mh_total_month","mh_wait_buy","mh_ordered_not_paid_seller",
#     "mh_wait_cn_wh","mh_arrived_cn_wait_vn","mh_at_port","mh_realtime_status",
#     "mh_seller_cancel_oos","mh_urgent_issues",
#     "seller_frequent","seller_on_time_rate","seller_inprogress_for_name",
#     "seller_late_or_cancel","seller_reputation","seller_avg_to_cn","seller_blacklist",
#     "cn_count_items","cn_order_arrived","cn_wait_packing","cn_overstay",
#     "cn_storage_cost","cn_overloaded","cn_total_weight",
#     "intl_in_transit","intl_eta","intl_order_batch","intl_customs_stuck",
#     "intl_cost","intl_partner","intl_avg_time","intl_tracking"
# }

# def _fmt_table(rows: List[Dict[str, Any]], headers: List[str]) -> str:
#     return _print_table(rows, headers)

# def _safe(s: Optional[str]) -> str:
#     return (s or "").strip()

# def handle_db_message(user_text: str, session_id: str) -> Tuple[bool, str, Dict[str, Any]]:
#     """
#     Trả về:
#       (True, answer, meta) nếu đã xử lý bằng DB
#       (False, "", {}) nếu không phải intent DB
#     """
#     try:
#         intent, params, conf = classify_query(user_text)
#         if intent not in DB_INTENTS:
#             return (False, "", {})

#         # Lưu Redis context cơ bản
#         remember_intent(session_id, intent, conf)

#         # ---------- Ý định chi tiết ----------
#         # Các nhánh dưới đây copy logic từ CLI, nhưng trả string thay vì print.
#         # Chỉ trích phần kết quả (giữ định dạng bảng giống CLI).

#         # 1) Tra đơn / mã đơn
#         if intent in {"order_lookup","unknown"}:
#             code = extract_order_code_from_text(user_text)
#             if code:
#                 remember_order_code(session_id, code)
#                 snap = order_snapshot_by_code(code)
#                 return (True, format_snapshot(snap), {"intent": intent, "confidence": conf})
#             return (True, "⚠️ Không thấy mã đơn trong câu hỏi.", {"intent": intent, "confidence": conf})

#         # 2) Hồ sơ tài khoản
#         if intent == "profile_by":
#             fld, val = params.get("field"), params.get("value")
#             prof = person_full_profile(fld, val, recent_limit=20)
#             if not prof:
#                 return (True, "❌ Không tìm thấy tài khoản.", {"intent": intent, "confidence": conf})
#             acct = prof["account"]; role = (acct.get("role") or "").upper()
#             rows_orders = [{"order_code": o.get("order_code",""), "status": o.get("status","")} for o in prof["orders_recent"][:10]]
#             blocks = []
#             blocks.append(f"👤 Account #{acct.get('account_id')} — {acct.get('name','N/A')}")
#             blocks.append(f"   • Email: {acct.get('email','N/A')} | Phone: {acct.get('phone','N/A')} | Username: {acct.get('username','N/A')}")
#             blocks.append(f"   • Role: {role or 'N/A'} | Status: {acct.get('status','N/A')}")
#             ag = prof["aggregates"]; blocks.append(f"💰 Payments recent: paid={money_fmt(ag.get('total_paid_recent',0))} | outstanding={money_fmt(ag.get('outstanding_recent',0))} | count={ag.get('payments_count_recent',0)}")
#             if rows_orders:
#                 blocks.append("📦 Orders recent:\n" + _fmt_table(rows_orders, ["order_code","status"]))
#             blocks.append(f"🏬 Warehouse recent: {len(prof['warehouse_recent'])} | 📝 Logs: {len(prof['logs_recent'])} | ⭐ Feedback: {len(prof['feedback_recent'])}")
#             return (True, "\n".join(blocks), {"intent": intent, "confidence": conf})

#         # 3) Doanh thu / thời gian
#         if intent in {"revenue_month","revenue_week","revenue_day"}:
#             if intent=="revenue_month":
#                 parsed = resolve_month_from_text(user_text, _now(), VN_TZ)
#                 lo,hi = parsed if parsed else this_month_range_iso()
#             elif intent=="revenue_week":
#                 lo,hi = this_week_range_iso()
#             else:
#                 lo,hi = today_range_iso()
#             remember_time_window(session_id, lo, hi)

#             pays_paid = fetch_payment_range(lo, hi, paid_only=True, end_inclusive=False)
#             pays_unpaid = fetch_table_all("payment", {"gte__action_at": lo, "lt__action_at": hi, "in__status": ",".join(sorted(UNPAID_STATUSES))})
#             total = sum_revenue_from_payments(pays_paid)
#             head = f"💰 Doanh thu {lo} → {hi}: {money_fmt(total)} (giao dịch: {len(pays_paid)})"

#             rows_total = [{
#                 "window": f"{lo[:10]}→{hi[:10]}",
#                 "paid_orders": len(pays_paid),
#                 "paid_amount": money_fmt(sum_revenue_from_payments(pays_paid)),
#                 "unpaid_orders": len(pays_unpaid),
#                 "unpaid_amount": money_fmt(sum(_f(r.get('amount')) for r in pays_unpaid)),
#             }]
#             body = "\n▶ Tổng\n" + _fmt_table(rows_total, ["window","paid_orders","paid_amount","unpaid_orders","unpaid_amount"])
#             return (True, head + "\n" + body, {"intent": intent, "confidence": conf, "time_window": {"lo": lo, "hi": hi}})

#         # 4) Các hàm còn lại: tái sử dụng giống CLI (rút gọn)
#         # Để không kéo dài: gom vào một dispatcher nhỏ
#         return _dispatch_misc(intent, params, session_id, conf, user_text)

#     except Exception as e:
#         tb = traceback.format_exc(limit=2)
#         return (True, f"⚠️ Lỗi DB branch: {e}\n{tb}", {"error": "db_branch_failed"})

# def _dispatch_misc(intent: str, params: Dict[str,Any], session_id: str, conf: float, user_text: str):
#     # Mẫu 1-2 intent tiêu biểu; các intent còn lại bạn đã có trong CLI — bạn có thể mở rộng tương tự
#     if intent == "revenue_by_staff":
#         lo,hi = this_month_range_iso()
#         remember_time_window(session_id, lo, hi)
#         pays = fetch_payment_range(lo, hi, paid_only=True, end_inclusive=False)
#         agg = group_revenue_by_staff(pays)
#         rows = []
#         for sid, amt in sorted(agg.items(), key=lambda x: x[1], reverse=True):
#             acct = fetch_account_by_id(int(sid)) or {}
#             rows.append({"staff_id": sid, "name": acct.get("name",""), "revenue": money_fmt(amt)})
#         txt = "▶ Doanh thu theo nhân viên (tháng)\n" + (_print_table(rows, ["staff_id","name","revenue"]) if rows else "(không có dữ liệu)")
#         return (True, txt, {"intent": intent, "confidence": conf, "time_window": {"lo": lo, "hi": hi}})
#     if intent == "intl_order_batch":
#         code = params.get("code") or extract_order_code_from_text(user_text)
#         if code: remember_order_code(session_id, code)
#         pk = order_belongs_to_batch(code) if code else None
#         return (True, f"📦 Đơn {code}: thuộc lô {pk or '(không tìm thấy)'}", {"intent": intent, "confidence": conf})

#     # Mặc định: báo đã nhận diện intent DB nhưng chưa map riêng → rơi về CLI logic ngắn
#     return (True, f"✅ Intent DB: {intent} (conf={conf:.2f}) — vui lòng bật thêm mapping nếu muốn định dạng riêng.", {"intent": intent, "confidence": conf})

# app/services/db_router.py
# -*- coding: utf-8 -*-
"""
Adapter chuyển toàn bộ logic DB-CLI sang hàm server-side để chat.py có thể
định tuyến “DB trước, RAG sau”. Trả về text (bảng ASCII giống CLI).

- handle_db_message(user_text, session_id) -> (handled: bool, answer: str, meta: dict)
- Meta gồm intent, confidence, time_window (nếu có).
"""

from __future__ import annotations
from typing import Tuple, Optional, Dict, Any, List
import traceback
# from app.Model_LLM.Chat_Database.db_cli import db_cli as DB
from app.Model_LLM.Chat_Database.redis_ctx import (
    remember_time_window,
    remember_order_code,
    remember_intent,
)
from app.Model_LLM.Chat_Database.db_cli import (
    UNPAID_STATUSES, _f, _now, _print_table,
    agg_revenue_by_route, classify_query, cn_total_weight,
    extract_order_code_from_text, fetch_account_by_id,
    fetch_orders_range, fetch_payment_range, fetch_routes_map,
    fetch_table_all, fetch_warehouse_in_period, format_snapshot,
    group_revenue_by_staff, money_fmt, order_belongs_to_batch,
    order_snapshot_by_code, person_full_profile, resolve_month_from_text,
    seller_reputation, sum_revenue_from_payments, this_month_range_iso,
    this_week_range_iso, today_range_iso,
)
from app.config.config_supabase import VN_TZ

DB_INTENTS = {
    "order_lookup", "profile_by",
    "revenue_month", "revenue_week", "revenue_day",
    "cashflow", "revenue_by_staff", "revenue_by_route", "revenue_by_destination",
    "top_customers", "aov_by_customer",
    "orders_wait_buy", "orders_purchased", "warehouse_inventory", "flights_waiting",
    "mh_total_today", "mh_total_week", "mh_total_month",
    "mh_wait_buy", "mh_ordered_not_paid_seller",
    "mh_wait_cn_wh", "mh_arrived_cn_wait_vn", "mh_at_port", "mh_realtime_status",
    "mh_seller_cancel_oos", "mh_urgent_issues",
    "seller_frequent", "seller_on_time_rate", "seller_inprogress_for_name",
    "seller_late_or_cancel", "seller_reputation", "seller_avg_to_cn", "seller_blacklist",
    "cn_count_items", "cn_order_arrived", "cn_wait_packing", "cn_overstay",
    "cn_storage_cost", "cn_overloaded", "cn_total_weight",
    "intl_in_transit", "intl_eta", "intl_order_batch", "intl_customs_stuck",
    "intl_cost", "intl_partner", "intl_avg_time", "intl_tracking",
}


def _fmt_table(rows: List[Dict[str, Any]], headers: List[str]) -> str:
    return _print_table(rows, headers)

def _safe(s: Optional[str]) -> str:
    return (s or "").strip()

def handle_db_message(user_text: str, session_id: str) -> Tuple[bool, str, Dict[str, Any]]:
    try:
        intent, params, conf = classify_query(user_text)
        if intent not in DB_INTENTS:
            return (False, "", {})
        remember_intent(session_id, intent, conf)
        if intent in {"order_lookup", "unknown"}:
            code = extract_order_code_from_text(user_text)
            if code:
                remember_order_code(session_id, code)
                snap = order_snapshot_by_code(code)
                return (True, format_snapshot(snap), {"intent": intent, "confidence": conf})
            return (True, "⚠️ Không thấy mã đơn trong câu hỏi.", {"intent": intent, "confidence": conf})

        if intent == "profile_by":
            fld, val = params.get("field"), params.get("value")
            prof = person_full_profile(fld, val, recent_limit=20)
            if not prof:
                return (True, "❌ Không tìm thấy tài khoản.", {"intent": intent, "confidence": conf})
            acct = prof["account"]
            role = (acct.get("role") or "").upper()
            rows_orders = [{"order_code": o.get("order_code", ""), "status": o.get("status", "")}
                           for o in prof["orders_recent"][:10]]
            blocks = []
            blocks.append(f"👤 Account #{acct.get('account_id')} — {acct.get('name','N/A')}")
            blocks.append(f"   • Email: {acct.get('email','N/A')} | Phone: {acct.get('phone','N/A')} | Username: {acct.get('username','N/A')}")
            blocks.append(f"   • Role: {role or 'N/A'} | Status: {acct.get('status','N/A')}")
            ag = prof["aggregates"]
            blocks.append(f"💰 Payments recent: paid={money_fmt(ag.get('total_paid_recent',0))} | "
                          f"outstanding={money_fmt(ag.get('outstanding_recent',0))} | "
                          f"count={ag.get('payments_count_recent',0)}")
            if rows_orders:
                blocks.append("📦 Orders recent:\n" + _fmt_table(rows_orders, ["order_code", "status"]))
            blocks.append(f"🏬 Warehouse recent: {len(prof['warehouse_recent'])} | "
                          f"📝 Logs: {len(prof['logs_recent'])} | ⭐ Feedback: {len(prof['feedback_recent'])}")
            return (True, "\n".join(blocks), {"intent": intent, "confidence": conf})

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

            # Lấy dữ liệu
            pays_paid = fetch_payment_range(lo, hi, paid_only=True, end_inclusive=False)
            pays_unpaid = fetch_table_all(
                "payment",
                {"gte__action_at": lo, "lt__action_at": hi, "in__status": ",".join(sorted(UNPAID_STATUSES))}
            )
            total = sum_revenue_from_payments(pays_paid)

            # Helper định dạng ngày dd/mm/yyyy
            def _dmy(iso: str) -> str:
                try:
                    y, m, d = iso[:10].split("-")
                    return f"{d}/{m}/{y}"
                except Exception:
                    return iso[:10]

            # Hàng bảng tổng quan
            rows_total = [{
                "window": f"{lo[:10]}→{hi[:10]}",
                "paid_orders": len(pays_paid),
                "paid_amount": money_fmt(sum_revenue_from_payments(pays_paid)),
                "unpaid_orders": len(pays_unpaid),
                "unpaid_amount": money_fmt(sum(_f(r.get('amount')) for r in pays_unpaid)),
            }]

            # ===== PHẦN MỚI: tóm tắt + “Tổng quan doanh thu …” (giống log cũ) =====
            summary_header = f"chi tiết tổng doanh thu {label} nay"
            d1, d2 = _dmy(lo), _dmy(hi)
            summary_para = (
                f"{summary_header}\n\n"
                f"Doanh thu từ {d1} đến {d2} đạt {money_fmt(total)} với {len(pays_paid)} giao dịch.\n\n"
                f"Tổng quan doanh thu trong giai đoạn này như sau:\n\n"
                + _print_table(rows_total, ["window", "paid_orders", "paid_amount", "unpaid_orders", "unpaid_amount"])
            )

            # ===== PHẦN CŨ: head + các bảng chi tiết =====
            head = f"💰 Doanh thu {lo} → {hi}: {money_fmt(total)} (giao dịch: {len(pays_paid)})"
            body_total = "\n▶ Tổng\n" + _print_table(
                rows_total, ["window", "paid_orders", "paid_amount", "unpaid_orders", "unpaid_amount"]
            )

            # Tổng hợp PAID/UNPAID theo status
            def _agg_by_status(rows, paid: bool):
                by, cnt = {}, {}
                for r in rows:
                    st = (r.get("status") or "").upper()
                    v = _f(r.get("collected_amount" if paid else "amount"))
                    by[st] = by.get(st, 0.0) + v
                    cnt[st] = cnt.get(st, 0) + 1
                return [{"pay_status": k, "orders": cnt.get(k, 0), "amount": money_fmt(by.get(k, 0.0))}
                        for k in sorted((cnt.keys() | by.keys()))]

            det_paid = _agg_by_status(pays_paid, True)
            det_unpd = _agg_by_status(pays_unpaid, False)

            paid_tbl = _print_table(det_paid, ["pay_status", "orders", "amount"]) if det_paid else "(khong co du lieu)"
            unpd_tbl = _print_table(det_unpd, ["pay_status", "orders", "amount"]) if det_unpd else "(khong co du lieu)"

            sections: List[str] = [
                summary_para,  # <<==== chèn phần mới lên trước
                head,
                body_total,
                "▶ Tổng hợp thanh toán (" + label + ")\n" + _print_table(
                    [
                        {"group": "PAID_STATUSES", "orders": len(pays_paid),
                         "amount": money_fmt(sum_revenue_from_payments(pays_paid))},
                        {"group": "UNPAID_STATUSES", "orders": len(pays_unpaid),
                         "amount": money_fmt(sum(_f(r.get('amount')) for r in pays_unpaid))},
                    ],
                    ["group", "orders", "amount"]
                ),
                "▶ Chi tiết thanh toán (" + label + ") — PAID_STATUSES\n" + paid_tbl,
                "▶ Chi tiết thanh toán (" + label + ") — UNPAID_STATUSES\n" + unpd_tbl,
            ]

            # Chỉ riêng "tháng" mới thêm 2 bảng kho & trạng thái đơn (giữ đúng như log cũ)
            if intent == "revenue_month":
                wh = fetch_warehouse_in_period(lo, hi)
                routes = fetch_routes_map()
                kg = {}
                for r in wh:
                    rid = r.get("route_id")
                    w = _f(r.get("weight"))
                    name = routes.get(int(rid), f"ROUTE#{rid}") if rid is not None else "UNKNOWN"
                    kg[name] = kg.get(name, 0.0) + w
                rows_kg = [{"route": k, "kg": round(v, 2)} for k, v in sorted(kg.items())]
                sections.append("\n▶ Số kg theo tuyến (theo warehouse.created_at trong tháng)\n" +
                                (_print_table(rows_kg, ["route", "kg"]) if rows_kg else "(khong co du lieu)"))

                ords = fetch_orders_range(lo, hi)
                agg_stat: Dict[str, int] = {}
                for o in ords:
                    st = (o.get("status") or "UNKNOWN").upper()
                    agg_stat[st] = agg_stat.get(st, 0) + 1
                stat_rows = [{"status": k.replace("_", " ").title(), "orders": v} for k, v in sorted(agg_stat.items())]
                sections.append("\n▶ Trạng thái đơn (tháng)\n" +
                                (_print_table(stat_rows, ["status", "orders"]) if stat_rows else "(khong co du lieu)"))
                sections.append("ℹ️  Lưu ý: Đây là trạng thái NGHIỆP VỤ của đơn (orders.status), "
                                "KHÁC với trạng thái thanh toán (payment.status).")

            txt = "\n".join(sections)
            return (True, txt, {"intent": intent, "confidence": conf, "time_window": {"lo": lo, "hi": hi}})

        # 4) Các intent khác — gom trong dispatcher gọn để tránh file quá dài
        return _dispatch_misc(intent, params, session_id, conf, user_text)

    except Exception as e:
        tb = traceback.format_exc(limit=2)
        return (True, f"⚠️ Lỗi DB branch: {e}\n{tb}", {"error": "db_branch_failed"})


# =========================
# Dispatcher cho các intent còn lại (mẫu + có thể mở rộng)
# =========================
def _dispatch_misc(intent: str, params: Dict[str, Any], session_id: str, conf: float, user_text: str):
    # === Doanh thu theo nhân viên (ví dụ) ===
    if intent == "revenue_by_staff":
        lo, hi = this_month_range_iso()
        remember_time_window(session_id, lo, hi)
        pays = fetch_payment_range(lo, hi, paid_only=True, end_inclusive=False)
        agg = group_revenue_by_staff(pays)
        rows = []
        for sid, amt in sorted(agg.items(), key=lambda x: x[1], reverse=True):
            acct = fetch_account_by_id(int(sid)) or {}
            rows.append({"staff_id": sid, "name": acct.get("name", ""), "revenue": money_fmt(amt)})
        txt = "▶ Doanh thu theo nhân viên (tháng)\n" + (_print_table(rows, ["staff_id", "name", "revenue"]) if rows else "(khong co du lieu)")
        return (True, txt, {"intent": intent, "confidence": conf, "time_window": {"lo": lo, "hi": hi}})

    # === Doanh thu theo tuyến ===
    if intent == "revenue_by_route":
        lo, hi = this_month_range_iso()
        remember_time_window(session_id, lo, hi)
        rows = [{"route": k, "revenue": money_fmt(v)} for k, v in agg_revenue_by_route(lo, hi)]
        txt = "▶ Doanh thu theo tuyến (tháng)\n" + (_print_table(rows, ["route", "revenue"]) if rows else "(khong co du lieu)")
        return (True, txt, {"intent": intent, "confidence": conf, "time_window": {"lo": lo, "hi": hi}})

    # === Liên kết đơn với lô (ví dụ) ===
    if intent == "intl_order_batch":
        code = params.get("code") or extract_order_code_from_text(user_text)
        if code:
            remember_order_code(session_id, code)
        pk = order_belongs_to_batch(code) if code else None
        return (True, f"📦 Đơn {code}: thuộc lô {pk or '(không tìm thấy)'}", {"intent": intent, "confidence": conf})

    # === Kho TQ: tổng cân nặng tháng ===
    if intent == "cn_total_weight":
        lo, hi = this_month_range_iso()
        remember_time_window(session_id, lo, hi)
        kg = cn_total_weight(lo, hi)
        return (True, f"⚖️ Tổng cân nặng hàng về kho TQ (tháng): {kg:.2f} kg",
                {"intent": intent, "confidence": conf, "time_window": {"lo": lo, "hi": hi}})

    # === Seller uy tín ===
    if intent == "seller_reputation":
        lo, hi = this_month_range_iso()
        remember_time_window(session_id, lo, hi)
        shop = (params.get("shop") or "").lower()
        r = seller_reputation(shop, lo, hi)
        rows = [r]
        txt = f"▶ Đánh giá uy tín shop '{shop}'\n" + _print_table(rows, ["shop", "on_time_rate", "cancel_rate", "avg_rating", "orders"])
        return (True, txt, {"intent": intent, "confidence": conf, "time_window": {"lo": lo, "hi": hi}})

    # === Mặc định: báo intent DB đã bắt, nhưng chưa map riêng (để bạn bổ sung dần) ===
    return (True, f"✅ Intent DB: {intent} (conf={conf:.2f}) — hãy bổ sung mapping riêng nếu muốn định dạng chi tiết hơn.",
            {"intent": intent, "confidence": conf})
