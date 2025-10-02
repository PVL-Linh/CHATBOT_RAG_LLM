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
import os
from flask import Flask, jsonify
from dotenv import load_dotenv
from flask_compress import Compress
from app.routes import register_blueprints, register_error_handlers
from werkzeug.middleware.proxy_fix import ProxyFix
from app.tools.migrate_users_csv_to_sqlite import migrate
from app.Login.login_required import init_auth_storage
# from app.routes.hr_rag import bp_hr_rag

def create_app() -> Flask:
    # Load env early
    load_dotenv()

    # Keep template/static roots identical to your current layout
    app = Flask(__name__, template_folder="templates", static_folder="static")
    # app.register_blueprint(bp_hr_rag)
    # Production configuration
    app.config.update(
        SECRET_KEY=os.environ.get('SECRET_KEY', 'dev-key-change-in-production'),
        DEBUG=os.environ.get('FLASK_DEBUG', 'False').lower() == 'true',
        SEND_FILE_MAX_AGE_DEFAULT=0,  # 1 year cache
        MAX_CONTENT_LENGTH=16 * 1024 * 1024,  # 16MB max file size
        JSON_SORT_KEYS=False,
        JSONIFY_PRETTYPRINT_REGULAR=False,
        PREFERRED_URL_SCHEME="https",
    )
    
    # Try to load from your existing config.py if it exists
    try:
        app.config.from_object('app.config.Config')
    except (ImportError, AttributeError):
        print("⚠️  Warning: Could not load Config class, using defaults")
        pass  # Config file doesn't exist or Config class not found
    
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
    # Optional compression (same as before)
    Compress(app)

    # Health check endpoint for Docker and monitoring
    @app.route('/health')
    def health_check():
        return jsonify({
            'status': 'healthy',
            'version': '1.0.0',
            'environment': os.environ.get('FLASK_ENV', 'development'),
            'debug': app.config.get('DEBUG', False)
        }), 200

    # Ping endpoint for simple checks
    @app.route('/ping')
    def ping():
        return 'pong', 200

    # Register blueprints + error handlers (your existing code)
    register_blueprints(app)
    register_error_handlers(app)
    migrate()
    init_auth_storage()

    return app

# #APP FACTORY v3
# import os
# import hashlib
# import time
# from pathlib import Path
# from flask import Flask, jsonify, url_for as _url_for, request
# from dotenv import load_dotenv
# from flask_compress import Compress
# from werkzeug.middleware.proxy_fix import ProxyFix

# from app.routes import register_blueprints, register_error_handlers
# from app.tools.migrate_users_csv_to_sqlite import migrate
# from app.Login.login_required import init_auth_storage


# def create_app() -> Flask:
#     # Load env early
#     load_dotenv()

#     app = Flask(__name__, template_folder="templates", static_folder="static")

#     # Base config
#     app.config.update(
#         SECRET_KEY=os.environ.get('SECRET_KEY', 'dev-key-change-in-production'),
#         DEBUG=os.environ.get('FLASK_DEBUG', 'False').lower() == 'true',
#         SEND_FILE_MAX_AGE_DEFAULT=0,
#         MAX_CONTENT_LENGTH=16 * 1024 * 1024,
#         JSON_SORT_KEYS=False,
#         JSONIFY_PRETTYPRINT_REGULAR=False,
#         PREFERRED_URL_SCHEME="https",
#     )

#     # Load optional Config class
#     try:
#         app.config.from_object('app.config.Config')
#     except (ImportError, AttributeError):
#         print("⚠️  Warning: Could not load Config class, using defaults")

#     # Determine environment
#     is_dev = app.config.get('DEBUG', False) or os.environ.get('FLASK_ENV') == 'development'
    
#     if is_dev:
#         app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
#         app.config['TEMPLATES_AUTO_RELOAD'] = True
#         try:
#             app.jinja_env.auto_reload = True
#             app.jinja_env.cache = {}
#         except Exception:
#             pass
#         print("🔧 Running in DEVELOPMENT mode - cache disabled")

