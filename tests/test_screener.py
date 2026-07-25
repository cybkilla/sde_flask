# tests/test_screener.py — logique pure de l'entonnoir à 2 étages, hors réseau.
#
# _scan_technique / _scan_complet sont monkeypatchées (comme dans
# test_backtest.py) : on vérifie uniquement la mécanique de lancer_scan()
# (tri, entonnoir N_SHORTLIST -> N_TOP, gestion du verrou, état exposé),
# pas les appels réseau réels.

import sys, pathlib, time
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from analysis import screener

screener.PAUSE_ETAGE1_S    = 0   # pas de pause entre tickers dans les tests
screener.PAUSE_RATTRAPAGE_S = 0  # pas de pause de rattrapage dans les tests

# lancer_scan()/appliquer_univers()/sauvegarder_prompt() écrivent dans
# Supabase quand la base est joignable (`db.is_available()`) — ce qui
# arrivait bel et bien en local avec un .env valide, et a réellement
# écrasé la table opportunites_scan de PROD avec un ticker de test "OK1"
# le 24.07.2026 (`lancer_scan(univers=["ERR", "OK1"])` ci-dessous). Ce
# module doit rester HORS RÉSEAU même quand des identifiants Supabase
# valides sont disponibles dans l'environnement de dev.
import db
db.is_available = lambda: False


def _attendre_fin_scan(timeout=5):
    t0 = time.time()
    while screener.get_scan_state()["en_cours"]:
        if time.time() - t0 > timeout:
            raise TimeoutError("scan pas terminé à temps")
        time.sleep(0.01)


# ── Cas nominal : tri par score technique puis par score global ──
def _fausse_technique(ticker):
    scores = {"AAA": 80, "BBB": 40, "CCC": 90, "DDD": 30}
    return {"ticker": ticker, "company_name": ticker + " Inc.", "score_tech": scores[ticker]}


def _faux_complet(ticker):
    # Le classement final doit suivre score_global, PAS score_tech de l'étage 1
    scores_globaux = {"AAA": 55, "CCC": 70}
    return {
        "ticker": ticker, "company_name": ticker + " Inc.",
        "score_global": scores_globaux[ticker], "recommandation": "ACHETER",
        "prix": 10.0, "divergence": None,
    }


screener._scan_technique = _fausse_technique
screener._scan_complet   = _faux_complet
screener.N_SHORTLIST = 2   # seuls les 2 meilleurs de l'étage 1 passent à l'étage 2
screener.N_TOP       = 5

ok = screener.lancer_scan(univers=["AAA", "BBB", "CCC", "DDD"])
assert ok is True
_attendre_fin_scan()

state = screener.get_scan_state()
assert state["erreur"] is None
# Seuls CCC (90) et AAA (80) passent l'entonnoir (top 2 technique) — BBB/DDD écartés
assert [r["ticker"] for r in state["resultats"]] == ["CCC", "AAA"]  # trié par score_global (70 > 55)
assert state["derniere_maj"] is not None
print("✓ entonnoir : tri technique -> shortlist -> tri score_global")


# ── Verrou : un scan déjà en cours refuse un second lancement ──
import threading

def _lente(ticker):
    time.sleep(0.2)
    return {"ticker": ticker, "company_name": ticker, "score_tech": 50}

screener._scan_technique = _lente
screener._scan_complet   = _faux_complet
screener._state["resultats"] = []

ok1 = screener.lancer_scan(univers=["AAA"])
ok2 = screener.lancer_scan(univers=["BBB"])   # doit être refusé, scan1 en cours
assert ok1 is True
assert ok2 is False
_attendre_fin_scan()
print("✓ verrou : deuxième lancement refusé pendant qu'un scan tourne")


