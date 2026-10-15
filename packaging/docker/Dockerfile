# Server target. Build from the repo root:
#   docker build -f packaging/docker/Dockerfile -t money-webapp .
# Config comes from the environment (compose env_file); .env is dockerignored. The same
# image runs the web server (default) and the jobs process (`python manage.py run_jobs`).
FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml README.md manage.py ./
COPY app ./app
COPY config ./config
COPY packaging/docker/entrypoint.sh /app/entrypoint.sh
RUN pip install --no-cache-dir . \
 && chmod +x /app/entrypoint.sh \
 && SESSION_SECRET=build-only-not-a-real-secret python manage.py collectstatic --noinput -v 0
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)"
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "-c", "config/gunicorn.conf.py", "config.wsgi"]
