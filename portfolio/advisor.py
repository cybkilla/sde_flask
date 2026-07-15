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

def _get_data_date(snapshot: dict) -> str:
    """
    Retourne la date du dernier jour de TRADING au format DD.MM.YYYY.
    Ignore les lignes weekend (artefacts yfinance/TwelveData sur les snapshots dominicaux).
    """
    try:
        hist = snapshot.get("market", {}).get("history")
        if hist is not None and len(hist) > 0:
            for idx in reversed(list(hist.index)):
                if hasattr(idx, "weekday"):
                    wd = idx.weekday()
                else:
                    from datetime import datetime
                    wd = datetime.strptime(str(idx)[:10], "%Y-%m-%d").weekday()
                if wd < 5:  # lundi(0)–vendredi(4) uniquement
                    if hasattr(idx, "strftime"):
                        return idx.strftime("%d.%m.%Y")
                    y, m, d = str(idx)[:10].split("-")
                    return f"{d}.{m}.{y}"
    except Exception:
        pass
    return ""


def _dominant_signals_note(snapshot: dict, data_date: str = "",
                           direction: str = "", threshold: int = 10) -> str:
    """
    Retourne des lignes HTML pour les signaux à fort impact (|points| >= threshold).
    - Signaux techniques → préfixés de data_date (date du dernier cours)
    - Signaux fondamentaux (EPS, PE…) → sans date (métriques de bilan, pas de cours)
    direction filtre par sens selon le conseil final.
    """
    tech_sigs = [{"sig": s, "date": data_date} for s in snapshot.get("signals_tech", [])]
    fund_sigs = [{"sig": s, "date": ""}         for s in snapshot.get("signals_fund", [])]
    items = [item for item in tech_sigs + fund_sigs
             if abs(item["sig"].get("points", 0)) >= threshold]
    if direction:
        items = [item for item in items if item["sig"].get("sens") == direction]
    if not items:
        return ""
    items.sort(key=lambda x: abs(x["sig"].get("points", 0)), reverse=True)
    lines = []
    for item in items[:3]:
        s, sig_date = item["sig"], item["date"]
        pts   = s["points"]
        arrow = "↑" if pts > 0 else "↓"
        d     = f"{sig_date} : " if sig_date else ""
        lines.append(f"<br><span style='color:var(--sde-muted);font-size:.85em'>"
                     f"{d}{arrow} {s['nom']} ({pts:+.0f})</span>")
    return "".join(lines)


