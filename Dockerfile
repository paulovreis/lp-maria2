FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/data \
    PORT=5926

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
CMD ["sh", "-c", "exec gunicorn --preload -w 2 -b 0.0.0.0:${PORT} --access-logfile - --forwarded-allow-ips='*' app:app"]
