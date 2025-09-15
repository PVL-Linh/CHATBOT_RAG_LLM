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


import os
from flask import Flask, jsonify
from dotenv import load_dotenv
from flask_compress import Compress
from app.routes import register_blueprints, register_error_handlers
from werkzeug.middleware.proxy_fix import ProxyFix
from app.tools.migrate_users_csv_to_sqlite import migrate
from app.Login.login_required import init_auth_storage


def create_app() -> Flask:
    # Load env early
    load_dotenv()

    # Keep template/static roots identical to your current layout
    app = Flask(__name__, template_folder="templates", static_folder="static")
    
    # Production configuration
    app.config.update(
        SECRET_KEY=os.environ.get('SECRET_KEY', 'dev-key-change-in-production'),
        DEBUG=os.environ.get('FLASK_DEBUG', 'False').lower() == 'true',
        SEND_FILE_MAX_AGE_DEFAULT=31536000,  # 1 year cache
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