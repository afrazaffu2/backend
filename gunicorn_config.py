# Gunicorn Configuration for Event Management Backend
# This file configures Gunicorn for production deployment

# Server socket
bind = "0.0.0.0:8000"
backlog = 2048

# Worker processes
workers = 3
worker_class = "sync"
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 100
timeout = 30
keepalive = 2

# Restart workers after this many requests, to help prevent memory leaks
max_requests = 1000
max_requests_jitter = 100

# Logging
accesslog = "/var/log/gunicorn/access.log"
errorlog = "/var/log/gunicorn/error.log"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

# Process naming
proc_name = "event-backend"

# Server mechanics
daemon = False
pidfile = "/var/run/gunicorn/event-backend.pid"
user = "www-data"
group = "www-data"
tmp_upload_dir = None

# SSL (uncomment if using SSL)
# keyfile = "/path/to/keyfile"
# certfile = "/path/to/certfile"

# Preload app for better performance
preload_app = True

# Worker timeout
graceful_timeout = 30

# Server socket
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190 