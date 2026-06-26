# portfolio/advisor.py — Génération du conseil journalier par ticker
# Logique basée sur les signaux SDE + position de l'utilisateur.
# Pas d'appel LLM : règles transparentes, explicables, sans quota.

from datetime import date, datetime, timezone

_TABLE = "daily_advice"

# Labels lisibles pour chaque action
ACTION_LABELS = {
    "ACHETER":    ("↑ Acheter",    "#1D9E75", "success"),
    "RENFORCER":  ("↗ Renforcer",  "#15803d", "success"),
    "TENIR":      ("◆ Tenir",      "#BA7517", "warning"),
    "SURVEILLER": ("◎ Surveiller", "#5a6a7a", "secondary"),
    "ALLÉGER":    ("↘ Alléger",    "#D85A30", "danger"),
    "VENDRE":     ("↓ Vendre",     "#991b1b", "danger"),
}


# ── Génération du conseil ─────────────────────────────────────────────────────

def generate_advice(summary: dict | None, market: dict, snapshot: dict,
                    candle_info: dict | None = None,
                    cfg: dict | None = None) -> dict:
    """
    Génère un conseil structuré à partir de la position et de l'analyse SDE.

    summary     : résultat de get_portfolio_summary() — None si pas de position
    market      : dict market avec price, rsi, var_1d
    snapshot    : dict pipeline avec score_global, recommandation, etc.
    candle_info : dict optionnel {signal, pattern, description} depuis detect_patterns()
    cfg         : seuils configurables (get_config(username)) — valeurs par défaut si None
    """
    from portfolio.config_advisor import DEFAULTS
    c = {**DEFAULTS, **(cfg or {})}

    score  = float(snapshot.get("score_global", 50))
    reco   = snapshot.get("recommandation", "NEUTRE")
    rsi    = float(market.get("rsi") or 50)
    prix   = float(market.get("price") or 0)

    # ── Cas 1 : pas de position ───────────────────────────────────────────────
    if summary is None:
        if reco == "ACHETER" and score >= c["score_acheter"]:
            base = _conseil("ACHETER", None, prix,
                f"Pas de position. Signal SDE haussier ({score:.0f}/100, RSI {rsi:.0f}). "
                f"Opportunité d'entrée autour de {prix:.2f} $.")
        else:
            base = _conseil("SURVEILLER", None, None,
                f"Pas de position. Signal SDE {reco} ({score:.0f}/100) — "
                f"attendre un signal plus fort avant d'entrer.")
        return _with_candle(base, candle_info, pnl_pct=None,
                            score=score, reco=reco)

    # ── Cas 2 : position existante ────────────────────────────────────────────
    pnl_pct      = float(summary["pnl_pct"])
    total_shares = float(summary["total_shares"])
    cout_moyen   = float(summary["cout_moyen"])

    # Stop loss automatique
    if pnl_pct <= c["stop_loss_pct"]:
        base = _conseil("VENDRE", total_shares, prix,
            f"Stop loss atteint : position à {pnl_pct:+.1f}% (coût moyen {cout_moyen:.2f} $). "
            f"Limitation des pertes recommandée.")
        return _with_candle(base, candle_info, pnl_pct, score, reco)

    # Prise de bénéfices sur signal vendeur fort
    if pnl_pct >= c["take_profit_pct"] and reco == "VENDRE":
        alleger = max(1, round(total_shares * 0.5))
        base = _conseil("ALLÉGER", alleger, prix,
            f"Plus-value de {pnl_pct:+.1f}% + signal SDE baissier ({score:.0f}/100). "
            f"Sécurisation de la moitié de la position recommandée.")
        return _with_candle(base, candle_info, pnl_pct, score, reco)

    # Signal vendeur fort sans plus-value importante
    if reco == "VENDRE" and score <= c["score_vendre"]:
        base = _conseil("VENDRE", total_shares, prix,
            f"Signal SDE baissier fort ({score:.0f}/100, RSI {rsi:.0f}). "
            f"Sortie de position recommandée (P&L actuelle : {pnl_pct:+.1f}%).")
        return _with_candle(base, candle_info, pnl_pct, score, reco)

    # Renforcement sur faiblesse
    if pnl_pct <= c["pnl_renforcer"] and reco == "ACHETER" and rsi <= c["rsi_renforcer"]:
        renforcer = max(1, round(total_shares * 0.25))
        base = _conseil("RENFORCER", renforcer, prix,
            f"RSI bas ({rsi:.0f}) + signal SDE haussier ({score:.0f}/100). "
            f"Opportunité de renforcement sur faiblesse ({pnl_pct:+.1f}% de latence).")
        return _with_candle(base, candle_info, pnl_pct, score, reco, total_shares, prix)

    # Signal haussier confirmé en territoire positif
    if reco == "ACHETER" and score >= c["score_tenir"] and pnl_pct > 0:
        base = _conseil("TENIR", None, None,
            f"Signal SDE haussier ({score:.0f}/100) avec position en positif ({pnl_pct:+.1f}%). "
            f"Maintien recommandé, la tendance reste favorable.")
        return _with_candle(base, candle_info, pnl_pct, score, reco)

    # Défaut : tenir
    base = _conseil("TENIR", None, None,
        f"Position à {pnl_pct:+.1f}% (coût moyen {cout_moyen:.2f} $). "
        f"Signal SDE {reco} ({score:.0f}/100) — maintien de la position.")
    return _with_candle(base, candle_info, pnl_pct, score, reco, total_shares, prix)


