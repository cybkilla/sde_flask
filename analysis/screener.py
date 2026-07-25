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

# RSI > 70 = zone de surachat (même seuil que le signal "rsi_surachat" de
# analysis/scoring.py) — filtré du Top 5 (24.07.2026) : un ticker déjà en
# surachat a probablement déjà fait le plus gros de son mouvement, ce n'est
# plus une opportunité D'ENTRÉE, même si son score technique reste élevé
# (momentum non pénalisé au niveau du SCORE lui-même, cf. discussion ADVB
# du 23.07.2026 — le spéculatif n'est pas le problème, le TIMING l'est).
RSI_SURACHAT_SEUIL = 70

# Filtre complémentaire (25.07.2026) : un RSI(14) lissé peut rester sous le
# seuil de surachat même en pleine séance de retournement brutal — un seul
# mauvais jour pèse peu dans une moyenne sur 14. Repéré en réel sur NBIS
# (var_5d +28.6%, RSI 51.6 "sain") qui perdait pourtant -15% CE JOUR-LÀ.
# var_1d < seuil -> exclu, en plus du RSI : un ticker qui plonge le jour
# même du scan n'est pas un point d'entrée, peu importe sa tendance récente.
VAR_1D_CHUTE_SEUIL = -8.0

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


def _passe_filtre_entree(d: dict) -> bool:
    """
    Un ticker n'est une opportunité D'ENTRÉE valable que s'il n'est NI en
    surachat (RSI, extension étalée sur plusieurs jours) NI en train de
    plonger CE JOUR-LÀ (var_1d, retournement brutal qu'un RSI lissé sur 14
    jours peut ne pas encore refléter) — deux signaux de timing distincts
    et complémentaires. Fonction PURE, utilisée aux deux étages du scan.
    """
    rsi    = d.get("rsi")
    var_1d = d.get("var_1d")
    if rsi is not None and rsi > RSI_SURACHAT_SEUIL:
        return False
    if var_1d is not None and var_1d < VAR_1D_CHUTE_SEUIL:
        return False
    return True


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
            "rsi":          data.get("rsi"),
            "var_1d":       data.get("var_1d"),
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
            # RSI affiché à part du score : la qualité de l'opportunité
            # (score_global) et le timing d'entrée (RSI) sont deux questions
            # différentes — les fondre en un seul tri masquerait l'une des
            # deux (discuté avec l'utilisateur le 23.07.2026 sur le cas ADVB,
            # RSI 79 mais ACHETER car momentum fort par ailleurs).
            "rsi":            res["market"].get("rsi"),
            "var_5d":         res["market"].get("var_5d"),
            "var_1d":         res["market"].get("var_1d"),
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

    univers = univers or get_univers_actif()

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
            # Filtre d'ENTRÉE (RSI + var_1d, cf. _passe_filtre_entree) : un
            # ticker en surachat ou en train de plonger aujourd'hui n'est plus
            # une opportunité, même bien classé techniquement. Peut réduire le
            # nombre de candidats, voire les vider tous un jour de rallye
            # généralisé (ou de repli brutal) — résultat attendu, pas un bug.
            candidats = [c for c in candidats if _passe_filtre_entree(c)]
            shortlist = candidats[:N_SHORTLIST]

            resultats = []
            for i, c in enumerate(shortlist):
                _state["progression"] = f"Analyse complète {i + 1}/{len(shortlist)} ({c['ticker']})"
                r = _scan_complet(c["ticker"])
                # Deuxième passage du même filtre : pipeline.run() peut réutiliser
                # un snapshot légèrement différent de l'appel étage 1 (cache),
                # RSI/var_1d ont pu évoluer entre-temps — garantit qu'aucun
                # ticker affiché en Top 5 ne les enfreint, même en cas limite.
                # + recommandation ACHETER exigée (25.07.2026) : le score_tech
                # (étage 1, momentum seul) et le score_global (étage 2, agrège
                # aussi fondamental/média/régime/hystérésis) sont deux
                # évaluations différentes — un ticker peut passer les filtres
                # de TIMING (RSI, var_1d) sans que le pipeline complet le juge
                # globalement bon. Une liste d'"opportunités d'achat" n'a pas
                # de sens si elle peut afficher un NEUTRE, voire un VENDRE.
                if r and _passe_filtre_entree(r) and r.get("recommandation") == "ACHETER":
                    resultats.append(r)

            resultats.sort(key=lambda r: r["score_global"], reverse=True)
            _state["resultats"]    = resultats[:N_TOP]
            _state["derniere_maj"] = datetime.now(timezone.utc).isoformat()
            _persister_resultats()

            # Historique pour évaluation future (J+1/J+5/J+20) — voir
            # analysis/opportunites_evaluator.py. Séparé de _persister_resultats
            # (qui ne garde que le DERNIER Top 5) : ici chaque scan s'accumule.
            from analysis.opportunites_evaluator import enregistrer_resultats
            enregistrer_resultats(_state["resultats"])
        except Exception as e:
            _state["erreur"] = str(e)
            print(f"[Screener] scan erreur : {e}", flush=True)
        finally:
            _state["progression"] = None
            _state["en_cours"] = False
            _lock.release()

    threading.Thread(target=_run, daemon=True).start()
    return True


