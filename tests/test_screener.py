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


# ── suggerer_univers(prompt=...) : le prompt personnalisé est bien retenu
#    dans l'état, même si l'appel échoue ensuite (ex. clé Groq absente) ──
import config as _config
_cle_groq_orig = _config.GROQ_API_KEY
_config.GROQ_API_KEY = ""   # force l'échec avant tout appel réseau réel

ok = screener.suggerer_univers(prompt="mon prompt personnalisé de test")
assert ok is True
_t0 = time.time()
while screener.get_suggestion_state()["en_cours"]:
    if time.time() - _t0 > 5:
        raise TimeoutError("suggestion pas terminée à temps")
    time.sleep(0.01)

state = screener.get_suggestion_state()
assert state["prompt"] == "mon prompt personnalisé de test"
assert state["erreur"] is not None   # clé absente -> échoue, mais le prompt a bien été retenu
_config.GROQ_API_KEY = _cle_groq_orig
print("✓ suggerer_univers : le prompt personnalisé est retenu dans l'état même en cas d'échec")

print("\n✓ Tous les tests test_screener.py sont OK (hors réseau)")
