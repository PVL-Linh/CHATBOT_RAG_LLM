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
    PORT=10000 \
    EMBED_DEVICE=cpu \
    EMBED_AUTO_DOWNGRADE=1

WORKDIR /app

# libs hệ thống (faiss cần libgomp1; ffmpeg nếu có STT)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential git curl libgomp1 ffmpeg \
 && rm -rf /var/lib/apt/lists/*

# Cài deps Python
COPY requirements.txt .
RUN python -m pip install --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir gunicorn

# Copy mã nguồn
COPY . .

# (tuỳ chọn) preload model lúc build: set ARG EMBED_PRELOAD=1
ARG EMBED_PRELOAD=0
ARG EMBED_MODEL_ID=intfloat/multilingual-e5-base
ARG EMBED_MODEL_PATH=/opt/models/local_multilingual_e5_base
ENV EMBED_MODEL_ID=${EMBED_MODEL_ID} \
    EMBED_MODEL_PATH=${EMBED_MODEL_PATH}

RUN if [ "$EMBED_PRELOAD" = "1" ]; then \
      python -c "import os; os.environ.setdefault('REPO_ROOT','/app'); \
                 from app.Model_LLM.model_llm import ensure_local_hf_model; \
                 ensure_local_hf_model(os.environ.get('EMBED_MODEL_PATH','/opt/models/local_multilingual_e5_base'), \
                                       os.environ.get('EMBED_MODEL_ID','intfloat/multilingual-e5-base'))"; \
    fi

EXPOSE 10000
CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
