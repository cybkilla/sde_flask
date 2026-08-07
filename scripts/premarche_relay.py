# scripts/premarche_relay.py — relais pré-marché exécuté par GitHub Actions.
#
# Pourquoi ce script existe : yfinance est la SEULE source gratuite d'un
# vrai prix pré-marché, mais Yahoo bloque les IP de Render (vérifié au
# fil du projet). Les runners GitHub Actions ont d'autres IP (Azure) :
# ce script y exécute yfinance pendant la fenêtre pré-marché et dépose
# les prix dans Supabase — l'app Render n'a plus qu'à lire la table
# (cf. data/market.py::get_premarket_gap, qui lit le relais en premier).
#
# Lancé par .github/workflows/premarche.yml toutes les 30 min ; sort
# immédiatement hors fenêtre (le cron GitHub est en UTC et ignore le
# passage heure d'été/hiver de Paris — le contrôle précis se fait ici).

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fenetre_premarche_paris() -> bool:
    """Même fenêtre que alerts/scheduler.py::_fenetre_premarche (10h00-15h25
    Paris, jours ouvrés) — dupliquée ici pour ne pas importer la chaîne
    d'alertes complète dans un runner CI minimal."""
    import zoneinfo
    now = datetime.now(zoneinfo.ZoneInfo("Europe/Paris"))
    tot = now.hour * 60 + now.minute
    return now.weekday() < 5 and 10 * 60 <= tot < 15 * 60 + 25


def _tickers_en_position() -> list[str]:
    """Tous les tickers présents dans positions — sans filtrer les positions
    clôturées (le tri fin est fait côté app ; quelques lignes de trop dans
    la table relais ne coûtent rien)."""
    import db
    rows = db.find("positions", {})
    return sorted({r["ticker"] for r in rows if r.get("ticker")})


def relayer() -> int:
    # RELAY_FORCE (input "force" du workflow_dispatch) : valider la chaîne
    # complète (secrets → yfinance → écriture) hors fenêtre — Yahoo garde
    # les champs preMarket* renseignés même après l'ouverture.
    if os.getenv("RELAY_FORCE", "").lower() == "true":
        print("[Relay] mode forcé (test manuel) — fenêtre pré-marché ignorée")
    elif not _fenetre_premarche_paris():
        print("[Relay] hors fenêtre pré-marché (10h00-15h25 Paris, lun-ven) — rien à faire")
        return 0

    import yfinance as yf
    import db

    if not db.is_available():
        print("[Relay] Supabase inaccessible — secrets SUPABASE_URL / "
              "SUPABASE_KEY manquants ou vides sur le dépôt GitHub "
              "(Settings → Secrets and variables → Actions)")
        return 1

    tickers = _tickers_en_position()
    if not tickers:
        # Piège vu au premier run réel (07.08.2026) : avec la clé anon,
        # RLS fait passer les tables pour VIDES sans lever d'erreur — le
        # run était vert et la table restait vide, sans explication.
        print("[Relay] 0 position lue — si des positions existent bien en "
              "base, SUPABASE_KEY est probablement la clé anon : il faut "
              "la service_role key (RLS bloque la lecture sinon)")
        return 0

    ok = 0
    for t in tickers:
        try:
            info     = yf.Ticker(t).info or {}
            pm_price = info.get("preMarketPrice")
            pm_pct   = info.get("preMarketChangePercent")
            prev     = info.get("regularMarketPreviousClose")
            if pm_price is None or (prev is None and pm_pct is None):
                # Pas de donnée pré-marché pour ce titre à cet instant :
                # on n'écrit RIEN (pas de fausse ligne), la ligne
                # précédente périmera d'elle-même via fetched_at.
                print(f"[Relay] {t} : pas de donnée pré-marché chez Yahoo")
                continue
            # Gap calculé depuis les deux prix, pas le % Yahoo — ses
            # champs .info sont désynchronisés entre eux (constaté le
            # 07.08.2026, même fix que get_premarket_gap côté app)
            gap = (round((float(pm_price) / float(prev) - 1) * 100, 2) if prev
                   else round(float(pm_pct), 2))
            db.update_one("premarche_quotes", {"ticker": t}, {"$set": {
                "prix":       round(float(pm_price), 4),
                "gap_pct":    gap,
                "prev_close": round(float(prev), 4) if prev else None,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }}, upsert=True)
            ok += 1
            print(f"[Relay] {t} : {pm_price} ({gap:+.2f}%) déposé")
        except Exception as e:
            print(f"[Relay] {t} échoué : {type(e).__name__}: {e}")

    print(f"[Relay] terminé — {ok}/{len(tickers)} tickers relayés")
    # Code retour 0 même en échec partiel : un ticker sans donnée ne doit
    # pas faire apparaître le workflow entier comme cassé. Échec TOTAL en
    # revanche = probablement Yahoo qui bloque aussi GitHub -> voyant rouge.
    return 0 if (ok > 0 or not tickers) else 1


if __name__ == "__main__":
    sys.exit(relayer())
