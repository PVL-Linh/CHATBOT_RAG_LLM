# ---- Base image
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Ho_Chi_Minh

# ---- System deps (tuỳ nhu cầu code: ffmpeg, poppler, tesseract cho PDF/Media)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc \
    ffmpeg poppler-utils tesseract-ocr \
    libmagic1 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ---- Python deps
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt \
    || (pip install --upgrade pip && pip install gunicorn && true)

# ---- App source
# Chỉ copy mã nguồn chính; model/venv/logs mount qua volumes để nhẹ image
COPY src ./src
COPY gunicorn.conf.py ./

# (Tuỳ chọn) nếu bạn có file config.py/.env cần trong image, hãy COPY thêm

EXPOSE 8000

# ---- Run with Gunicorn (application factory)
CMD ["gunicorn", "--factory", "-c", "gunicorn.conf.py", "src.app:create_app"]
