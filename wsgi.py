# # wsgi.py (root) – entrypoint cho Gunicorn
# import os

# # Bảo đảm import được code trong src/
# os.environ.setdefault("REPO_ROOT", "/app")
# os.environ.setdefault("PYTHONPATH", "/app/src")

# # Ưu tiên app factory nếu bạn có create_app()
# try:
#     from src.app.app_factory import create_app  # src/app/app_factory.py (nếu có)
#     app = create_app()
# except Exception:
#     # Fallback: app = Flask(...) nằm trong src/app/app.py
#     from importlib import import_module
#     mod = import_module("app.app")  # src/app/app.py
#     app = getattr(mod, "app", None)
#     if app is None:
#         raise RuntimeError("Không tìm thấy Flask app. Cần create_app() hoặc app = Flask(__name__).")


# import os, sys
# PROJECT_ROOT = "/home/linh/www/tiximax"
# SRC_DIR = f"{PROJECT_ROOT}/src"
# if SRC_DIR not in sys.path:
#     sys.path.insert(0, SRC_DIR)

# # Production => không tự load .env, dùng ENV từ UI
# os.environ.setdefault("RUN_ENV", "production")

from src.app.app_factory import create_app  # src/app/app_factory.py
app = create_app()              # alwaysdata cần biến tên 'application'


# wsgi.py
# try:
#     from src.app.app_factory import create_app
# except Exception:
#     from src.app import create_app
# app = create_app()
