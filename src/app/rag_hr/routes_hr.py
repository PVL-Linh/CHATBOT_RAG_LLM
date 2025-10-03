# -*- coding: utf-8 -*-
# Ví dụ Flask route đơn giản để gọi engine
try:
    from flask import Blueprint, request, jsonify
    from .engine_hr import answer_with_rag, continue_with_last
except Exception:
    # Cho phép import module này ngay cả khi không dùng Flask
    answer_with_rag = None
    continue_with_last = None

bp_hr = Blueprint("hr", __name__)

@bp_hr.route("/hr/ask", methods=["POST"])
def hr_ask():
    data = request.get_json(force=True) or {}
    q = (data.get("q") or "").strip()
    if not q:
        return jsonify({"error":"missing q"}), 400
    ans, trace = answer_with_rag(q)
    return jsonify({"answer": ans, "trace": trace})

@bp_hr.route("/hr/continue", methods=["POST"])
def hr_continue():
    data = request.get_json(force=True) or {}
    q = (data.get("q") or "").strip()
    if not q:
        return jsonify({"error":"missing q"}), 400
    ans, trace = continue_with_last(q)
    return jsonify({"answer": ans, "trace": trace})
