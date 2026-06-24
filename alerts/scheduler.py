# alerts/scheduler.py
# Surveille périodiquement tous les tickers de toutes les watchlists.
# Envoie une alerte si la recommandation change
# ou si la variation du cours dépasse le seuil.
# Lancer depuis le dossier stockengine/ : python alerts/scheduler.py

import sys
import time
import yaml
from datetime import datetime, timedelta
from pathlib  import Path

# Assure que la racine du projet est dans sys.path (utile en mode one-shot)
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config import ALERT_VAR_THRESHOLD, CHECK_INTERVAL_MIN

USERS_FILE = Path(__file__).parent.parent / "auth" / "users.yaml"


def get_all_users() -> dict:
    """Retourne {username: email} depuis Supabase, ou users.yaml en fallback."""
    try:
        from db import find, is_available
        if is_available():
            rows = find("users", {})
            if rows:
                return {r["username"]: r.get("email", "") for r in rows}
    except Exception as e:
        print(f"[Scheduler] Supabase get_all_users erreur : {e}", flush=True)
    # Fallback YAML (dev local sans Supabase)
    try:
        with open(USERS_FILE) as f:
            config = yaml.safe_load(f) or {}
        users = config.get("credentials", {}).get("usernames", {})
        return {u: d.get("email", "") for u, d in users.items()}
    except FileNotFoundError:
        print(f"[Scheduler] users.yaml introuvable et Supabase vide — aucun utilisateur", flush=True)
        return {}


def check_all():
    """
    Parcourt toutes les watchlists et analyse chaque ticker.
    Envoie un email si :
      - La recommandation a changé depuis la dernière vérification
      - La variation du cours dépasse ALERT_VAR_THRESHOLD (défaut 5%)
    """
    from pipeline            import run
    from watchlist.watchlist import get_watchlist, get_last_score, save_last_score
    from alerts.mailer       import send_alert

    users = get_all_users()
    now  = datetime.now()
    next_run = now + timedelta(minutes=CHECK_INTERVAL_MIN)
    print(f"[Scheduler] Vérification de {len(users)} utilisateur(s)…  "
          f"| Exécution : {now.strftime('%Y-%m-%d %H:%M')}  "
          f"| Prochaine : {next_run.strftime('%Y-%m-%d %H:%M')}", flush=True)

    for username, email in users.items():
        watchlist = get_watchlist(username)
        if not watchlist:
            continue

        for item in watchlist:
            ticker  = item["ticker"]
            company = item.get("company", ticker)

            try:
                # Relance le pipeline complet pour ce ticker
                res      = run(ticker, use_cache=False)
                new_reco = res["recommandation"]
                new_score= res["score_global"]
                prix     = res["market"]["price"]
                variation= res["market"]["var_1d"]

                # Récupère le dernier état connu
                last      = get_last_score(ticker)
                old_reco  = last.get("reco", "")
                last_prix = last.get("prix")

                # Variation relative au DERNIER prix enregistré par le scheduler.
                # Plus fiable que var_1d (yfinance) qui mesure toujours
                # "hier → aujourd'hui" et rate les chutes des jours précédents.
                if last_prix and last_prix > 0:
                    variation_tracked = round(
                        (prix - last_prix) / last_prix * 100, 2
                    )
                else:
                    # Premier passage pour ce ticker → fallback sur var_1d
                    variation_tracked = variation

                # Conditions d'alerte
                reco_change = bool(old_reco) and old_reco != new_reco
                var_alert   = abs(variation_tracked) >= ALERT_VAR_THRESHOLD

                if reco_change or var_alert:
                    print(f"  → Alerte {ticker} pour {username} "
                          f"({old_reco}→{new_reco}, "
                          f"var_tracked={variation_tracked:+.1f}%)")
                    context = res.get("explication", {}).get("texte", "")
                    send_alert(
                        to_email      = email,
                        username      = username,
                        ticker        = ticker,
                        company       = company,
                        old_reco      = old_reco or "—",
                        new_reco      = new_reco,
                        score         = new_score,
                        prix          = prix,
                        variation     = variation_tracked,
                        reco_changed  = reco_change,
                        var_triggered = var_alert,
                        context       = context,
                    )

                # Met à jour le dernier état connu (prix inclus)
                save_last_score(ticker, new_score, new_reco, prix)

            except Exception as e:
                print(f"  ✗ Erreur {ticker} : {e}")


if __name__ == "__main__":
    import sys
    if "--once" in sys.argv:
        # Mode GitHub Actions : un seul passage puis exit
        print("[Scheduler] Mode one-shot (--once)")
        check_all()
    else:
        # Mode local : boucle infinie
        print(f"[Scheduler] Démarré — vérification toutes les "
              f"{CHECK_INTERVAL_MIN} minutes")
        while True:
            check_all()
            time.sleep(CHECK_INTERVAL_MIN * 60)
        