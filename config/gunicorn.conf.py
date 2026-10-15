"""gunicorn: one worker (the login rate limiter and the feed's single-run lock are
in-process state) with threads for concurrent page loads; a long timeout for a manual
Sync now or an ML retrain; logs to stdout for the container."""

bind = "0.0.0.0:8000"
workers = 1
worker_class = "gthread"
threads = 4
timeout = 120
accesslog = "-"
errorlog = "-"
