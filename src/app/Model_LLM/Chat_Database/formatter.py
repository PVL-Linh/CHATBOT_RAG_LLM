# -*- coding: utf-8 -*-
from tabulate import tabulate

def _money(x: float) -> str:
    try:
        return f"{x:,.0f}₫"
    except Exception:
        return str(x)

def out(obj) -> str:
    # hàm định dạng tổng quát cho KPI (giữ như bản bạn đang dùng)
    if obj is None:
        return "Không có dữ liệu."
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        if not obj:
            return "Không có dữ liệu."
        if isinstance(obj[0], (list, tuple)):
            return tabulate(obj, tablefmt="github")
        if isinstance(obj[0], dict):
            headers = sorted({k for r in obj for k in r.keys()})
            rows = [[r.get(h, "") for h in headers] for r in obj]
            return tabulate([headers] + rows, tablefmt="github")
        return "\n".join(map(str, obj))
    if isinstance(obj, dict):
        # in key-value
        lines = []
        for k, v in obj.items():
            lines.append(f"- {k}: {v}")
        return "\n".join(lines)
    return str(obj)

def format_snapshot(snap: dict) -> str:
    if not snap:
        return "Không tìm thấy đơn theo mã đã nhập."
    lines = []
    lines.append(f"📦 Đơn: {snap.get('order_code')} (#{snap.get('order_id')})")
    lines.append(f"   • Trạng thái: {snap.get('status')}")
    lines.append(f"   • Thời gian tạo: {snap.get('created_at')}")
    lines.append(f"   • Nhân viên phụ trách: {snap.get('staff_label')} (id={snap.get('staff_id')}) — {snap.get('staff_name') or '—'}")
    lines.append(f"   • Khách hàng: #{snap.get('customer_id')} — {snap.get('customer_name') or '—'}")
    lines.append(f"   • Tuyến: {snap.get('route_name')} (id={snap.get('route_id')})")
    lines.append(f"   • Điểm đến: {snap.get('destination_name')} (id={snap.get('destination_id')})")
    pays = snap.get("payments") or {}
    lines.append(f"💰 Thanh toán: đã thu {_money(pays.get('paid_total',0.0))} | còn chờ {_money(pays.get('pending_total',0.0))} | giao dịch: {pays.get('count',0)}")
    lg = snap.get("last_log")
    if lg:
        lines.append(f"📝 Log gần nhất: {lg.get('action')} @ {lg.get('timestamp')} (staff_id={lg.get('staff_id')})")
    return "\n".join(lines)

# (Nếu bạn đã có format_person_profile thì giữ nguyên; nếu chưa, dùng bản này)
def _fmt_money(x: float) -> str:
    try:
        return f"{x:,.0f}₫"
    except Exception:
        return str(x)

def format_person_profile(pf: dict) -> str:
    if not pf:
        return "Không tìm thấy tài khoản phù hợp."
    acct = pf.get("account") or {}
    lines = []
    lines.append(f"👤 Account #{acct.get('account_id')} — {acct.get('name') or ''}")
    lines.append(f"   • Email: {acct.get('email') or '—'} | Phone: {acct.get('phone') or '—'} | Username: {acct.get('username') or '—'}")
    lines.append(f"   • Role: {pf.get('role') or '—'} | Status: {acct.get('status') or '—'}")
    if pf.get("customer"):
        c = pf["customer"]
        try:
            bal = float(c.get("balance") or 0)
        except Exception:
            bal = 0.0
        lines.append(f"🏷 Customer: code={c.get('customer_code')} | balance={_fmt_money(bal)} | total_weight={c.get('total_weight') or 0}")
    if pf.get("staff"):
        s = pf["staff"]
        lines.append(f"🧑‍💼 Staff: code={s.get('staff_code')} | location={s.get('location') or '—'} | dept={s.get('department') or '—'}")
    ag = pf.get("aggregates") or {}
    lines.append(f"💰 Payments recent: paid={_fmt_money(ag.get('total_paid_recent',0))} | outstanding={_fmt_money(ag.get('outstanding_recent',0))} | count={ag.get('payments_count_recent',0)}")
    ros = pf.get("orders_recent") or []
    if ros:
        show = []
        for r in ros[:5]:
            show.append(f"{r.get('order_code') or '#'+str(r.get('order_id'))}({r.get('status')})")
        lines.append("📦 Orders recent: " + ", ".join(show))
    wh = pf.get("warehouse_recent") or []
    if wh:
        lines.append(f"🏬 Warehouse records recent: {len(wh)}")
    lg = pf.get("logs_recent") or []
    fb = pf.get("feedback_recent") or []
    if lg:
        lines.append(f"📝 Logs recent: {len(lg)}")
    if fb:
        lines.append(f"⭐ Feedback recent: {len(fb)}")
    return "\n".join(lines)
