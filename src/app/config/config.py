import os
from datetime import timedelta

class Config:
    SECRET_KEY = os.environ.get("34b648919ffb98dbfd185b1e429572b0e448f9232345685a9442f7e59af147cb", "change-me-in-prod")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)
    TEMPLATES_AUTO_RELOAD = True