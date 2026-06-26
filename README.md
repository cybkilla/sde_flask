# SDE — Stock Decision Engine (Flask)

Application web d'aide à la décision boursière. Analyse n'importe quelle action cotée en combinant signaux techniques, données fondamentales, analyse médiatique et synthèse IA. Gestion de portefeuille avec conseil journalier personnalisé et évaluation automatique de la pertinence des conseils.

## Fonctionnalités

### Analyse
- **Score global** (0–100) avec jauge visuelle et décomposition en 3 composantes pondérées
- **Recommandation** ACHETER / NEUTRE / VENDRE avec niveau de confiance
- **Signaux techniques** : RSI, MACD, moyennes mobiles (MA20/MA50), volume ratio
- **Données fondamentales** : P/E, EPS, dette/capitalisation, croissance CA
- **Analyse médiatique** : sentiment NLP (VADER) sur presse et flux RSS
- **Activité insiders** : transactions des dirigeants (disponible pour les valeurs US uniquement — source SEC/Yahoo Finance)
- **Risque dirigeants** : détection d'événements (scandales, départs, rachats)
- **Zones de trading** : entrée, objectif cible, stop-loss, ratio R/R
- **Synthèse IA** : résumé généré par LLaMA 3.3 70B via Groq (fallback Python)
- **Graphiques** : cours + volume (matplotlib), RSI, chandeliers Plotly interactifs
- **Figures chartistes** : détection de 12 patterns avec explication contextuelle

### Portfolio & Conseil
- **Positions** : enregistrement des lots d'achat et de vente par ticker (DCA supporté)
- **P&L complet** : gain/perte latent(e) sur positions ouvertes + gain/perte encaissé(e) sur positions clôturées, calculés séparément
- **Vente validée** : blocage serveur et client si solde d'actions insuffisant ; quantité entière uniquement
- **Conseil du jour** : recommandation journalière rule-based (ACHETER / RENFORCER / TENIR / SURVEILLER / ALLÉGER / VENDRE) combinant score SDE, RSI, P&L et pattern chandelier
- **Conseil immutable** : un seul conseil par ticker et par jour — pas de régénération intempestive
- **Suivi de conseil** : lien explicite `conseil_date` entre chaque transaction et le conseil qui l'a déclenchée
- **Historique** : 14 derniers conseils avec taux de fiabilité calculé automatiquement
- **Pré-saisie modale** : clic sur le badge conseil → modal pré-rempli (type, prix live, quantité suggérée)

