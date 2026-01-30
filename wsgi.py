import sys
import os

# Add src directory to Python path for local development
# (In Docker/Render, PYTHONPATH is already set to /app/src)
src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from app.app_factory import create_app
app = create_app()
