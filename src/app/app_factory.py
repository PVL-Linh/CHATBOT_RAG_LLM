import os
from flask import Flask, jsonify
from flask_compress import Compress
from app.routes import register_blueprints, register_error_handlers
from werkzeug.middleware.proxy_fix import ProxyFix
from app.tools.migrate_users_csv_to_sqlite import migrate
from app.Login.login_required import init_auth_storage
from app.config.settings import AppConfig


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(AppConfig)
    
    try:
        app.config.from_object('app.config.Config')
    except (ImportError, AttributeError):
        print("⚠️  Warning: Could not load Config class, using defaults")
        pass
    
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
    Compress(app)

    @app.route('/health')
    def health_check():
        return jsonify({
            'status': 'healthy',
            'version': '1.0.0',
            'environment': os.environ.get('FLASK_ENV', 'development'),
            'debug': app.config.get('DEBUG', False)
        }), 200

    @app.route('/ping')
    def ping():
        return 'pong', 200

    register_blueprints(app)
    register_error_handlers(app)
    migrate()
    init_auth_storage()
    return app