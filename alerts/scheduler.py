# alerts/scheduler.py
# Surveille périodiquement tous les tickers de toutes les watchlists.
# Envoie une alerte si la recommandation change
# ou si la variation du cours dépasse le seuil.
#
# Architecture deux vitesses :
#   Chemin rapide  (chaque passage) : get_live_price() → Finnhub quote seul
#   Chemin complet (snapshot > 24h) : pipeline.run()  → tous les modules

import sys
import time
import yaml
from datetime import datetime, timedelta
from pathlib  import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config import ALERT_VAR_THRESHOLD, CHECK_INTERVAL_MIN

USERS_FILE = Path(__file__).parent.parent / "auth" / "users.yaml"

# Anti-spam mémoire des paliers d'alerte {(ticker, date): palier} —
# filet si la migration var_alerte_* n'est pas encore appliquée
# (sinon re-email à chaque passage de 30 min)
_PALIERS_MEM: dict = {}


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
    try:
        with open(USERS_FILE) as f:
            config = yaml.safe_load(f) or {}
        users = config.get("credentials", {}).get("usernames", {})
        return {u: d.get("email", "") for u, d in users.items()}
    except FileNotFoundError:
        print(f"[Scheduler] users.yaml introuvable et Supabase vide — aucun utilisateur", flush=True)
        return {}


def _check_ticker(ticker: str, company: str, username: str, email: str) -> None:
    """
    Vérifie un ticker et envoie une alerte si nécessaire.

    Chemin rapide  : get_live_price() (Finnhub /quote) + snapshot Supabase
                     → 1 appel API léger, pas de NewsAPI, pas de Groq
    Chemin complet : pipeline.run() si snapshot expiré (> 24h)
                     → renouvelle le snapshot, consomme tous les quotas
    """
    from data.market         import get_live_price
    from snapshot            import get_snapshot, MAX_AGE_HOURS
    from watchlist.watchlist import get_last_score, save_last_score
    from alerts.mailer       import send_alert

    # ── 1. Prix live — toujours (appel léger Finnhub) ────
    live      = get_live_price(ticker)
    prix_live = live.get("price") or 0

    # ── 2. Reco + score — snapshot ou pipeline complet ───
    snap = get_snapshot(ticker, max_age_hours=MAX_AGE_HOURS)

    if snap:
        new_reco  = snap["recommandation"]
        new_score = snap["score_global"]
        context   = snap.get("explication", {}).get("texte", "")
        prix      = prix_live or snap["market"].get("price", 0)
        print(f"  [{ticker}] chemin rapide — snapshot Supabase utilisé", flush=True)
    else:
        # Snapshot absent ou expiré → pipeline complet → met à jour Supabase
        print(f"  [{ticker}] chemin complet — pipeline lancé", flush=True)
        from pipeline import run as pipeline_run
        res       = pipeline_run(ticker, use_cache=False)
        new_reco  = res["recommandation"]
        new_score = res["score_global"]
        context   = res.get("explication", {}).get("texte", "")
        prix      = prix_live or res["market"]["price"]

    # ── 3. Variation par rapport au dernier prix enregistré ──
    # Fenêtre de courtoisie : hors 08h-23h Paris, ni email ni mise à jour
    # du dernier état (sinon le changement nocturne serait avalé sans
    # alerte — la comparaison se fera au premier passage du matin)
    if not _fenetre_courtoisie():
        return

    last      = get_last_score(ticker)
    old_reco  = last.get("reco", "")

    # ── 4. Conditions d'alerte ────────────────────────────
    reco_change = bool(old_reco) and old_reco != new_reco

    # Variation QUOTIDIENNE (vs clôture de la veille, fournie par Finnhub).
    # L'ancienne comparaison au passage précédent (30 min) ratait les
    # chutes progressives : -8.5% par pas de ~1% ne franchissait jamais
    # le seuil de 5% (vécu TMC 16.07 — aucune alerte reçue).
    # Anti-spam par PALIERS : alerte à ±5%, re-alerte à ±10%, ±15%…
    # une seule fois par palier et par jour (persisté dans scores).
    from datetime import date as _date
    var_jour  = live.get("var_1d")
    palier    = 0
    if var_jour is not None and abs(var_jour) >= ALERT_VAR_THRESHOLD:
        palier = int(abs(var_jour) // ALERT_VAR_THRESHOLD) * int(ALERT_VAR_THRESHOLD)
    cle_mem = (ticker, str(_date.today()))
    deja_alerte = (
        (str(last.get("var_alerte_date") or "") == str(_date.today())
         and float(last.get("var_alerte_pct") or 0) >= palier)
        or _PALIERS_MEM.get(cle_mem, 0) >= palier
    )
    var_alert = palier > 0 and not deja_alerte
    variation_tracked = var_jour if var_jour is not None else 0

    # Note position pour l'email de chute : où est le seuil de
    # renforcement, combien de trésorerie — l'info pour DÉCIDER
    # (demande utilisateur du 17.07 après la chute non alertée)
    position_note = ""
    if var_alert and (var_jour or 0) < 0:
        try:
            from portfolio.positions import get_portfolio_summary, get_cash_disponible
            from portfolio.risk import atr_pct, seuils_adaptes
            from portfolio.config_advisor import get_config
            s = get_portfolio_summary(username, ticker, prix_live)
            if s and not s.get("position_fermee"):
                atr_e   = atr_pct((snap or {}).get("market", {}).get("history"))
                seuils  = seuils_adaptes(get_config(username), atr_e)
                cout    = float(s["cout_moyen"])
                prix_rf = cout * (1 + seuils["pnl_renforcer"] / 100)
                cash    = get_cash_disponible(username)
                cash_tx = (f" · trésorerie disponible : ${cash:,.2f}"
                           if cash is not None else "")
                position_note = (
                    f"Votre position : {s['total_shares']:g} actions à "
                    f"{cout:.2f} $ de coût moyen ({s['pnl_pct']:+.1f}%). "
                    f"Seuil de renforcement SDE : {prix_rf:.2f} $ "
                    f"({seuils['pnl_renforcer']:+.1f}% de latence){cash_tx}."
                )
        except Exception as e:
            print(f"  [Alerte] note position indisponible : {e}", flush=True)

    if reco_change or var_alert:
        print(f"  → Alerte {ticker} pour {username} "
              f"({old_reco}→{new_reco}, var={variation_tracked:+.1f}%)", flush=True)
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
            position_note = position_note,
        )
        if var_alert:
            # Mémorise le palier alerté (anti-spam) — limitation connue :
            # clé par ticker (pas par user) — si plusieurs utilisateurs
            # suivent le même ticker, seul le premier du passage reçoit
            # l'alerte de palier. À revoir si le multi-utilisateur
            # devient réel.
            _PALIERS_MEM[cle_mem] = palier
            save_last_score(ticker, new_score, new_reco, prix_live or prix,
                            extra={"var_alerte_pct": palier,
                                   "var_alerte_date": str(_date.today())})

    # ── 5. Mise à jour du dernier état connu ─────────────
    save_last_score(ticker, new_score, new_reco, prix_live or prix)

    # ── 6. Évaluation du conseil d'hier (J+1) ────────────
    if prix_live:
        try:
            from portfolio.advisor import evaluate_yesterday_advice
            evaluate_yesterday_advice(username, ticker, prix_live)
        except Exception as e:
            print(f"  [Advisor] evaluate J+1 erreur ({ticker}) : {e}", flush=True)

    # ── 7. Vérification Take Profit / Stop Loss ───────────
    if prix_live and email:
        try:
            from portfolio.targets import check_and_alert
            check_and_alert(username, ticker, company, prix_live, email)
        except Exception as e:
            print(f"  [Targets] TP/SL check erreur ({ticker}) : {e}", flush=True)


