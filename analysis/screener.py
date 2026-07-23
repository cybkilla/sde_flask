# analysis/screener.py — scan d'opportunités court terme sur un univers NASDAQ
#
# Objectif : aider à déployer du cash disponible en repérant, parmi un
# univers de tickers plus large que la watchlist personnelle, ceux dont
# le potentiel court terme (mesuré par le pipeline SDE) est le plus élevé.
#
# Entonnoir à DEUX étages — indispensable sur le plan gratuit Render
# (workers=1, quotas NewsAPI/Groq limités) :
#   1. Filtre TECHNIQUE seul (get_market_data + score_technique, poids
#      manuels — pas de calibration/backtest ici, trop coûteux à l'échelle
#      de tout l'univers) sur la totalité de l'univers.
#   2. Pipeline COMPLET (news, fondamentaux, calibration, LLM) uniquement
#      sur les N_SHORTLIST survivants de l'étage 1.
#
# Déclenché UNIQUEMENT à la demande (bouton admin) — jamais par cron, pour
# ne pas consommer de quota API à chaque exécution planifiée si personne
# n'a de cash à placer ce jour-là.

import threading
import time
from datetime import datetime, timezone

from data.market       import get_market_data
from analysis.scoring  import score_technique

# Univers de scan par défaut — sélection curatée NASDAQ (mi-2026, à jour à la
# main), pas l'intégralité du Nasdaq-100 : titres suivis pour leur potentiel
# de croissance / dynamique court terme, répartis sur 3 thèmes. Éditable
# directement ici : ajouter/retirer un ticker ne demande aucune autre
# modification de code.
UNIVERS_SCAN = [
    # IA / semi-conducteurs
    "NVDA", "AVGO", "AMD", "SMCI", "ASML", "LRCX", "MRVL",
    # Tech / cloud / SaaS
    "MSFT", "GOOGL", "META", "AAPL", "PLTR", "DDOG", "ZS",
    # Consommation / fintech / énergies futures
    "TSLA", "AMZN", "APP", "TTD", "CELH", "FCEL",
]

N_SHORTLIST = 10   # nb de survivants de l'étage 1 promus au pipeline complet
N_TOP       = 5    # taille du Top affiché
PAUSE_ETAGE1_S     = 3    # espacement entre tickers à l'étage 1 (0 dans les tests)
PAUSE_RATTRAPAGE_S  = 65  # pause avant le passage de rattrapage groupé (0 dans les tests)

_lock = threading.Lock()
_TABLE_SCAN = "opportunites_scan"

# État partagé en mémoire (mono-process, workers=1 sur Render — même pattern
# que cache.py / backtest._CACHE). Complété par un backup Supabase
# (_persister_resultats / _charger_dernier_scan) : gunicorn recycle le
# worker toutes les ~200 requêtes (max_requests, cf. mémoire projet) et
# perdait le Top 5 en mémoire — sans compter la simple navigation qui, elle,
# ne touche pas _state (mono-process) mais était perçue comme "perdue" par
# l'utilisateur au premier chargement après un redémarrage.
_state = {
    "en_cours":     False,
    "progression":  None,   # ex. "Analyse complète 4/15 (NVDA)"
    "derniere_maj": None,   # ISO 8601 UTC de la fin du dernier scan
    "resultats":    [],     # liste de dicts, la plus récente, triée décroissant
    "erreur":       None,
}
_hydrate_tentee = False   # une seule tentative de rechargement Supabase par process


def _persister_resultats():
    """Sauvegarde le Top N dans Supabase (silencieux si indisponible)."""
    try:
        from db import update_one, is_available
        if not is_available():
            return
        update_one(
            _TABLE_SCAN,
            {"id": 1},
            {"$set": {"resultats": _state["resultats"], "derniere_maj": _state["derniere_maj"]}},
            upsert=True,
        )
    except Exception as e:
        print(f"[Screener] persistance Supabase échouée : {e}", flush=True)


def _charger_dernier_scan():
    """Recharge le dernier Top N depuis Supabase dans l'état mémoire (silencieux si indisponible)."""
    try:
        from db import find_one, is_available
        if not is_available():
            return
        row = find_one(_TABLE_SCAN, {"id": 1})
        if row and row.get("resultats"):
            _state["resultats"]    = row["resultats"]
            _state["derniere_maj"] = row.get("derniere_maj")
    except Exception as e:
        print(f"[Screener] rechargement Supabase échoué : {e}", flush=True)


