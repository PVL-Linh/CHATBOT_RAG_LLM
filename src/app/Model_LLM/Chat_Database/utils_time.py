
from datetime import datetime
from dateutil.relativedelta import relativedelta
try:
    from .config_supabase import VN_TZ as _VN_TZ
except Exception:
    import pytz
    _VN_TZ = pytz.timezone("Asia/Ho_Chi_Minh")

def now_vn():
    return datetime.now(_VN_TZ)

def month_bounds(dt=None):
    dt = dt or now_vn()
    start = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = start + relativedelta(months=1)
    return start, end

def prev_month_bounds(dt=None):
    this_start, _ = month_bounds(dt)
    prev_end = this_start
    prev_start = this_start - relativedelta(months=1)
    return prev_start, prev_end

def monthN_bounds(month:int, year:int):
    start = now_vn().replace(year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0)
    end = start + relativedelta(months=1)
    return start, end

def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S%z")[:-2] + ":" + dt.strftime("%z")[-2:]
