# SDE — Configuration Supabase

Supabase est le backend de persistance principal. Il expose une API REST sur HTTPS (port 443), compatible avec Render et tout environnement cloud.

---

## Création du projet

1. [supabase.com](https://supabase.com) → **New project**
2. Nom : `sde` — région : **Frankfurt (eu-central-1)**
3. Attendre ~1 min que le projet soit prêt

---

## Schéma SQL complet

**SQL Editor → New query** — exécuter une seule fois sur une installation vierge :

```sql
-- Comptes utilisateurs
CREATE TABLE users (
  username TEXT PRIMARY KEY,
  name     TEXT NOT NULL,
  email    TEXT DEFAULT '',
  password TEXT NOT NULL
);

-- Tickers suivis par utilisateur
CREATE TABLE watchlist (
  id       SERIAL PRIMARY KEY,
  username TEXT NOT NULL,
  ticker   TEXT NOT NULL,
  company  TEXT DEFAULT '',
  added_at TEXT DEFAULT '',
  UNIQUE(username, ticker)
);

-- Dernier score/reco connu par ticker (scheduler)
CREATE TABLE scores (
  ticker  TEXT PRIMARY KEY,
  score   FLOAT,
  reco    TEXT,
  updated TEXT,
  prix    FLOAT,
  var_alerte_pct  FLOAT,   -- dernier palier de variation quotidienne alerté (5, 10, 15…)
  var_alerte_date TEXT,    -- date (YYYY-MM-DD) de ce palier — anti-spam par jour
  hyst_stable     TEXT,    -- recommandation STABLE (lissée par hystérésis)
  hyst_candidat   TEXT,    -- nouvelle reco candidate pas encore confirmée
  hyst_streak     INTEGER  -- nombre de calculs frais consécutifs confirmant le candidat
);

-- Cache pipeline sérialisé (TTL 24h)
CREATE TABLE ticker_snapshots (
  ticker       TEXT PRIMARY KEY,
  data         JSONB NOT NULL,       -- colonne "data" (pas "payload")
  refreshed_at TIMESTAMPTZ DEFAULT now()
);

-- Dernier Top 5 du scan d'opportunités admin (single-row, id=1 fixe)
CREATE TABLE opportunites_scan (
  id           INTEGER PRIMARY KEY DEFAULT 1,
  resultats    JSONB,
  derniere_maj TEXT,
  CHECK (id = 1)
);

-- Override de l'univers de scan d'opportunités (single-row, id=1 fixe)
CREATE TABLE opportunites_univers (
  id           INTEGER PRIMARY KEY DEFAULT 1,
  tickers      JSONB,
  derniere_maj TEXT,
  CHECK (id = 1)
);

-- Lots d'achat ET de vente par utilisateur (supporte le DCA et les ventes partielles)
CREATE TABLE positions (
  id           SERIAL PRIMARY KEY,
  username     TEXT NOT NULL,
  ticker       TEXT NOT NULL,
  company      TEXT DEFAULT '',
  date_achat   DATE NOT NULL,
  prix_achat   FLOAT NOT NULL,
  quantite     FLOAT NOT NULL,
  currency     TEXT DEFAULT 'USD',
  notes        TEXT DEFAULT '',
  type         TEXT DEFAULT 'achat',  -- 'achat' ou 'vente'
  conseil_date DATE,                  -- date du conseil qui a déclenché la transaction (NULL si saisie manuelle)
  created_at   TIMESTAMPTZ DEFAULT now()
);

-- Conseils journaliers + évaluation automatique J+1
CREATE TABLE daily_advice (
  id                SERIAL PRIMARY KEY,
  username          TEXT NOT NULL,
  ticker            TEXT NOT NULL,
  date_conseil      DATE NOT NULL,
  action            TEXT NOT NULL,        -- ACHETER / RENFORCER / TENIR / SURVEILLER / ALLÉGER / VENDRE
  quantite_suggeree FLOAT,
  prix_jour         FLOAT,
  prix_cible        FLOAT,
  score_sde         FLOAT,
  recommandation    TEXT,
  raisonnement      TEXT,
  prix_j1           FLOAT,               -- prix de clôture le lendemain (évaluation J+1)
  variation_j1      FLOAT,               -- variation % entre prix_jour et prix_j1
  bon_conseil       BOOLEAN,             -- TRUE si le conseil était pertinent à J+1 (sens correct)
  evaluated_at      TIMESTAMPTZ,
  signaux_actifs    JSONB,               -- {code_signal: points} actifs au moment du conseil
  prix_j5           FLOAT,               -- évaluation multi-horizons : clôture 5 séances après
  variation_j5      FLOAT,
  bon_conseil_j5    BOOLEAN,
  prix_j20          FLOAT,               -- J+20 = l'horizon qui fait foi (signaux 14-50j)
  variation_j20     FLOAT,
  bon_conseil_j20   BOOLEAN,
  gain_j20_pct      FLOAT,               -- gain/coût réel signé du conseil directionnel à J+20
  UNIQUE(username, ticker, date_conseil)
);
```

---

## Activer RLS (Row Level Security) — tables initiales

RLS doit être activé sur **toutes les tables**. L'app utilise la `service_role` key côté serveur, qui bypasse RLS — l'activation empêche tout accès direct non autorisé via la clé anon.

```sql
-- À exécuter juste après le schéma initial (6 tables ci-dessus)
ALTER TABLE users             ENABLE ROW LEVEL SECURITY;
ALTER TABLE watchlist         ENABLE ROW LEVEL SECURITY;
ALTER TABLE scores            ENABLE ROW LEVEL SECURITY;
ALTER TABLE ticker_snapshots  ENABLE ROW LEVEL SECURITY;
ALTER TABLE positions         ENABLE ROW LEVEL SECURITY;
ALTER TABLE daily_advice      ENABLE ROW LEVEL SECURITY;
```

Aucune policy supplémentaire n'est nécessaire : l'app accède toujours via `service_role` (bypass RLS).

> Les tables créées par migration (weekly_reports, advisor_config, portfolio_snapshots, position_targets, auth_tokens) activent RLS dans leur propre bloc ci-dessous.

---

## Vérifier que le schéma est à jour

Les migrations ci-dessous doivent être exécutées **à la main** dans l'éditeur SQL
Supabase — une migration oubliée ne casse rien visiblement (le code retombe en
mode dégradé) mais des fonctionnalités meurent en silence. Pour vérifier :

```bash
python check_supabase_schema.py
```

Le script sonde toutes les tables et colonnes critiques et affiche ✓/✗.
À lancer après chaque migration, et à compléter (`SCHEMA_ATTENDU`) à chaque
nouvelle colonne ajoutée ici.

---

## Migrations sur une installation existante

**Table `opportunites_univers`** (2026-07-23 — override persisté de l'univers
de scan d'opportunités : par défaut `UNIVERS_SCAN` dans analysis/screener.py,
remplaçable via le bouton "Rafraîchir via IA" + "Appliquer" de la page
opportunités. Single-row, `id=1` fixe, upsert) :

```sql
CREATE TABLE IF NOT EXISTS opportunites_univers (
  id           INTEGER PRIMARY KEY DEFAULT 1,
  tickers      JSONB,
  derniere_maj TEXT,
  CHECK (id = 1)
);
```

**Table `opportunites_scan`** (2026-07-22 — persistance du dernier Top 5 du
scan d'opportunités admin. Sans elle, le résultat ne vit qu'en mémoire
process et disparaît au recyclage du worker gunicorn (`max_requests=200`,
cf. section Mémoire & performances) ; single-row, `id=1` fixe, upsert) :

```sql
CREATE TABLE IF NOT EXISTS opportunites_scan (
  id           INTEGER PRIMARY KEY DEFAULT 1,
  resultats    JSONB,
  derniere_maj TEXT,
  CHECK (id = 1)
);
```

**Colonnes `var_alerte_pct` / `var_alerte_date`** (2026-07-17 — alerte de
variation QUOTIDIENNE vs clôture de la veille, par paliers de 5% avec
anti-spam ; l'ancienne comparaison au passage précédent ratait les chutes
progressives : -8.5% par pas de 1% ne franchissait jamais le seuil) :

```sql
ALTER TABLE scores
  ADD COLUMN IF NOT EXISTS var_alerte_pct  FLOAT,
  ADD COLUMN IF NOT EXISTS var_alerte_date TEXT;
```

**Colonnes `hyst_stable` / `hyst_candidat` / `hyst_streak`** (2026-07-19 —
hystérésis sur la recommandation globale : le score de TMC a franchi les
seuils ACHETER/VENDRE 6 fois en une semaine, provoquant des allers-retours
de conseil. La reco stable n'adopte un changement qu'après confirmation
sur 2 calculs frais consécutifs, ou un franchissement net) :

```sql
ALTER TABLE scores
  ADD COLUMN IF NOT EXISTS hyst_stable   TEXT,
  ADD COLUMN IF NOT EXISTS hyst_candidat TEXT,
  ADD COLUMN IF NOT EXISTS hyst_streak   INTEGER;
```


**Colonne `signaux_actifs`** (2026-07-08 — vecteur de signaux techniques stocké
avec chaque conseil ; matière première de la future calibration adaptative des
poids ; sans elle les conseils sont sauvés mais sans le détail des signaux) :

```sql
ALTER TABLE daily_advice ADD COLUMN IF NOT EXISTS signaux_actifs JSONB;
```

**Colonnes évaluation multi-horizons** (2026-07-08 — le conseil s'appuie sur des
signaux 14-50j : le juger à J+1 seul mesure surtout le bruit quotidien. J+20 est
l'horizon qui fait foi ; `gain_j20_pct` = gain/coût réel signé du conseil.
Sans ces colonnes, l'évaluateur retombe en mode J+1 seul) :

```sql
ALTER TABLE daily_advice
  ADD COLUMN IF NOT EXISTS prix_j5         FLOAT,
  ADD COLUMN IF NOT EXISTS variation_j5    FLOAT,
  ADD COLUMN IF NOT EXISTS bon_conseil_j5  BOOLEAN,
  ADD COLUMN IF NOT EXISTS prix_j20        FLOAT,
  ADD COLUMN IF NOT EXISTS variation_j20   FLOAT,
  ADD COLUMN IF NOT EXISTS bon_conseil_j20 BOOLEAN,
  ADD COLUMN IF NOT EXISTS gain_j20_pct    FLOAT;
```

**Table `weekly_reports`** (anti-doublon rapport hebdo — à créer si absente) :

```sql
CREATE TABLE IF NOT EXISTS weekly_reports (
  id         BIGSERIAL PRIMARY KEY,
  username   TEXT NOT NULL,
  week_start DATE NOT NULL,
  sent_at    TIMESTAMPTZ DEFAULT now(),
  UNIQUE(username, week_start)
);

ALTER TABLE weekly_reports ENABLE ROW LEVEL SECURITY;
```

**Table `advisor_config`** (seuils de conseil configurables — à créer si absente) :

```sql
CREATE TABLE IF NOT EXISTS advisor_config (
  username        TEXT PRIMARY KEY,
  stop_loss_pct   FLOAT DEFAULT -20,
  take_profit_pct FLOAT DEFAULT 15,
  score_acheter   FLOAT DEFAULT 60,
  score_vendre    FLOAT DEFAULT 38,
  rsi_renforcer   FLOAT DEFAULT 42,
  pnl_renforcer   FLOAT DEFAULT -5,
  score_tenir     FLOAT DEFAULT 62,
  var_tenir_eval  FLOAT DEFAULT 3,
  updated_at      TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE advisor_config ENABLE ROW LEVEL SECURITY;
```

**Table `portfolio_snapshots`** (historique de valeur du portefeuille — à créer si absente) :

```sql
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
  id             BIGSERIAL PRIMARY KEY,
  username       TEXT NOT NULL,
  snapshot_date  DATE NOT NULL,
  currency       TEXT NOT NULL DEFAULT 'USD',
  portfolio_val  FLOAT NOT NULL DEFAULT 0,
  cash_dispo     FLOAT NOT NULL DEFAULT 0,
  total_compte   FLOAT NOT NULL DEFAULT 0,
  pnl_cumul      FLOAT NOT NULL DEFAULT 0,
  created_at     TIMESTAMPTZ DEFAULT now(),
  UNIQUE(username, snapshot_date, currency)
);

ALTER TABLE portfolio_snapshots ENABLE ROW LEVEL SECURITY;
```

**Table `position_targets`** (Take Profit / Stop Loss — à créer si absente) :

```sql
CREATE TABLE IF NOT EXISTS position_targets (
  id             BIGSERIAL PRIMARY KEY,
  username       TEXT NOT NULL,
  ticker         TEXT NOT NULL,
  take_profit    FLOAT,
  stop_loss      FLOAT,
  tp_alerted_at  TIMESTAMPTZ,
  sl_alerted_at  TIMESTAMPTZ,
  updated_at     TIMESTAMPTZ DEFAULT now(),
  UNIQUE(username, ticker)
);

ALTER TABLE position_targets ENABLE ROW LEVEL SECURITY;
```

**Table `users`** (colonne avatar — à ajouter si absente) :

```sql
ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar TEXT DEFAULT '';
```

**Table `auth_tokens`** (activation de compte + reset de mot de passe — à créer si absente) :

```sql
CREATE TABLE IF NOT EXISTS auth_tokens (
  id         BIGSERIAL PRIMARY KEY,
  username   TEXT NOT NULL,
  token      TEXT NOT NULL UNIQUE,
  type       TEXT NOT NULL,        -- 'activation' | 'reset'
  expires_at TIMESTAMPTZ NOT NULL,
  used       BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE auth_tokens ENABLE ROW LEVEL SECURITY;
```

**Table `users`** (colonne activation — à ajouter si absente) :

```sql
-- Les comptes existants restent actifs (DEFAULT TRUE)
-- Les nouvelles inscriptions avec email partent à FALSE jusqu'à activation
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN DEFAULT TRUE;
```

**Table `positions`** (colonnes ajoutées après création initiale) :

```sql
-- Ajouter la colonne type (achat par défaut pour les lots existants)
ALTER TABLE positions ADD COLUMN IF NOT EXISTS type TEXT DEFAULT 'achat';

-- Ajouter la colonne conseil_date (lien explicite avec le conseil déclencheur)
ALTER TABLE positions ADD COLUMN IF NOT EXISTS conseil_date DATE;
```

---

## Récupérer les clés

**Project Settings → API** :

| Variable | Source Supabase | Usage |
|---|---|---|
| `SUPABASE_URL` | Project URL | Toutes les requêtes |
| `SUPABASE_SERVICE_KEY` | `service_role` key | **Production** — bypass RLS, server-side uniquement |
| `SUPABASE_KEY` | `anon` / `public` key | Fallback dev local si SERVICE_KEY absent |

> `SUPABASE_SERVICE_KEY` est la clé principale utilisée par l'app en production.  
> Ne jamais l'exposer côté client ni dans le code source.

---

## Variables d'environnement

### Local (`.env`)
```env
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_SERVICE_KEY=eyJhbGci...   # service_role — obligatoire
SUPABASE_KEY=eyJhbGci...           # anon — fallback optionnel
```

### Render (Production)
Render → Service → **Environment** → ajouter :
- `SUPABASE_URL`
- `SUPABASE_SERVICE_KEY`

---

## Architecture de la couche DB (`db.py`)

`db.py` expose une interface générique utilisée par tous les modules :

| Fonction | Description |
|---|---|
| `is_available()` | `True` si Supabase est configuré |
| `find_one(table, filter)` | SELECT … LIMIT 1 |
| `find(table, filter)` | SELECT … |
| `insert_one(table, doc)` | INSERT |
| `update_one(table, filter, update, upsert)` | UPDATE ou UPSERT |
| `delete_one(table, filter)` | DELETE |
| `count_documents(table, filter)` | COUNT |

`db.py` utilise `SUPABASE_SERVICE_KEY` en priorité (bypass RLS).  
Si absent, bascule sur `SUPABASE_KEY` (anon).  
Si les deux sont absents, toutes les fonctions retournent `None` / `[]` / `0`.

---

## Cache snapshot (`snapshot.py`)

Le module `snapshot.py` sérialise le résultat complet du pipeline dans `ticker_snapshots` :

- **TTL** : 24h (configurable via `MAX_AGE_HOURS`)
- **Sérialisation** : DataFrames → listes de dicts, numpy → scalaires Python natifs
- **Désérialisation** : reconstruction des DataFrames avec DatetimeIndex

Flux d'une requête d'analyse :
```
1. Cache mémoire (15 min)       → hit → réponse immédiate
2. ticker_snapshots (< 24h)     → hit → prix superposé via get_live_price()
3. Pipeline complet              → calcul → sauvegardé en mémoire + Supabase
```

---

## Logique P&L positions (`positions.py`)

La colonne `type` permet de distinguer achats et ventes dans `get_portfolio_summary()` :

```
total_buy_shares  = Σ quantite  pour type='achat'
total_sell_shares = Σ quantite  pour type='vente'
total_shares      = total_buy_shares - total_sell_shares
cout_moyen        = total_buy_amount / total_buy_shares

pnl_realise     = Σ(prix_vente × qty_vendue) - (total_sell_shares × cout_moyen)
pnl_non_realise = total_shares × (prix_live - cout_moyen)   [0 si position fermée]
pnl_total       = pnl_realise + pnl_non_realise
```

La colonne `conseil_date` est renseignée quand l'utilisateur clique sur un badge conseil (date du conseil cliqué). Elle est `NULL` pour les saisies manuelles. Utilisée pour le ✓ Suivi et les KPIs admin.

---

## Évaluation J+1 des conseils (`daily_advice`)

La colonne `bon_conseil` est remplie par deux chemins :

| Chemin | Déclencheur | Fenêtre | Source prix |
|---|---|---|---|
| `evaluate_yesterday_advice()` | Scheduler (toutes les 30 min) | **20h00–22h00 Paris** | Finnhub live |
| `evaluate_pending()` | Ouverture dashboard admin | Conseils antérieurs à aujourd'hui | yfinance historique |

**Fenêtre 20h–22h** : restreinte à la fin de séance pour éviter le bruit du prix d'ouverture (les 5–15 premières minutes du marché sont volatiles et peu représentatives de la tendance J+1).

**`reset_intraday_evals()`** : appelée automatiquement avant `evaluate_pending()` dans la route admin. Invalide les évaluations des 7 derniers jours qui ont été faites hors de la fenêtre 20h–22h (e.g. évaluations hors-marché avec prix stale) pour forcer une ré-évaluation propre.

**Colonnes clés `daily_advice`** :
- `prix_jour` : prix au moment de la génération du conseil (J0)
- `prix_j1` : prix de clôture le lendemain évalué (J+1, fin de séance)
- `variation_j1` : `(prix_j1 - prix_jour) / prix_jour × 100`
- `bon_conseil` : `TRUE` si le sens était correct (NULL = pas encore évalué)
- `evaluated_at` : timestamp de l'évaluation (utile pour détecter les évaluations hors-fenêtre)

---

## Fallback local (dev sans Supabase)

| Données | Fichier local |
|---|---|
| Utilisateurs | `auth/users.yaml` |
| Watchlist | `watchlist/watchlist.json` |
| Scores | `watchlist/last_scores.json` |
| Positions | `portfolio/positions_local.json` |

Le fallback est actif automatiquement quand les variables Supabase sont absentes du `.env`.