def generate_advice(summary: dict | None, market: dict, snapshot: dict,
                    candle_info: dict | None = None,
                    cfg: dict | None = None,
                    cash_dispo: float = None) -> dict:
    """
    Génère un conseil structuré à partir de la position et de l'analyse SDE.

    summary     : résultat de get_portfolio_summary() — None si pas de position
    market      : dict market avec price, rsi, var_1d
    snapshot    : dict pipeline avec score_global, recommandation, etc.
    candle_info : dict optionnel {signal, pattern, description} depuis detect_patterns()
    cfg         : seuils configurables (get_config(username)) — valeurs par défaut si None
    cash_dispo  : trésorerie suivie (ventes − achats, tous tickers) — None si
                  inconnue : les conseils d'achat ne sont alors PAS contraints
    """
    from portfolio.config_advisor import DEFAULTS
    c = {**DEFAULTS, **(cfg or {})}

    score  = float(snapshot.get("score_global", 50))
    reco   = snapshot.get("recommandation", "NEUTRE")
    rsi    = float(market.get("rsi") or 50)
    prix   = float(market.get("price") or 0)

    # ── Seuils normalisés par la volatilité du titre (ATR) ────────────
    # -20% est du bruit sur une small cap volatile et une catastrophe
    # sur un titre calme : les seuils % fixes de la config deviennent
    # des multiples d'ATR, bornés autour des valeurs configurées.
    # Sans historique (vieux snapshot) → seuils config inchangés.
    from portfolio.risk import atr_pct, seuils_adaptes, TRAIL_ATR_MULT
    hist_px = market.get("history")
    atr     = atr_pct(hist_px)
    seuils  = seuils_adaptes(c, atr)

    # Dates pour préfixer chaque ligne du raisonnement
    conseil_date_str = date.today().strftime("%d.%m.%Y")
    data_date_str    = _get_data_date(snapshot)
    cd = f"{conseil_date_str} : "

    # ── Mémoire des exécutions du jour ────────────────────────────────
    # Suivre un ALLÉGER invalide le conseil (recalcul avec la position à
    # jour) — mais sans mémoire, le même signal re-déclenchait un nouvel
    # ALLÉGER sur le restant : en suivant chaque conseil, on liquiderait
    # toute la position 25% par 25% dans la journée (vécu TMC 15.07).
    # Règle : une vente exécutée aujourd'hui suspend les NOUVELLES
    # suggestions de réduction pour la journée (le stop loss et le signal
    # VENDRE fort restent actifs — ce sont des contrôles de risque).
    _auj = str(date.today())
    _lots = (summary or {}).get("lots") or []
    vendu_auj  = sum(float(l.get("quantite") or 0) for l in _lots
                     if l.get("type") == "vente"
                     and str(l.get("date_achat", ""))[:10] == _auj)
    achete_auj = sum(float(l.get("quantite") or 0) for l in _lots
                     if l.get("type", "achat") == "achat"
                     and str(l.get("date_achat", ""))[:10] == _auj)

    # ── Ré-entrée après clôture ───────────────────────────────────────
    # Une position entièrement vendue laissait le ticker orphelin de
    # conseil : summary existait toujours (les lots restent en base),
    # donc le monde « sans position » — le seul qui produit ACHETER —
    # était inaccessible. On bascule explicitement en mode ré-entrée,
    # avec le contexte de sortie dans le texte.
    intro_sans_position = "Pas de position."
    if summary and summary.get("position_fermee"):
        ventes = [l for l in _lots if l.get("type") == "vente"]
        if ventes:
            derniere = max(ventes, key=lambda l: str(l.get("date_achat", "")))
            ds = str(derniere.get("date_achat", ""))[:10]
            ps = float(derniere.get("prix_achat") or 0)
            intro_sans_position = (
                f"Position clôturée le {ds[8:10]}.{ds[5:7]} à {ps:.2f} $ "
                f"(P&L réalisé {summary.get('pnl_realise', 0):+.2f} $)."
            )
        summary = None    # → cas « sans position » : ACHETER redevient possible

    def _finalize(conseil, pnl=None, shares=0, px=0):
        # var_1d LIVE (fourni par la route / le scheduler) : permet à
        # _with_candle d'invalider un pattern baissier de la veille
        # contredit par le rebond de la séance en cours
        r = _with_candle(conseil, candle_info, pnl, score, reco, shares, px,
                         data_date=data_date_str,
                         var_1d=market.get("var_1d"),
                         deja_vendu=vendu_auj)
        # Filtrer les signaux dans le sens du conseil final
        action = r["action"]
        if action in ("VENDRE", "ALLÉGER"):
            direction = "baissier"
        elif action in ("ACHETER", "RENFORCER"):
            direction = "haussier"
        else:
            direction = ""  # TENIR/SURVEILLER : pas de signaux dominants à afficher
        note = _dominant_signals_note(snapshot, data_date_str, direction)
        if note:
            r["raisonnement"] += note
        # Contexte macro : le score étant déjà ajusté par le régime dans le
        # pipeline, on EXPLIQUE ici l'ajustement plutôt que de le ré-appliquer
        # (sinon double comptage). Absent des vieux snapshots → .get défensif.
        mr = snapshot.get("market_regime")
        if mr and mr.get("regime") != "haussier":
            vol_txt = " et volatil" if mr.get("volatil") else ""
            r["raisonnement"] += (
                f"<br>{cd}Contexte marché {mr['regime']}{vol_txt} "
                f"(QQQ {mr.get('var_5j', 0):+.1f}% sur 5j) — "
                f"le score SDE intègre déjà cette prudence."
            )
        # Gap overnight : quand le conseil est (re)généré en pré-marché sur
        # un écart significatif vs la clôture de la veille, on l'explique —
        # le gap a déjà traversé les règles via le prix live (P&L, stop…),
        # cette ligne dit POURQUOI le conseil a pu changer avant l'ouverture.
        gap = market.get("gap_overnight")
        if gap is not None:
            sens_gap = "haussier" if gap > 0 else "baissier"
            r["raisonnement"] += (
                f"<br>{cd}Pré-marché : {gap:+.1f}% vs clôture de la veille "
                f"— gap {sens_gap} attendu à l'ouverture, conseil réévalué "
                f"avant la séance."
            )
        # Mémoire du jour : rappeler ce qui a déjà été exécuté
        if pnl is not None and vendu_auj > 0:
            r["raisonnement"] += (
                f"<br>{cd}Allégement de {vendu_auj:g} action(s) déjà réalisé "
                f"aujourd'hui — pas de nouvelle réduction suggérée le même "
                f"jour (le stop loss reste actif)."
            )
        # Seuils ATR : affichés sur TOUT conseil avec position (pnl fourni),
        # pas seulement quand un seuil se déclenche — l'utilisateur doit voir
        # en permanence à quels niveaux SDE réagira pour CE titre.
        if seuils["adapte"] and pnl is not None:
            r["raisonnement"] += (
                f"<br>{cd}Seuils adaptés à la volatilité du titre "
                f"(ATR {atr:.1f}%/j) : stop {seuils['stop_loss_pct']:+.1f}%, "
                f"objectif {seuils['take_profit_pct']:+.1f}%, "
                f"renforcement sous {seuils['pnl_renforcer']:+.1f}%."
            )
        return r

    # ── Cas 1 : pas de position (ou position clôturée → ré-entrée) ────────────
    if summary is None:
        # Clôture AUJOURD'HUI → jamais de ré-entrée le même jour : vendre
        # tout puis racheter dans la foulée serait du flip-flop assumé
        if vendu_auj > 0:
            base = _conseil("SURVEILLER", None, None,
                f"{cd}{intro_sans_position} Clôture réalisée aujourd'hui — "
                f"pas de ré-entrée le même jour, laisser le titre se stabiliser.")
        elif reco == "ACHETER" and score >= c["score_acheter"]:
            # Trésorerie suivie insuffisante pour UNE action → pas de
            # conseil d'achat inapplicable, on surveille en l'expliquant
            if cash_dispo is not None and prix > 0 and cash_dispo < prix:
                base = _conseil("SURVEILLER", None, None,
                    f"{cd}{intro_sans_position} Signal d'achat ({score:.0f}/100) "
                    f"mais trésorerie suivie insuffisante ({cash_dispo:.2f} $ "
                    f"pour un cours à {prix:.2f} $) — entrée non proposée.")
            else:
                cash_txt = (f" Trésorerie suivie disponible : {cash_dispo:,.2f} $ "
                            f"(≈ {int(cash_dispo // prix)} actions)."
                            if cash_dispo is not None and prix > 0 else "")
                base = _conseil("ACHETER", None, prix,
                    f"{cd}{intro_sans_position} Signal SDE haussier ({score:.0f}/100, RSI {rsi:.0f}). "
                    f"Opportunité d'entrée autour de {prix:.2f} $.{cash_txt}")
        else:
            base = _conseil("SURVEILLER", None, None,
                f"{cd}{intro_sans_position} Signal SDE {reco} ({score:.0f}/100) — "
                f"attendre un signal plus fort avant d'entrer.")
        return _finalize(base)

    # ── Cas 2 : position existante ────────────────────────────────────────────
    pnl_pct      = float(summary["pnl_pct"])
    total_shares = float(summary["total_shares"])
    cout_moyen   = float(summary["cout_moyen"])

    # Stop loss automatique — seuil ATR (borné par la config utilisateur)
    if pnl_pct <= seuils["stop_loss_pct"]:
        base = _conseil("VENDRE", total_shares, prix,
            f"{cd}Stop loss atteint : position à {pnl_pct:+.1f}% "
            f"(seuil {seuils['stop_loss_pct']:+.1f}%, coût moyen {cout_moyen:.2f} $). "
            f"Limitation des pertes recommandée.")
        return _finalize(base, pnl=pnl_pct)

    # Stop suiveur : la position est en gain mais rend ses acquis.
    # Le P&L vs prix d'entrée ne le voit pas — on compare au PLUS HAUT
    # atteint depuis l'achat (high-water mark) : repli > 2×ATR → sécuriser.
    if seuils["adapte"] and pnl_pct > 0 and vendu_auj == 0:
        from portfolio.risk import drawdown_depuis_plus_haut
        hwm, dd = drawdown_depuis_plus_haut(hist_px, summary.get("lots"), prix)
        if dd is not None and dd <= -(TRAIL_ATR_MULT * atr):
            alleger = max(1, round(total_shares * 0.5))
            base = _conseil("ALLÉGER", alleger, prix,
                f"{cd}Position toujours en gain ({pnl_pct:+.1f}%) mais repli de "
                f"{dd:+.1f}% depuis le plus haut ({hwm:.2f} $) — soit plus de "
                f"{TRAIL_ATR_MULT:.0f}× le bruit quotidien du titre (ATR {atr:.1f}%). "
                f"Sécuriser la moitié des gains recommandé.")
            return _finalize(base, pnl=pnl_pct)

    # Prise de bénéfices sur signal vendeur fort — objectif ATR
    if pnl_pct >= seuils["take_profit_pct"] and reco == "VENDRE" and vendu_auj == 0:
        alleger = max(1, round(total_shares * 0.5))
        base = _conseil("ALLÉGER", alleger, prix,
            f"{cd}Plus-value de {pnl_pct:+.1f}% (objectif {seuils['take_profit_pct']:+.1f}%) "
            f"+ signal SDE baissier ({score:.0f}/100). "
            f"Sécurisation de la moitié de la position recommandée.")
        return _finalize(base, pnl=pnl_pct)

    # Signal vendeur fort sans plus-value importante
    if reco == "VENDRE" and score <= c["score_vendre"]:
        base = _conseil("VENDRE", total_shares, prix,
            f"{cd}Signal SDE baissier fort ({score:.0f}/100, RSI {rsi:.0f}). "
            f"Sortie de position recommandée (P&L actuelle : {pnl_pct:+.1f}%).")
        return _finalize(base, pnl=pnl_pct)

    # Renforcement sur faiblesse — la "faiblesse" est mesurée en ATR :
    # -5% n'est une opportunité que si c'est inhabituel pour ce titre
    if pnl_pct <= seuils["pnl_renforcer"] and reco == "ACHETER" \
            and rsi <= c["rsi_renforcer"] and achete_auj == 0:
        renforcer = max(1, round(total_shares * 0.25))
        note_cash = ""
        if cash_dispo is not None and prix > 0:
            max_achetable = int(cash_dispo // prix)
            if max_achetable < 1:
                # Renforcement indiqué mais rien pour le financer :
                # un conseil inapplicable est pire que pas de conseil
                base = _conseil("TENIR", None, None,
                    f"{cd}Renforcement indiqué (RSI {rsi:.0f}, signal haussier "
                    f"{score:.0f}/100, position à {pnl_pct:+.1f}%) mais trésorerie "
                    f"suivie insuffisante ({cash_dispo:.2f} $) — maintien.")
                return _finalize(base, pnl=pnl_pct, shares=total_shares, px=prix)
            if renforcer > max_achetable:
                renforcer  = max_achetable
                note_cash = (f" Quantité limitée par la trésorerie disponible "
                             f"({cash_dispo:,.2f} $).")
        base = _conseil("RENFORCER", renforcer, prix,
            f"{cd}RSI bas ({rsi:.0f}) + signal SDE haussier ({score:.0f}/100). "
            f"Opportunité de renforcement sur faiblesse ({pnl_pct:+.1f}% de latence, "
            f"seuil {seuils['pnl_renforcer']:+.1f}%).{note_cash}")
        return _finalize(base, pnl=pnl_pct, shares=total_shares, px=prix)

    # Signal haussier confirmé en territoire positif
    if reco == "ACHETER" and score >= c["score_tenir"] and pnl_pct > 0:
        base = _conseil("TENIR", None, None,
            f"{cd}Signal SDE haussier ({score:.0f}/100) avec position en positif ({pnl_pct:+.1f}%). "
            f"Maintien recommandé, la tendance reste favorable.")
        return _finalize(base, pnl=pnl_pct)

    # Défaut : tenir
    base = _conseil("TENIR", None, None,
        f"{cd}Position à {pnl_pct:+.1f}% (coût moyen {cout_moyen:.2f} $). "
        f"Signal SDE {reco} ({score:.0f}/100) — maintien de la position.")
    return _finalize(base, pnl=pnl_pct, shares=total_shares, px=prix)


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
                 total_shares: float = 0, prix: float = 0,
                 data_date: str = "", var_1d: float = None,
                 deja_vendu: float = 0) -> dict:
    """
    Enrichit un conseil de base avec le signal du dernier pattern chandelier.
    Peut modifier l'action (ex. TENIR → ALLÉGER sur signal baissier fort)
    et complète toujours le raisonnement pour la transparence.
    """
    if not candle_info:
        return conseil

    # La date du pattern est celle où il a été détecté, pas la dernière bougie
    candle_date = candle_info.get("date") or data_date
    d = f"{candle_date} : " if candle_date else ""

    if candle_info.get("signal") == "neutre":
        name = candle_info.get("pattern", "")
        if name:
            raison = (f"{conseil['raisonnement']}<br>"
                      f"<span style='color:var(--sde-muted)'>{d}Figure chandelier : {name} — indécision.</span>")
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
            # MÉMOIRE DU JOUR : l'utilisateur a déjà allégé aujourd'hui —
            # re-suggérer une réduction sur le MÊME signal ferait liquider
            # la position 25% par 25% dans la journée (vécu TMC 15.07)
            if deja_vendu and deja_vendu > 0:
                raison = (f"{raison}<br>"
                          f"{d}Pattern chandelier {label} ({name}) toujours actif, "
                          f"mais allégement déjà réalisé aujourd'hui "
                          f"({deja_vendu:g} actions) — pas de nouvelle réduction "
                          f"sur le même signal.")
                return _conseil(action, conseil.get("quantite_suggeree"),
                                conseil.get("prix_cible"), raison)
            # INVALIDATION : un pattern de retournement baissier (détecté
            # sur la clôture de la VEILLE) est contredit par un fort rebond
            # du jour — vendre 25% pendant que le titre monte de +5% était
            # l'incohérence TMC du 14.07. Seuil : +2% sur la séance en cours.
            if var_1d is not None and var_1d >= 2.0:
                raison = (f"{raison}<br>"
                          f"{d}Pattern chandelier {label} ({name}) détecté sur la "
                          f"clôture précédente, mais rebond de {var_1d:+.1f}% sur la "
                          f"séance en cours — signal probablement invalidé, "
                          f"pas d'allégement.")
                return _conseil(action, conseil.get("quantite_suggeree"),
                                conseil.get("prix_cible"), raison)

            alleger = max(1, round(total_shares * 0.25)) if total_shares > 0 else None
            # Le texte de base disait « maintien de la position » : on le
            # retire, sinon la première phrase contredit le badge ALLÉGER
            # (incohérence constatée en prod sur TMC le 14.07.2026)
            raison = (raison
                      .replace(" — maintien de la position.", ".")
                      .replace(" Maintien recommandé, la tendance reste favorable.", ""))
            raison = (f"{raison}<br>"
                      f"{d}Pattern chandelier {label} ({name}) — allégement préventif "
                      f"de 25% de la position conseillé à court terme.")
            return _conseil("ALLÉGER", alleger, prix or None, raison)

        # RENFORCER + baissier → revenir à TENIR
        if action == "RENFORCER":
            raison = (f"{d}Signal SDE {reco} ({score:.0f}/100) suggère un renforcement,<br>"
                      f"{d}mais le pattern chandelier {label} ({name}) contre-indique un achat "
                      f"immédiat. Maintien préférable dans l'attente d'une confirmation haussière.")
            return _conseil("TENIR", None, None, raison)

        # Pas de position + baissier → rester sur SURVEILLER
        if action == "ACHETER" and pnl_pct is None:
            raison = (f"{raison}<br>"
                      f"{d}Pattern chandelier {label} ({name}) — attendre confirmation "
                      f"avant d'entrer en position.")
            return _conseil("SURVEILLER", None, None, raison)

        # Autres cas : note de vigilance seulement
        raison = f"{raison}<br>{d}Note : pattern chandelier {label} ({name}) — rester vigilant."

    elif signal == "bullish":
        if action in ("RENFORCER", "ACHETER"):
            raison = f"{raison}<br>{d}Confirmé par un signal chandelier {label} ({name})."
        elif action == "TENIR" and pnl_pct is not None and pnl_pct < 0:
            raison = (f"{raison}<br>"
                      f"{d}Pattern chandelier {label} ({name}) — rebond potentiel à surveiller.")
        elif action in ("ALLÉGER", "VENDRE"):
            raison = (f"{raison}<br>"
                      f"{d}Attention : signal chandelier {label} ({name}) en contradiction "
                      f"avec la recommandation de vente — surveiller avant d'agir.")
        else:
            raison = f"{raison}<br>{d}Pattern chandelier {label} ({name}) — tendance positive à court terme."

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