# ── Résilience : un ticker qui échoue à l'étage 1 est simplement écarté ──
# (le contrat de _scan_technique/_scan_complet est d'avaler leurs propres
# exceptions et de retourner None — c'est CE contrat qu'on vérifie ici,
# côté orchestration : un retour None ne doit pas entrer dans les résultats
# ni faire planter le reste du scan)
screener._scan_technique = lambda t: None if t == "ERR" else {"ticker": t, "company_name": t, "score_tech": 60}
screener._scan_complet   = lambda t: {"ticker": t, "company_name": t, "score_global": 50, "recommandation": "TENIR", "prix": 1.0, "divergence": None}
screener._state["resultats"] = []

ok = screener.lancer_scan(univers=["ERR", "OK1"])
assert ok is True
_attendre_fin_scan()
state = screener.get_scan_state()
assert state["erreur"] is None   # une erreur ticker isolée ne fait pas planter tout le scan
assert [r["ticker"] for r in state["resultats"]] == ["OK1"]
print("✓ résilience : un ticker en échec à l'étage 1 est écarté sans casser le scan")


# ── Filtre RSI surachat : un ticker déjà en surachat n'est plus une
#    opportunité d'ENTRÉE, même bien classé techniquement (24.07.2026) ──
screener._scan_technique = lambda t: {
    "ticker": t, "company_name": t, "score_tech": 80,
    "rsi": {"LOW": 40, "HIGH": 85, "SEUIL": 70, "DRIFT": 50}[t],
}
screener._scan_complet = lambda t: {
    "ticker": t, "company_name": t, "score_global": 60, "recommandation": "ACHETER",
    "prix": 10.0, "divergence": None,
    # DRIFT : passe l'étage 1 (RSI 50) mais son RSI a "dérivé" au-dessus du
    # seuil au moment de l'étage 2 (cache différent) -> doit être rattrapé
    # par le deuxième filtre, pas seulement le premier.
    "rsi": {"LOW": 40, "SEUIL": 70, "DRIFT": 78}.get(t),
}
screener._state["resultats"] = []

ok = screener.lancer_scan(univers=["LOW", "HIGH", "SEUIL", "DRIFT"])
assert ok is True
_attendre_fin_scan()
tickers_finaux = [r["ticker"] for r in screener.get_scan_state()["resultats"]]
assert "HIGH" not in tickers_finaux    # filtré dès l'étage 1 (RSI 85 > 70)
assert "DRIFT" not in tickers_finaux   # rattrapé par le filtre étage 2 (RSI 78 > 70)
assert "LOW" in tickers_finaux
assert "SEUIL" in tickers_finaux       # RSI exactement 70 -> <= seuil -> accepté (pas < strict)
print("✓ lancer_scan : filtre le surachat (RSI > 70) à l'étage 1 ET à l'étage 2")


# ── Extraction de tickers depuis un texte libre (pure, hors réseau) ──
# La suggestion IA doit dédoublonner, garder l'ordre d'apparition, et ne
# jamais planter même si le LLM ignore le format demandé.
texte_propre = "NVDA,AAPL,MSFT,GOOGL"
assert screener._extraire_tickers(texte_propre) == ["NVDA", "AAPL", "MSFT", "GOOGL"]

texte_bavard = "Voici ma liste : NVDA, AAPL, et aussi MSFT.\n1. GOOGL\n2. NVDA (doublon)"
extrait = screener._extraire_tickers(texte_bavard)
assert extrait == ["NVDA", "AAPL", "MSFT", "GOOGL"], extrait   # dédoublonné, ordre conservé

assert screener._extraire_tickers("") == []
assert screener._extraire_tickers("aucun ticker ici en minuscules") == []
print("✓ _extraire_tickers : dédoublonne, garde l'ordre, robuste au bruit/texte vide")


# ── Validation d'un ticker suggéré (rejette une hallucination du LLM) ──
# Retourne aussi nom + performance récente (var_5d), pour l'affichage UI.
screener.get_market_data = lambda t: (
    {"price": 123.45, "company_name": "Real Corp", "var_5d": 4.2} if t == "REAL"
    else (_ for _ in ()).throw(ValueError("introuvable"))
)
detail = screener._valider_ticker("REAL")
assert detail == {"ticker": "REAL", "company_name": "Real Corp", "prix": 123.45, "var_5d": 4.2}
assert screener._valider_ticker("FAKE") is None   # get_market_data lève -> rejeté, pas de crash