#     # ========== STATIC FINGERPRINT ==========
#     def _asset_fingerprint(path: Path, chunk_size: int = 1 << 16) -> str:
#         """Hash file content for cache busting."""
#         h = hashlib.sha1()
#         with path.open("rb") as f:
#             while True:
#                 chunk = f.read(chunk_size)
#                 if not chunk:
#                     break
#                 h.update(chunk)
#         return h.hexdigest()[:10]

#     def _url_for_with_fingerprint(endpoint, **values):
#         """Custom url_for with automatic cache busting."""
#         if endpoint == 'static':
#             filename = values.get('filename', '')
#             if filename:
#                 fp = Path(app.static_folder) / filename
#                 if fp.exists():
#                     try:
#                         if is_dev:
#                             # Dev: timestamp để force reload mỗi lần request
#                             values['v'] = int(time.time() * 1000)  # milliseconds
#                         else:
#                             # Prod: content hash (chỉ đổi khi file thay đổi)
#                             values['v'] = _asset_fingerprint(fp)
#                     except Exception as e:
#                         # Fallback to mtime
#                         values['v'] = int(fp.stat().st_mtime * 1000)
#         return _url_for(endpoint, **values)

#     # Override url_for globally
#     app.jinja_env.globals['url_for'] = _url_for_with_fingerprint

#     # ========== CACHE CONTROL ==========
#     @app.after_request
#     def set_response_headers(response):
#         """Set appropriate cache headers based on environment."""
#         path = request.path
        
#         if is_dev:
#             # DEV: No cache for everything
#             response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
#             response.headers['Pragma'] = 'no-cache'
#             response.headers['Expires'] = '0'
#             response.headers['Surrogate-Control'] = 'no-store'
#         else:
#             # PROD: Cache static files aggressively (we have fingerprints)
#             if path.startswith('/static/'):
#                 response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
#             else:
#                 # HTML pages: cache nhẹ
#                 response.headers['Cache-Control'] = 'public, max-age=300'  # 5 minutes
        
#         return response

#     # Reverse proxy fix + gzip
#     app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
#     Compress(app)

#     # ========== HEALTH CHECKS ==========
#     @app.get('/health')
#     def health_check():
#         return jsonify({
#             'status': 'healthy',
#             'version': '1.0.0',
#             'environment': os.environ.get('FLASK_ENV', 'production'),
#             'debug': app.config.get('DEBUG', False),
#             'cache_mode': 'disabled' if is_dev else 'enabled'
#         }), 200

#     @app.get('/ping')
#     def ping():
#         return 'pong', 200

#     # ========== DEBUG ENDPOINTS (chỉ cho dev) ==========
#     if is_dev:
#         @app.get("/__debug_static")
#         def __debug_static():
#             """Debug endpoint to check static file fingerprinting."""
#             rel = request.args.get("file", "js/main.js")
#             fp = Path(app.static_folder) / rel
#             exists = fp.exists()
#             info = {}
            
#             if exists:
#                 try:
#                     info = {
#                         "abs_path": str(fp.resolve()),
#                         "size": fp.stat().st_size,
#                         "mtime": fp.stat().st_mtime,
#                         "fingerprint": _asset_fingerprint(fp),
#                         "url": _url_for_with_fingerprint("static", filename=rel),
#                         "timestamp_version": int(time.time() * 1000)
#                     }
#                 except Exception as e:
#                     info = {"error": str(e)}
            
#             return jsonify({
#                 "exists": exists,
#                 "file": rel,
#                 "static_folder": app.static_folder,
#                 **info
#             })

#         @app.get("/__debug_cache")
#         def __debug_cache():
#             """Check current cache settings."""
#             return jsonify({
#                 "is_dev": is_dev,
#                 "DEBUG": app.config.get('DEBUG'),
#                 "FLASK_ENV": os.environ.get('FLASK_ENV'),
#                 "SEND_FILE_MAX_AGE_DEFAULT": app.config.get('SEND_FILE_MAX_AGE_DEFAULT'),
#                 "TEMPLATES_AUTO_RELOAD": app.config.get('TEMPLATES_AUTO_RELOAD'),
#                 "message": "Cache is DISABLED in dev mode" if is_dev else "Cache is ENABLED"
#             })

#     # Initialize app
#     register_blueprints(app)
#     register_error_handlers(app)
#     migrate()
#     init_auth_storage()

#     return app
