# SDE — Stack technique, services externes et coûts

Récapitulatif de tout ce sur quoi SDE s'appuie : hébergement, données,
IA, email — avec la fonction de chacun et son coût. Photographie du
01.08.2026 ; les offres gratuites évoluent, à revérifier périodiquement
sur les sites eux-mêmes.

---

## 1. Vue d'ensemble

```
Navigateur
   │
   ▼
Render (hébergement web)  ──cron-job.org (toutes les 30 min)──▶ /scheduler/run
   │
   ├── Supabase (base de données)
   ├── Finnhub / Twelve Data / yfinance (données boursières)
   ├── NewsAPI + flux RSS (actualités)
   ├── Groq / Gemini (IA)
   └── Resend (emails)
```

Tout le code est sur **GitHub** (`github.com/cybkilla/sde_flask`, dépôt
privé) — pas un service utilisé par l'app elle-même, mais l'endroit d'où
Render récupère le code à chaque déploiement.

---

## 2. Hébergement & infrastructure

### Render
**Fonction** : héberge le serveur web Flask (via gunicorn) qui sert toutes
les pages de SDE, 24h/24.
**Config actuelle** : plan gratuit, 512 Mo de RAM — un seul worker
gunicorn (sync) tourne en permanence ; `max_requests=200` pour libérer la
mémoire régulièrement (pandas/matplotlib s'accumulent sinon).
**Prix** : gratuit sur le plan actuel. Render facture au-delà pour plus de
RAM/CPU ou pour éviter la mise en veille après inactivité prolongée
(le plan gratuit peut mettre le service en veille — un premier appel
après veille est plus lent le temps du redémarrage).

### cron-job.org
**Fonction** : déclenche `POST /scheduler/run` toutes les 30 minutes —
c'est ce qui fait tourner en arrière-plan les alertes email, les
réévaluations de conseils, les snapshots quotidiens du portefeuille, le
digest pré-marché, etc. Sans lui, rien ne se passe tant que personne ne
visite le site.
**Prix** : gratuit (service dédié justement à ce genre d'usage léger).

### GitHub
**Fonction** : hébergement du code source, historique des commits.
**Prix** : gratuit (dépôt privé, plan gratuit GitHub).

---

## 3. Base de données

### Supabase
**Fonction** : toute la persistance — comptes utilisateurs, positions,
conseils quotidiens, historique du portefeuille, watchlist, cache des
analyses (snapshots), config admin, etc. Postgres managé, accédé via API
REST (pas de connexion SQL directe depuis l'app).
**Prix** : gratuit jusqu'à 500 Mo de base de données et 5 Go de bande
passante/mois sur le plan actuel — largement suffisant pour ce volume
d'usage (quelques utilisateurs).

---

## 4. Données boursières

### yfinance (bibliothèque, pas un service à clé)
**Fonction** : source *primaire* voulue pour les prix, historiques OHLCV
et données pré-marché (`preMarketPrice`) — la seule des trois sources à
exposer un vrai prix pré-marché.
**Limite connue** : **bloqué au niveau réseau depuis Render** (Yahoo
Finance bloque les IP de Render) — fonctionne en local/dev, pas en
production. D'où le besoin des deux sources suivantes en secours.
**Prix** : gratuit (scrape l'API non-officielle de Yahoo Finance, pas de
clé requise).

### Finnhub
**Fonction** : prix "temps réel" (`/quote`), source *primaire* en
production pour le prix courant et la variation du jour.
**Limite connue** : hors séance, son `/quote` reste figé sur la clôture
de la veille (pas de vrai pré-marché sur le plan gratuit).
**Prix** : gratuit — 60 appels/minute.

### Twelve Data
**Fonction** : historique OHLCV (bougies quotidiennes) en secours de
yfinance pour tous les calculs techniques (RSI, moyennes mobiles, MACD…).
**Limite connue** : quota serré, ~8 crédits/minute réellement observés en
usage (au-delà : erreurs de rate-limit) — d'où les pauses entre appels
dans le scan d'opportunités.
**Prix** : gratuit — 800 appels/jour.

### Alpha Vantage *(exploré, non intégré)*
**Fonction envisagée** : alternative pour un vrai prix pré-marché.
**Résultat** : testé en réel le 31.07.2026 (clé fournie par l'utilisateur)
— son `GLOBAL_QUOTE` gratuit n'a pas de donnée pré-marché, et son
endpoint `extended_hours` est explicitely réservé aux offres payantes.
Non utilisé dans le code.
**Prix** : gratuit en usage basique (25 requêtes/jour) ; heures étendues
réservées aux plans payants (à partir de ~50$/mois selon leur grille).

### Financial Modeling Prep *(évoqué, jamais testé)*
**Fonction envisagée** : même piste qu'Alpha Vantage.
**Résultat** : la clé de démo publique ne fonctionne plus ; jamais testé
avec un vrai compte.
**Prix** : gratuit annoncé à 250 requêtes/jour sur leur doc — non vérifié.

---

## 5. Actualités

### NewsAPI
**Fonction** : articles de presse financière récents par ticker, utilisés
dans le score "médiatique" et l'analyse de sentiment.
**Prix** : gratuit — 100 requêtes/jour.
⚠️ **Point d'attention** : l'offre gratuite de NewsAPI est documentée par
eux comme réservée au développement (`localhost`), pas à un usage en
production — à garder en tête si le projet grandit.

### Flux RSS (feedparser)
**Fonction** : source complémentaire d'actualités (Google News RSS et
équivalents), sans clé — comble les trous quand NewsAPI ne remonte rien
ou est à quota.
**Prix** : gratuit (flux RSS publics).

---

## 6. Intelligence artificielle

### Groq
**Fonction** : moteur LLM *principal* — génère le texte d'explication de
chaque conseil ("pourquoi ce score, ce signal") en langage naturel.
Modèle : `llama-3.3-70b-versatile`.
**Prix** : gratuit — 14 400 requêtes/jour.

### Gemini (Google AI Studio)
**Fonction** : *uniquement* pour le grounding Google Search dans la
suggestion IA de l'univers de scan d'opportunités (savoir quels tickers
bougent réellement, pas juste ce que le modèle a mémorisé à
l'entraînement).
**Limite connue** : le *grounding* spécifiquement nécessite une carte
bancaire liée au projet Google Cloud (sinon "quota dépassé" même sous la
limite gratuite) ; et il est **bloqué géographiquement depuis Render**
(région Frankfurt/UE) — d'où le mode "copier-coller manuel" du prompt
utilisé aujourd'hui à la place d'un appel serveur automatique.
**Prix** : gratuit — 5 000 requêtes/mois (génération de texte simple) ;
le grounding reste gratuit sous quota une fois la carte liée.

### Ollama (fallback local)
**Fonction** : filet de secours pour la génération de texte si Groq est
indisponible — tourne en local sur la machine de dev, pas utilisable sur
Render (pas de GPU/RAM dédiée sur le plan gratuit).
**Prix** : gratuit et open-source, aucune clé — mais nécessite d'installer
et faire tourner Ollama soi-même.

---

## 7. Email

### Resend
**Fonction** : envoi de tous les emails automatiques — alertes de
variation, changements de conseil, TP/SL atteint, digest pré-marché,
rapport hebdomadaire.
**Prix** : gratuit — 3 000 emails/mois. Sans domaine propre vérifié,
l'expéditeur est limité à `onboarding@resend.dev` (adresse de test
fournie par Resend).

---

## 8. Frontend (chargé depuis un CDN, pas de compte/clé)

| Techno | Fonction | Prix |
|---|---|---|
| **Bootstrap 5.3.3** | Mise en page, composants UI (modales, boutons, formulaires) | Gratuit, open-source |
| **Bootstrap Icons 1.11.3** | Icônes (`bi bi-*`) utilisées partout dans l'interface | Gratuit, open-source |
| **Plotly.js** | Graphiques interactifs (courbe backtest, évolution du portefeuille) | Gratuit, open-source |

---

## 9. Backend Python — bibliothèques principales

| Bibliothèque | Rôle |
|---|---|
| **Flask** + flask-login/flask-wtf/flask-session | Framework web, authentification, formulaires, sessions |
| **gunicorn** | Serveur WSGI de production (celui que Render lance) |
| **pandas / numpy** | Manipulation des séries de prix, calculs techniques |
| **ta** | Indicateurs techniques (RSI, MACD, moyennes mobiles) |
| **scikit-learn** | Modèle de classification (probabilité de hausse à 20j, backtest) |
| **vaderSentiment** | Analyse de sentiment des actualités (fallback si pas de LLM) |
| **beautifulsoup4 / lxml** | Parsing HTML pour le scraping de secours |
| **bcrypt / cryptography** | Hachage des mots de passe, sécurité des tokens |
| **matplotlib** | Génération de graphiques statiques (export) |
| **python-dotenv** | Chargement des clés API depuis `.env` en local |

Toutes gratuites et open-source (pas de coût, juste du code).

---

## 10. Récapitulatif des coûts

| Service | Fonction | Coût actuel |
|---|---|---|
| Render | Hébergement web | Gratuit |
| cron-job.org | Déclencheur du scheduler | Gratuit |
| GitHub | Hébergement du code | Gratuit |
| Supabase | Base de données | Gratuit (< 500 Mo) |
| yfinance | Prix/pré-marché (bloqué en prod) | Gratuit |
| Finnhub | Prix temps réel | Gratuit (60/min) |
| Twelve Data | Historique OHLCV | Gratuit (800/jour) |
| NewsAPI | Actualités | Gratuit (100/jour, usage dev selon leurs CGU) |
| Groq | LLM principal | Gratuit (14 400/jour) |
| Gemini | Suggestion IA (grounding) | Gratuit (5 000/mois, carte requise) |
| Resend | Emails | Gratuit (3 000/mois) |
| Bootstrap / Plotly | Frontend | Gratuit (CDN) |

**Total actuel : 0 €/mois.** Le principal risque n'est pas financier mais
de **quota** (Twelve Data en particulier) et de **disponibilité des
données** (yfinance bloqué sur Render, aucune source gratuite de vrai
prix pré-marché) — des compromis déjà documentés dans le code au fil des
sessions plutôt que des coûts cachés.