screener.get_market_data = lambda t: {"price": None}   # réponse sans prix exploitable
assert screener._valider_ticker("SANSPRIX") is None
print("✓ _valider_ticker : renvoie le détail (nom, prix, perf) si valide, None sinon (hors réseau, mocké)")


# ── appliquer_univers : validation d'entrée AVANT tout accès réseau/Supabase ──
try:
    screener.appliquer_univers([])
    raise AssertionError("aurait dû lever ValueError")
except ValueError:
    pass
try:
    screener.appliquer_univers(["  ", ""])
    raise AssertionError("aurait dû lever ValueError (aucun ticker exploitable)")
except ValueError:
    pass
print("✓ appliquer_univers : liste vide/inexploitable rejetée avant tout accès réseau")


# ── analyser_texte_univers : mode collage manuel (contourne le blocage
#    géographique Gemini sur Render EU), même pipeline que le mode auto —
#    désormais par SOURCE (Gemini/GPT/Autre), pour permettre la fusion
#    multi-IA demandée le 24.07.2026 ──
screener.get_market_data = lambda t: (
    {"price": 50.0, "company_name": t + " Inc.", "var_5d": {"AAA": -2.0, "BBB": 6.0}[t]}
    if t in ("AAA", "BBB") else (_ for _ in ()).throw(ValueError("introuvable"))
)


def _attendre_fin_univers(source, timeout=5):
    t0 = time.time()
    while screener.get_suggestion_state()["sources"][source]["en_cours"]:
        if time.time() - t0 > timeout:
            raise TimeoutError("analyse univers pas terminée à temps")
        time.sleep(0.01)


try:
    screener.analyser_texte_univers("AAA, BBB", source="inconnue")
    raise AssertionError("aurait dû lever ValueError sur une source IA inconnue")
except ValueError:
    pass
print("✓ analyser_texte_univers : source IA inconnue rejetée")

ok = screener.analyser_texte_univers("Voici ma liste : AAA, BBB (copié depuis Gemini)", source="gemini")
assert ok is True
_attendre_fin_univers("gemini")
state = screener.get_suggestion_state()
assert state["sources"]["gemini"]["erreur"] is None
assert [d["ticker"] for d in state["sources"]["gemini"]["suggestion"]] == ["BBB", "AAA"]   # trié par var_5d décroissant
print("✓ analyser_texte_univers : extrait, valide et trie le texte collé manuellement (par source)")

# Texte vide -> erreur claire, pas de crash, isolée à SA source (gpt), pas gemini
screener._state_univers["sources"]["gpt"]["suggestion"] = None
ok = screener.analyser_texte_univers("   ", source="gpt")
assert ok is True
_attendre_fin_univers("gpt")
state = screener.get_suggestion_state()
assert state["sources"]["gpt"]["erreur"] is not None
assert state["sources"]["gemini"]["suggestion"] is not None   # source gemini non affectée
print("✓ analyser_texte_univers : texte vide rejeté proprement, sans affecter les autres sources")


# ── _fusionner_sources : consensus priorisé, robuste si sources vides ──
sources_test = {
    "gemini": {"suggestion": [
        {"ticker": "AAA", "company_name": "AAA Inc.", "prix": 10.0, "var_5d": 2.0},
        {"ticker": "CCC", "company_name": "CCC Inc.", "prix": 30.0, "var_5d": 8.0},
    ]},
    "gpt": {"suggestion": [
        {"ticker": "AAA", "company_name": "AAA Inc.", "prix": 10.0, "var_5d": 2.0},
        {"ticker": "BBB", "company_name": "BBB Inc.", "prix": 20.0, "var_5d": 12.0},
    ]},
    "autre": {"suggestion": None},   # onglet jamais renseigné -> ne doit pas planter
}
fusion = screener._fusionner_sources(sources_test)
# AAA : consensus (2 sources) -> priorisé même si var_5d plus faible que BBB/CCC (1 seule source)
assert fusion[0]["ticker"] == "AAA"
assert fusion[0]["sources"] == ["gemini", "gpt"]
assert [d["ticker"] for d in fusion[1:]] == ["BBB", "CCC"]   # reste trié par var_5d décroissant
print("✓ _fusionner_sources : tickers en consensus priorisés, reste trié par performance récente")

