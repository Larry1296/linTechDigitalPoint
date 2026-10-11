# The Django app (API, platform admin, M-Pesa callbacks), run by Gunicorn. Built from the repository root:
#   docker build -f deploy/server.Dockerfile .
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 app

WORKDIR /app
COPY server/requirements.txt .
RUN pip install -r requirements.txt

COPY server/ .
COPY deploy/gunicorn.conf.py deploy/entrypoint.sh /app/deploy/
# The admin's static files are collected into the image (settings need placeholder values to load at build time).
RUN SECRET_KEY=build DB_NAME=build DB_USER=build DB_PASSWORD=build python manage.py collectstatic --noinput \
    && mkdir -p /app/media && chown -R app:app /app/media && chmod +x /app/deploy/entrypoint.sh

USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"
ENTRYPOINT ["/app/deploy/entrypoint.sh"]
CMD ["gunicorn", "-c", "/app/deploy/gunicorn.conf.py", "config.wsgi:application"]
