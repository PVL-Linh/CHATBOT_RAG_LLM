"""
Flask extensions initialization and global configuration
"""
import os
import threading
from dotenv import load_dotenv

load_dotenv()

# Global configuration constants
LLM_SEM = threading.Semaphore(int(os.environ.get("SEM_LLM", "24")))
MAX_HISTORY = int(os.environ.get("MAX_HISTORY", "50"))
CHAT_LOGS_DIR = os.environ.get("CHAT_LOGS_DIR", "./src/app/Data_app/chat_logs")
LOCAL_TZ_NAME = os.environ.get("LOCAL_TZ", "Asia/Ho_Chi_Minh")

def init_extensions(app):
    """Initialize Flask extensions and app configuration"""
    app.config.setdefault('SEND_FILE_MAX_AGE_DEFAULT', 31536000)
    
    # Initialize compression if available
    try:
        from flask_compress import Compress
        Compress(app)
    except ImportError:
        app.logger.warning("flask_compress not available, skipping compression")
    except Exception as e:
        app.logger.warning(f"Failed to initialize compression: {e}")
    
    return app