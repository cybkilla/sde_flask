# analysis/llm_explain.py
# Génère une explication textuelle du scoring via un LLM gratuit.
# Moteur principal : Groq (LLaMA 3.3 70B) — gratuit, rapide.
# Fallback : Ollama local si Groq indisponible.
# Si les deux échouent : texte de remplacement généré en Python pur.

import os
import requests
import pandas  as pd
from analysis.prompt_builder import build_prompt
from config import (
    GROQ_API_KEY, GROQ_MODEL,
    OLLAMA_URL, OLLAMA_MODEL,
    LLM_MAX_TOKENS, LLM_TIMEOUT,
)


def _trim_to_last_sentence(text: str) -> str:
    """Tronque le texte au dernier signe de ponctuation final (.!?)."""
    for i in range(len(text) - 1, -1, -1):
        if text[i] in ".!?":
            return text[: i + 1].strip()
    return text.strip()


# ── Moteur 1 : Groq API ───────────────────────────────────
def _call_groq(prompt: str) -> str:
    """
    Appelle l'API Groq (LLaMA 3.3 70B gratuit).
    Endpoint REST compatible OpenAI — headers + JSON body.

    Paramètres
    ----------
    prompt : texte du prompt construit par build_prompt()

    Retour
    ------
    str : texte généré par le LLM
    Lève une exception si la clé est absente ou l'appel échoue.
    """
    if not GROQ_API_KEY or GROQ_API_KEY == "votre_cle_groq":
        raise ValueError("Clé Groq absente — voir config.py")

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type":  "application/json",
    }

    payload = {
        "model": GROQ_MODEL,    # "llama-3.3-70b-versatile"
        "messages": [
            # Rôle système : cadre le LLM comme analyste financier
            {
                "role":    "system",
                "content": (
                    "Tu es un analyste financier concis. "
                    "Tu expliques en 3 phrases maximum, "
                    "en français, pourquoi un score boursier "
                    "a été attribué à une action. "
                    "Sois factuel et direct. "
                    "N'invente aucune donnée. "
                    "Commence directement par l'explication."
                ),
            },
            # Rôle user : le prompt avec les données du pipeline
            {"role": "user", "content": prompt},
        ],
        "max_tokens":  LLM_MAX_TOKENS,   # ~200 tokens = ~150 mots
        "temperature": 0.4,              # faible = réponses stables
    }

    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=LLM_TIMEOUT,
    )
    resp.raise_for_status()   # lève une exception si code HTTP ≠ 2xx

    # Extraction du texte depuis la réponse JSON
    return resp.json()["choices"][0]["message"]["content"].strip()


# ── Moteur 2 : Ollama local (fallback sans internet) ──────
def _call_ollama(prompt: str) -> str:
    """
    Appelle un modèle Ollama tournant en local.
    Nécessite : 'ollama run mistral' dans un terminal.

    Plus lent que Groq (~5–10s) mais 100% hors-ligne et gratuit.
    """
    payload = {
        "model":  OLLAMA_MODEL,   # "mistral" ou "llama3"
        "prompt": (
            "Tu es un analyste financier concis. Explique en 3 phrases "
            "maximum en français pourquoi ce score a été attribué. "
            "Sois direct, factuel, ne commence pas par 'Bien sûr'.\n\n"
        ) + prompt,
        "stream": False,   # réponse complète d'un seul coup
        "options": {"temperature": 0.4, "num_predict": LLM_MAX_TOKENS},
    }

    resp = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json=payload,
        timeout=LLM_TIMEOUT * 3,   # Ollama est plus lent → timeout 3x
    )
    resp.raise_for_status()
    return resp.json()["response"].strip()


# ── Fallback pur Python (aucun LLM dispo) ─────────────────
def _fallback_text(result: dict) -> str:
    """
    Génère un texte d'explication déterministe sans LLM.
    Utilisé si Groq et Ollama sont tous les deux indisponibles.
    Basé uniquement sur les données Pandas du pipeline.
    """
    reco  = result["recommandation"]
    score = result["score_global"]
    name  = result["company_name"]
    sent  = result["sentiment"]["label"]
    tech  = result["score_tech"]
    fund  = result["score_fund"]
    media = result["score_media"]

    # Texte adaptatif selon la recommandation
    intro = {
        "ACHETER": f"L'analyse de {name} indique un signal haussier ({score}/100).",
        "VENDRE":  f"L'analyse de {name} indique un signal baissier ({score}/100).",
        "NEUTRE":  f"L'analyse de {name} ne dégage pas de signal clair ({score}/100).",
    }.get(reco, f"Score de {score}/100 pour {name}.")

    detail = (
        f"Le score technique est de {tech}/100, "
        f"le score fondamental de {fund}/100 "
        f"et le score médiatique de {media}/100. "
        f"Le sentiment des actualités récentes est {sent}. "
    )

    # Mention des alertes dirigeants si présentes
    nb_alerts = len(result.get("df_events", pd.DataFrame()))
    alert_str = (
        f"Aucune alerte concernant les dirigeants n'a été détectée."
        if nb_alerts == 0
        else f"{nb_alerts} alerte(s) concernant le dirigeant ont été détectées."
    )

    return intro + " " + detail + alert_str


# ── Fonction principale ───────────────────────────────────
def generate_explanation(result: dict) -> dict:
    """
    Génère l'explication textuelle du scoring via LLM.

    Ordre de priorité :
      1. Groq API       (rapide, cloud gratuit)
      2. Ollama local   (lent, 100% hors-ligne)
      3. Fallback Python (déterministe, toujours dispo)

    Paramètres
    ----------
    result : dict retourné par pipeline.run()

    Retour
    ------
    dict avec :
      'texte'  : str — explication générée
      'source' : str — "groq" | "ollama" | "fallback"
      'tokens' : int — estimation du nombre de tokens utilisés
    """
    # Construction du prompt depuis les données du pipeline
    prompt = build_prompt(result)

    # Tentative 1 : Groq
    try:
        texte  = _trim_to_last_sentence(_call_groq(prompt))
        source = "groq"
        print("  [LLM] Groq — OK")

    # Tentative 2 : Ollama local
    except Exception as e_groq:
        print(f"  [LLM] Groq échoué ({e_groq}) — essai Ollama...")
        try:
            texte  = _trim_to_last_sentence(_call_ollama(prompt))
            source = "ollama"
            print("  [LLM] Ollama — OK")

        # Fallback Python si les deux LLM sont indisponibles
        except Exception as e_ollama:
            print(f"  [LLM] Ollama échoué ({e_ollama}) — fallback Python")
            texte  = _fallback_text(result)
            source = "fallback"

    return {
        "texte":  texte,
        "source": source,
        "tokens": len(texte.split()),   # estimation grossière
    }
