# 🔔 Job Alerts – Vladimir Andriana

Script Python autonome de veille emploi quotidienne.
Scrape Indeed CH, Jobup.ch et Jobscout24.ch et envoie un email récapitulatif chaque matin.

---

## 📁 Structure

```
job_alerts/
├── .github/
│   └── workflows/
│       └── job_alert.yml      ← GitHub Action (planification)
├── config/
│   └── keywords.yml           ← ✏️  TON FICHIER DE CONFIG (mots-clés, localisations)
├── src/
│   ├── __init__.py
│   ├── main.py                ← Point d'entrée
│   ├── scraper.py             ← Scrapers Indeed / Jobup / Jobscout24
│   └── mailer.py              ← Génération et envoi de l'email HTML
├── requirements.txt
└── README.md
```

---

## ⚙️ Configuration des mots-clés

Édite **`config/keywords.yml`** directement sur GitHub ou en local :

```yaml
keywords:
  - "SQL Server"
  - "Data Engineer"
  - "Sybase"
  # Ajoute ou retire des termes ici

locations:
  - "Genève"
  - "Lausanne"

exclude_keywords:
  - "stage"
  - "internship"
```

---

## 🔐 Secrets GitHub à configurer

Dans ton repo GitHub → **Settings → Secrets and variables → Actions** :

| Secret         | Valeur                                      |
|----------------|---------------------------------------------|
| `SMTP_HOST`    | `smtp.gmail.com`                            |
| `SMTP_PORT`    | `587`                                       |
| `SMTP_USER`    | ton adresse Gmail (ex. `toi@gmail.com`)     |
| `SMTP_PASSWORD`| **Mot de passe d'application Gmail** (⚠️ pas ton vrai mot de passe) |

### Créer un mot de passe d'application Gmail

1. Va sur [myaccount.google.com/security](https://myaccount.google.com/security)
2. Active la **validation en deux étapes** si ce n'est pas fait
3. Cherche **"Mots de passe des applications"**
4. Crée une app → copie le mot de passe à 16 caractères → colle-le dans `SMTP_PASSWORD`

---

## 🚀 Installation dans ton repo SDE

```bash
# Depuis la racine de ton repo sde
git clone https://github.com/TON_USER/sde.git
cd sde

# Copier le dossier job_alerts dans le repo
cp -r /chemin/vers/job_alerts ./job_alerts
git add job_alerts/
git commit -m "feat: ajout du script d'alerte emploi quotidienne"
git push
```

GitHub Actions se déclenche automatiquement **du lundi au vendredi à 07h00** (heure de Genève).

---

## ▶️ Lancer manuellement

Dans GitHub → onglet **Actions** → sélectionne **"Alerte Emploi Quotidienne"** → **Run workflow**.

---

## 📧 Exemple d'email reçu

L'email HTML récapitule les offres groupées par source, avec :
- Titre de l'offre (lien cliquable)
- Entreprise et localisation
- Mots-clés ayant déclenché la correspondance

---

## 🛠 Lancer en local (pour tester)

```bash
cd job_alerts
pip install -r requirements.txt

export SMTP_HOST=smtp.gmail.com
export SMTP_PORT=587
export SMTP_USER=ton@gmail.com
export SMTP_PASSWORD=motdepasseapp

python -m src.main
```
