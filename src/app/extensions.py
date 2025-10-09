import os
import threading
from app.config.paths import CHAT_LOGS_DIR
from app.config.settings import ChatConfig

# Global configuration constants
LLM_SEM = ChatConfig.LLM_SEM
MAX_HISTORY = ChatConfig.MAX_HISTORY
LOCAL_TZ_NAME = ChatConfig.LOCAL_TZ_NAME

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