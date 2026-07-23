# tests/test_net_timeout.py — with_timeout() doit rendre la main au bout du
# délai imparti, même si l'appel sous-jacent ne revient JAMAIS (simulé par
# un event.wait() sans timeout) — c'est exactement le scénario de l'incident
# du 23.07.2026 (yfinance bloqué au niveau réseau, aucun timeout natif).

import sys, pathlib, time, threading
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from utils.net_timeout import with_timeout, NetTimeout


# ── Cas nominal : la fonction revient normalement avant le délai ──
r = with_timeout(lambda: 42, 2)
assert r == 42
print("✓ appel rapide : résultat retourné normalement")


# ── Cas bloqué indéfiniment : with_timeout doit rendre la main SANS
#    attendre que le thread abandonné se termine (piège shutdown(wait=True)) ──
_jamais = threading.Event()   # jamais .set() -> .wait() bloque pour toujours

def _bloque_pour_toujours():
    _jamais.wait()   # simule un appel réseau qui ne revient jamais
    return "jamais atteint"

t0 = time.time()
try:
    with_timeout(_bloque_pour_toujours, 1)
    raise AssertionError("aurait dû lever NetTimeout")
except NetTimeout:
    elapsed = time.time() - t0
    assert elapsed < 1.5, f"with_timeout a mis {elapsed:.2f}s à rendre la main (attendu ~1s)"
    print(f"✓ appel bloqué indéfiniment : NetTimeout levée après {elapsed:.2f}s (pas de blocage sur shutdown)")


# ── Une exception normale du fn appelé remonte telle quelle (pas masquée) ──
def _casse():
    raise ValueError("erreur réseau simulée")

try:
    with_timeout(_casse, 2)
    raise AssertionError("aurait dû lever ValueError")
except ValueError as e:
    assert "erreur réseau simulée" in str(e)
    print("✓ exception du fn appelé propagée telle quelle")

print("\n✓ Tous les tests test_net_timeout.py sont OK (hors réseau)")
