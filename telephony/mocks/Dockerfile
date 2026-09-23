FROM python:3.11-slim

WORKDIR /app
COPY mock_services.py .
COPY scenarios ./scenarios

# Заглушки ML (/ml) и Backend (/backend) на одном порту — см. mock_services.py
EXPOSE 8093
ENV PYTHONUNBUFFERED=1 LISTEN_PORT=8093

HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8093/health', timeout=3).status == 200 else 1)"

CMD ["python", "mock_services.py"]
