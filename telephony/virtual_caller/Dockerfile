FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY fastagi_server.py .
COPY scenarios ./scenarios

# Порт, который слушает наш FastAGI-сервер — на него Asterisk делает
# TCP-подключение по команде AGI(agi://virtual-caller:4573/...)
EXPOSE 4573

ENV LISTEN_PORT=4573
ENV SESSIONS_LOG_PATH=/data/sessions.log

CMD ["python", "fastagi_server.py"]
