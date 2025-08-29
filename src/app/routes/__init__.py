from flask import Flask


def register_blueprints(app: Flask) -> None:
    from .auth import bp as auth_bp
    from .pages import bp as pages_bp
    from .chat import bp as chat_bp
    from .marketing import bp as marketing_bp
    from .saves import bp as saves_bp
    from .history_api import bp as history_bp
    from .pdf_to_txt import bp as pdf_bp
    from .transcribe import bp as stt_bp
    from .errors import init_error_handlers as _eh # noqa


    app.register_blueprint(auth_bp)
    app.register_blueprint(pages_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(marketing_bp)
    app.register_blueprint(saves_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(pdf_bp)
    app.register_blueprint(stt_bp)




def register_error_handlers(app: Flask) -> None:
    from .errors import init_error_handlers
    init_error_handlers(app)