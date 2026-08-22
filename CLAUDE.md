# SDE — Stock Decision Engine (Flask)

Ce fichier est lu automatiquement par Claude Code à chaque session, sur
n'importe quelle machine où ce dépôt est cloné. Il capture les conventions
de travail établies et les pièges déjà rencontrés — pas l'historique complet
(pour ça : `git log`, `doc/STACK_TECHNIQUE.md`, `doc/SUPABASE.md`).

## Le projet en une phrase

Application Flask d'aide à la décision boursière : analyse multi-signaux
(technique/fondamental/média/IA), conseil quotidien par position, portefeuille
avec P&L, dashboard admin d'évaluation de la fiabilité des conseils.

**Objectif métier** (pas juste "avoir raison sur chaque trade") : faire
grandir la VALEUR TOTALE DU COMPTE = cash suivi + valeur de marché du
portefeuille. Le cash est une position à part entière, pas une absence de
conseil. Toute nouvelle métrique se juge à l'aune de cette valeur totale.

- **Dépôt** : github.com/cybkilla/sde_flask, branche `main`
- **Prod** : https://sde-flask.onrender.com (Render, plan gratuit)
- **Compte principal** : username `admin` (email cybkilla@gmail.com) — c'est
  sous ce nom que positions et watchlist sont stockées, pas "Vlad" (le nom
  affiché) ni "vlad"
- **Lancer en local** : `python run_flask.py` (port 5000) ou
  `docker compose up --build` (plus proche de la prod, gunicorn)
- Détail complet de la stack, des services externes et de leurs coûts :
  `doc/STACK_TECHNIQUE.md`. Schéma Supabase et migrations : `doc/SUPABASE.md`.

## Architecture essentielle

- `run_flask.py` → `flask_app/__init__.py::create_app()` (factory)
- Blueprints : `auth`, `stock` (page d'accueil + analyse), `portfolio`
  (positions, conseils, Q&A), `cron` (scheduler HTTP), `admin`, `profile`
- `pipeline.py` : orchestrateur principal appelé par `/analyze/<ticker>`
- Cache à 3 niveaux : mémoire (15 min) → snapshot Supabase (24h) → pipeline
  complet. `snapshot.py` gère la sérialisation JSONB des DataFrames.
- Scheduler deux vitesses (`alerts/scheduler.py`) : chemin rapide (prix live
  Finnhub, toutes les 30 min via cron-job.org → `/scheduler/run`) vs chemin
  complet (pipeline entier, 1×/jour si snapshot > 24h)
- Données marché : yfinance en primaire (bloqué depuis les IP Render —
  fonctionne en local/Docker) → Finnhub (quote live) → Twelve Data (OHLCV)
  en secours cloud
- Persistance : Supabase (PostgreSQL via REST), pas de connexion SQL directe
- gunicorn `workers=1` en prod (Render free tier 512 Mo — plus de workers = OOM)

## Conventions de travail (à respecter sans qu'on ait besoin de le redemander)

- **Toujours demander confirmation avant `git commit`/`git push`** — même
  pour un correctif urgent. Récapituler ce qui va être commité avant de
  demander. Raccourci établi : l'utilisateur tape **"cp"** pour valider
  commit + push d'un coup.
- Grouper les modifications d'une même session avant de committer plutôt que
  committer à chaque petite modification (chaque push déclenche un rebuild
  Render de 5-10 min).
- **Commentaires de code** : écrire comme un formateur Python — expliquer le
  POURQUOI d'un choix technique, nommer les concepts Pandas/Python utilisés,
  rester court (1-2 lignes). Pas de commentaire qui décrit juste ce que fait
  une ligne évidente.
- **Toute modification du schéma Supabase** (nouvelle table/colonne) →
  mettre à jour `doc/SUPABASE.md` (schéma de référence + section migrations
  datée) ET `check_supabase_schema.py::SCHEMA_ATTENDU`, dans le même commit.
  Avant de créer une nouvelle table pour une donnée liée à un utilisateur,
  se demander si c'est un attribut scalaire (→ colonne sur `users`, comme
  email/password) ou un historique un-à-plusieurs (→ table séparée, comme
  positions/daily_advice).
- **Nouvelle fonctionnalité visible utilisateur** → mettre à jour
  `flask_app/static/presentation_utilisateurs.html` ET
  `doc/presentation_utilisateurs.html` (toujours synchronisées, copies
  identiques), dans le même commit. Max 12 slides — modifier une slide
  existante plutôt qu'en ajouter une si possible.