# ── Univers de scan : suggestion IA + application ─────────────────────────
# Demandé par l'utilisateur (23.07.2026) après avoir constitué la liste
# initiale à la main via Gemini (interface web, probablement avec recherche
# live). Groq (déjà intégré à SDE pour les explications, cf. llm_explain.py)
# n'a PAS d'accès web — une suggestion via Groq est un rappel de mémoire
# d'entraînement, pas une donnée de marché vérifiée ni aussi fraîche qu'une
# recherche live. D'où : chaque ticker suggéré est VALIDÉ (résolution réelle
# via get_market_data) avant d'être proposé, et l'application à l'univers
# actif est une étape SÉPARÉE et EXPLICITE (jamais de remplacement silencieux).

_TABLE_UNIVERS = "opportunites_univers"

# Plusieurs IA plutôt qu'une seule (24.07.2026) : chaque IA a ses propres
# biais de suggestion — un ticker proposé indépendamment par PLUSIEURS
# sources est un signal de consensus plus fort qu'une suggestion isolée.
# "gemini" reste la seule à avoir un appel API automatique (grounding
# Google Search, cf. suggerer_univers) ; gpt/autre sont toujours en
# collage manuel (aucune IA tierce n'est intégrée par API dans ce projet).
SOURCES_IA        = ("gemini", "gpt", "autre")
MAX_UNIVERS_FUSION = 20   # taille visée pour l'univers final, comme UNIVERS_SCAN
_locks_ia         = {src: threading.Lock() for src in SOURCES_IA}

PROMPT_SUGGESTION_DEFAUT = (
    "Tu es un analyste financier. Réponds UNIQUEMENT avec des symboles "
    "ticker NASDAQ séparés par des virgules, sans aucun texte avant, après "
    "ou entre — pas de phrase, pas de numérotation, pas d'explication.\n\n"
    "Liste exactement 20 tickers NASDAQ qui affichent une dynamique de "
    "performance RÉCENTE POSITIVE (en hausse sur les 5 derniers jours de "
    "bourse), pas simplement des entreprises connues ou de grosse "
    "capitalisation — vérifie leur cours actuel avant de répondre.\n\n"
    "Pour chaque candidat, évalue aussi où il en est dans son mouvement : "
    "privilégie les tickers dont le potentiel de hausse semble encore "
    "significatif (catalyseur récent pas encore pleinement intégré au "
    "cours), et écarte ceux dont la hausse principale semble déjà "
    "terminée — dans ce cas une consolidation ou un repli devient "
    "probable, même si la performance sur 5 jours reste positive."
)

_state_univers = {
    "prompt": PROMPT_SUGGESTION_DEFAUT,   # UN SEUL prompt, partagé entre les 3 sources
                                           # (même question posée à plusieurs IA — sinon
                                           # le consensus ne veut plus rien dire)
    "sources": {
        src: {
            "en_cours":    False,
            "progression": None,
            "suggestion":  None,   # liste de dicts {ticker, company_name, prix, var_5d}
            "erreur":      None,
        }
        for src in SOURCES_IA
    },
}
_hydrate_prompt_tentee = False   # une seule tentative de rechargement Supabase par process


