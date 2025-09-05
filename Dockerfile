# # Dockerfile (root)
# FROM python:3.11-slim

# ENV PYTHONDONTWRITEBYTECODE=1 \
#     PYTHONUNBUFFERED=1 \
#     PIP_NO_CACHE_DIR=1 \
#     PIP_ROOT_USER_ACTION=ignore \
#     REPO_ROOT=/app \
#     PYTHONPATH=/app/src \
#     HF_HUB_ENABLE_HF_TRANSFER=1 \
#     TOKENIZERS_PARALLELISM=true \
#     PORT=10000 \
#     EMBED_DEVICE=cpu \
#     EMBED_AUTO_DOWNGRADE=1

# WORKDIR /app

# # libs hệ thống (faiss cần libgomp1; ffmpeg nếu có STT)
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     build-essential git curl libgomp1 ffmpeg \
#  && rm -rf /var/lib/apt/lists/*

# # Cài deps Python
# COPY requirements.txt .
# RUN python -m pip install --upgrade pip \
#  && pip install --no-cache-dir -r requirements.txt \
#  && pip install --no-cache-dir gunicorn

# # Copy mã nguồn
# COPY . .

# # (tuỳ chọn) preload model lúc build: set ARG EMBED_PRELOAD=1
# ARG EMBED_PRELOAD=0
# ARG EMBED_MODEL_ID=intfloat/multilingual-e5-base
# ARG EMBED_MODEL_PATH=/opt/models/local_multilingual_e5_base
# ENV EMBED_MODEL_ID=${EMBED_MODEL_ID} \
#     EMBED_MODEL_PATH=${EMBED_MODEL_PATH}

# RUN if [ "$EMBED_PRELOAD" = "1" ]; then \
#       python -c "import os; os.environ.setdefault('REPO_ROOT','/app'); \
#                  from app.Model_LLM.model_llm import ensure_local_hf_model; \
#                  ensure_local_hf_model(os.environ.get('EMBED_MODEL_PATH','/opt/models/local_multilingual_e5_base'), \
#                                        os.environ.get('EMBED_MODEL_ID','intfloat/multilingual-e5-base'))"; \
#     fi

# EXPOSE 10000
# CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
# Dockerfile (root)
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
    DATA_DIR=/var/lib/tiximax/data \
    EMBED_MODEL_ID=intfloat/multilingual-e5-base \
    EMBED_MODEL_PATH=/var/lib/tiximax/models/local_multilingual_e5_base \
    SQLITE_PATH=/var/lib/tiximax/data/users.db \
    USERS_DB=/var/lib/tiximax/data/users.db \
    CHAT_DB_PATH=/var/lib/tiximax/data/app.db \
    HF_HOME=/var/lib/tiximax/models \
    TRANSFORMERS_CACHE=/var/lib/tiximax/models/cache

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential git curl libgomp1 ffmpeg \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m pip install --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir gunicorn

COPY . .

EXPOSE 10000

# Tạo thư mục cần thiết rồi chạy gunicorn (gthread). Mặc định 1 worker cho SQLite.
CMD sh -lc '\
  mkdir -p "$DATA_DIR" "$HF_HOME" "$TRANSFORMERS_CACHE" && \
  echo "[boot] DATA_DIR=$DATA_DIR SQLITE_PATH=$SQLITE_PATH HF_HOME=$HF_HOME" && \
  gunicorn -w ${WEB_CONCURRENCY:-1} -k gthread --threads ${WEB_THREADS:-8} \
    --timeout ${GUNICORN_TIMEOUT:-120} -b 0.0.0.0:${PORT:-10000} \
    "app.app_factory:create_app()" --access-logfile - --error-logfile - \
'
