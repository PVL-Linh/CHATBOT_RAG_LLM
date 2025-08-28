# FROM python:3.11-slim

# RUN apt-get update && apt-get install -y --no-install-recommends \
#     build-essential curl && rm -rf /var/lib/apt/lists/*

# WORKDIR /app

# # cài deps
# COPY requirements.txt .
# RUN pip install --no-cache-dir -r requirements.txt && pip install --no-cache-dir gunicorn

# # copy toàn repo (đã filter bằng .dockerignore)
# COPY . .

# # để import được "app.app_factory"
# ENV PYTHONUNBUFFERED=1 \
#     PYTHONPATH=/app \
#     PORT=8000 \
#     GUNICORN_WORKERS=3 \
#     GUNICORN_TIMEOUT=60

# EXPOSE 8000

# # CMD không cần nếu đã dùng command trong compose

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl build-essential \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir gunicorn

COPY . .

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PORT=8000 \
    GUNICORN_WORKERS=1 \
    GUNICORN_TIMEOUT=60

EXPOSE 8000
