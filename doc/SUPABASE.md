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
  prix    FLOAT
);

-- Cache pipeline sérialisé (TTL 24h)
CREATE TABLE ticker_snapshots (
  ticker     TEXT PRIMARY KEY,
  payload    JSONB NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT now()
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
  bon_conseil       BOOLEAN,             -- TRUE si le conseil était pertinent (sens correct)
  evaluated_at      TIMESTAMPTZ,
  UNIQUE(username, ticker, date_conseil)
);
```

---

## Activer RLS (Row Level Security)

RLS doit être activé sur **toutes les tables**. L'app utilise la `service_role` key côté serveur, qui bypasse RLS — l'activation empêche tout accès direct non autorisé via la clé anon.

```sql
ALTER TABLE users             ENABLE ROW LEVEL SECURITY;
ALTER TABLE watchlist         ENABLE ROW LEVEL SECURITY;
ALTER TABLE scores            ENABLE ROW LEVEL SECURITY;
ALTER TABLE ticker_snapshots  ENABLE ROW LEVEL SECURITY;
ALTER TABLE positions         ENABLE ROW LEVEL SECURITY;
ALTER TABLE daily_advice      ENABLE ROW LEVEL SECURITY;
ALTER TABLE position_targets    ENABLE ROW LEVEL SECURITY;
ALTER TABLE portfolio_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE advisor_config      ENABLE ROW LEVEL SECURITY;
ALTER TABLE weekly_reports      ENABLE ROW LEVEL SECURITY;
```

Aucune policy supplémentaire n'est nécessaire : l'app accède toujours via `service_role` (bypass RLS).

---

## Migrations sur une installation existante

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

## Fallback local (dev sans Supabase)

| Données | Fichier local |
|---|---|
| Utilisateurs | `auth/users.yaml` |
| Watchlist | `watchlist/watchlist.json` |
| Scores | `watchlist/last_scores.json` |
| Positions | `portfolio/positions_local.json` |

Le fallback est actif automatiquement quand les variables Supabase sont absentes du `.env`.
