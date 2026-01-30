# config.py
import os, datetime as dt
from dotenv import load_dotenv
load_dotenv()

BASE_API_URL = os.environ.get("BASE_API_URL", "https://get-api-supabase-tiximax-seven.vercel.app").rstrip("/")
API_KEY = os.environ.get("API_KEY", "")
DEFAULT_PAGE_SIZE = int(os.environ.get("DEFAULT_PAGE_SIZE", "500"))

# múi giờ Việt Nam
TZ_OFFSET_HOURS = int(os.environ.get("TZ_OFFSET_HOURS", "7"))
VN_TZ = dt.timezone(dt.timedelta(hours=TZ_OFFSET_HOURS))

# định dạng tiền
CURRENCY = (os.environ.get("CURRENCY", "VND") or "VND").upper()

# Redis (nếu có dùng redis_cache.py)
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", "300"))