def get_univers_actif() -> list[str]:
    """Univers courant : override persisté si présent, sinon UNIVERS_SCAN par défaut."""
    try:
        from db import find_one, is_available
        if is_available():
            row = find_one(_TABLE_UNIVERS, {"id": 1})
            if row and row.get("tickers"):
                return row["tickers"]
    except Exception as e:
        print(f"[Screener] lecture univers actif échouée : {e}", flush=True)
    return UNIVERS_SCAN


def _fusionner_sources(sources: dict) -> list[dict]:
    """
    Fusionne les suggestions des différentes IA en une seule liste :
    un ticker proposé par PLUSIEURS sources est priorisé (consensus), le
    reste est classé par performance récente (var_5d) décroissante — même
    logique que le tri à source unique, simplement appliquée après fusion.
    Fonction PURE — testable sans réseau. Robuste par construction si une
    ou plusieurs sources n'ont encore rien produit (`.get(...) or []`) :
    aucune source renseignée -> liste vide, pas d'erreur.
    """
    par_ticker: dict[str, dict] = {}
    for src, etat in (sources or {}).items():
        for item in (etat or {}).get("suggestion") or []:
            t = item["ticker"]
            if t not in par_ticker:
                par_ticker[t] = {**item, "sources": []}
            if src not in par_ticker[t]["sources"]:
                par_ticker[t]["sources"].append(src)

    fusion = list(par_ticker.values())
    # Tri à deux clés, toutes deux décroissantes via reverse=True :
    # d'abord le nombre de sources en consensus, puis la perf récente.
    fusion.sort(
        key=lambda d: (len(d["sources"]),
                       d["var_5d"] if d["var_5d"] is not None else float("-inf")),
        reverse=True,
    )
    return fusion[:MAX_UNIVERS_FUSION]


def get_suggestion_state() -> dict:
    # Même pattern que get_scan_state() : le prompt personnalisé vit en
    # mémoire process (workers=1, donc partagé entre requêtes tant que le
    # worker vit), mais gunicorn le recycle périodiquement (max_requests) —
    # sans ce rechargement, un prompt sauvegardé "disparaissait" après un
    # recyclage silencieux, revenant au défaut sans que rien ne l'indique.
    global _hydrate_prompt_tentee
    if not _hydrate_prompt_tentee:
        _hydrate_prompt_tentee = True
        try:
            from db import find_one, is_available
            if is_available():
                row = find_one(_TABLE_UNIVERS, {"id": 1})
                if row and row.get("prompt"):
                    _state_univers["prompt"] = row["prompt"]
        except Exception as e:
            print(f"[Screener] rechargement prompt échoué : {e}", flush=True)
    return {
        "prompt":  _state_univers["prompt"],
        "sources": {src: dict(etat) for src, etat in _state_univers["sources"].items()},
        "fusion":  _fusionner_sources(_state_univers["sources"]),
    }


def sauvegarder_prompt(prompt: str):
    """
    Persiste le prompt édité par l'utilisateur, indépendamment d'un lancement
    de suggestion — demandé pour ne pas avoir à relancer une analyse juste
    pour ne pas perdre une modification du texte. Même table que l'univers
    (id=1, single-row) : un prompt sans univers associé n'a pas de sens.
    """
    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("Prompt vide")

    from db import update_one, is_available
    if not is_available():
        raise RuntimeError("Supabase indisponible — impossible de sauvegarder le prompt")
    update_one(
        _TABLE_UNIVERS,
        {"id": 1},
        {"$set": {"prompt": prompt}},
        upsert=True,
    )
    _state_univers["prompt"] = prompt


def _valider_ticker(ticker: str) -> dict | None:
    """
    Rejette une hallucination du LLM : le ticker doit vraiment répondre.
    Retourne aussi le nom et la performance récente (var_5d) pour l'affichage
    UI — demandé pour que la suggestion soit lisible sans devoir cliquer sur
    chaque ticker séparément.
    """
    try:
        data = get_market_data(ticker)
        if not data or not data.get("price"):
            return None
        return {
            "ticker":       ticker,
            "company_name": data.get("company_name", ticker),
            "prix":         data.get("price"),
            "var_5d":       data.get("var_5d"),
        }
    except Exception:
        return None


