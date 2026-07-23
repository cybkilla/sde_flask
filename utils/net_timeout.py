# utils/net_timeout.py — borne stricte sur un appel réseau bloquant.
#
# yfinance n'expose aucun timeout natif sur .history()/.info/.news : un seul
# appel qui reste bloqué au niveau TCP (pas un rate-limit rapide, un vrai
# silence réseau) gèle le thread appelant indéfiniment. Sur Render, gunicorn
# tourne en 1 seul worker SYNC (aucun autre thread ne sert de requêtes HTTP
# pendant qu'une requête est en cours) — un appel bloqué y rend TOUTE
# l'application injoignable, pas seulement la page qui l'a déclenché
# (incident réel du 23.07.2026 : /analyze/SMCI?nocache=1 a rendu le site
# entier inaccessible).
#
# Piège à éviter : ThreadPoolExecutor crée des threads NON-daemon — même
# avec shutdown(wait=False), le thread abandonné reste un thread normal qui
# empêche l'interpréteur de se terminer proprement (vérifié : le process
# de test restait accroché en sortie malgré un with_timeout() qui rendait
# la main correctement). threading.Thread(daemon=True) est la bonne brique :
# le thread orphelin ne bloque jamais la fin du programme/worker, qu'il se
# termine un jour ou jamais.

import threading


class NetTimeout(Exception):
    """Levée quand l'appel dépasse le délai imparti."""


def with_timeout(fn, timeout_s: float, *args, **kwargs):
    resultat = {}

    def _run():
        try:
            resultat["valeur"] = fn(*args, **kwargs)
        except Exception as e:
            resultat["erreur"] = e

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout_s)

    if t.is_alive():
        raise NetTimeout(f"dépassement de {timeout_s}s")
    if "erreur" in resultat:
        raise resultat["erreur"]
    return resultat.get("valeur")
