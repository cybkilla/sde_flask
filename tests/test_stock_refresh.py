# tests/test_stock_refresh.py — rafraîchissement auto en arrière-plan de
# la page d'analyse, hors réseau (pipeline.run monkeypatché).
#
# Signalé 28.07.2026 : un snapshot vieux de plusieurs heures ne se
# rafraîchissait que sur clic manuel ("Rafraîchir"). Le déclenchement
# lui-même (seuil, appel pipeline.run) est testé ici ; le rendu de la page
# Flask (route /analyze/<ticker>) ne l'est pas — hors périmètre (nécessite
# app context/login, comme les autres routes de ce fichier).

import sys, pathlib, time
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import pipeline
from flask_app.blueprints import stock

appels = []


def _faux_run_lent(ticker, use_cache):
    appels.append(ticker)
    time.sleep(0.1)   # simule un pipeline qui prend un peu de temps
    return {"ticker": ticker}


pipeline.run = _faux_run_lent


def _attendre_fin(ticker, timeout=2):
    t0 = time.time()
    while ticker in stock._refresh_en_cours:
        if time.time() - t0 > timeout:
            raise TimeoutError(f"refresh {ticker} pas terminé à temps")
        time.sleep(0.01)


# ── Déclenchement nominal : pipeline.run appelé avec use_cache=False ──
appels.clear()
stock._lancer_refresh_arriere_plan("AAA")
_attendre_fin("AAA")
assert appels == ["AAA"]
print("✓ _lancer_refresh_arriere_plan : lance pipeline.run(ticker, use_cache=False) en tâche de fond")


# ── Dédoublonnage : deux appels rapprochés sur le MÊME ticker -> un seul run ──
appels.clear()
stock._lancer_refresh_arriere_plan("BBB")
stock._lancer_refresh_arriere_plan("BBB")   # pendant que le premier tourne encore
_attendre_fin("BBB")
assert appels == ["BBB"], f"attendu un seul appel, obtenu {appels}"
print("✓ _lancer_refresh_arriere_plan : un refresh déjà en cours n'en relance pas un second")


# ── Deux tickers différents : chacun son propre refresh, aucun blocage mutuel ──
appels.clear()
stock._lancer_refresh_arriere_plan("CCC")
stock._lancer_refresh_arriere_plan("DDD")
_attendre_fin("CCC")
_attendre_fin("DDD")
assert sorted(appels) == ["CCC", "DDD"]
print("✓ _lancer_refresh_arriere_plan : tickers différents rafraîchis indépendamment")


# ── Après la fin, un nouveau refresh est de nouveau possible (pas de fuite d'état) ──
appels.clear()
stock._lancer_refresh_arriere_plan("AAA")
_attendre_fin("AAA")
assert appels == ["AAA"]
assert "AAA" not in stock._refresh_en_cours
print("✓ _lancer_refresh_arriere_plan : l'état se libère après coup, pas de blocage permanent")

print("\n✓ Tous les tests test_stock_refresh.py sont OK (hors réseau)")