def _conseil(action, quantite, prix_cible, raisonnement) -> dict:
    return {
        "action":             action,
        "quantite_suggeree":  quantite,
        "prix_cible":         round(prix_cible, 4) if prix_cible else None,
        "raisonnement":       raisonnement,
    }


def _with_candle(conseil: dict, candle_info: dict | None,
                 pnl_pct: float | None,
                 score: float = 50, reco: str = "NEUTRE",
                 total_shares: float = 0, prix: float = 0) -> dict:
    """
    Enrichit un conseil de base avec le signal du dernier pattern chandelier.
    Peut modifier l'action (ex. TENIR → ALLÉGER sur signal baissier fort)
    et complète toujours le raisonnement pour la transparence.
    """
    if not candle_info:
        return conseil
    if candle_info.get("signal") == "neutre":
        name = candle_info.get("pattern", "")
        if name:
            raison = (f"{conseil['raisonnement']}<br>"
                      f"<span style='color:var(--sde-muted)'>Figure chandelier : {name} — indécision.</span>")
            return _conseil(conseil["action"], conseil.get("quantite_suggeree"),
                            conseil.get("prix_cible"), raison)
        return conseil

    action  = conseil["action"]
    signal  = candle_info["signal"]   # "bullish" | "bearish"
    name    = candle_info["pattern"]
    raison  = conseil["raisonnement"]
    label   = "haussier" if signal == "bullish" else "baissier"

    if signal == "bearish":
        # TENIR + baissier + P&L pas catastrophique → alléger prudemment
        if action == "TENIR" and pnl_pct is not None and pnl_pct > -10:
            alleger = max(1, round(total_shares * 0.25)) if total_shares > 0 else None
            raison = (f"{raison}<br>"
                      f"Pattern chandelier {label} ({name}) — allégement partiel conseillé "
                      f"à court terme.")
            return _conseil("ALLÉGER", alleger, prix or None, raison)

        # RENFORCER + baissier → revenir à TENIR
        if action == "RENFORCER":
            raison = (f"Signal SDE {reco} ({score:.0f}/100) suggère un renforcement,<br>"
                      f"mais le pattern chandelier {label} ({name}) contre-indique un achat "
                      f"immédiat. Maintien préférable dans l'attente d'une confirmation haussière.")
            return _conseil("TENIR", None, None, raison)

        # Pas de position + baissier → rester sur SURVEILLER
        if action == "ACHETER" and pnl_pct is None:
            raison = (f"{raison}<br>"
                      f"Pattern chandelier {label} ({name}) — attendre confirmation "
                      f"avant d'entrer en position.")
            return _conseil("SURVEILLER", None, None, raison)

        # Autres cas : note de vigilance seulement
        raison = f"{raison}<br>Note : pattern chandelier {label} ({name}) — rester vigilant."

    elif signal == "bullish":
        if action in ("RENFORCER", "ACHETER"):
            raison = f"{raison}<br>Confirmé par un signal chandelier {label} ({name})."
        elif action == "TENIR" and pnl_pct is not None and pnl_pct < 0:
            raison = (f"{raison}<br>"
                      f"Pattern chandelier {label} ({name}) — rebond potentiel à surveiller.")
        elif action in ("ALLÉGER", "VENDRE"):
            raison = (f"{raison}<br>"
                      f"Attention : signal chandelier {label} ({name}) en contradiction "
                      f"avec la recommandation de vente — surveiller avant d'agir.")
        else:
            raison = f"{raison}<br>Pattern chandelier {label} ({name}) — tendance positive à court terme."

    return _conseil(action, conseil.get("quantite_suggeree"), conseil.get("prix_cible"), raison)