def _fenetre_paris(h_debut: int, m_debut: int, h_fin: int, m_fin: int,
                    jours_ouvres: bool = False) -> bool:
    """Vrai si l'heure de Paris est dans [début, fin) — le serveur est en UTC."""
    try:
        import zoneinfo
        now = datetime.now(zoneinfo.ZoneInfo("Europe/Paris"))
        if jours_ouvres and now.weekday() >= 5:
            return False
        tot = now.hour * 60 + now.minute
        return h_debut * 60 + m_debut <= tot < h_fin * 60 + m_fin
    except Exception:
        return False


def _fenetre_conseils() -> bool:
    """
    Génération des conseils position : 10h00-22h30 Paris, jours ouvrés.
    Avant : date.today() (UTC) basculait à 2h du matin Paris → le conseil
    du jour naissait la nuit sur le prix de clôture de la veille, et
    l'email de changement partait à 2h (vécu nuit du 15-16.07). Désormais
    il naît au pré-marché, avec des données fraîches et le gap détecté.
    """
    return _fenetre_paris(10, 0, 22, 30, jours_ouvres=True)


def _fenetre_courtoisie() -> bool:
    """Alertes email (reco/variation/TP-SL) : 08h00-23h00 Paris seulement."""
    return _fenetre_paris(8, 0, 23, 0)


def _fenetre_premarche() -> bool:
    """
    True pendant le pré-marché US en heure de Paris (10h00-15h25, jours
    ouvrés) — la fenêtre où un gap overnight est mesurable ET où il reste
    du temps pour réagir avant l'ouverture (15h30).
    """
    try:
        import zoneinfo
        now = datetime.now(zoneinfo.ZoneInfo("Europe/Paris"))
        tot = now.hour * 60 + now.minute
        return now.weekday() < 5 and 10 * 60 <= tot < 15 * 60 + 25
    except Exception:
        return False


