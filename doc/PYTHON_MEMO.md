# Python, Pandas & Flask — Mémo

---

## Variables & Types de base

```python
x = 42          # int
pi = 3.14       # float
nom = "Alice"   # str
ok = True       # bool
rien = None     # NoneType

type(x)         # <class 'int'>
isinstance(x, int)  # True
```

---

## Listes

```python
# Déclaration
fruits = ["pomme", "banane", "cerise"]

# Accès
fruits[0]       # "pomme"
fruits[-1]      # "cerise"  (dernier)
fruits[1:3]     # ["banane", "cerise"]  (slice)

# Modifier
fruits[0] = "kiwi"
fruits.append("mangue")     # ajoute à la fin
fruits.insert(1, "poire")   # insère à l'index 1
fruits.remove("banane")     # supprime par valeur
fruits.pop(0)               # supprime par index

# Infos
len(fruits)         # nombre d'éléments
"kiwi" in fruits    # True / False

# Itération
for f in fruits:
    print(f)

for i, f in enumerate(fruits):   # avec index
    print(i, f)

# List comprehension
majuscules = [f.upper() for f in fruits]
longs = [f for f in fruits if len(f) > 4]
```

---

## Dictionnaires

```python
# Déclaration
personne = {"nom": "Alice", "age": 30, "ville": "Paris"}

# Accès
personne["nom"]             # "Alice"
personne.get("email", "")   # "" si clé absente (pas d'erreur)

# Modifier / ajouter
personne["age"] = 31
personne["email"] = "alice@mail.com"

# Supprimer
del personne["ville"]
personne.pop("email", None)   # None si absent

# Infos
"nom" in personne       # True
personne.keys()         # dict_keys(["nom", "age"])
personne.values()       # dict_values(["Alice", 31])
personne.items()        # paires (clé, valeur)

# Itération
for cle, val in personne.items():
    print(cle, "→", val)

# Dict comprehension
carre = {n: n**2 for n in range(5)}  # {0:0, 1:1, 2:4, 3:9, 4:16}
```

---

## Tuples & Sets

```python
coords = (48.85, 2.35)   # tuple — immuable
coords[0]                 # 48.85
a, b = coords             # unpacking

unique = {1, 2, 2, 3}    # set — {1, 2, 3}, pas de doublon
unique.add(4)
unique.discard(2)
```

---

## Conditions

```python
# Standard
if x > 10:
    print("grand")
elif x == 10:
    print("égal")
else:
    print("petit")

# Ternaire (une ligne)
statut = "majeur" if age >= 18 else "mineur"

# Chaîné
label = "haut" if score > 70 else ("moyen" if score > 40 else "bas")
```

---

## Boucles

```python
# for classique
for i in range(5):        # 0, 1, 2, 3, 4
    print(i)

for i in range(2, 10, 2): # 2, 4, 6, 8
    print(i)

# while
i = 0
while i < 5:
    i += 1

# break / continue
for n in range(10):
    if n == 3: continue   # saute le 3
    if n == 7: break      # stop au 7
```

---

## Fonctions

```python
# Déclaration
def saluer(nom, titre="M."):
    return f"Bonjour {titre} {nom}"

saluer("Dupont")            # "Bonjour M. Dupont"
saluer("Curie", "Mme")     # "Bonjour Mme Curie"

# *args (liste variable) / **kwargs (dict variable)
def somme(*args):
    return sum(args)        # somme(1, 2, 3) → 6

def afficher(**kwargs):
    for k, v in kwargs.items(): print(k, v)

# Lambda (fonction anonyme courte)
double = lambda x: x * 2
double(5)   # 10

carre = lambda x: x**2
sorted([3,1,2], key=lambda x: -x)  # [3, 2, 1]
```

---

## Classes

```python
class Animal:
    def __init__(self, nom, poids):   # constructeur
        self.nom = nom
        self.poids = poids

    def parle(self):
        return f"{self.nom} fait un bruit"

    def __repr__(self):               # affichage
        return f"Animal({self.nom})"

class Chien(Animal):                  # héritage
    def parle(self):                  # surcharge
        return f"{self.nom} aboie !"

rex = Chien("Rex", 25)
rex.parle()   # "Rex aboie !"
```

---

## Erreurs & Exceptions

```python
try:
    resultat = 10 / 0
except ZeroDivisionError as e:
    print("Erreur :", e)
except (ValueError, TypeError):
    print("Valeur ou type invalide")
finally:
    print("toujours exécuté")

# Lever une exception
raise ValueError("Valeur négative interdite")
```

---

## Fichiers & JSON

```python
import json

# Lire
with open("data.json") as f:
    data = json.load(f)       # dict/list Python

# Écrire
with open("data.json", "w") as f:
    json.dump(data, f, indent=2)

# Fichier texte
with open("notes.txt") as f:
    lignes = f.readlines()    # liste de str
```

