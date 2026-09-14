FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NEXUS_DATA_DIR=/data \
    NEXUS_ACTION=run

WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY nexus/ ./nexus/
COPY tests/ ./tests/
COPY config.example.json ./
RUN python -m unittest discover -s tests -v

# The host must attach a durable volume at /data. No token or local state is copied.
STOPSIGNAL SIGTERM
CMD ["python", "-m", "nexus.hosted"]