def _check_position_advice(username: str, email: str) -> None:
    """
    Pour chaque ticker où l'utilisateur a une position OUVERTE :
    génère le conseil du jour s'il n'existe pas encore, et envoie un
    email si l'action a changé par rapport au dernier conseil connu.

    Pré-marché : si un gap overnight significatif (≥ max(2%, 1×ATR))
    rend obsolète un conseil déjà généré, il est invalidé et régénéré
    avec le prix pré-marché — les règles ATR (stop, trailing…) réagissent
    au gap via le P&L, et l'email de changement part AVANT l'ouverture.
    Anti flip-flop : une seule réévaluation par jour (marqueur
    'Pré-marché' dans le raisonnement).
    """
    from db import find, is_available
    if not is_available():
        return

    # Tickers distincts ayant au moins un lot pour cet utilisateur
    lots = find("positions", {"username": username}) or []
    tickers = {}
    for l in lots:
        t = l.get("ticker")
        if t:
            tickers.setdefault(t, l.get("company") or t)

    premarche = _fenetre_premarche()

    for ticker, company in tickers.items():
        try:
            from data.market       import get_live_price
            from portfolio.advisor import (ensure_today_advice, get_previous_advice,
                                           get_today_advice, delete_today_advice)

            live      = get_live_price(ticker) or {}
            prix_live = live.get("price") or 0
            if not prix_live:
                continue

            # ATR du titre (depuis le snapshot) — sert au gap pré-marché
            # ET à la réévaluation en séance
            from portfolio.risk import gap_significatif, atr_pct
            from snapshot import get_snapshot, MAX_AGE_HOURS
            snap_t = get_snapshot(ticker, max_age_hours=MAX_AGE_HOURS)
            atr_t  = atr_pct(snap_t.get("market", {}).get("history")) if snap_t else None

            # ── Gap overnight (pré-marché uniquement) ─────────────────
            gap_pct = None
            if premarche and live.get("prev_close"):
                gap = live.get("var_1d")     # prix pré-marché vs clôture veille
                if gap_significatif(gap, atr_t):
                    gap_pct = gap

            # Conseil du jour déjà généré + gap significatif + pas encore
            # réévalué aujourd'hui → invalider et régénérer avec le gap
            ancienne_action = None
            if gap_pct is not None:
                existant = get_today_advice(username, ticker)
                if existant and "Pré-marché" not in (existant.get("raisonnement") or ""):
                    ancienne_action = existant.get("action")
                    delete_today_advice(username, ticker)
                    print(f"  [Advice] {ticker} : gap pré-marché {gap_pct:+.1f}% "
                          f"— conseil réévalué", flush=True)

            # ── Réévaluation EN SÉANCE (15h30-22h Paris) ───────────────
            # Le conseil du jour était figé au prix de sa création : une
            # chute de -8.5% l'après-midi le laissait périmé toute la
            # journée (vécu TMC 16.07 — achat manuel sans conseil).
            # Si le cours s'écarte de ≥ 1×ATR du prix du conseil →
            # invalidation + régénération (1 fois par jour, marqueur).
            intraday_pct = None
            if (ancienne_action is None and atr_t
                    and _fenetre_paris(15, 30, 22, 0, jours_ouvres=True)):
                existant = get_today_advice(username, ticker)
                ref = float(existant.get("prix_jour") or 0) if existant else 0
                if (existant and ref > 0
                        and "réévalué en séance" not in (existant.get("raisonnement") or "")):
                    move = (prix_live - ref) / ref * 100
                    if abs(move) >= atr_t:
                        ancienne_action = existant.get("action")
                        delete_today_advice(username, ticker)
                        intraday_pct = round(move, 1)
                        print(f"  [Advice] {ticker} : mouvement en séance "
                              f"{move:+.1f}% (≥ 1×ATR {atr_t}%) — conseil réévalué",
                              flush=True)

            # ── Point de contrôle POST-OUVERTURE (16h30-17h30 Paris) ───
            # Le conseil du jour naît le matin sur la clôture de la veille :
            # la première heure de séance révèle le ton du jour (gap comblé
            # ou confirmé). Régénération systématique UNE fois, avec les
            # données réelles — email seulement si l'action change.
            # (demande utilisateur du 17.07 : « attendre 1h après
            # l'ouverture avant de décider »)
            post_open = False
            if (ancienne_action is None
                    and _fenetre_paris(16, 30, 17, 30, jours_ouvres=True)):
                existant = get_today_advice(username, ticker)
                r_txt = (existant or {}).get("raisonnement") or ""
                if (existant
                        and "après la première heure de séance" not in r_txt
                        and "réévalué en séance" not in r_txt):
                    ancienne_action = existant.get("action")
                    delete_today_advice(username, ticker)
                    post_open = True
                    print(f"  [Advice] {ticker} : point de contrôle "
                          f"post-ouverture — conseil réévalué", flush=True)

            advice, created = ensure_today_advice(username, ticker, prix_live,
                                                  gap_pct=gap_pct,
                                                  var_1d=live.get("var_1d"),
                                                  intraday_pct=intraday_pct,
                                                  post_open=post_open)
            if not created or not advice:
                continue          # déjà généré (page visitée) ou données manquantes

            # Référence de comparaison : le conseil invalidé du jour si
            # réévaluation sur gap, sinon le dernier conseil d'avant
            prev = ({"action": ancienne_action} if ancienne_action
                    else get_previous_advice(username, ticker))
            if prev and email and prev.get("action") != advice.get("action"):
                print(f"  [Advice] {ticker} : {prev['action']} → {advice['action']} "
                      f"— email à {username}", flush=True)
                from alerts.mailer import send_advice_change_alert
                send_advice_change_alert(
                    to_email   = email,
                    username   = username,
                    ticker     = ticker,
                    company    = company,
                    old_action = prev["action"],
                    new_action = advice["action"],
                    advice     = advice,
                    prix       = prix_live,
                )
            else:
                print(f"  [Advice] {ticker} : conseil du jour généré "
                      f"({advice.get('action')}, inchangé)", flush=True)
        except Exception as e:
            print(f"  [Advice] {ticker} erreur : {e}", flush=True)


