from flask import render_template, request, jsonify

def init_error_handlers(app):
    @app.errorhandler(404)
    def not_found(e):
        if request.path.startswith('/api/'):
            return jsonify({"ok": False, "error": "Not found"}), 404
        try:
            return render_template('home/404.html'), 404
        except Exception:
            return "<h1>404 Not Found</h1>", 404