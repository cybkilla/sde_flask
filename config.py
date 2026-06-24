# config.py — centralise tous les paramètres du projet
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Clés API ──────────────────────────────────────────
# Définir ces variables dans un fichier .env (voir .env.example)
NEWS_API_KEY        = os.getenv("NEWS_API_KEY",        "")
FINNHUB_API_KEY     = os.getenv("FINNHUB_API_KEY",     "")
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")
CRON_SECRET         = os.getenv("CRON_SECRET",         "")

# ── Paramètres d'analyse ──────────────────────────────
RSI_PERIOD       = 14
MA_SHORT         = 20
MA_LONG          = 50
HISTORY_DAYS     = "90d"
MAX_NEWS         = 10     # articles max par source lors de la collecte
MAX_SECTOR_NEWS  = 8      # articles max pour les news sectorielles
MAX_NEWS_DISPLAY = 10     # articles max affichés dans l'UI par ticker

# ── Poids du score global ─────────────────────────────
# Média moins pondéré : souvent peu d'articles ou signaux bruités
WEIGHT_TECH      = 0.40
WEIGHT_FUND      = 0.35
WEIGHT_MEDIA     = 0.25

# ── Seuils de décision (bande neutre ±4 autour de 50) ─
SCORE_BUY        = 54
SCORE_SELL       = 46

# ── Mots-clés surveillance dirigeants ────────────────
# Catégories utilisées pour la recherche RSS et le scoring

# Scandales / risques légaux — sévérité CRITIQUE
KEYWORDS_SCANDAL_CRITICAL = [
    "arrested", "fraud", "indicted", "SEC probe", "DOJ investigation",
    "corruption", "money laundering", "bribery", "criminal charges",
]

# Changements leadership + risques réputationnels — sévérité HAUTE
KEYWORDS_SCANDAL_HIGH = [
    "investigation", "lawsuit", "misconduct", "scandal",
    "insider trading", "whistleblower", "compliance issue",
    "ethics violation", "resigned", "fired", "dismissed",
]

# Signaux négatifs modérés — sévérité MOYENNE
KEYWORDS_NEGATIVE_MED = [
    "stepped down", "departure", "controversy", "divorce",
    "insider selling", "sell shares", "stake reduction",
    "profit warning", "cuts guidance", "misses expectations",
    "layoffs", "regulatory pressure",
]

# Signaux positifs (pour bonus dans ExecutiveRiskScore)
KEYWORDS_POSITIVE = [
    "appointed", "insider buying", "raises guidance",
    "beats expectations", "record growth", "strong outlook",
    "strategic investment", "stake increase",
]

# Liste plate pour get_executive_events() (requêtes RSS — 1 appel / mot-clé)
# Volontairement limitée aux signaux les plus impactants
EXEC_KEYWORDS = (
    KEYWORDS_SCANDAL_CRITICAL
    + KEYWORDS_SCANDAL_HIGH
    + KEYWORDS_NEGATIVE_MED
)

# Map sévérité → pénalité points
KEYWORD_SEVERITY_MAP: dict[str, str] = {
    **{kw: "CRITIQUE" for kw in KEYWORDS_SCANDAL_CRITICAL},
    **{kw: "HAUTE"    for kw in KEYWORDS_SCANDAL_HIGH},
    **{kw: "MOYENNE"  for kw in KEYWORDS_NEGATIVE_MED},
    **{kw: "POSITIVE" for kw in KEYWORDS_POSITIVE},
}

SEVERITY_PENALTY_POINTS: dict[str, int] = {
    "CRITIQUE": 20,
    "HAUTE":    10,
    "MOYENNE":   5,
    "POSITIVE":  0,
}

# Alias héritage (garde la compatibilité avec l'existant)
KEYWORDS_HIGH_SEVERITY = [
    kw for kw, sev in KEYWORD_SEVERITY_MAP.items()
    if sev in ("CRITIQUE", "HAUTE")
]

# ── Modèle NLP ────────────────────────────────────────
NLP_MODEL        = "ProsusAI/finbert"   # ou "vader" pour fallback
USE_FINBERT      = False  # True si GPU dispo, False → VADER

# config.py — AJOUTS pour l'intégration LLM
# ── LLM — Groq (moteur principal) ─────────────────────────
# Clé gratuite sur : https://console.groq.com/keys
# Quota gratuit : 14 400 requêtes / jour
GROQ_API_KEY  = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL    = "llama-3.3-70b-versatile"

# ── LLM — Ollama (fallback local) ─────────────────────────
# Installer : https://ollama.com → puis 'ollama pull mistral'
OLLAMA_URL    = "http://localhost:11434"
OLLAMA_MODEL  = "mistral"             # ou "llama3", "phi3"

# ── Paramètres communs ────────────────────────────────────
LLM_MAX_TOKENS = 220     # marge pour 3 phrases complètes (~60 mots)
LLM_TIMEOUT    = 15      # secondes avant abandon
LLM_ENABLED    = True    # False = désactive le LLM, fallback systématique

# ── Resend — envoi d'emails d'alerte (HTTP, port 443) ────
# Compte gratuit : https://resend.com/ → API Keys
# RESEND_FROM doit être une adresse vérifiée sur Resend.
# Sans domaine propre, utiliser l'adresse test : onboarding@resend.dev
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_FROM    = os.getenv("RESEND_FROM", "SDE StockDecisionEngine <onboarding@resend.dev>")
 
# ── Alertes — seuils de déclenchement ────────────────────
# Variation minimale du cours (en %) pour envoyer une alerte
ALERT_VAR_THRESHOLD = 5
 
# Intervalle entre deux vérifications du scheduler (en minutes)
CHECK_INTERVAL_MIN  = 60
 
# ── Auth — cookie Streamlit ───────────────────────────────
# Clé secrète pour signer les cookies de session
# Changer cette valeur en production
AUTH_COOKIE_KEY  = "stockengine_secret_key_changez_moi"
AUTH_COOKIE_NAME = "stockengine_auth"
AUTH_COOKIE_DAYS = 30
 