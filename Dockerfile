# Backend image: Flask app served by gunicorn (processes x threads).
# Build:  docker build -t ecode-backend .      (normally started through docker-compose.yml)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Shared libraries needed by opencv-python
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first: this layer is rebuilt only when requirements.txt changes
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY config.py run.py ./
COPY app ./app
COPY migrations ./migrations

# Do not run as root
RUN useradd --create-home --uid 10001 ecode
USER ecode

EXPOSE 5000

# WEB_WORKERS processes x WEB_THREADS threads. The decoding libraries release the GIL, so threads work in
# parallel inside a process; several processes also share nothing, which keeps latency steady under load.
# Workers are recycled after N requests to cap memory growth.
CMD ["sh", "-c", "exec gunicorn run:app --worker-class gthread --workers ${WEB_WORKERS:-2} --threads ${WEB_THREADS:-4} --bind 0.0.0.0:5000 --timeout 60 --max-requests 5000 --max-requests-jitter 500 --access-logfile -"]

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=2)"
