bind = "0.0.0.0:8000"
workers = 2          # VPS nhỏ: 2-3; tăng nếu RAM/CPU tốt
threads = 4
timeout = 180
graceful_timeout = 30
accesslog = "-"
errorlog = "-"
loglevel = "info"
# Nếu dùng app factory: chạy gunicorn kèm --factory (đã set trong CMD)