# ── Persistance Supabase ──────────────────────────────────────────────────────

def get_today_advice(username: str, ticker: str) -> dict | None:
    """Retourne le conseil du jour depuis Supabase si déjà généré."""
    try:
        from db import find_one, is_available
        if not is_available():
            return None
        row = find_one(_TABLE, {
            "username":     username,
            "ticker":       ticker.upper(),
            "date_conseil": str(date.today()),
        })
        return row
    except Exception as e:
        print(f"[Advisor] get_today_advice erreur : {e}", flush=True)
        return None


def save_advice(username: str, ticker: str, advice: dict,
                market: dict, snapshot: dict) -> dict:
    """Upsert le conseil du jour dans Supabase. Retourne la ligne."""
    try:
        from db import update_one, is_available
        if not is_available():
            return advice
        row = {
            "action":             advice["action"],
            "quantite_suggeree":  advice.get("quantite_suggeree"),
            "prix_jour":          market.get("price"),
            "prix_cible":         advice.get("prix_cible"),
            "score_sde":          snapshot.get("score_global"),
            "recommandation":     snapshot.get("recommandation"),
            "raisonnement":       advice.get("raisonnement"),
        }
        update_one(
            _TABLE,
            {"username": username, "ticker": ticker.upper(), "date_conseil": str(date.today())},
            {"$set": row},
            upsert=True,
        )
        return {**row, "username": username, "ticker": ticker, "date_conseil": str(date.today())}
    except Exception as e:
        print(f"[Advisor] save_advice erreur : {e}", flush=True)
        return advice


def get_all_today_advice(username: str, tickers: list) -> dict:
    """Retourne {ticker: advice_row} pour plusieurs tickers en une seule requête Supabase."""
    if not tickers:
        return {}
    try:
        from db import _init, _client, is_available
        if not is_available():
            return {}
        _init()
        rows = (
            _client.table(_TABLE)
            .select("*")
            .eq("username", username)
            .in_("ticker", [t.upper() for t in tickers])
            .eq("date_conseil", str(date.today()))
            .execute()
            .data or []
        )
        return {r["ticker"]: r for r in rows}
    except Exception as e:
        print(f"[Advisor] get_all_today_advice erreur : {e}", flush=True)
        return {}


def get_advice_history(username: str, ticker: str, limit: int = 30) -> list:
    """Retourne l'historique des conseils (plus récent en premier)."""
    try:
        from db import _init, _client, is_available
        if not is_available():
            return []
        _init()
        rows = (
            _client.table(_TABLE)
            .select("*")
            .eq("username", username)
            .eq("ticker", ticker.upper())
            .order("date_conseil", desc=True)
            .limit(limit)
            .execute()
            .data or []
        )
        return rows
    except Exception as e:
        print(f"[Advisor] get_advice_history erreur : {e}", flush=True)
        return []


