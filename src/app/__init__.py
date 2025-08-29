import os
from flask import Flask
from dotenv import load_dotenv
from flask_compress import Compress

def create_app() -> Flask:
    # Load env early
    load_dotenv()

    # Keep template/static roots identical to your current layout
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object('config.Config')
    app.config.setdefault('SEND_FILE_MAX_AGE_DEFAULT', 31536000)

    # Optional compression (same as before)
    Compress(app)

    # Register blueprints + error handlers
    from routes import register_blueprints, register_error_handlers
    register_blueprints(app)
    register_error_handlers(app)

    return app