### Dashboard Admin
- Accessible aux emails listés dans `ADMIN_EMAILS`
- **Évaluation automatique J+1** : deux chemins — `evaluate_yesterday_advice()` via scheduler (fenêtre 20h–22h Paris, prix fin de séance Finnhub) + `evaluate_pending()` via admin (yfinance historique, skip si J+1 = aujourd'hui marché ouvert)
- `reset_intraday_evals()` : invalide automatiquement les évaluations hors-fenêtre (7j) à chaque refresh admin pour forcer une ré-évaluation propre
- **Taux de pertinence global** : % de bons conseils sur l'ensemble de l'historique
- **Taux sur conseils suivis** : pertinence uniquement sur les conseils qui ont déclenché une transaction
- **Breakdown par type** : taux par action (ACHETER, RENFORCER, TENIR, SURVEILLER, ALLÉGER, VENDRE)
- **Breakdown par ticker** : taux de fiabilité et dernier conseil pour chaque valeur suivie
- **Gestion des données** : réinitialisation (positions, conseils, watchlist, historique) ou suppression de compte par utilisateur ou pour tous — protégé par `ADMIN_DATA_PASSWORD`
- **Suppression granulaire** : suppression d'un ticker précis pour n'importe quel utilisateur (positions + TP/SL + conseils liés) — protégé par `ADMIN_DATA_PASSWORD`
- **Reset mot de passe** : envoi d'un lien de réinitialisation par email pour n'importe quel utilisateur

### Plateforme
- **Statut marché NASDAQ** : badge "Marché ouvert" (15h30–22h00 heure de Paris) / "Clôture J-1" sur tous les affichages de prix
- **Watchlist** personnelle (AJAX, sans rechargement de page)
- **Cache 3 niveaux** : mémoire 15 min → snapshot Supabase 24h → pipeline complet
- **Prix live** : superposition du prix Finnhub en temps réel sur les analyses en cache
- **Authentification renforcée** : inscription / connexion / déconnexion, sessions persistantes (Flask-Login + bcrypt), politique de mot de passe (8+ chars, majuscule, chiffre, spécial), activation de compte par email, mot de passe oublié (lien email one-use 1h), rate limiting (5 tentatives / 15 min / IP)
- **Profil utilisateur** : modification du nom, email (obligatoire), photo de profil (redimensionnée 128×128 JPEG côté client, stockée en base64)
- **Alertes email** : notification sur variation de cours ou changement de recommandation (Resend HTTP)
- **Scheduler deux vitesses** : prix live toutes les 30 min (Finnhub léger) + pipeline complet 1×/jour
- **Interface responsive** : navbar intégrée, mobile-first, Bootstrap 5

## Stack technique

| Couche | Technologie |
|---|---|
| Framework web | Flask 3 + Blueprints |
| Auth | Flask-Login, Flask-WTF (CSRF), bcrypt |
| Base de données | Supabase (PostgreSQL) via REST HTTPS |
| Données marché | yfinance (primaire) · Finnhub (quote live + fallback) · Twelve Data (fallback historique) |
| NLP / Sentiment | VADER |
| LLM | Groq API (LLaMA 3.3 70B) + fallback Python |
| Graphiques | matplotlib (PNG base64), Plotly (JSON → JS) |
| Actualités | NewsAPI, feedparser (RSS) |
| Email | Resend (HTTP API — fonctionne sur Render) |
| Scheduler | cron-job.org → `POST /scheduler/run` toutes les 30 min |
| Serveur prod | gunicorn (`workers=1`, `max_requests=200`) |
| Déploiement cloud | Render free tier — `https://sde-flask.onrender.com` |

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

# Données marché
FINNHUB_API_KEY=votre_cle_finnhub
TWELVE_DATA_API_KEY=votre_cle_twelvedata

# Actualités
NEWS_API_KEY=votre_cle_newsapi

# LLM (optionnel — fallback Python si absent)
GROQ_API_KEY=votre_cle_groq

# Supabase (obligatoire en production)
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_SERVICE_KEY=eyJhbGci...   # service_role — bypass RLS, server-side uniquement
SUPABASE_KEY=eyJhbGci...           # anon/public — fallback si SERVICE_KEY absent

# Email alertes
RESEND_API_KEY=re_xxxxxxxxxxxx
RESEND_FROM=SDE StockDecisionEngine <onboarding@resend.dev>

# Scheduler
CRON_SECRET=un_token_aleatoire_long

# Admin dashboard
ADMIN_EMAILS=votre_email@domaine.com
ADMIN_DATA_PASSWORD=choisir_un_mot_de_passe_fort_ici
```

Sources des clés :
- **Finnhub** : [finnhub.io](https://finnhub.io) — 60 req/min gratuit
- **Twelve Data** : [twelvedata.com](https://twelvedata.com) — 800 req/jour gratuit
- **NewsAPI** : [newsapi.org](https://newsapi.org) — 100 req/jour gratuit
- **Groq** : [console.groq.com](https://console.groq.com) — gratuit
- **Supabase** : [supabase.com](https://supabase.com) — voir `doc/SUPABASE.md` pour le schéma SQL
- **Resend** : [resend.com](https://resend.com) — 3 000 emails/mois gratuit
- **CRON_SECRET** : `python -c "import secrets; print(secrets.token_hex(24))"`

### 3. Lancer en développement

```bash
python run_flask.py
```

Ouvrir [http://localhost:5000](http://localhost:5000)

### 4. Lancer en production (gunicorn)

```bash
gunicorn --config gunicorn.conf.py "run_flask:app"
```

## Scheduler & Alertes

Le scheduler vérifie toutes les watchlists via [cron-job.org](https://cron-job.org).

| Endpoint | Rôle |
|---|---|
| `POST /scheduler/run` | Déclenche le scheduler (thread background, répond 202) |
| `GET /scheduler/test-email?to=...` | Envoie un email de test Resend |

Protégés par le header `X-Cron-Secret` (ou paramètre `?secret=CRON_SECRET`).

**Architecture deux vitesses :**
- **Chemin rapide** (toutes les 30 min) : `get_live_price()` Finnhub + snapshot Supabase
- **Chemin complet** (1×/jour) : pipeline complet si snapshot > 24h (renouvelle NewsAPI, Groq…)

**Configuration cron-job.org :**
- URL : `https://sde-flask.onrender.com/scheduler/run`
- Méthode : POST
- Header : `X-Cron-Secret: CRON_SECRET`
- Intervalle : toutes les 30 minutes

## Structure du projet

```
sde_flask/
├── run_flask.py              # Point d'entrée Flask
├── config.py                 # Paramètres centralisés (charge .env)
├── pipeline.py               # Orchestrateur de l'analyse complète
├── snapshot.py               # Cache Supabase 24h (sérialisation/désérialisation)
├── cache.py                  # Cache in-memory 15 min
├── db.py                     # Couche persistance Supabase (service_role key)
├── flask_app/
│   ├── __init__.py           # Factory create_app()
│   ├── blueprints/
│   │   ├── auth.py           # Routes /auth/login, /register, /logout, /activate, /forgot-password, /reset-password
│   │   ├── stock.py          # Routes /, /analyze/<ticker>, /api/search, /watchlist
│   │   ├── portfolio.py      # Routes /portfolio/positions, /portfolio/advice, /portfolio/overview
│   │   ├── profile.py        # Routes /profile/ (infos, mot de passe, avatar)
│   │   ├── admin.py          # Route /admin/dashboard, /admin/stats, /admin/data/* (ADMIN_EMAILS requis)
│   │   └── cron.py           # Route /scheduler/run (protégée par CRON_SECRET)
│   ├── static/
│   │   ├── css/sde.css       # Design system (Dashboard Financier)
│   │   └── js/
│   │       ├── search.js     # Autocomplete navbar
│   │       └── watchlist.js  # AJAX watchlist (modal Bootstrap)
│   └── templates/
│       ├── base.html         # Layout : navbar, modal watchlist, sdeMarketStatus() JS
│       ├── home.html         # Page d'accueil
│       ├── analysis.html     # Page d'analyse + section Ma position + modal transaction
│       ├── portfolio.html    # Vue d'ensemble positions + P&L + conseils du jour
│       ├── admin.html        # Dashboard admin : taux pertinence conseils
│       ├── profile.html      # Page profil : nom, email, photo, mot de passe
│       └── auth/             # login.html, register.html, forgot_password.html, reset_password.html
├── analysis/
│   ├── scoring.py            # Score global pondéré (technique + fondamental + médiatique)
│   ├── candle_patterns.py    # Détection de 12 figures chartistes
│   ├── sentiment.py          # NLP VADER
│   ├── media_score.py        # Score médiatique agrégé
│   ├── executive_risk.py     # Risque dirigeants
│   └── llm_explain.py        # Appels Groq / fallback Python
├── auth/
│   ├── password_policy.py    # Politique mot de passe (8+ chars, majuscule, chiffre, spécial)
│   └── auth_tokens.py        # Génération / validation / consommation tokens activation & reset (table auth_tokens)
├── data/
│   ├── market.py             # get_market_data() + get_live_price() (Finnhub → yfinance fallback)
│   ├── news.py               # NewsAPI + feedparser RSS
│   └── insider.py            # Transactions insiders (US uniquement — SEC via Yahoo Finance)
├── portfolio/
│   ├── positions.py          # get_portfolio_summary(), add_position(), delete_position()
│   │                         # P&L séparé : pnl_realise + pnl_non_realise + position_fermee
│   ├── advisor.py            # generate_advice() — conseil rule-based (SDE + RSI + P&L + chandelier)
│   └── evaluator.py          # evaluate_pending() J+1 yfinance + get_global_stats() admin KPIs
├── alerts/
│   ├── scheduler.py          # Architecture deux vitesses (Finnhub live + snapshot + pipeline)
│   └── mailer.py             # Envoi alertes via Resend
├── watchlist/
│   └── watchlist.py          # get_watchlist(), add/remove, get_last_score()
├── ui/
│   └── charts.py             # Génération graphiques (matplotlib + Plotly)
├── gunicorn.conf.py          # workers=1, max_requests=200 (Render free tier 512MB)
└── .env.example
```

## Supabase — Tables

Voir `doc/SUPABASE.md` pour le schéma SQL complet et les politiques RLS.

| Table | Rôle |
|---|---|
| `users` | Comptes utilisateurs — colonnes `name`, `email`, `password` (bcrypt), `avatar` (base64), `email_verified` |
| `auth_tokens` | Tokens one-use d'activation de compte et de reset de mot de passe (expiry, type) |
| `watchlist` | Tickers suivis par utilisateur |
| `scores` | Dernier score/reco connu par ticker |
| `ticker_snapshots` | Résultats pipeline sérialisés (cache 24h) — colonne `data` (JSONB) |
| `positions` | Lots d'achat ET de vente — colonnes `type` (achat/vente) et `conseil_date` |
| `daily_advice` | Conseils journaliers + évaluation J+1 (`bon_conseil`, `variation_j1`, `evaluated_at`) |
| `position_targets` | Take Profit / Stop Loss par user/ticker + alertes email (`tp_alerted_at`, `sl_alerted_at`) |
| `portfolio_snapshots` | Historique de valeur du portefeuille (snapshot quotidien) |
| `advisor_config` | Seuils du moteur de conseil configurables par utilisateur |
| `weekly_reports` | Anti-doublon rapports hebdomadaires envoyés par email |

## Horaires de trading NASDAQ

Le NASDAQ est ouvert de **15h30 à 22h00 heure de Paris** (lundi–vendredi).

SDE utilise cette plage pour :
- Afficher le badge "Marché ouvert" / "Clôture J-1" sur tous les prix
- Informer l'admin que les évaluations J+1 sont incomplètes avant 22h00
- Interpréter les prix live (yfinance renvoie le cours de clôture J-1 hors séance)

La détection s'effectue côté client via `window.sdeMarketStatus()` (JavaScript, `Intl.DateTimeFormat` avec timezone `Europe/Paris`).

## Sécurité

- Clés API uniquement via `os.getenv()` — jamais en dur dans le code
- `.env` dans `.gitignore` — seul `.env.example` est versionné
- `FLASK_SECRET_KEY` et `SUPABASE_SERVICE_KEY` obligatoires via variables d'environnement
- RLS activé sur toutes les tables Supabase ; `SUPABASE_SERVICE_KEY` (service_role) uniquement côté serveur
- Protection CSRF sur tous les formulaires et requêtes AJAX (Flask-WTF + header `X-CSRFToken`)
- Sessions HTTP-only, SameSite=Lax
- `ADMIN_EMAILS` : accès dashboard admin vérifié via `current_user.email` (pas `current_user.id`)
- Politique mot de passe : 8+ caractères, 1 majuscule, 1 chiffre, 1 spécial — vérifiée à l'inscription, au profil et au reset
- Rate limiting login : 5 tentatives / 15 min / IP (in-memory, compatible `workers=1` Gunicorn)
- Tokens auth one-use (`auth_tokens`) avec expiry (24h activation, 1h reset) — `hmac.compare_digest` pour comparaisons sécurisées
- `ADMIN_DATA_PASSWORD` : protège les opérations de reset/suppression de données en admin

## Avertissement

SDE est un outil d'aide à la décision. Les informations fournies ne constituent pas un conseil financier. Investir comporte des risques de perte en capital.