def get_previous_advice(username: str, ticker: str) -> dict | None:
    """
    Dernier conseil AVANT aujourd'hui — la référence pour détecter un
    changement d'action (TENIR → ALLÉGER…) qui mérite une notification.
    """
    try:
        import db
        from db import _init, is_available
        if not is_available():
            return None
        _init()
        rows = (
            db._client.table(_TABLE)
            .select("date_conseil,action,score_sde")
            .eq("username", username)
            .eq("ticker", ticker.upper())
            .lt("date_conseil", str(date.today()))
            .order("date_conseil", desc=True)
            .limit(1)
            .execute()
            .data or []
        )
        return rows[0] if rows else None
    except Exception as e:
        print(f"[Advisor] get_previous_advice erreur : {e}", flush=True)
        return None


def delete_today_advice(username: str, ticker: str) -> bool:
    """
    Invalide le conseil du jour — utilisé par le scheduler quand un gap
    pré-marché significatif rend obsolète un conseil généré plus tôt.
    """
    try:
        import db
        from db import _init, is_available
        if not is_available():
            return False
        _init()
        db._client.table(_TABLE).delete() \
            .eq("username", username).eq("ticker", ticker.upper()) \
            .eq("date_conseil", str(date.today())).execute()
        return True
    except Exception as e:
        print(f"[Advisor] delete_today_advice erreur : {e}", flush=True)
        return False


