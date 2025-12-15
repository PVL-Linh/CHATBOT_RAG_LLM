from __future__ import annotations
from flask import Blueprint, render_template, session, redirect, url_for

from app.Login.login_required import login_required

# Import từ wrapper history mới (Supabase version)
from app.services.wrapper import (
    get_current_session_id,
    get_session_messages,
    get_sessions_list,
)

bp = Blueprint('pages', __name__)


# ===============================================
# Trang Chat Chính - Hỗ trợ session hiện tại
# ===============================================
@bp.route('/', methods=['GET'])
@login_required
def chat():
    """
    Trang chat chính: redirect về session hiện tại (mới nhất).
    """
    current_session_id = get_current_session_id()
    return redirect(url_for('pages.chat_session', session_id=current_session_id))


@bp.route('/chat/<session_id>', methods=['GET'])
@login_required
def chat_session(session_id: str):
    """
    Trang chat chi tiết theo session_id.
    Nếu session không tồn tại → vẫn load session mới nhất để tránh lỗi.
    """
    # Lấy danh sách tất cả session của user
    sessions = get_sessions_list()

    # Kiểm tra session_id có hợp lệ không
    valid_session_ids = {s["id"] for s in sessions}
    if session_id not in valid_session_ids:
        # Nếu không hợp lệ → chuyển về session mới nhất
        fallback_session_id = get_current_session_id()
        return redirect(url_for('pages.chat_session', session_id=fallback_session_id))

    # Load tin nhắn trong session hiện tại (50 tin nhắn gần nhất)
    messages = get_session_messages(session_id, limit=60)

    return render_template(
        'home/chat.html',
        messages=messages,
        sessions=sessions,                  # để làm sidebar
        current_session_id=session_id,
        current_user=session.get('user'),
        active='chat'
    )

@bp.route('/marketing', methods=['GET'])
@login_required(roles=['marketing', 'manager_marketing', 'sales', 'manager_sales'])
def marketing():
    return render_template('home/marketing.html', current_user=session.get('user'), active='marketing')


@bp.route('/sales', methods=['GET'])
@login_required
def sales():
    return render_template('home/sales.html', current_user=session.get('user'), active='sales')

@bp.route('/hr', methods=['GET'])
@login_required(roles=['hr', 'accountant'])
def hr():
    return render_template('home/hr.html', current_user=session.get('user'), active='hr')

@bp.route('/accountant', methods=['GET'])
@login_required(roles=['hr', 'accountant'])
def accountant():
    return render_template('home/accountant.html', current_user=session.get('user'), active='accountant')

@bp.route('/guide', methods=['GET'])
@login_required
def guide():
    return render_template('home/guide.html', current_user=session.get('user'), active='guide')

@bp.route('/admin', methods=['GET'])
@login_required(roles=['admin'])
def admin():
    return render_template('home/admin.html', current_user=session.get('user'), active='admin')

@bp.get("/indexing")
@login_required
def indexing_faiss():
    return render_template("home/indexing_Faiss.html", active="indexing_faiss")

@bp.route("/warehouse", methods=['GET'])
@login_required
def warehouse():
    return render_template("home/warehouse.html", active="warehouse")

@bp.route('/post-login')
def post_login():
    return render_template('home/post_login.html')