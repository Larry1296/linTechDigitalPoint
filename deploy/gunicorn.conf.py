"""Gunicorn for the app container. Threads, not more processes: the assistant chats stream their answers for up to a
couple of minutes, and a thread waiting on the AI must not hold a whole worker process."""
import os

bind = "0.0.0.0:8000"
workers = int(os.environ.get("GUNICORN_WORKERS", "2"))
worker_class = "gthread"
threads = int(os.environ.get("GUNICORN_THREADS", "8"))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "180"))  # a long assistant answer, or a slow Safaricom reply
graceful_timeout = 30
keepalive = 5
max_requests = 2000  # restart workers now and then, so a slow leak never builds up
max_requests_jitter = 200
forwarded_allow_ips = "*"  # only Caddy, on the private Docker network, can reach this port
accesslog = "-"
errorlog = "-"
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(M)sms'