def ensure_today_advice(username: str, ticker: str, prix_live: float,
                        gap_pct: float = None, var_1d: float = None):
    """
    Garantit qu'un conseil existe pour aujourd'hui — appelé par le
    scheduler pour les tickers en POSITION, afin que le conseil quotidien
    existe même si l'utilisateur n'ouvre pas la page (et que l'évaluateur
    ait un conseil par jour à noter, pas seulement les jours de visite).

    Reprend la même chaîne que la route /portfolio/advice : snapshot +
    prix live + position + chandeliers + config utilisateur.

    Retourne (advice_row, created) :
      created=False si le conseil existait déjà (page visitée avant) ou
      si les données manquent (pas de snapshot, pas de position ouverte).
    """
    existing = get_today_advice(username, ticker)
    if existing:
        return existing, False

    try:
        from snapshot import get_snapshot, MAX_AGE_HOURS
        from portfolio.positions import get_portfolio_summary

        snap = get_snapshot(ticker, max_age_hours=MAX_AGE_HOURS)
        if not snap:
            # Pas de snapshot frais (ticker hors watchlist ?) — on ne lance
            # PAS le pipeline complet ici : le scheduler le fait déjà pour
            # les tickers de la watchlist, et un conseil sur données
            # périmées serait pire que pas de conseil.
            print(f"[Advisor] {ticker} : pas de snapshot — conseil non généré "
                  f"(ajouter le ticker à la watchlist pour le suivi complet)",
                  flush=True)
            return None, False

        summary = get_portfolio_summary(username, ticker, prix_live)
        if not summary:
            return None, False       # jamais détenu → pas de conseil position
        # Position clôturée : on continue de générer — generate_advice
        # bascule en mode ré-entrée (ACHETER/SURVEILLER) et l'email de
        # changement d'action préviendra au bon moment

        market = {**snap.get("market", {}), "price": prix_live or snap["market"].get("price")}
        # Gap pré-marché (fourni par le scheduler pendant la fenêtre
        # 10h-15h25 Paris) : le prix live gappé traverse déjà les règles
        # via le P&L — cette clé ne sert qu'à l'EXPLIQUER dans le texte.
        if gap_pct is not None:
            market["gap_overnight"] = gap_pct
        # var_1d LIVE (pas celui du snapshot, daté de la veille) : sert à
        # invalider un pattern chandelier baissier contredit par le rebond
        # de la séance en cours
        if var_1d is not None:
            market["var_1d"] = var_1d

        # Pattern chandelier — même construction que la route portfolio
        candle_info = None
        try:
            from analysis.candle_patterns import detect_patterns
            hist = snap.get("market", {}).get("history")
            if hist is not None and len(hist) > 0:
                pat_df = detect_patterns(hist.tail(60))
                if not pat_df.empty:
                    last = pat_df.iloc[-1]
                    raw_date = last.get("date") if hasattr(last, "get") else last["date"]
                    try:
                        candle_date = raw_date.strftime("%d.%m.%Y")
                    except Exception:
                        p = str(raw_date)[:10].split("-")
                        candle_date = f"{p[2]}.{p[1]}.{p[0]}" if len(p) == 3 else ""
                    candle_info = {
                        "signal":      last["signal"],
                        "pattern":     last["pattern"],
                        "description": last.get("description", ""),
                        "date":        candle_date,
                    }
        except Exception:
            pass

        from portfolio.config_advisor import get_config
        from portfolio.positions import get_cash_disponible
        advice = generate_advice(summary, market, snap,
                                 candle_info=candle_info,
                                 cfg=get_config(username),
                                 cash_dispo=get_cash_disponible(username))
        row = save_advice(username, ticker, advice, market, snap)
        return row, True
    except Exception as e:
        print(f"[Advisor] ensure_today_advice erreur ({ticker}) : {e}", flush=True)
        return None, False


