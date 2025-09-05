# wsgi.py (root) – entrypoint cho Gunicorn
import os

# Bảo đảm import được code trong src/
os.environ.setdefault("REPO_ROOT", "/app")
os.environ.setdefault("PYTHONPATH", "/app/src")

# Ưu tiên app factory nếu bạn có create_app()
try:
    from src.app.app_factory import create_app  # src/app/app_factory.py (nếu có)
    app = create_app()
except Exception:
    # Fallback: app = Flask(...) nằm trong src/app/app.py
    from importlib import import_module
    mod = import_module("app.app")  # src/app/app.py
    app = getattr(mod, "app", None)
    if app is None:
        raise RuntimeError("Không tìm thấy Flask app. Cần create_app() hoặc app = Flask(__name__).")