def _extraire_texte_gemini(data: dict) -> str:
    """
    Extrait le texte généré par generateContent : data["candidates"][0]
    ["content"]["parts"][0]["text"] — forme VÉRIFIÉE en réel le 23.07.2026
    (la doc officielle, résumée via un fetch web, indiquait une tout autre
    forme "steps[]" pour un autre endpoint — elle s'est révélée fausse pour
    generateContent une fois testée avec une vraie clé. Leçon : un test
    réel bat toujours un résumé de documentation).
    On lève une ValueError explicite plutôt que de laisser un KeyError brut
    remonter — plus facile à diagnostiquer si Google change encore la forme.
    """
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        raise ValueError(f"Format de réponse Gemini inattendu : {data}")


def _extraire_tickers(texte: str, limite: int = 30) -> list[str]:
    """
    Extrait des symboles ticker plausibles (1-5 lettres majuscules) d'un texte
    libre, dédoublonnés, en conservant l'ordre d'apparition. Pure — testable
    sans appel réseau. `limite` est un garde-fou si le LLM déborde du format
    demandé (texte parasite, numérotation, etc.).
    """
    import re
    vus, candidats = set(), []
    for m in re.findall(r"\b[A-Z]{1,5}\b", texte):
        if m not in vus:
            vus.add(m)
            candidats.append(m)
    return candidats[:limite]


def _traiter_reponse_ia(texte: str, etat: dict = None) -> list[dict]:
    """
    Pipeline partagé entre le mode automatique (appel Gemini) et le mode
    collage manuel (copié depuis l'interface web d'une IA, pour contourner
    le blocage géographique de l'API Gemini sur Render EU — vérifié en réel
    le 23.07.2026 : "User location is not supported"). Extraction des
    tickers, validation réelle (get_market_data), tri par performance
    récente décroissante — la partie qui compte vraiment pour la qualité du
    résultat, peu importe QUI a proposé les candidats.

    `etat` (optionnel) : sous-dict de progression À METTRE À JOUR (une des 3
    sources IA) — None quand appelé hors contexte d'état partagé (tests).
    """
    candidats = _extraire_tickers(texte)

    valides = []
    for i, ticker in enumerate(candidats):
        if etat is not None:
            etat["progression"] = f"Vérification {i + 1}/{len(candidats)} ({ticker})"
        detail = _valider_ticker(ticker)
        if detail:
            valides.append(detail)
        if len(valides) >= 20:
            break
        if i < len(candidats) - 1:
            time.sleep(PAUSE_ETAGE1_S)

    if not valides:
        raise ValueError("Aucun ticker valide n'a pu être extrait du texte")

    # Tri par performance récente décroissante — même en demandant une
    # dynamique positive, l'IA reste biaisée vers les valeurs connues
    # (vérifié en réel : suggestions correctes mais majoritairement en
    # baisse malgré le prompt). Le tri rend ce biais visible d'un coup
    # d'œil plutôt que de le masquer dans une liste à l'ordre arbitraire.
    # None (perf indisponible) en dernier, jamais traité comme "positif".
    valides.sort(key=lambda d: d["var_5d"] if d["var_5d"] is not None else float("-inf"),
                 reverse=True)
    return valides


def analyser_texte_univers(texte: str, source: str) -> bool:
    """
    Mode manuel : l'utilisateur copie le prompt affiché côté UI dans une IA
    de son choix (Gemini, ChatGPT, autre) depuis son propre navigateur —
    jamais bloqué géographiquement, contrairement à un appel serveur depuis
    Render EU — puis colle la réponse dans l'onglet correspondant à CETTE
    source. Même pipeline d'extraction/validation/tri que le mode
    automatique (_traiter_reponse_ia), sans appel réseau vers une API IA
    côté serveur. `source` doit être l'une de SOURCES_IA (un onglet) —
    permet à plusieurs IA de contribuer en parallèle à la fusion finale.
    """
    if source not in SOURCES_IA:
        raise ValueError(f"Source IA inconnue : {source}")
    lock = _locks_ia[source]
    if not lock.acquire(blocking=False):
        return False

    texte = (texte or "").strip()
    etat  = _state_univers["sources"][source]

    def _run():
        try:
            etat["en_cours"]    = True
            etat["erreur"]      = None
            etat["suggestion"]  = None
            etat["progression"] = "Analyse du texte collé…"

            if not texte:
                raise ValueError("Texte collé vide")

            etat["suggestion"] = _traiter_reponse_ia(texte, etat=etat)
        except Exception as e:
            etat["erreur"] = str(e)
            print(f"[Screener] analyse texte collé ({source}) erreur : {e}", flush=True)
        finally:
            etat["progression"] = None
            etat["en_cours"] = False
            lock.release()

    threading.Thread(target=_run, daemon=True).start()
    return True


