# gunicorn.conf.py (root)
import os, multiprocessing

bind = ":" + os.environ.get("PORT", "10000")
workers = int(os.environ.get("WEB_CONCURRENCY", str(max(2, multiprocessing.cpu_count() * 2 + 1))))
threads = int(os.environ.get("WEB_THREADS", "8"))
timeout = int(os.environ.get("TIMEOUT", "180"))
keepalive = 75
worker_class = "gthread"
preload_app = True

loglevel = os.environ.get("LOGLEVEL", "info")
accesslog = "-"   # stdout
errorlog  = "-"   # stderr