assert screener._fusionner_sources({}) == []
assert screener._fusionner_sources({"gemini": {"suggestion": None}, "gpt": {}}) == []
print("✓ _fusionner_sources : robuste si aucune (ou une seule) source n'a été renseignée")


# ── Tri par performance récente décroissante (même clé que suggerer_univers) ──
# Vérifié en réel le 23.07.2026 : même en demandant une dynamique positive,
# l'IA reste biaisée vers les valeurs connues (Gemini avait renvoyé une
# majorité de tickers en baisse malgré le prompt) — le tri rend ce biais
# visible plutôt que de le laisser dans un ordre arbitraire.
brut = [
    {"ticker": "A", "var_5d": -3.0},
    {"ticker": "B", "var_5d": 5.0},
    {"ticker": "C", "var_5d": None},   # perf indisponible -> ne doit jamais passer pour "positif"
    {"ticker": "D", "var_5d": 0.0},
]
brut.sort(key=lambda d: d["var_5d"] if d["var_5d"] is not None else float("-inf"), reverse=True)
assert [d["ticker"] for d in brut] == ["B", "D", "A", "C"]
print("✓ tri par var_5d : meilleure perf d'abord, valeur manquante toujours en dernier")


# ── _extraire_texte_gemini : forme réponse generateContent, vérifiée en réel ──
reponse_generate_content = {"candidates": [{"content": {"parts": [{"text": "MSFT,GOOGL"}]}}]}
assert screener._extraire_texte_gemini(reponse_generate_content) == "MSFT,GOOGL"

try:
    screener._extraire_texte_gemini({"quelquechose": "inattendu"})
    raise AssertionError("aurait dû lever ValueError sur un format inconnu")
except ValueError:
    pass
print("✓ _extraire_texte_gemini : parse le format generateContent, échoue proprement sinon")


# ── suggerer_univers(prompt=...) : le prompt personnalisé est bien retenu
#    dans l'état, même si l'appel échoue ensuite (ex. clé Gemini absente) ──
import config as _config
_cle_gemini_orig = _config.GEMINI_API_KEY
_config.GEMINI_API_KEY = ""   # force l'échec avant tout appel réseau réel

ok = screener.suggerer_univers(prompt="mon prompt personnalisé de test")
assert ok is True
_attendre_fin_univers("gemini")

state = screener.get_suggestion_state()
assert state["prompt"] == "mon prompt personnalisé de test"
assert state["sources"]["gemini"]["erreur"] is not None   # clé absente -> échoue, mais le prompt a bien été retenu
_config.GEMINI_API_KEY = _cle_gemini_orig
print("✓ suggerer_univers : le prompt personnalisé est retenu dans l'état même en cas d'échec")

# ── sauvegarder_prompt : validation AVANT tout accès Supabase (même
#    ordre que appliquer_univers, pour rester testable hors réseau) ──
try:
    screener.sauvegarder_prompt("")
    raise AssertionError("aurait dû lever ValueError")
except ValueError:
    pass
try:
    screener.sauvegarder_prompt("   ")
    raise AssertionError("aurait dû lever ValueError (prompt vide après strip)")
except ValueError:
    pass
print("✓ sauvegarder_prompt : prompt vide rejeté avant tout accès Supabase")

print("\n✓ Tous les tests test_screener.py sont OK (hors réseau)")
