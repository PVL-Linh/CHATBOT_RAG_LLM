# import os
# from flask import Flask
# from dotenv import load_dotenv
# from flask_compress import Compress
# from .routes import register_blueprints, register_error_handlers

# def create_app() -> Flask:
#     # Load env early
#     load_dotenv()

#     # Keep template/static roots identical to your current layout
#     app = Flask(__name__, template_folder="templates", static_folder="static")
#     app.config.from_object('app.config.Config')
#     app.config.setdefault('SEND_FILE_MAX_AGE_DEFAULT', 31536000)

#     # Optional compression (same as before)
#     Compress(app)

#     # Register blueprints + error handlers
#     register_blueprints(app)
#     register_error_handlers(app)

#     return app

# V2
# import os
# from flask import Flask, jsonify
# from dotenv import load_dotenv
# from flask_compress import Compress
# from app.routes import register_blueprints, register_error_handlers
# from werkzeug.middleware.proxy_fix import ProxyFix
# from app.tools.migrate_users_csv_to_sqlite import migrate
# from app.Login.login_required import init_auth_storage
# # from app.routes.hr_rag import bp_hr_rag

# def create_app() -> Flask:
#     # Load env early
#     load_dotenv()

#     # Keep template/static roots identical to your current layout
#     app = Flask(__name__, template_folder="templates", static_folder="static")
#     # app.register_blueprint(bp_hr_rag)
#     # Production configuration
#     app.config.update(
#         SECRET_KEY=os.environ.get('SECRET_KEY', 'dev-key-change-in-production'),
#         DEBUG=os.environ.get('FLASK_DEBUG', 'False').lower() == 'true',
#         SEND_FILE_MAX_AGE_DEFAULT=0,  # 1 year cache
#         MAX_CONTENT_LENGTH=16 * 1024 * 1024,  # 16MB max file size
#         JSON_SORT_KEYS=False,
#         JSONIFY_PRETTYPRINT_REGULAR=False,
#         PREFERRED_URL_SCHEME="https",
#     )
    
#     # Try to load from your existing config.py if it exists
#     try:
#         app.config.from_object('app.config.Config')
#     except (ImportError, AttributeError):
#         print("⚠️  Warning: Could not load Config class, using defaults")
#         pass  # Config file doesn't exist or Config class not found
    
#     app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
#     # Optional compression (same as before)
#     Compress(app)

#     # Health check endpoint for Docker and monitoring
#     @app.route('/health')
#     def health_check():
#         return jsonify({
#             'status': 'healthy',
#             'version': '1.0.0',
#             'environment': os.environ.get('FLASK_ENV', 'development'),
#             'debug': app.config.get('DEBUG', False)
#         }), 200

#     # Ping endpoint for simple checks
#     @app.route('/ping')
#     def ping():
#         return 'pong', 200

#     # Register blueprints + error handlers (your existing code)
#     register_blueprints(app)
#     register_error_handlers(app)
#     migrate()
#     init_auth_storage()

#     return app

# #APP FACTORY v3
import os
import hashlib
import time
from pathlib import Path
from flask import Flask, jsonify, url_for as _url_for, request
from dotenv import load_dotenv
from flask_compress import Compress
from werkzeug.middleware.proxy_fix import ProxyFix

from app.routes import register_blueprints, register_error_handlers
from app.tools.migrate_users_csv_to_sqlite import migrate
from app.Login.login_required import init_auth_storage


def _asbool(val, default=False):
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "t", "yes", "y", "on"}

def create_app() -> Flask:
    load_dotenv()

    app = Flask(__name__, template_folder="templates", static_folder="static")

    # ---- ĐỌC DEBUG CHUẨN: chấp nhận 1/true/yes/on ----
    debug_env = os.getenv("FLASK_DEBUG", os.getenv("DEBUG", "0"))
    debug_flag = _asbool(debug_env)

    app.config.update(
        SECRET_KEY=os.environ.get('SECRET_KEY', 'dev-key-change-in-production'),
        DEBUG=debug_flag,                                # <— dùng bool chuẩn
        SEND_FILE_MAX_AGE_DEFAULT=0 if debug_flag else 31536000,
        MAX_CONTENT_LENGTH=16 * 1024 * 1024,
        JSON_SORT_KEYS=False,
        JSONIFY_PRETTYPRINT_REGULAR=False,
        PREFERRED_URL_SCHEME="https",
        # BẬT auto-reload template khi debug
        TEMPLATES_AUTO_RELOAD=True if debug_flag else False,
        EXPLAIN_TEMPLATE_LOADING=True if debug_flag else False,
    )

    # Không còn dựa vào FLASK_ENV (đã deprecated)
    def is_dev() -> bool:
        # app.debug sẽ phản ánh DEBUG, nhưng vẫn kiểm tra env để chắc ăn
        return bool(app.debug or _asbool(os.getenv("FLASK_DEBUG")))

    if is_dev():
        try:
            app.jinja_env.auto_reload = True
            app.jinja_env.cache = {}  # tắt cache template
        except Exception:
            pass
        print("🔧 DEVELOPMENT mode: template auto-reload + no-cache everywhere")

    # ========== STATIC FINGERPRINT ==========
    def _asset_fingerprint(path: Path, chunk_size: int = 1 << 16) -> str:
        h = hashlib.sha1()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                h.update(chunk)
        return h.hexdigest()[:10]

    def _url_for_with_fingerprint(endpoint, **values):
        if endpoint == 'static':
            filename = values.get('filename', '')
            if filename:
                fp = Path(app.static_folder) / filename
                if fp.exists():
                    try:
                        if is_dev():
                            # Dev: đổi mỗi request để chắc chắn browser không giữ cache
                            values['v'] = int(time.time() * 1000)
                        else:
                            # Prod: theo content hash (chỉ đổi khi file đổi)
                            values['v'] = _asset_fingerprint(fp)
                    except Exception:
                        values['v'] = int(fp.stat().st_mtime * 1000)
        return _url_for(endpoint, **values)

    app.jinja_env.globals['url_for'] = _url_for_with_fingerprint

    # ========== CACHE CONTROL ==========
    @app.after_request
    def set_response_headers(response):
        path = request.path
        if is_dev():
            # DEV: triệt để no-cache
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            response.headers['Surrogate-Control'] = 'no-store'
        else:
            if path.startswith('/static/'):
                response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
            else:
                response.headers['Cache-Control'] = 'public, max-age=300'
        return response

    # Reverse proxy + gzip
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
    Compress(app)

    # ======= HEALTH =======
    @app.get('/health')
    def health_check():
        return jsonify({
            'status': 'healthy',
            'version': '1.0.0',
            'environment': 'development' if is_dev() else 'production',
            'debug': bool(app.debug),
            'cache_mode': 'disabled' if is_dev() else 'enabled'
        }), 200

    @app.get('/ping')
    def ping():
        return 'pong', 200

    # Debug endpoints giữ nguyên nếu bạn muốn

    # Initialize app
    register_blueprints(app)
    register_error_handlers(app)
    migrate()
    init_auth_storage()

    return app