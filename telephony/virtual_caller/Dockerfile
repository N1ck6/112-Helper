FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY caller ./caller

# 4573 — FastAGI: Asterisk подключается по AGI(agi://virtual-caller:4573/<scenario_id>)
# 8092 — HTTP API звонков для Backend (telephony/API.md)
EXPOSE 4573 8092

ENV PYTHONUNBUFFERED=1 \
    AGI_PORT=4573 \
    API_PORT=8092 \
    SESSIONS_LOG_PATH=/data/sessions.log

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import socket; socket.create_connection(('127.0.0.1', 4573), 3).close(); socket.create_connection(('127.0.0.1', 8092), 3).close()"

CMD ["python", "-m", "caller"]