---

## Chaînes de caractères

```python
s = "  Hello World  "
s.strip()           # "Hello World"
s.lower()           # "  hello world  "
s.upper()           # "  HELLO WORLD  "
s.replace("o", "0") # "  Hell0 W0rld  "
s.split(" ")        # ["", "", "Hello", "World", "", ""]
",".join(["a","b"]) # "a,b"
"World" in s        # True

# f-string
nom, score = "Alice", 87.5
f"{nom} a eu {score:.1f}/100"   # "Alice a eu 87.5/100"
f"{score:+.2f}"                  # "+87.50"
f"{'oui' if score > 50 else 'non'}"  # "oui"
```

---

## Pandas — Essentiels

```python
import pandas as pd
import numpy as np
```

### Créer un DataFrame

```python
df = pd.DataFrame({
    "nom":   ["Alice", "Bob", "Clara"],
    "age":   [30, 25, 35],
    "score": [87.5, 62.0, np.nan]
})
```

### Lire / Écrire

```python
df = pd.read_csv("data.csv")
df = pd.read_json("data.json")
df.to_csv("out.csv", index=False)
```

### Infos générales

```python
df.shape          # (3, 3) — lignes × colonnes
df.dtypes         # types de chaque colonne
df.info()         # résumé + mémoire
df.describe()     # stats : mean, std, min, max…
df.head(2)        # 2 premières lignes
```

### Accès aux données

```python
df["age"]              # Series (colonne)
df[["nom", "age"]]     # DataFrame (plusieurs colonnes)

df.loc[0]              # ligne par label/index
df.loc[0, "nom"]       # cellule précise
df.iloc[1, 2]          # ligne 1, colonne 2 (position)
df.iloc[:2]            # 2 premières lignes
```

### Filtres

```python
df[df["age"] > 28]                          # filtre simple
df[(df["age"] > 25) & (df["score"] > 60)]  # ET
df[df["nom"].isin(["Alice", "Clara"])]      # isin
df[df["nom"].str.startswith("A")]           # str filter
```

### Modifier

```python
df["age"] = df["age"] + 1                   # modifier colonne
df["adulte"] = df["age"] >= 18              # nouvelle colonne booléenne
df["label"] = df["score"].apply(
    lambda x: "bon" if x > 70 else "moyen" # apply + lambda
)
df.rename(columns={"nom": "name"}, inplace=True)
df.drop(columns=["adulte"], inplace=True)
df.drop(index=0, inplace=True)
```

### NaN (valeurs manquantes)

```python
df.isna()                    # masque booléen
df.isna().sum()              # nb de NaN par colonne
df.dropna()                  # supprime lignes avec NaN
df["score"].fillna(0)        # remplace NaN par 0
df["score"].fillna(df["score"].mean())  # remplace par moyenne
```

### Trier & Grouper

```python
df.sort_values("score", ascending=False)

df.groupby("adulte")["score"].mean()   # moyenne par groupe
df.groupby("adulte").agg({"score": ["mean","max"], "age": "min"})
```

### Fusionner des DataFrames

```python
# Comme un JOIN SQL
pd.merge(df1, df2, on="id", how="left")   # left join
pd.concat([df1, df2], ignore_index=True)   # empilement vertical
```

### Opérations sur Series

```python
s = df["score"]
s.mean()     # moyenne
s.max()      # maximum
s.min()      # minimum
s.sum()      # somme
s.std()      # écart-type
s.value_counts()    # fréquence de chaque valeur
s.unique()          # valeurs uniques
s.map({"bon": 1, "moyen": 0})   # remplacer valeurs par dict
```

---

## Flask — Bases

```python
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify

app = Flask(__name__)
app.secret_key = "une_cle_secrete"

# Route GET simple
@app.route("/")
def accueil():
    return render_template("home.html", titre="SDE")

# Route GET + POST
@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        nom = request.form.get("nom", "").strip()   # données formulaire HTML
        flash(f"Merci {nom} !", "success")          # message flash (1 affichage)
        return redirect(url_for("accueil"))          # redirection par nom de vue
    return render_template("contact.html")

# Route avec paramètre d'URL
@app.route("/analyse/<ticker>")
def analyse(ticker):
    return render_template("analysis.html", ticker=ticker.upper())

# Route API JSON
@app.route("/api/score/<ticker>")
def api_score(ticker):
    return jsonify({"ticker": ticker, "score": 72.5})

if __name__ == "__main__":
    app.run(debug=True)   # http://localhost:5000
```

---

## Flask — App Factory & Blueprints

Découpe l'application en modules indépendants.