def signaux_compacts(snapshot: dict) -> dict:
    """
    Extrait le vecteur des signaux techniques actifs sous forme compacte
    {code: points} — ex. {"ma_cross_up": 15, "rsi_surachat": -20}.

    Pourquoi stocker ça : l'évaluateur note déjà chaque conseil (bon/mauvais),
    mais sans les signaux du jour en format structuré, impossible de relier
    une erreur à son critère d'origine. Cette colonne est la matière première
    de la future calibration adaptative des poids.

    .get("code", s.get("nom")) : les snapshots antérieurs au champ "code"
    n'ont que le label français — on le prend en secours plutôt que de
    perdre la donnée.
    """
    out = {}
    for s in snapshot.get("signals_tech", []) or []:
        cle = s.get("code") or s.get("nom")
        if cle:
            out[cle] = s.get("points", 0)
    return out


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
            "signaux_actifs":     signaux_compacts(snapshot),
        }
        cle_conseil = {"username": username, "ticker": ticker.upper(),
                       "date_conseil": str(date.today())}
        try:
            update_one(_TABLE, cle_conseil, {"$set": row}, upsert=True)
        except Exception:
            # Filet de sécurité : si la colonne signaux_actifs n'existe pas
            # encore dans Supabase (migration SQL non appliquée), on sauve
            # le conseil SANS elle plutôt que de tout perdre.
            row.pop("signaux_actifs", None)
            update_one(_TABLE, cle_conseil, {"$set": row}, upsert=True)
            print("[Advisor] colonne signaux_actifs absente — lancer la "
                  "migration : ALTER TABLE daily_advice ADD COLUMN "
                  "signaux_actifs JSONB;", flush=True)
        return {**row, **cle_conseil}
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