def check_all():
    """Parcourt toutes les watchlists et vérifie chaque ticker."""
    from watchlist.watchlist import get_watchlist

    users    = get_all_users()
    now      = datetime.now()
    next_run = now + timedelta(minutes=CHECK_INTERVAL_MIN)
    print(f"[Scheduler] {len(users)} utilisateur(s) | "
          f"{now.strftime('%Y-%m-%d %H:%M')} → {next_run.strftime('%H:%M')}", flush=True)

    seen_tickers: set = set()   # évite de re-vérifier un ticker commun à plusieurs users

    for username, email in users.items():
        watchlist = get_watchlist(username)

        for item in (watchlist or []):
            ticker  = item["ticker"]
            company = item.get("company", ticker)

            try:
                _check_ticker(ticker, company, username, email)
                seen_tickers.add(ticker)
            except Exception as e:
                print(f"  ✗ Erreur {ticker} : {e}", flush=True)

        # ── Conseil quotidien sur les POSITIONS ouvertes ─────────
        # Le conseil n'était généré qu'à l'ouverture de la page : le
        # scheduler le génère désormais chaque jour ouvré pour chaque
        # position, et alerte par email si l'ACTION change (TENIR →
        # ALLÉGER…). Anti-doublon par construction : l'email ne part
        # qu'à la CRÉATION du conseil du jour (1×/jour/ticker max).
        if _fenetre_conseils():
            try:
                _check_position_advice(username, email)
            except Exception as e:
                print(f"  [Advice] Erreur conseils positions {username} : {e}", flush=True)

        # ── Rapport hebdomadaire (dimanche ≥ 8h Paris) ───────────
        # Déclenché même si la watchlist est vide (le rapport inclut le portefeuille)
        if email:
            try:
                from alerts.weekly_report import should_send, send_weekly_report
                if should_send(username):
                    print(f"[Weekly] Génération rapport pour {username}…", flush=True)
                    send_weekly_report(username, email, watchlist or [])
            except Exception as e:
                print(f"  [Weekly] Erreur rapport {username} : {e}", flush=True)

    # ── Évaluation multi-horizons (J+1 / J+5 / J+20) des conseils passés ──
    # Complète les colonnes manquantes de daily_advice. Peu coûteux : la
    # requête ne retourne que les lignes incomplètes, et l'historique est
    # téléchargé une seule fois par ticker concerné. Avant, seul le
    # dashboard admin déclenchait ce rattrapage — les J+5/J+20 ne se
    # remplissaient donc que si quelqu'un ouvrait la page.
    try:
        from portfolio.evaluator import evaluate_pending
        r = evaluate_pending(days_back=60)
        if r.get("evaluated"):
            print(f"[Scheduler] Évaluations complétées : {r}", flush=True)
    except Exception as e:
        print(f"[Scheduler] evaluate_pending erreur : {e}", flush=True)

    print(f"[Scheduler] Terminé — {len(seen_tickers)} ticker(s) vérifiés", flush=True)


if __name__ == "__main__":
    if "--once" in sys.argv:
        print("[Scheduler] Mode one-shot (--once)")
        check_all()
    else:
        print(f"[Scheduler] Démarré — vérification toutes les {CHECK_INTERVAL_MIN} min")
        while True:
            check_all()
            time.sleep(CHECK_INTERVAL_MIN * 60)