def suggerer_univers(prompt: str | None = None) -> bool:
    """
    Lance en thread background : interroge Gemini AVEC grounding Google
    Search (contrairement à Groq/LLaMA, qui répond uniquement depuis sa
    mémoire d'entraînement — Gemini peut vérifier ce qui bouge réellement
    sur le marché avant de répondre) avec `prompt` (ou le prompt par défaut
    si None/vide — l'utilisateur peut l'éditer côté UI et relancer), extrait
    les tickers, valide chacun (get_market_data réel, récupère aussi nom +
    performance récente pour l'affichage), stocke la suggestion dans la
    source "gemini" de _state_univers (seule IA appelée par API dans ce
    projet) — ne touche PAS l'univers actif (appliquer_univers est un
    appel séparé, déclenché explicitement).
    """
    source = "gemini"
    lock = _locks_ia[source]
    if not lock.acquire(blocking=False):
        return False

    prompt = (prompt or "").strip() or PROMPT_SUGGESTION_DEFAUT
    etat   = _state_univers["sources"][source]

    def _run():
        try:
            etat["en_cours"]   = True
            etat["erreur"]     = None
            etat["suggestion"] = None
            _state_univers["prompt"] = prompt   # prompt partagé entre les 3 sources
            etat["progression"] = "Interrogation de l'IA (recherche web)…"

            import requests
            from config import GEMINI_API_KEY, GEMINI_MODEL, LLM_TIMEOUT

            if not GEMINI_API_KEY or GEMINI_API_KEY == "votre_cle_gemini_ici":
                raise ValueError("Clé Gemini absente — voir config.py")

            resp = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
                params={"key": GEMINI_API_KEY},
                headers={"Content-Type": "application/json"},
                json={
                    # `prompt` EST le texte envoyé tel quel — rien de caché côté
                    # serveur. Le textarea de l'UI montre exactement ceci, pour
                    # que "ce que l'utilisateur voit" == "ce que Gemini reçoit"
                    # (demandé après que la consigne "analyste financier" était
                    # cachée dans le code, invisible/non éditable côté UI).
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "tools": [{"google_search": {}}],
                },
                timeout=LLM_TIMEOUT,
            )
            # resp.raise_for_status() ne garde que le code HTTP dans le
            # message ("400 Client Error: Bad Request for url: ...") — le
            # JSON d'erreur de Google (raison précise : clé invalide, quota,
            # modèle indisponible...) est perdu. On le récupère nous-mêmes
            # pour ne pas avoir à reproduire l'appel en local à chaque panne.
            if not resp.ok:
                raise ValueError(f"Gemini a répondu {resp.status_code} : {resp.text[:500]}")
            texte = _extraire_texte_gemini(resp.json())

            etat["suggestion"] = _traiter_reponse_ia(texte, etat=etat)
        except Exception as e:
            etat["erreur"] = str(e)
            print(f"[Screener] suggestion univers erreur : {e}", flush=True)
        finally:
            etat["progression"] = None
            etat["en_cours"] = False
            lock.release()

    threading.Thread(target=_run, daemon=True).start()
    return True


def appliquer_univers(tickers: list[str]):
    """Remplace l'univers actif (persisté Supabase). Étape explicite, séparée de la suggestion."""
    tickers = [t.upper().strip() for t in (tickers or []) if t and t.strip()]
    if not tickers:
        raise ValueError("Liste de tickers vide")

    from db import update_one, is_available
    if not is_available():
        raise RuntimeError("Supabase indisponible — impossible de persister l'univers")
    update_one(
        _TABLE_UNIVERS,
        {"id": 1},
        {"$set": {"tickers": tickers, "derniere_maj": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    _state_univers["suggestion"] = None   # suggestion consommée