def _is_eval_window(now_paris=None) -> bool:
    """
    Fenêtre d'évaluation J+1 : 2 dernières heures de séance (20h00-22h00 Paris).
    Les prix sont stables (pas de bruit d'ouverture ni de mid-day).
    Utilisé pour décider si on peut évaluer le conseil de la veille.
    """
    if now_paris is None:
        now_paris = _paris_now()
    wd  = now_paris.weekday()
    tot = now_paris.hour * 60 + now_paris.minute
    return wd < 5 and 20 * 60 <= tot < 22 * 60


def evaluate_yesterday_advice(username: str, ticker: str, current_price: float):
    """
    Appelé par le scheduler : évalue le conseil d'hier avec le prix actuel.
    N'évalue que dans la fenêtre 20h00-22h00 Paris (fin de séance, prix stables)
    pour éviter le bruit des prix d'ouverture ou intraday.
    Ré-évalue si une évaluation précédente était hors de cette fenêtre.
    """
    from datetime import timedelta
    try:
        now_paris = _paris_now()
        if not _is_eval_window(now_paris):
            return   # Hors fenêtre d'évaluation (20h-22h) — on attend les prix stables
    except Exception:
        return   # tzdata absent → fail-closed

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
            # Ré-évaluer seulement si l'évaluation précédente était hors fenêtre (20h-22h)
            try:
                prev_eval  = datetime.fromisoformat(row["evaluated_at"])
                import zoneinfo
                prev_paris = prev_eval.astimezone(zoneinfo.ZoneInfo("Europe/Paris"))
                if _is_eval_window(prev_paris):
                    return  # Déjà évalué en fin de séance — valeur fiable, on garde
                # Sinon : évaluation hors marché → on corrige
                print(f"[Advisor] {ticker} ré-évaluation (précédente hors marché à "
                      f"{prev_paris.strftime('%H:%M')} Paris)", flush=True)
            except Exception:
                return  # Sécurité : ne pas écraser si on ne peut pas vérifier

        prix_hier    = float(row.get("prix_jour") or 0)
        action       = row.get("action", "")
        variation_j1 = round((current_price - prix_hier) / prix_hier * 100, 2) if prix_hier else 0

        # Bande TENIR normalisée par la volatilité du titre — MÊME règle
        # que l'évaluateur batch (_juger), sinon les deux chemins jugent
        # différemment : ±3% fixe marquait KO des TENIR sur TMC (ATR 6.3%)
        # pour des variations qui sont son bruit quotidien normal.
        atr = None
        try:
            from snapshot import get_snapshot, MAX_AGE_HOURS
            from portfolio.risk import atr_pct
            snap = get_snapshot(ticker, max_age_hours=MAX_AGE_HOURS)
            if snap:
                atr = atr_pct(snap.get("market", {}).get("history"))
        except Exception:
            pass

        # Le conseil était-il bon ? (règle unique partagée avec le batch)
        from portfolio.evaluator import _juger
        bon = _juger(action, variation_j1, 1, atr)

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