def get_scan_state() -> dict:
    global _hydrate_tentee
    if not _hydrate_tentee and not _state["resultats"] and not _state["en_cours"]:
        _hydrate_tentee = True   # une seule tentative, même si elle échoue/ne trouve rien
        _charger_dernier_scan()
    return dict(_state)


def _scan_technique(ticker: str) -> dict | None:
    """
    Étage 1 : score technique seul, pas de news/LLM. Rapide et peu coûteux —
    MAIS get_market_data() route sur Twelve Data en prod (yfinance bloqué sur
    Render), dont le plan gratuit tolère 8 CRÉDITS/MIN (message d'erreur
    Twelve Data confirmé en réel le 22.07 : "17 credits used, limit 8"). Le
    quota se réinitialise à la minute calendaire suivante, pas de façon
    glissante. La retentative se fait au niveau de l'orchestrateur
    (lancer_scan, un seul passage de rattrapage groupé) plutôt qu'ici, pour
    ne pas empiler N pauses individuelles si plusieurs tickers sont touchés
    en même temps par le même quota.
    """
    try:
        data = get_market_data(ticker)
        tech = score_technique(data)
        return {
            "ticker":       ticker,
            "company_name": data.get("company_name", ticker),
            "score_tech":   tech["score"],
        }
    except Exception as e:
        print(f"[Screener] étage 1 échoué pour {ticker} : {e}", flush=True)
        return None


def _scan_complet(ticker: str) -> dict | None:
    """Étage 2 : pipeline complet (réutilise le cache 15 min / snapshot 24 h)."""
    try:
        from pipeline import run
        res = run(ticker, use_cache=True)
        return {
            "ticker":         res["ticker"],
            "company_name":   res["company_name"],
            "score_global":   res["score_global"],
            "recommandation": res["recommandation"],
            "prix":           res["market"].get("price"),
            "divergence":     res.get("divergence"),
        }
    except Exception as e:
        print(f"[Screener] étage 2 échoué pour {ticker} : {e}", flush=True)
        return None


def lancer_scan(univers: list[str] | None = None) -> bool:
    """
    Lance le scan en thread background (retour immédiat, même pattern que
    flask_app/blueprints/cron.py). Retourne False si un scan est déjà en
    cours (évite deux scans concurrents qui doubleraient la consommation
    API sur un double-clic).
    """
    if not _lock.acquire(blocking=False):
        return False

    univers = univers or UNIVERS_SCAN

    def _run():
        try:
            _state["en_cours"] = True
            _state["erreur"] = None
            total = len(univers)

            candidats = []
            echecs    = []
            for i, ticker in enumerate(univers):
                _state["progression"] = f"Filtre technique {i + 1}/{total} ({ticker})"
                r = _scan_technique(ticker)
                (candidats if r else echecs).append(r or ticker)
                # Espacement des appels — Twelve Data (source prod, yfinance
                # bloqué sur Render) tolère ~8 requêtes/min sur le plan
                # gratuit : sans pause, un balayage de 20 tickers se fait
                # rate-limiter en plein milieu (vérifié en réel le 22.07).
                if i < total - 1:
                    time.sleep(PAUSE_ETAGE1_S)

            # Rattrapage groupé : UNE pause (pas une par ticker en échec)
            # pour repasser dans une nouvelle fenêtre de quota Twelve Data.
            if echecs:
                _state["progression"] = f"Pause quota API — rattrapage de {len(echecs)} ticker(s)…"
                time.sleep(PAUSE_RATTRAPAGE_S)
                for i, ticker in enumerate(echecs):
                    _state["progression"] = f"Rattrapage {i + 1}/{len(echecs)} ({ticker})"
                    r = _scan_technique(ticker)
                    if r:
                        candidats.append(r)
                    if i < len(echecs) - 1:
                        time.sleep(PAUSE_ETAGE1_S)

            candidats.sort(key=lambda r: r["score_tech"], reverse=True)
            shortlist = candidats[:N_SHORTLIST]

            resultats = []
            for i, c in enumerate(shortlist):
                _state["progression"] = f"Analyse complète {i + 1}/{len(shortlist)} ({c['ticker']})"
                r = _scan_complet(c["ticker"])
                if r:
                    resultats.append(r)

            resultats.sort(key=lambda r: r["score_global"], reverse=True)
            _state["resultats"]    = resultats[:N_TOP]
            _state["derniere_maj"] = datetime.now(timezone.utc).isoformat()
            _persister_resultats()
        except Exception as e:
            _state["erreur"] = str(e)
            print(f"[Screener] scan erreur : {e}", flush=True)
        finally:
            _state["progression"] = None
            _state["en_cours"] = False
            _lock.release()

    threading.Thread(target=_run, daemon=True).start()
    return True
