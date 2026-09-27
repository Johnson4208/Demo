# syntax=docker/dockerfile:1.7
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SOLVAI_DATA_DIR=/data \
    SOLVAI_HOST=0.0.0.0 \
    SOLVAI_PORT=5000 \
    OCR_ENABLED=1 \
    OCR_LANG=vie+eng

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-vie \
        libgomp1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.in requirements.txt requirements.lock ./
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --require-hashes -r requirements.lock

COPY . .

# /data is supplied by the Docker volume. On first start the application
# migrates the bundled legacy database/reports into the persistent volume.
RUN mkdir -p /data

EXPOSE 5000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import os,urllib.request; port=os.getenv('PORT',os.getenv('SOLVAI_PORT','5000')); urllib.request.urlopen(f'http://127.0.0.1:{port}/api/ready',timeout=4).read()" || exit 1

CMD ["sh", "-c", "exec gunicorn --no-control-socket --bind 0.0.0.0:${PORT:-${SOLVAI_PORT:-5000}} --workers ${WEB_CONCURRENCY:-1} --threads ${SOLVAI_THREADS:-8} --timeout ${SOLVAI_REQUEST_TIMEOUT:-180} --graceful-timeout 30 --max-requests 1000 --max-requests-jitter 100 --access-logfile - --error-logfile - app:app"]
