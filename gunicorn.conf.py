# gunicorn.conf.py — configuration production
import multiprocessing

# Bind
bind    = "0.0.0.0:5000"

# Render free tier = 512 Mo RAM. Un seul worker (sync) suffit pour ce trafic.
# Chaque worker charge pandas + matplotlib + yfinance ≈ 300 Mo ;
# 2+ workers dépassent la limite et provoquent un OOM restart.
workers = 1

# Redémarre le worker après N requêtes pour libérer la mémoire accumulée
# (DataFrames pandas, figures matplotlib non collectées, etc.)
max_requests        = 200
max_requests_jitter = 20

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
