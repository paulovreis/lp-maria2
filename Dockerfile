FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/data \
    PORT=8352

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

RUN useradd --create-home --uid 1000 appuser \
 && mkdir -p /app/data/uploads \
 && chown -R appuser:appuser /app/data
USER appuser

# --preload: o banco é criado uma única vez antes de subir os workers.
# Porta vem de $PORT (cada LP usa a sua, definida no docker-compose.yml).
CMD ["sh", "-c", "exec gunicorn --preload -k gthread -w ${WEB_WORKERS:-2} --threads ${WEB_THREADS:-8} --worker-tmp-dir /dev/shm --keep-alive 15 --timeout 30 --graceful-timeout 20 --max-requests 5000 --max-requests-jitter 500 -b 0.0.0.0:${PORT} --access-logfile - --forwarded-allow-ips=* app:app"]