def _paris_now():
    """Retourne datetime actuel en heure Paris. Lève RuntimeError si tzdata absent."""
    import zoneinfo
    return datetime.now(zoneinfo.ZoneInfo("Europe/Paris"))


def _is_market_open(now_paris=None) -> bool:
    """True si le NASDAQ est ouvert : lun-ven, 15h30-22h00 Paris."""
    if now_paris is None:
        now_paris = _paris_now()
    wd  = now_paris.weekday()   # 0=lun … 6=dim
    tot = now_paris.hour * 60 + now_paris.minute
    return wd < 5 and 15 * 60 + 30 <= tot < 22 * 60


def evaluate_yesterday_advice(username: str, ticker: str, current_price: float):
    """
    Appelé par le scheduler : évalue le conseil d'hier avec le prix actuel.
    Met à jour prix_j1, variation_j1, bon_conseil dans daily_advice.
    N'évalue qu'après l'ouverture du NASDAQ (15h30 Paris) pour éviter
    les faux-négatifs liés au prix de clôture de la veille encore en cache.
    Ré-évalue si une évaluation précédente était hors heures de marché.
    """
    from datetime import timedelta
    try:
        now_paris = _paris_now()
        if not _is_market_open(now_paris):
            return   # Prix non significatif hors marché
    except Exception:
        return   # tzdata absent → on ne risque pas une évaluation erronée

    yesterday = str(date.today() - timedelta(days=1))
    try:
        from db import find_one, update_one, is_available
        if not is_available():
            return

        row = find_one(_TABLE, {
            "username":     username,
            "ticker":       ticker.upper(),
            "date_conseil": yesterday,
        })
        if not row:
            return

        if row.get("evaluated_at"):
            # Ré-évaluer si l'évaluation précédente était hors heures de marché
            try:
                prev_eval  = datetime.fromisoformat(row["evaluated_at"])
                import zoneinfo
                prev_paris = prev_eval.astimezone(zoneinfo.ZoneInfo("Europe/Paris"))
                if _is_market_open(prev_paris):
                    return  # Déjà évalué pendant les heures de marché — on garde
                # Sinon : évaluation hors marché → on corrige
                print(f"[Advisor] {ticker} ré-évaluation (précédente hors marché à "
                      f"{prev_paris.strftime('%H:%M')} Paris)", flush=True)
            except Exception:
                return  # Sécurité : ne pas écraser si on ne peut pas vérifier

        prix_hier    = float(row.get("prix_jour") or 0)
        action       = row.get("action", "")
        variation_j1 = round((current_price - prix_hier) / prix_hier * 100, 2) if prix_hier else 0

        # Seuil TENIR depuis la config utilisateur
        from portfolio.config_advisor import get_config as _get_cfg
        var_tenir = _get_cfg(username).get("var_tenir_eval", 3.0)

        # Le conseil était-il bon ?
        bon = None
        if action in ("ACHETER", "RENFORCER"):
            bon = variation_j1 > 0
        elif action in ("VENDRE", "ALLÉGER"):
            bon = variation_j1 < 0
        elif action in ("TENIR", "SURVEILLER"):
            bon = abs(variation_j1) < var_tenir

        update_one(
            _TABLE,
            {"username": username, "ticker": ticker.upper(), "date_conseil": yesterday},
            {"$set": {
                "prix_j1":       round(current_price, 4),
                "variation_j1":  variation_j1,
                "bon_conseil":   bon,
                "evaluated_at":  datetime.now(timezone.utc).isoformat(),
            }},
        )
        emoji = "✓" if bon else "✗" if bon is not None else "?"
        print(f"[Advisor] {ticker} conseil {yesterday} évalué : {emoji} "
              f"({action}, var={variation_j1:+.1f}%)", flush=True)
    except Exception as e:
        print(f"[Advisor] evaluate_yesterday_advice erreur : {e}", flush=True)
