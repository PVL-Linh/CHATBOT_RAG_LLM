FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libglib2.0-0 libgl1 ffmpeg \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app
RUN useradd -m appuser && mkdir -p /app/instance && chown -R appuser:appuser /app
USER appuser
ENV PYTHONUNBUFFERED=1 TZ=Asia/Ho_Chi_Minh
# app của bạn là app.py với biến Flask tên 'app'
ENV APP_MODULE=app:app
EXPOSE 8000
CMD ["sh","-c","gunicorn -w 2 -k gthread -b 0.0.0.0:8000 ${APP_MODULE} --timeout 180"]
