# SDE — Stock Decision Engine (Flask)

Application web d'aide à la décision boursière. Analyse n'importe quelle action cotée en combinant signaux techniques, données fondamentales, analyse médiatique et synthèse par IA.

## Fonctionnalités

- **Score global** (0–100) avec jauge visuelle et décomposition en 3 composantes pondérées
- **Recommandation** ACHETER / NEUTRE / VENDRE avec niveau de confiance
- **Signaux techniques** : RSI, MACD, moyennes mobiles (MA20/MA50), volume ratio
- **Données fondamentales** : P/E, EPS, dette/capitalisation, croissance CA
- **Analyse médiatique** : sentiment NLP (VADER/FinBERT) sur presse et flux RSS
- **Activité insiders** : transactions des dirigeants
- **Risque dirigeants** : détection d'événements (scandales, départs, rachats)
- **Zones de trading** : entrée, objectif cible, stop-loss, ratio R/R
- **Synthèse IA** : résumé généré par LLaMA 3.3 70B via Groq (fallback Ollama local)
- **Graphiques** : cours + volume (matplotlib), RSI, chandeliers Plotly interactifs
- **Figures chartistes** : détection de patterns avec explication contextuelle
- **Watchlist** personnelle (AJAX, sans rechargement de page)
- **Authentification** : inscription / connexion / sessions persistantes (Flask-Login + bcrypt)
- **Alertes email** : notification sur variation de cours (SMTP Gmail)
- **Interface responsive** : navbar intégrée, mobile-first, pas de sidebar

## Stack technique

| Couche | Technologie |
|---|---|
| Framework web | Flask 3 + Blueprints |
| Auth | Flask-Login, Flask-WTF (CSRF), bcrypt, YAML |
| Base de données | Supabase (PostgreSQL) via REST HTTPS — fallback YAML/JSON local |
| Données marché | yfinance (primaire) · Finnhub + Twelve Data (fallback cloud) |
| NLP / Sentiment | VADER (défaut), FinBERT (optionnel GPU) |
| LLM | Groq API (LLaMA 3.3 70B) + Ollama (fallback local) |
| Graphiques | matplotlib (PNG base64), Plotly (JSON → JS) |
| Actualités | NewsAPI, feedparser (RSS) |
| Serveur prod | gunicorn |
| Conteneur | Docker + docker-compose |
| Déploiement cloud | Render (Docker) |

## Installation

### Prérequis

- Python 3.10+
- pip

### 1. Cloner et installer

```bash
git clone https://github.com/cybkilla/SDE_FLASK.git
cd SDE_FLASK
pip install -r requirements.txt
```

### 2. Configurer les variables d'environnement

```bash
cp .env.example .env
# Éditer .env avec vos clés
```

Variables requises dans `.env` :

```env
FLASK_SECRET_KEY=une_cle_aleatoire_longue
NEWS_API_KEY=votre_cle_newsapi
GROQ_API_KEY=votre_cle_groq
# Données marché — fallback cloud (Render) si Yahoo Finance est bloqué
FINNHUB_API_KEY=votre_cle_finnhub
TWELVE_DATA_API_KEY=votre_cle_twelvedata
# Supabase (laisser vide → fallback YAML/JSON local)
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_KEY=eyJhbGci...            # clé anon (publique)
SMTP_PASSWORD=app_password_gmail    # optionnel, pour les alertes email
```

- **NewsAPI** : clé gratuite sur [newsapi.org](https://newsapi.org)
- **Groq** : clé gratuite sur [console.groq.com](https://console.groq.com)
- **Finnhub** : clé gratuite sur [finnhub.io](https://finnhub.io) — quote temps réel + fondamentaux (60 req/min)
- **Twelve Data** : clé gratuite sur [twelvedata.com](https://twelvedata.com) — historique OHLCV NASDAQ/NYSE (800 req/jour)
- **Supabase** : projet gratuit sur [supabase.com](https://supabase.com) — voir `doc/SUPABASE.md`
- **SMTP** : mot de passe d'application Gmail (Compte → Sécurité → Mots de passe d'applications)

### 3. Lancer en développement

```bash
python run_flask.py
```

Ouvrir [http://localhost:5000](http://localhost:5000)

### 4. Lancer en production (gunicorn)

```bash
gunicorn --config gunicorn.conf.py "run_flask:app"
```

### 5. Lancer avec Docker

```bash
docker-compose up --build
```

Le conteneur expose le port `5000`. Les données utilisateurs (watchlist, auth) sont persistées dans Supabase (variables `SUPABASE_URL` et `SUPABASE_KEY` requises en production).

## Structure du projet

```
sde_flask/
├── run_flask.py              # Point d'entrée Flask
├── config.py                 # Paramètres centralisés (charge .env)
├── pipeline.py               # Orchestrateur de l'analyse complète
├── db.py                     # Couche persistance Supabase (fallback YAML/JSON)
├── migrate_to_supabase.py    # Script one-shot : importe users/watchlist/scores dans Supabase
├── flask_app/
│   ├── __init__.py           # Factory create_app()
│   ├── blueprints/
│   │   ├── auth.py           # Routes /auth/login, /auth/register, /auth/logout
│   │   └── stock.py          # Routes /, /analyze/<ticker>, /api/search, /watchlist
│   ├── charts_helpers.py     # build_charts() → PNG base64 + Plotly JSON
│   ├── static/
│   │   ├── css/sde.css       # Design system v2 (Dashboard Financier)
│   │   └── js/
│   │       ├── search.js     # Autocomplete navbar + hero home
│   │       └── watchlist.js  # AJAX watchlist (modal Bootstrap)
│   └── templates/
│       ├── base.html         # Layout : navbar sticky, modal watchlist, scripts
│       ├── home.html         # Page d'accueil : hero + recherche + features
│       ├── analysis.html     # Page d'analyse complète
│       └── auth/
│           ├── login.html
│           └── register.html
├── analysis/                 # Moteurs d'analyse
│   ├── signals.py            # Signaux techniques (RSI, MACD, MA)
│   ├── scoring.py            # Score global pondéré
│   ├── trading_zones.py      # Calcul entrée / cible / stop-loss
│   ├── candle_patterns.py    # Détection de figures chartistes
│   ├── sentiment.py          # NLP VADER / FinBERT
│   ├── media_score.py        # Score médiatique agrégé
│   ├── executive_risk.py     # Risque dirigeants (RSS + mots-clés)
│   ├── llm_explain.py        # Appels Groq / Ollama
│   └── explainer.py          # Tableau de signaux détaillés
├── watchlist/                # Données watchlist (JSON par utilisateur)
├── auth/                     # Données utilisateurs (users.yaml, bcrypt)
├── Dockerfile
├── docker-compose.yml
├── gunicorn.conf.py
└── .env.example
```

## Sécurité

- Les clés API ne sont **jamais** codées en dur — uniquement via `os.getenv()` avec fallback vide
- `.env` est dans `.gitignore` ; seul `.env.example` est versionné
- `FLASK_SECRET_KEY` doit être définie en variable d'environnement en production
- Protection CSRF activée sur tous les formulaires et requêtes AJAX (Flask-WTF + header `X-CSRFToken`)
- Sessions HTTP-only, SameSite=Lax

## Avertissement

SDE est un outil d'aide à la décision. Les informations fournies ne constituent pas un conseil financier. Investir comporte des risques de perte en capital.
