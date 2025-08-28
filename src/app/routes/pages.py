from flask import Blueprint, render_template, session
from app.Login.login_required import login_required
from app.services.history import get_history

bp = Blueprint('pages', __name__)

@bp.route('/', methods=['GET'])
@login_required
def chat():
    return render_template('home/chat.html', messages=get_history()[-30:], current_user=session.get('user'), active='chat')


@bp.route('/marketing', methods=['GET'])
@login_required(roles=['marketing', 'manager_marketing'])
def marketing():
    return render_template('home/marketing.html', current_user=session.get('user'), active='marketing')


@bp.route('/sales', methods=['GET'])
@login_required
def sales():
    return render_template('home/sales.html', current_user=session.get('user'), active='sales')

@bp.route('/hr', methods=['GET'])
@login_required
def hr():
    return render_template('home/hr.html', current_user=session.get('user'), active='hr')


@bp.route('/guide', methods=['GET'])
@login_required
def guide():
    return render_template('home/guide.html', current_user=session.get('user'), active='guide')


@bp.route('/admin', methods=['GET'])
@login_required(roles=['admin'])
def admin():
    return render_template('home/admin.html', current_user=session.get('user'), active='admin')