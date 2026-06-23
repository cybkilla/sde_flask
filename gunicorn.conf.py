# gunicorn.conf.py — configuration production
import multiprocessing

# Bind
bind    = "0.0.0.0:5000"

# Workers : 2 workers sync suffisent (pipeline IO-bound ~15s)
# Augmenter avec prudence : chaque worker consomme ~300 Mo (yfinance + matplotlib)
workers = min(multiprocessing.cpu_count() * 2 + 1, 4)

# Timeout étendu car le pipeline prend 15-25 secondes
# (yfinance + news + LLM + graphiques matplotlib)
timeout         = 120
keepalive       = 5
graceful_timeout = 30

# Logging
accesslog = "-"   # stdout
errorlog  = "-"   # stderr
loglevel  = "info"

# Sécurité
limit_request_line       = 4094
limit_request_fields     = 100
limit_request_field_size = 8190
