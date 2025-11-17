FROM python:3.11-slim-bookworm

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
    VECTORSTORE_ROOT=/app/src/app/vectorstore \
    EMBED_MODEL_ID=intfloat/multilingual-e5-large \
    EMBED_MODEL_PATH=/var/lib/tiximax/models/local_multilingual_e5_large \
    USERS_DB=/var/lib/tiximax/Data_app/users.db \
    SQLITE_PATH=/var/lib/tiximax/Data_app/users.db \
    CHAT_DB_PATH=/var/lib/tiximax/Data_app/chat.db \
    HF_HOME=/var/lib/tiximax/models \
    TRANSFORMERS_CACHE=/var/lib/tiximax/models/cache \
    PORT=10000 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

RUN set -eux; \

  printf '%s\n' \
    'Acquire::Retries "5";' \
    'Acquire::http::Timeout "30";' \
    'Acquire::https::Timeout "30";' \
    'Acquire::http::No-Cache "true";' \
    'Acquire::https::No-Cache "true";' \
    'Acquire::http::Pipeline-Depth "0";' \
    'Acquire::ForceIPv4 "true";' \
    > /etc/apt/apt.conf.d/80-network-tuning; \
  DEB_MAIN_1="https://deb.debian.org/debian"; \
  DEB_MAIN_2="https://ftp.hk.debian.org/debian"; \
  DEB_MAIN_3="https://mirror.sjtu.edu.cn/debian"; \
  DEB_SEC="https://security.debian.org/debian-security"; \
  install_with_mirror() { \
    local MAIN="$1"; \
    echo ">>> Using main mirror: $MAIN"; \
    printf '%s\n' \
      "deb $MAIN bookworm main contrib non-free non-free-firmware" \
      "deb $DEB_SEC bookworm-security main contrib non-free non-free-firmware" \
      "deb $MAIN bookworm-updates main contrib non-free non-free-firmware" \
      > /etc/apt/sources.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates gnupg; \
    update-ca-certificates; \
    for i in 1 2 3; do \
      if apt-get update && \
         apt-get install -y --no-install-recommends \
           build-essential git curl libgomp1 ffmpeg poppler-utils \
           tesseract-ocr tesseract-ocr-eng tesseract-ocr-osd; \
      then \
        return 0; \
      fi; \
      echo "APT attempt $i failed on $MAIN; retrying in 5s..."; sleep 5; \
    done; \
    return 1; \
  }; \
  if ! install_with_mirror "$DEB_MAIN_1"; then \
    echo "Primary mirror failed, trying HK mirror..."; \
    if ! install_with_mirror "$DEB_MAIN_2"; then \
      echo "HK mirror failed, trying SJTU mirror..."; \
      install_with_mirror "$DEB_MAIN_3"; \
    fi; \
  fi; \
  command -v tesseract >/dev/null 2>&1 || { echo "tesseract not installed"; exit 1; }; \
  rm -rf /var/lib/apt/lists/*



COPY requirements.txt constraints.txt ./
RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu \
      torch==2.3.1 torchvision==0.18.1 torchaudio==2.3.1 && \
    pip install --no-cache-dir -r requirements.txt -c constraints.txt && \
    pip install --no-cache-dir gunicorn

COPY src ./src
COPY wsgi.py gunicorn.conf.py ./

EXPOSE 10000

CMD ["bash","-lc","mkdir -p \"$DATA_DIR\" \"$HF_HOME\" \"$TRANSFORMERS_CACHE\" && \
  echo \"[boot] DATA_DIR=$DATA_DIR SQLITE_PATH=$SQLITE_PATH HF_HOME=$HF_HOME\" && \
  exec gunicorn -w ${WEB_CONCURRENCY:-1} -k gthread --threads ${WEB_THREADS:-8} \
    --timeout ${GUNICORN_TIMEOUT:-120} -b 0.0.0.0:${PORT:-10000} \
    wsgi:app --access-logfile - --error-logfile -"]
