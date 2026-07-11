# SDE — Grille d'évaluation PPL 2026

> Récap technique par critère — version Flask (refonte depuis Streamlit).

---

## 01 Conception du projet

| Sous-critère | Ce qui est fait dans SDE |
|---|---|
| **Ambition & Originalité** | Moteur d'analyse boursière multi-source : scoring composite technique + fondamental + sentiment NLP + risque dirigeants + LLM. Gestion de portefeuille avec conseil journalier personnalisé et évaluation automatique de la pertinence (bon/mauvais conseil) via yfinance J+1. |
| **Fonctionnalités** | Recherche de ticker, analyse complète, watchlist multi-utilisateurs, positions (achat + vente), P&L réalisé/latent, conseil quotidien immutable (généré automatiquement par le scheduler pour chaque position ouverte), dashboard admin KPIs, alertes email automatisées (changement de recommandation, variation > 5&nbsp;%, TP/SL, **changement du conseil position** TENIR→ALLÉGER…, **gap pré-marché** : conseil réévalué avant l'ouverture si l'écart overnight dépasse max(2&nbsp;%, 1×ATR)). **Backtest 2 ans** (rejeu du scoring jour par jour, taux de réussite à 5/20j, courbes stratégie vs buy & hold), **attribution par signal** (fiabilité de chaque critère en épisodes), **régime de marché QQQ** (score ajusté selon le contexte NASDAQ, pondéré par le R² ticker/marché), **classifieur probabiliste** P(hausse 20j) en régression logistique avec validation walk-forward, **calibration adaptative des poids par ticker** (chaque critère technique modulé par sa fiabilité mesurée sur 2 ans — shrinkage bayésien, bornes [0;1.5], min 8 épisodes, ajustements affichés), **seuils de conseil normalisés par la volatilité** (stop/TP/renforcement en multiples d'ATR bornés autour de la config utilisateur) + **stop suiveur** (ALLÉGER si repli > 2×ATR depuis le plus haut atteint depuis l'achat) + bouton « ⚡ Seuils SDE » qui pré-remplit les objectifs de prix TP/SL depuis ces mêmes seuils (l'utilisateur valide). |
| **Description des processus** | `pipeline.py::run(ticker)` orchestre : collecte marché → sous-scores (technique/fondamental/médiatique) → score global → recommandation → explication LLM → conseil position. |
| **Modélisation du Workflow** | 5 modules d'analyse indépendants agrégés par `scoring.py`. `evaluator.py` évalue en batch les conseils passés. `scheduler.py` deux vitesses (30 min live / 24h pipeline). |

---

## 02 Structure logique de l'application

| Sous-critère | Ce qui est fait dans SDE |
|---|---|
| **Architecture** | Flask Blueprints : `auth`, `stock`, `portfolio`, `admin`, `cron`. Séparation nette données (`data/`), analyse (`analysis/`), portfolio (`portfolio/`), rendu (`flask_app/templates/`), alertes (`alerts/`). |
| **Modules externes** | `yfinance`, `finnhub-python`, `twelvedata`, `newsapi-python`, `feedparser`, `vaderSentiment`, `groq`, `plotly`, `matplotlib`, `supabase`, `flask-login`, `flask-wtf`. |
| **Système de classes** | `ui/charts.py` : figures Plotly encapsulées. `db.py` : interface générique Supabase. `snapshot.py` : sérialisation/désérialisation DataFrames. `evaluator.py` : batch évaluation conseils. |
| **Gestion des données** | Données temps réel via yfinance/Finnhub/NewsAPI. Persistance PostgreSQL via Supabase REST. Cache mémoire 15 min + cache snapshot 24h. Fallback fichiers JSON si Supabase absent. |
| **Local / Serveur** | Dev local (`python run_flask.py`), production Render (gunicorn `workers=1`). Scheduler cron-job.org → `POST /scheduler/run` toutes les 30 min. |

---

## 03 Programmation Python

| Sous-critère | Ce qui est fait dans SDE |
|---|---|
| **Organisation des fichiers** | Un fichier = une responsabilité (`market.py`, `news.py`, `sentiment.py`, `scoring.py`, `positions.py`, `advisor.py`, `evaluator.py`). Imports dans les fonctions pour éviter les imports circulaires. |
| **Fonctions & variables** | Nommage explicite (`get_portfolio_summary`, `evaluate_pending`, `get_global_stats`, `generate_advice`). Constantes dans `config.py`. |
| **Classes, méthodes, héritage** | Architecture fonctionnelle volontaire (fonctions pures, pas de classes inutiles). Classes légères dans `ui/`. `db.py` encapsule l'accès Supabase. |
| **Bibliothèques Standard** | `pathlib`, `json`, `os`, `re`, `datetime`, `zoneinfo` (timezone Paris), `threading` (scheduler background), `traceback`. |
| **Modules Built-In** | `typing` (hints), `functools`, `collections`. |
| **Organisation & Extensibilité** | `pipeline.py` API unique `run(ticker)`. Ajouter un sous-score = créer un module + l'intégrer dans `scoring.py`. Blueprints Flask isolés et indépendants. |

---

## 04 Analyse du code utilisé

| Sous-critère | Ce qui est fait dans SDE |
|---|---|
| **Justification du design** | VADER vs FinBERT (GPU non disponible sur Render). Groq vs Ollama (fallback Python si quota). Scoring pondéré 40/35/25 (technique/fondamental/médiatique). Supabase REST vs SQLAlchemy (compatibilité Render, pas de driver C). `conseil_date` (FK explicite) vs heuristique date+type (trop de faux positifs). **R² vs bêta** pour pondérer le régime marché : choix tranché empiriquement par backtest (TMC bêta 1.45 mais corr 0.30 — le bêta mesure l'amplitude, le R² la part expliquée). **Walk-forward vs train_test_split** : jamais de mélange aléatoire passé/futur sur séries temporelles. QQQ vs ^VIX : le VIX est indisponible sur Twelve Data (fallback Render). **Calibration : atténuer sans inverser** — multiplicateur borné [0;1.5] car inverser un signal sur données passées = overfitter un régime révolu ; le backtest mesure toujours les poids standards (le thermomètre ne dépend pas du chauffage). |
| **Maîtrise du code** | Gestion index Pandas (`_col()` helper pour colonnes absentes). P&L en deux passes (réalisé sur lots vendus, latent sur solde restant). `_calcLock` JS pour éviter les boucles événements dans le modal bidir. Bloc/déblocage bouton Vente côté client + validation serveur. |

---

## 05 Interfaces utilisateur — Flask / Bootstrap

| Sous-critère | Ce qui est fait dans SDE |
|---|---|
| **Librairies UI** | Flask 3 + Jinja2, Bootstrap 5.3, Bootstrap Icons 1.11, Plotly 2.35 (JS), CSS custom (`sde.css` — Design System "Dashboard Financier"). |
| **Fonctionnalités UI** | Login/logout, recherche ticker avec autocomplétion AJAX, jauge score, graphiques OHLCV + chandeliers interactifs, watchlist modale, positions avec modal transaction (toggle Achat/Vente, calcul bidir prix×qté↔montant), badge conseil cliquable avec pré-saisie, P&L coloré (vert/rouge), statut marché (Ouvert / Clôture J-1), dashboard admin avec jauges taux de pertinence. |
| **Usabilité** | Interface mobile-first. Badge "Marché ouvert" temps réel (JS `Intl.DateTimeFormat` Europe/Paris). Blocage visuel du bouton Vente si 0 actions. Montant total auto-calculé sur blur. Note admin si évaluations incomplètes (< 22h). |

---

## 06 Modules externes

| Sous-critère | Ce qui est fait dans SDE |
|---|---|
| **Librairies externes** | `yfinance`, `vaderSentiment`, `feedparser`, `newsapi-python`, `groq`, `bcrypt`, `finnhub-python`, `twelvedata`, `supabase`, `plotly`, `matplotlib`, `ta` (indicateurs techniques), `scikit-learn` (régression logistique du classifieur probabiliste). |
| **Connexion APIs distantes** | **NewsAPI** (articles financiers), **Yahoo Finance** via yfinance (cours, fondamentaux, historique, insider), **Finnhub** (quote temps réel), **Twelve Data** (historique OHLCV fallback), **Groq API** (LLaMA 3.3-70b explication IA), **Supabase REST** (persistance), **Resend** (emails HTTP). |
| **Maps / GPS / Audio / Vidéo** | Non applicable. |

---

## 07 Flask — REST API

| Sous-critère | Ce qui est fait dans SDE |
|---|---|
| **Routes** | SDE est une application Flask complète avec Blueprints. Routes principales : `/` (accueil), `/analyze/<ticker>` (analyse), `/portfolio/overview` (positions), `/portfolio/advice/<ticker>` (conseil AJAX), `/admin/dashboard` + `/admin/stats` (KPIs), `/scheduler/run` (cron), `/auth/login` · `/register` · `/logout`. |
| **Authentification** | Flask-Login (session persistante) + bcrypt (hash mots de passe) + Flask-WTF CSRF. Middleware `@login_required` sur toutes les routes protégées. Admin protégé par vérification `current_user.email in ADMIN_EMAILS`. |
| **SGBD** | PostgreSQL via Supabase REST. Tables : `users`, `watchlist`, `scores`, `ticker_snapshots`, `positions`, `daily_advice`. RLS activé, accès via `service_role` key. |
| **Modélisation des données** | `positions` : lots typés (achat/vente) avec `conseil_date`. `daily_advice` : conseil + évaluation J+1 (`bon_conseil`, `variation_j1`) + `signaux_actifs` JSONB (vecteur des signaux au moment du conseil — dataset d'apprentissage pour la calibration adaptative). `ticker_snapshots` : payload JSONB (DataFrames sérialisés). |

---

## 07bis Traitement des données — NumPy & Pandas

| Sous-critère | Ce qui est fait dans SDE |
|---|---|
| **Collection des données** | `data/market.py` : DataFrame yfinance (OHLCV 90j + fondamentaux). `data/news.py` : DataFrame articles (titre, source, sentiment, type). `portfolio/evaluator.py` : DataFrame historique yfinance pour évaluation batch J+1. |
| **Visualisation** | `ui/charts.py` : chandelier Plotly interactif, RSI, MAs 20/50j. `flask_app/blueprints/admin.py` : barres de pertinence HTML dynamiques. Jauges score via CSS pur (pas de lib externe). |
| **Test accessibilité APIs** | Dossier `tests/` : suites hors réseau sur données synthétiques (`test_backtest.py`, `test_market_regime.py`, `test_predictor.py`) — dont un test anti-look-ahead (le score du jour T ne change pas si on ajoute des jours après T) et des cas limites (corrélation négative, historique court). |
| **Modules externes** | `pandas 2.2`, `numpy 1.26`, `plotly ≥ 5.24`, `ta 0.11` (RSI, MACD, Bollinger), `scikit-learn 1.9` (LogisticRegression, roc_auc_score). |

---

## 09 Techniques de Développement — DevOps

| Sous-critère | Ce qui est fait dans SDE |
|---|---|
| **GIT** | Repo GitHub `cybkilla/SDE_FLASK` avec historique de commits conventionnels (`feat:`, `fix:`, `refactor:`). GitHub Push Protection active (détection de secrets). |
| **Docker** | Pas de Dockerfile (gunicorn + Render suffisants). `Procfile` implicite via `gunicorn.conf.py`. |
| **Déploiement** | **Render** (cloud, free tier) : auto-deploy sur push `main`. **cron-job.org** : scheduler toutes les 30 min via `POST /scheduler/run` + header secret. |
| **Sécurité** | Clés API via `os.getenv()` exclusivement. `.env` gitignored. CSRF sur toutes les routes AJAX. `SUPABASE_SERVICE_KEY` server-side uniquement. Sessions HTTP-only SameSite=Lax. |

---

## 10 Fonctionnalités du projet

| Sous-critère | Ce qui est fait dans SDE |
|---|---|
| **Proof of work** | Score composite 0-100 → recommandation ACHETER/NEUTRE/VENDRE → conseil journalier 6 niveaux (ACHETER / RENFORCER / TENIR / SURVEILLER / ALLÉGER / VENDRE) → évaluation automatique J+1 → taux de pertinence admin. |
| **Usages incrémentables** | Multi-utilisateurs, multi-tickers, DCA (plusieurs lots), ventes partielles, conseil lié explicitement à chaque transaction, admin KPIs cross-utilisateur. |
| **Formulaires / interfaces avancées** | Modal transaction : toggle Achat/Vente, pré-saisie prix live + quantité suggérée, calcul bidir prix×qté↔montant, validation quantité entière, blocage vente si solde nul. Watchlist AJAX modale. Recherche autocomplete. |
| **Options de développement à venir** | Calibration adaptative des poids : croiser l'attribution historique (backtest) avec les données live `signaux_actifs` + `bon_conseil` (~3 mois d'accumulation), avec garde-fous (shrinkage vers la moyenne, ajustements bornés ±50%, mensuels, journalisés). Alertes email sur signal conseil. Vue portefeuille consolidé multi-ticker (allocation, concentration). Calendrier earnings (prudence avant publication). FinBERT GPU pour sentiment plus précis. |
| **Exploitation commerciale** | Outil d'aide à la décision pour investisseurs particuliers. Base pour un SaaS de screener + coach boursier personnalisé. Différenciant : évaluation objective de la pertinence de ses propres conseils (taux de fiabilité). |

---

## Points forts à mettre en avant

- **Pipeline entièrement découplé** : chaque source d'analyse est indépendante et testable seule.
- **Évaluation objective des conseils** : `evaluate_pending()` mesure automatiquement si le conseil J était juste via yfinance J+1 — boucle de rétroaction unique.
- **SDE se mesure lui-même** : backtest 2 ans sans look-ahead, attribution par signal en épisodes (une période continue d'activation = 1 observation), et un classifieur probabiliste qui AFFICHE quand il ne bat pas le hasard plutôt que de le cacher.
- **Choix de conception validés par l'expérience** : la pondération du régime marché (R² plutôt que bêta) a été tranchée en comparant 4 schémas sur les données réelles avant d'écrire la règle.
- **P&L complet** : réalisé (encaissé) et latent calculés séparément, même sur positions clôturées.
- **`conseil_date`** : lien explicite transaction ↔ conseil, élimine les faux positifs de l'heuristique date/type.
- **Statut marché temps réel** : `Intl.DateTimeFormat` Europe/Paris côté client — aucune dépendance serveur.
- **Sécurité production** : CSRF + service_role key + GitHub Push Protection + sessions HTTP-only.

## Lacunes à mentionner honnêtement

- Le classifieur probabiliste ne bat pas encore le hasard en test (450 jours, 15 features binaires) — affiché comme EXPÉRIMENTAL avec avertissement, non utilisé pour la recommandation.
- Le backtest ne rejoue que le score technique (pas d'archives de news/bilans datées pour les scores fondamental et médiatique) — limite affichée dans l'UI.
- Pas de tests unitaires sur `analysis/scoring.py` et `portfolio/evaluator.py` (couverture partielle).
- Render free tier : cold start 30–60 s après inactivité, RAM 512 MB (workers=1 obligatoire).
- Évaluation J+1 imparfaite pour les weekends (samedi → évalué avec le cours du lundi suivant).
- Pas de Dockerfile (déploiement Render natif mais non containerisé).