```python
# flask_app/__init__.py
from flask import Flask

def create_app():
    app = Flask(__name__)
    app.secret_key = "secret"

    from .blueprints.auth  import bp as auth_bp
    from .blueprints.stock import bp as stock_bp

    app.register_blueprint(auth_bp)    # préfixe défini dans le blueprint
    app.register_blueprint(stock_bp)
    return app
```

```python
# flask_app/blueprints/auth.py
from flask import Blueprint, render_template, redirect, url_for

bp = Blueprint("auth", __name__, url_prefix="/auth")

@bp.route("/login")
def login():
    return render_template("auth/login.html")

@bp.route("/logout")
def logout():
    return redirect(url_for("stock.home"))   # "blueprint.vue"
```

```python
# run_flask.py
from flask_app import create_app
app = create_app()
```

---

## Jinja2 — Templates

Jinja2 est le moteur de templates intégré à Flask.

```html
<!-- variables -->
<h1>{{ titre }}</h1>
<p>Score : {{ score | round(1) }}</p>       <!-- filtre -->
<p>{{ texte | upper | truncate(50) }}</p>   <!-- filtres chaînés -->

<!-- condition -->
{% if score > 70 %}
  <span class="vert">ACHETER</span>
{% elif score > 40 %}
  <span class="orange">NEUTRE</span>
{% else %}
  <span class="rouge">VENDRE</span>
{% endif %}

<!-- boucle -->
<ul>
{% for item in watchlist %}
  <li>{{ item.ticker }} — {{ item.company }}</li>
{% else %}
  <li>Watchlist vide</li>   <!-- affiché si liste vide -->
{% endfor %}
</ul>

<!-- url_for (génère l'URL d'une route) -->
<a href="{{ url_for('stock.home') }}">Accueil</a>
<a href="{{ url_for('auth.login') }}">Connexion</a>

<!-- message flash -->
{% with messages = get_flashed_messages(with_categories=true) %}
  {% for cat, msg in messages %}
    <div class="alert alert-{{ cat }}">{{ msg }}</div>
  {% endfor %}
{% endwith %}
```

### Héritage de templates

```html
<!-- base.html -->
<!DOCTYPE html>
<html>
<head><title>{% block title %}SDE{% endblock %}</title></head>
<body>
  <nav>...</nav>
  {% block content %}{% endblock %}
</body>
</html>
```

```html
<!-- analysis.html -->
{% extends "base.html" %}

{% block title %}Analyse {{ ticker }}{% endblock %}

{% block content %}
  <h1>{{ ticker }}</h1>
  <p>Score : {{ score }}</p>
{% endblock %}
```

---

## Flask-Login — Authentification

```python
# flask_app/__init__.py
from flask_login import LoginManager

login_manager = LoginManager()

def create_app():
    app = Flask(__name__)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"   # redirige si non connecté
    ...
```

```python
# blueprints/auth.py
from flask_login import UserMixin, login_user, logout_user, login_required, current_user

class User(UserMixin):
    def __init__(self, username, name):
        self.id       = username   # Flask-Login utilise .id
        self.username = username
        self.name     = name

@login_manager.user_loader
def load_user(username):
    data = trouver_en_base(username)
    return User(data["username"], data["name"]) if data else None

@bp.route("/login", methods=["POST"])
def login():
    user = User("alice", "Alice")
    login_user(user, remember=True)       # crée la session
    return redirect(url_for("stock.home"))

@bp.route("/logout")
@login_required                           # bloque si non connecté
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
```

```html
<!-- template : tester si connecté -->
{% if current_user.is_authenticated %}
  <p>Bonjour {{ current_user.name }}</p>
{% else %}
  <a href="{{ url_for('auth.login') }}">Connexion</a>
{% endif %}
```

---

## Flask-WTF — Protection CSRF

```python
# flask_app/__init__.py
from flask_wtf.csrf import CSRFProtect

csrf = CSRFProtect()

def create_app():
    app = Flask(__name__)
    csrf.init_app(app)
    ...
```

```html
<!-- base.html : méta-tag pour les requêtes AJAX -->
<meta name="csrf-token" content="{{ csrf_token() }}">

<!-- formulaire HTML classique : champ caché automatique -->
<form method="POST">
  {{ csrf_token() }}   {# ou utiliser Flask-WTF Form #}
  <input name="username"> <button type="submit">OK</button>
</form>
```

```javascript
// fetch AJAX avec le token CSRF
const token = document.querySelector('meta[name="csrf-token"]').content;

fetch("/api/watchlist/add", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRFToken": token },
    body: JSON.stringify({ ticker: "AAPL" })
});
```

---

## bcrypt — Mots de passe

Ne jamais stocker un mot de passe en clair — toujours le hacher.

