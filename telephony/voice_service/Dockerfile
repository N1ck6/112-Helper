FROM python:3.11-slim

# ffmpeg — ресемплинг TTS 22050 -> 8000 Гц для Asterisk.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY voice ./voice
COPY download_models.py .

# Рантайм без интернета: модели только из /models (см. download_models.py).
ENV HF_HUB_OFFLINE=1 \
    PYTHONUNBUFFERED=1 \
    MODELS_DIR=/models \
    LISTEN_PORT=8091

EXPOSE 8091

HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8091/health', timeout=4).status == 200 else 1)"

CMD ["python", "-m", "voice"]
