FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

RUN groupadd --system --gid 10001 shortpilot \
    && useradd --system --uid 10001 --gid shortpilot --home-dir /app shortpilot

COPY --chown=shortpilot:shortpilot . .
RUN mkdir -p /app/storage/tmp /app/logs /app/db \
    && chown -R shortpilot:shortpilot /app/storage /app/logs /app/db

USER shortpilot
EXPOSE 8000 8420
CMD ["python", "main.py"]