```python
import bcrypt

# À l'inscription : hacher
mdp_clair  = "monMotDePasse123"
mdp_hache  = bcrypt.hashpw(mdp_clair.encode(), bcrypt.gensalt()).decode()
# "$2b$12$..." — stocker cette chaîne en base

# À la connexion : vérifier
ok = bcrypt.checkpw(mdp_clair.encode(), mdp_hache.encode())  # True / False
```

---

## Variables d'environnement (.env)

```bash
# .env  (gitignored)
FLASK_SECRET_KEY=abc123xyz
GROQ_API_KEY=gsk_...
SUPABASE_URL=https://xxxxx.supabase.co
```

```python
import os
from dotenv import load_dotenv

load_dotenv()   # charge .env dans os.environ

cle    = os.getenv("FLASK_SECRET_KEY", "")   # "" si absente
groq   = os.getenv("GROQ_API_KEY",     "")
debug  = os.getenv("FLASK_DEBUG", "0") == "1"
```

---

## Finnhub — Quote & Fondamentaux

Plan gratuit : 60 appels/min, fonctionne sur Render et tout cloud.  
Utilisé en **fallback** si Yahoo Finance est bloqué sur l'IP du serveur.

```python
import finnhub
import os

client = finnhub.Client(api_key=os.getenv("FINNHUB_API_KEY", ""))

# Prix temps réel (c=current, pc=previous close, h=high, l=low)
q = client.quote("AAPL")
# {"c": 193.5, "pc": 191.2, "h": 194.1, "l": 190.5, "t": 1718000000}
prix      = q["c"]   # cours actuel
prev      = q["pc"]  # clôture précédente
var_pct   = (prix - prev) / prev * 100

# Profil entreprise (nom, secteur, devise, bourse)
p = client.company_profile2(symbol="AAPL")
# {"name": "Apple Inc", "finnhubIndustry": "Technology", "currency": "USD", ...}

# Fondamentaux (P/E, EPS, debt/equity, market cap…)
data    = client.company_basic_financials("AAPL", "all")
metrics = data["metric"]
pe      = metrics.get("peBasicExclExtraTTM")   # P/E trailing
eps     = metrics.get("epsBasicExclExtraTTM")
mktcap  = metrics.get("marketCapitalization")   # en millions → × 1_000_000

# Recherche de ticker par nom
res   = client.symbol_lookup("apple")
items = res["result"]   # [{"symbol": "AAPL", "description": "Apple Inc", "type": "Common Stock"}, ...]

# Dirigeants
execs = client.company_executives("AAPL")
persons = execs["executive"]   # [{"name": "Tim Cook", "title": "CEO", ...}, ...]
```

---

## Twelve Data — Historique OHLCV

Plan gratuit : 800 appels/jour, 8/min — marchés NASDAQ/NYSE uniquement.  
Utilisé en **fallback** pour l'historique des cours (yfinance bloqué sur cloud).

```python
from twelvedata import TDClient
import os

td = TDClient(apikey=os.getenv("TWELVE_DATA_API_KEY", ""))

# Historique journalier (90 jours, ordre chronologique)
ts = td.time_series(
    symbol    = "AAPL",
    interval  = "1day",
    outputsize= 90,       # nombre de points
    order     = "ASC",    # du plus ancien au plus récent
).as_pandas()

# ts est un DataFrame avec colonnes : open, high, low, close, volume
# → renommer en Open, High, Low, Close, Volume pour compatibilité pandas

ts = ts.rename(columns={
    "open": "Open", "high": "High",
    "low":  "Low",  "close": "Close", "volume": "Volume"
})
ts.index = pd.to_datetime(ts.index)
ts["Close"] = pd.to_numeric(ts["Close"])

# Autres intervalles disponibles : "1min", "5min", "1h", "1week", "1month"
```

---

## Supabase — Base de données

```python
from supabase import create_client
import os

client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

# SELECT
rows = client.table("watchlist").select("*").eq("username", "alice").execute().data
# [{"id": 1, "username": "alice", "ticker": "AAPL", ...}, ...]

# SELECT avec filtre multiple
row = client.table("users").select("*").eq("username", "alice").limit(1).execute().data
user = row[0] if row else None

# INSERT
client.table("watchlist").insert({
    "username": "alice", "ticker": "AAPL", "company": "Apple"
}).execute()

# UPSERT (insert ou update si existe déjà)
client.table("scores").upsert({
    "ticker": "AAPL", "score": 72.5, "reco": "ACHETER"
}).execute()

# DELETE
client.table("watchlist").delete().eq("username", "alice").eq("ticker", "AAPL").execute()

# COUNT
r = client.table("users").select("*", count="exact").eq("username", "alice").execute()
nb = r.count   # 0 ou 1
```
