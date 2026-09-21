FROM python:3.11-slim

# ffmpeg нужен именно здесь (не в Asterisk-контейнере) — конвертация
# WAV->MP3 логически не относится к SIP/телефонии, держим её при
# инструменте, который её выполняет.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY convert_to_mp3.py list_recordings.py serve_recordings.py ./

EXPOSE 8090

# По умолчанию контейнер просто раздаёт записи по HTTP (playback).
# Конвертацию и список запускайте вручную через `docker compose exec`
# (см. README этапа 4) — это осознанно ручные/по требованию операции.
CMD ["python", "serve_recordings.py"]