- `doc/EVALUATION.md` : ne plus le mettre à jour (jugé obsolète par
  l'utilisateur, 22.07.2026) — ne pas le supprimer sans demander non plus.
- **Tests** : scripts `assert` + `print("✓ ...")` purs dans `tests/test_*.py`,
  lancés individuellement (`python tests/test_X.py`) — pas de framework
  (pytest etc.). Toute fonction touchant DB/réseau doit être monkeypatchée
  dans le test (jamais de vrai appel Supabase/API depuis un test — un
  incident passé a écrit des données de test dans la vraie prod). Lancer
  toute la suite avant de proposer un commit :
  `for f in tests/test_*.py; do python "$f"; done`

## Pièges déjà rencontrés (pour ne pas les redécouvrir)

- **"Repli silencieux sur du vide" — le bug le plus récurrent du projet.**
  Motif : `if _db_ok(): try: ... except: pass` puis retour sur un fichier
  JSON local quasi toujours vide en prod. Trouvé et corrigé 3 fois
  (positions.py, watchlist.py, auth.py, 18-21.08.2026) — un vrai problème
  réseau/Supabase se déguisait en "aucune donnée" ou "mot de passe
  incorrect" plutôt qu'une erreur honnête. Si un nouveau symptôme du genre
  "ça a l'air vide/refusé sans raison" apparaît, chercher ce pattern en
  premier. Exception délibérée : `load_user()` (callback Flask-Login,
  rechargé à CHAQUE page) doit rester dégradé en déconnexion plutôt que de
  planter toute page — documenté dans son propre commentaire.
- **`request.remote_addr` vaut `127.0.0.1` pour tout le monde sur Render**
  sans `ProxyFix` (déjà en place dans `flask_app/__init__.py`) — sans ça,
  tout rate-limiting par IP (ex. login, 5 tentatives/15 min) devient un
  compteur global partagé par tous les visiteurs.
- **`.env` doit être chargé explicitement en tête de `flask_app/__init__.py`**
  (`load_dotenv()`) — ne pas compter sur l'import indirect de `config.py`
  via les blueprints, ça arrive trop tard pour les vérifications faites
  tout en haut de `create_app()` (ex. `FLASK_SECRET_KEY`).
- **Finnhub hors séance** : le champ `c` (quote) est la clôture RÉELLE de
  J-1, PAS un prix pré-marché ; `pc` est la clôture de J-2. Vérifier la
  sémantique EXACTE d'un champ d'API avant de choisir comment l'afficher —
  ne pas juste patcher le symptôme.
- **Yahoo/yfinance renvoie parfois `NaN`** (pas `None`/absent) pour des
  champs numériques — `NaN` est *truthy* en Python (`if prev:` le laisse
  passer) et Supabase (JSON strict) rejette `NaN` à l'écriture. Utiliser
  `_safe()` (déjà dans `data/market.py`, basé sur `pd.isna()`) plutôt qu'un
  simple `is None`.
- **yfinance bloqué depuis les IP Render** — fonctionne en local et en
  Docker, pas en prod. Le relais pré-marché (`scripts/premarche_relay.py`,
  GitHub Actions) contourne ça pour les prix pré-marché spécifiquement.
- **P&L dilué vs P&L de la position actuelle** : `get_portfolio_summary()`
  renvoie `pnl_pct` (dilué sur tout l'historique d'achat, légitime pour un
  affichage "performance globale") ET `pnl_position_pct` (non dilué, coût
  moyen des seules actions détenues). Les décisions de seuil de risque
  (stop loss, take profit, renforcement dans `advisor.py`) doivent utiliser
  `pnl_position_pct`, jamais `pnl_pct` — la dilution retarderait leur
  déclenchement.
- **Un signal SDE ne doit jamais être supprimé/rétrogradé par une
  contrainte externe** (trésorerie insuffisante, etc.) — seulement annoté
  dans le raisonnement. Principe de conception explicite de l'utilisateur.
- Après une install Windows (Git, Python, Docker Desktop) : **fermer
  complètement VSCode** (pas juste un nouvel onglet de terminal) pour que
  le PATH se rafraîchisse.

## Mémoire Claude Code

Ce fichier est partagé via git (visible sur toute machine où le dépôt est
cloné). La mémoire *conversationnelle* de Claude Code (contexte accumulé
au fil des sessions passées) reste en revanche locale à chaque machine —
elle ne suit pas le dépôt.
