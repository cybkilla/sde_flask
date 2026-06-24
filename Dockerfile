# Dockerfile — SDE Flask (Stock Decision Engine)
FROM python:3.12-slim

# Dépendances système pour matplotlib (rendu non-interactif) et lxml
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libfreetype6-dev \
        libpng-dev \
        pkg-config \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1. Installer les dépendances Python en premier (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2. Copier le code source
COPY . .

# 3. Matplotlib en mode non-interactif (pas d'affichage graphique)
ENV MPLBACKEND=Agg

# 4. Port exposé
EXPOSE 5000

# 5. Démarrage via gunicorn
#    L'application Flask est créée par la factory create_app() dans run_flask.py
CMD ["gunicorn", "--config", "gunicorn.conf.py", "run_flask:app"]
