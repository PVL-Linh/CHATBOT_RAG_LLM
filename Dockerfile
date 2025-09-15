# FROM python:3.11-slim

# ENV PYTHONDONTWRITEBYTECODE=1 \
#     PYTHONUNBUFFERED=1 \
#     PIP_NO_CACHE_DIR=1 \
#     PIP_ROOT_USER_ACTION=ignore \
#     REPO_ROOT=/app \
#     PYTHONPATH=/app/src \
#     HF_HUB_ENABLE_HF_TRANSFER=1 \
#     TOKENIZERS_PARALLELISM=true \
#     EMBED_DEVICE=cpu \
#     EMBED_AUTO_DOWNGRADE=1 \
#     DATA_DIR=/var/lib/tiximax/data \
#     EMBED_MODEL_ID=intfloat/multilingual-e5-base \
#     EMBED_MODEL_PATH=/var/lib/tiximax/models/local_multilingual_e5_base \
#     SQLITE_PATH=/var/lib/tiximax/data/users.db \
#     USERS_DB=/var/lib/tiximax/data/users.db \
#     CHAT_DB_PATH=/var/lib/tiximax/data/app.db \
#     HF_HOME=/var/lib/tiximax/models \
#     TRANSFORMERS_CACHE=/var/lib/tiximax/models/cache

# WORKDIR /app

# RUN apt-get update && apt-get install -y --no-install-recommends \
#     build-essential git curl libgomp1 ffmpeg \
#  && rm -rf /var/lib/apt/lists/*

# COPY requirements.txt .
# RUN python -m pip install --upgrade pip \
#  && pip install --no-cache-dir -r requirements.txt \
#  && pip install --no-cache-dir gunicorn

# COPY . .

# EXPOSE 10000

# # Tạo thư mục cần thiết rồi chạy gunicorn (gthread). Mặc định 1 worker cho SQLite.
# CMD sh -lc '\
#   mkdir -p "$DATA_DIR" "$HF_HOME" "$TRANSFORMERS_CACHE" && \
#   echo "[boot] DATA_DIR=$DATA_DIR SQLITE_PATH=$SQLITE_PATH HF_HOME=$HF_HOME" && \
#   gunicorn -w ${WEB_CONCURRENCY:-1} -k gthread --threads ${WEB_THREADS:-8} \
#     --timeout ${GUNICORN_TIMEOUT:-120} -b 0.0.0.0:${PORT:-10000} \
#     "app.app_factory:create_app()" --access-logfile - --error-logfile - \
# '

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore \
    REPO_ROOT=/app \
    PYTHONPATH=/app/src \
    HF_HUB_ENABLE_HF_TRANSFER=1 \
    TOKENIZERS_PARALLELISM=true \
    EMBED_DEVICE=cpu \
    EMBED_AUTO_DOWNGRADE=1 \
    DATA_DIR=/var/lib/tiximax/Data_app \
    EMBED_MODEL_ID=intfloat/multilingual-e5-base \
    EMBED_MODEL_PATH=/var/lib/tiximax/models/local_multilingual_e5_base \
    USERS_DB=/var/lib/tiximax/Data_app/users.db \
    SQLITE_PATH=/var/lib/tiximax/Data_app/users.db \
    CHAT_DB_PATH=/var/lib/tiximax/Data_app/chat.db \
    HF_HOME=/var/lib/tiximax/models \
    TRANSFORMERS_CACHE=/var/lib/tiximax/models/cache \
    PORT=10000

WORKDIR /app

# OS deps (pdf2image/pytesseract/ffmpeg, build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential git curl libgomp1 ffmpeg poppler-utils tesseract-ocr \
 && rm -rf /var/lib/apt/lists/*

# Chỉ copy file cần thiết để cache layer install
COPY requirements.txt constraints.txt ./

# 1) Cài pip + PyTorch CPU trước để tránh kéo sai wheel
RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu \
      torch==2.3.1 torchvision==0.18.1 torchaudio==2.3.1

# 2) Cài deps còn lại + gunicorn
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt && \
    pip install --no-cache-dir gunicorn

# Copy mã nguồn (không copy .env nhờ .dockerignore)
COPY src ./src
COPY wsgi.py gunicorn.conf.py ./

EXPOSE 10000

# Tạo thư mục dữ liệu & chạy gunicorn
CMD ["bash","-lc","mkdir -p \"$DATA_DIR\" \"$HF_HOME\" \"$TRANSFORMERS_CACHE\" && \
  echo \"[boot] DATA_DIR=$DATA_DIR SQLITE_PATH=$SQLITE_PATH HF_HOME=$HF_HOME\" && \
  exec gunicorn -w ${WEB_CONCURRENCY:-1} -k gthread --threads ${WEB_THREADS:-8} \
    --timeout ${GUNICORN_TIMEOUT:-120} -b 0.0.0.0:${PORT:-10000} \
    wsgi:app --access-logfile - --error-logfile -"]
