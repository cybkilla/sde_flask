# alerts/weekly_report.py — Rapport hebdomadaire du portefeuille (dimanche soir)

import os
from datetime import date, timedelta, datetime, timezone

SDE_BASE_URL = "https://sde-flask.onrender.com"
_TABLE = "weekly_reports"


# ── Timing ────────────────────────────────────────────────────────────────────

def should_send(username: str) -> bool:
    """
    Retourne True si c'est dimanche ≥ 22h00 Paris et que le rapport
    de cette semaine n'a pas encore été envoyé.
    """
    try:
        import zoneinfo
        paris = zoneinfo.ZoneInfo("Europe/Paris")
        now   = datetime.now(paris)
        if now.weekday() != 6 or now.hour < 22:   # 6 = dimanche
            return False
    except Exception:
        return False

    week_start = str(_current_week_start())
    try:
        from db import _init, _client, is_available
        if not is_available():
            return False
        _init()
        rows = (
            _client.table(_TABLE)
            .select("id")
            .eq("username", username)
            .eq("week_start", week_start)
            .limit(1)
            .execute()
            .data or []
        )
        return not bool(rows)
    except Exception as e:
        # Fail-safe : sans anti-doublon fiable on n'envoie PAS (sinon un
        # email par passage cron dans la fenêtre 22h-24h). Mais le log doit
        # être actionnable — c'est ici que l'absence de la table
        # weekly_reports a bloqué tous les rapports en silence.
        from db import log_db_error
        log_db_error("[Weekly] should_send", _TABLE, e)
        return False


def mark_sent(username: str):
    """Enregistre l'envoi pour éviter les doublons."""
    try:
        from db import _init, _client, is_available
        if not is_available():
            return
        _init()
        _client.table(_TABLE).upsert({
            "username":   username,
            "week_start": str(_current_week_start()),
            "sent_at":    datetime.now(timezone.utc).isoformat(),
        }, on_conflict="username,week_start").execute()
    except Exception as e:
        from db import log_db_error
        log_db_error("[Weekly] mark_sent", _TABLE, e)


def _current_week_start() -> date:
    """Retourne le lundi de la semaine courante."""
    today = date.today()
    return today - timedelta(days=today.weekday())


# ── Collecte des données ──────────────────────────────────────────────────────

def _get_week_variation(ticker: str, current_price: float) -> float | None:
    """
    Variation % sur la semaine : prix actuel vs prix enregistré il y a ~5 jours
    dans daily_advice (colonne prix_jour). Pas d'appel API supplémentaire.
    """
    try:
        from db import _init, _client, is_available
        if not is_available():
            return None
        _init()
        since = str(date.today() - timedelta(days=8))
        rows = (
            _client.table("daily_advice")
            .select("prix_jour,date_conseil")
            .eq("ticker", ticker.upper())
            .gte("date_conseil", since)
            .order("date_conseil")
            .limit(1)
            .execute()
            .data or []
        )
        if not rows or not rows[0].get("prix_jour"):
            return None
        prix_debut = float(rows[0]["prix_jour"])
        if prix_debut <= 0:
            return None
        return round((current_price - prix_debut) / prix_debut * 100, 2)
    except Exception:
        return None


def _get_week_advice_stats(username: str) -> dict:
    """Taux de pertinence des conseils des 7 derniers jours."""
    try:
        from db import _init, _client, is_available
        if not is_available():
            return {}
        _init()
        since = str(date.today() - timedelta(days=7))
        rows = (
            _client.table("daily_advice")
            .select("action,bon_conseil")
            .eq("username", username)
            .gte("date_conseil", since)
            .execute()
            .data or []
        )
        evaluated = [r for r in rows if r.get("bon_conseil") is not None]
        bons = sum(1 for r in evaluated if r["bon_conseil"])
        return {
            "total":    len(rows),
            "evaluated": len(evaluated),
            "bons":     bons,
            "taux_pct": round(bons / len(evaluated) * 100) if evaluated else None,
        }
    except Exception:
        return {}


# ── Email ─────────────────────────────────────────────────────────────────────

def send_weekly_report(username: str, email: str, watchlist: list,
                       mark: bool = True):
    """
    Construit et envoie le rapport hebdomadaire.
    mark=False pour les envois de TEST : sinon le test consomme le
    créneau anti-doublon de la semaine et l'envoi réel du dimanche
    est silencieusement sauté (vécu : test jeudi 09.07 → pas de
    rapport pour admin le dimanche 12.07).
    """
    from data.market         import get_live_price
    from portfolio.positions import get_positions, get_portfolio_summary

    _SYM = {"USD":"$","EUR":"€","GBP":"£","CHF":"Fr","CAD":"CA$","AUD":"A$"}
    ACTION_ICON = {
        "ACHETER":"↑","RENFORCER":"↗","TENIR":"◆",
        "SURVEILLER":"◎","ALLÉGER":"↘","VENDRE":"↓",
    }
    ACTION_COLOR = {
        "ACHETER":"#1D9E75","RENFORCER":"#15803d","TENIR":"#BA7517",
        "SURVEILLER":"#5a6a7a","ALLÉGER":"#D85A30","VENDRE":"#991b1b",
    }

    tickers = list({item["ticker"].upper() for item in watchlist})

    # Fallback : si watchlist vide, utiliser les tickers du portefeuille
    if not tickers:
        try:
            from portfolio.positions import get_positions
            portfolio_rows = get_positions(username)
            tickers = list({r["ticker"].upper() for r in portfolio_rows})
            print(f"[Weekly] Watchlist vide — fallback portefeuille : {tickers}", flush=True)
        except Exception:
            pass
    week_stats = _get_week_advice_stats(username)

    # Données par ticker
    ticker_rows = []
    total_investi = 0.0
    total_valeur  = 0.0
    total_pnl     = 0.0

    for ticker in tickers:
        try:
            live    = get_live_price(ticker)
            prix    = live.get("price") or 0
            var_1d  = live.get("var_1d") or 0
            var_wk  = _get_week_variation(ticker, prix)
            summary = get_portfolio_summary(username, ticker, prix)
            company = next(
                (item.get("company", ticker) for item in watchlist
                 if item["ticker"].upper() == ticker), ticker
            )

            # Conseil le plus récent de la semaine
            conseil = None
            try:
                from db import _init, _client, is_available
                if is_available():
                    _init()
                    since = str(date.today() - timedelta(days=7))
                    rows = (
                        _client.table("daily_advice")
                        .select("action,date_conseil")
                        .eq("username", username)
                        .eq("ticker", ticker)
                        .gte("date_conseil", since)
                        .order("date_conseil", desc=True)
                        .limit(1)
                        .execute()
                        .data or []
                    )
                    conseil = rows[0]["action"] if rows else None
            except Exception:
                pass

            if summary and not summary.get("position_fermee"):
                cur = summary.get("currency", "USD")
                total_investi += summary.get("total_investi",   0)
                total_valeur  += summary.get("valeur_actuelle", 0)
                total_pnl     += summary.get("pnl_euros",       0)

            ticker_rows.append({
                "ticker":  ticker,
                "company": company,
                "prix":    prix,
                "var_1d":  var_1d,
                "var_wk":  var_wk,
                "summary": summary,
                "conseil": conseil,
                "currency": (summary or {}).get("currency", "USD"),
            })
        except Exception as e:
            print(f"[Weekly] erreur ticker {ticker} : {e}", flush=True)

    if not ticker_rows:
        msg = f"[Weekly] Aucune donnée (watchlist et portefeuille vides) — rapport non envoyé pour {username}"
        print(msg, flush=True)
        raise RuntimeError(msg)

    # ── Métrique de tête : LE COMPTE TOTAL (objectif ultime de SDE) ──────────
    # cash + portefeuille, comparé à il y a ~7 jours (snapshots quotidiens)
    # et au buy & hold (qu'aurait valu le compte sans suivre aucun conseil).
    compte_block = ""
    try:
        from portfolio.positions import get_positions as _get_lots, etat_compte

        tous_lots = _get_lots(username) or []
        # Prix par ticker : ceux déjà récupérés dans la boucle, complétés
        # pour les tickers en portefeuille absents de la watchlist
        prix_map = {r["ticker"]: r.get("prix") or 0 for r in ticker_rows}
        for t in {l["ticker"] for l in tous_lots}:
            if not prix_map.get(t):
                prix_map[t] = (get_live_price(t) or {}).get("price") or 0

        # Une devise par bloc (la quasi-totalité des cas : USD seul)
        devises = {l.get("currency", "USD") for l in tous_lots} or {"USD"}
        for cur in sorted(devises):
            lots_cur = [l for l in tous_lots if l.get("currency", "USD") == cur]
            etat = etat_compte(lots_cur, prix_map)
            if etat["total"] <= 0:
                continue
            sym = _SYM.get(cur, "$")

            # Variation vs le snapshot le plus ancien des ~8 derniers jours
            var_sem_html = ""
            try:
                from portfolio.history import get_history as _hist
                anciens = [h for h in _hist(username, days=8)
                           if h.get("currency") == cur and h.get("total_compte")]
                if anciens:
                    ref = float(anciens[0]["total_compte"])
                    if ref > 0:
                        v = (etat["total"] - ref) / ref * 100
                        c = "#1D9E75" if v >= 0 else "#D85A30"
                        var_sem_html = (f'<span style="color:{c};font-size:15px;'
                                        f'font-weight:600"> {v:+.2f}% sur 7j</span>')
            except Exception:
                pass

            # Benchmark buy & hold : ce que les conseils suivis ont rapporté
            bh_html = ""
            if etat["buy_hold"] > 0:
                delta = etat["total"] - etat["buy_hold"]
                c = "#1D9E75" if delta >= 0 else "#D85A30"
                verbe = "rapporté" if delta >= 0 else "coûté"
                bh_html = (f'<div style="font-size:12px;color:#6b7280;margin-top:6px">'
                           f'vs Buy &amp; Hold (ne rien faire) : {sym}{etat["buy_hold"]:,.2f} '
                           f'— les conseils suivis ont {verbe} '
                           f'<b style="color:{c}">{delta:+,.2f} {sym}</b></div>')

            # Cash dormant : > 15% du compte en régime de marché haussier
            dormant_html = ""
            try:
                if etat["cash"] > 0.15 * etat["total"]:
                    from analysis.market_regime import get_market_context
                    ctx = get_market_context()
                    if ctx and ctx.get("regime") == "haussier":
                        dormant_html = (
                            f'<div style="background:#FEF3C7;border-radius:6px;'
                            f'padding:8px 12px;margin-top:8px;font-size:12px;color:#92400E">'
                            f'💤 Cash dormant : {sym}{etat["cash"]:,.2f} '
                            f'({etat["cash"]/etat["total"]*100:.0f}% du compte) en marché '
                            f'haussier — les signaux d\'entrée sur vos tickers sont surveillés.'
                            f'</div>')
            except Exception:
                pass

            compte_block += f"""
    <div style="background:#1E3A5F;border-radius:8px;padding:18px 20px;
                margin-bottom:16px;color:#fff">
      <div style="font-size:11px;text-transform:uppercase;letter-spacing:.05em;
                  opacity:.7;margin-bottom:4px">Compte total ({cur})</div>
      <div style="font-size:28px;font-weight:700">
        {sym}{etat["total"]:,.2f}{var_sem_html}
      </div>
      <div style="font-size:12px;opacity:.75;margin-top:4px">
        Portefeuille {sym}{etat["valeur_positions"]:,.2f}
        &nbsp;·&nbsp; Cash suivi {sym}{etat["cash"]:,.2f}
      </div>
      {bh_html}
      {dormant_html}
    </div>"""
    except Exception as e:
        print(f"[Weekly] bloc compte total indisponible : {e}", flush=True)

    # ── Construction HTML ─────────────────────────────────────────────────────
    week_start = _current_week_start()
    week_end   = week_start + timedelta(days=6)
    date_range = (f"{week_start.strftime('%d/%m')} – {week_end.strftime('%d/%m/%Y')}")

    pnl_color  = "#1D9E75" if total_pnl >= 0 else "#D85A30"
    pnl_sign   = "+" if total_pnl >= 0 else ""

    def _var_badge(v):
        if v is None:
            return '<span style="color:#9ca3af">—</span>'
        c = "#1D9E75" if v >= 0 else "#D85A30"
        return f'<span style="color:{c};font-weight:600">{v:+.1f}%</span>'

    # Résumé compte — table pour compatibilité email (flexbox ignoré par Gmail/Outlook)
    pertinence_cell = ""
    if week_stats.get("taux_pct") is not None:
        pert_color = "#1D9E75" if (week_stats.get("taux_pct") or 0) >= 55 else "#D85A30"
        pertinence_cell = f"""
        <td style="padding:14px 20px;text-align:center;
                   border-left:1px solid #E5E7EB">
          <div style="color:#6b7280;font-size:11px;text-transform:uppercase;
                      letter-spacing:.05em;margin-bottom:4px">Pertinence (7j)</div>
          <div style="font-size:22px;font-weight:700;color:{pert_color}">
            {week_stats["taux_pct"]}%
          </div>
        </td>"""

    summary_block = f"""
    <table width="100%" cellpadding="0" cellspacing="0"
           style="background:#F8FAFC;border-radius:8px;margin-bottom:20px;
                  border:1px solid #E5E7EB;border-collapse:separate;border-spacing:0">
      <tr>
        <td style="padding:14px 20px;text-align:center">
          <div style="color:#6b7280;font-size:11px;text-transform:uppercase;
                      letter-spacing:.05em;margin-bottom:4px">Valeur portefeuille</div>
          <div style="font-size:22px;font-weight:700;color:#111827">
            ${total_valeur:,.2f}
          </div>
        </td>
        <td style="padding:14px 20px;text-align:center;
                   border-left:1px solid #E5E7EB">
          <div style="color:#6b7280;font-size:11px;text-transform:uppercase;
                      letter-spacing:.05em;margin-bottom:4px">Investi total</div>
          <div style="font-size:22px;font-weight:700;color:#374151">
            ${total_investi:,.2f}
          </div>
        </td>
        <td style="padding:14px 20px;text-align:center;
                   border-left:1px solid #E5E7EB">
          <div style="color:#6b7280;font-size:11px;text-transform:uppercase;
                      letter-spacing:.05em;margin-bottom:4px">P&amp;L global</div>
          <div style="font-size:22px;font-weight:700;color:{pnl_color}">
            {pnl_sign}${abs(total_pnl):,.2f}
          </div>
        </td>
        {pertinence_cell}
      </tr>
    </table>"""

    # Lignes par ticker
    ticker_html = ""
    for r in ticker_rows:
        sym     = _SYM.get(r["currency"], "$")
        s       = r["summary"]
        conseil = r["conseil"]
        c_color = ACTION_COLOR.get(conseil, "#5a6a7a") if conseil else "#5a6a7a"
        c_icon  = ACTION_ICON.get(conseil, "◆")        if conseil else ""

        if s and not s.get("position_fermee"):
            pnl_e = s.get("pnl_euros", 0)
            pnl_p = s.get("pnl_pct",   0)
            pc    = "#1D9E75" if pnl_e >= 0 else "#D85A30"
            ps    = "+" if pnl_e >= 0 else ""
            pos_block = f"""
              <td style="padding:10px 8px;font-size:12px;color:#374151">
                {ps}{sym}{abs(pnl_e):,.2f}
                <span style="color:{pc};font-size:11px">({ps}{pnl_p:.1f}%)</span><br>
                <span style="color:#9ca3af;font-size:11px">
                  {s.get("total_shares",0):g} actions
                </span>
              </td>"""
        else:
            pos_block = '<td style="padding:10px 8px;color:#9ca3af;font-size:12px">Pas de position</td>'

        ticker_html += f"""
          <tr style="border-bottom:1px solid #f1f5f9">
            <td style="padding:10px 8px;font-weight:700;font-size:13px">
              <a href="{SDE_BASE_URL}/analyze/{r['ticker']}"
                 style="color:#111827;text-decoration:none">{r['ticker']}</a>
              <div style="font-size:11px;color:#9ca3af;font-weight:400">{r['company'][:25]}</div>
            </td>
            <td style="padding:10px 8px;font-weight:600;font-size:13px">
              {sym}{r['prix']:.2f}
              <div style="font-size:11px">{_var_badge(r['var_1d'])} j</div>
            </td>
            <td style="padding:10px 8px;font-size:12px">
              {_var_badge(r['var_wk'])}
            </td>
            {pos_block}
            <td style="padding:10px 8px">
              {f'<span style="background:{c_color};color:#fff;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:700">{c_icon} {conseil}</span>' if conseil else '<span style="color:#9ca3af;font-size:11px">—</span>'}
            </td>
          </tr>"""

    # Alertes à surveiller
    alerts_html = ""
    at_risk = [r for r in ticker_rows
               if r["summary"] and not r["summary"].get("position_fermee")
               and r["summary"].get("pnl_pct", 0) <= -10]
    if at_risk:
        alerts_html = '<div style="margin-top:16px">'
        alerts_html += '<p style="font-size:12px;font-weight:700;color:#D85A30;margin-bottom:6px">⚠️ Positions à surveiller</p>'
        for r in at_risk:
            s   = r["summary"]
            sym = _SYM.get(r["currency"], "$")
            alerts_html += f"""
              <div style="background:#FAECE7;border-left:3px solid #D85A30;
                          border-radius:4px;padding:8px 12px;margin-bottom:6px;font-size:12px">
                <strong>{r['ticker']}</strong> — P&L {s.get('pnl_pct',0):+.1f}%
                · coût moy. {sym}{s.get('cout_moyen',0):.4f}
                · cours actuel {sym}{r['prix']:.4f}
              </div>"""
        alerts_html += "</div>"

    body = f"""
    <div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto;padding:20px">

      <div style="border-left:4px solid #6366F1;padding-left:16px;margin-bottom:20px">
        <h2 style="margin:0 0 4px;color:#111827">
          📊 Rapport hebdomadaire SDE
        </h2>
        <p style="margin:0;color:#6b7280;font-size:13px">
          Semaine du {date_range} · {username}
        </p>
      </div>

      {compte_block}
      {summary_block}

      <table style="width:100%;border-collapse:collapse;margin-bottom:16px">
        <thead>
          <tr style="border-bottom:2px solid #e5e7eb;color:#6b7280;font-size:11px;
                     text-transform:uppercase;letter-spacing:.05em">
            <th style="padding:8px 8px;text-align:left">Ticker</th>
            <th style="padding:8px 8px;text-align:left">Prix</th>
            <th style="padding:8px 8px;text-align:left">Semaine</th>
            <th style="padding:8px 8px;text-align:left">P&L position</th>
            <th style="padding:8px 8px;text-align:left">Conseil</th>
          </tr>
        </thead>
        <tbody>
          {ticker_html}
        </tbody>
      </table>

      {alerts_html}

      {f'''<div style="background:#EEF2FF;border-radius:8px;padding:12px 14px;
                  margin-top:16px;font-size:12px;color:#374151">
        <strong style="color:#6366F1">Pertinence des conseils (7j)</strong> —
        {week_stats["bons"]} corrects sur {week_stats["evaluated"]} évalués
        {f'· <strong style="color:{"#1D9E75" if week_stats["taux_pct"] >= 55 else "#D85A30"}">{week_stats["taux_pct"]}%</strong>' if week_stats.get("taux_pct") is not None else ""}
        <span style="color:#9ca3af;font-size:11px">
          (conseils dont le résultat J+1 est connu)
        </span>
      </div>''' if week_stats.get("evaluated") else ""}

      <div style="border-top:1px solid #e5e7eb;padding-top:12px;margin-top:20px">
        <a href="{SDE_BASE_URL}/mes-positions"
           style="display:inline-block;background:#6366F1;color:#fff;
                  font-size:13px;font-weight:600;text-decoration:none;
                  padding:8px 18px;border-radius:6px;margin-bottom:10px">
          Voir mes positions →
        </a>
        <p style="color:#9ca3af;font-size:11px;margin:6px 0 0">
          Rapport généré automatiquement par StockDecisionEngine.
          Outil éducatif — pas un conseil financier.
        </p>
      </div>
    </div>
    """

    api_key   = os.getenv("RESEND_API_KEY", "")
    from_addr = os.getenv("RESEND_FROM", "SDE StockDecisionEngine <onboarding@resend.dev>")

    if not api_key:
        print(f"[Weekly] RESEND_API_KEY manquante — rapport non envoyé", flush=True)
        return

    import resend
    resend.api_key = api_key
    week_label = week_start.strftime("%d/%m")
    resend.Emails.send({
        "from":    from_addr,
        "to":      [email],
        "subject": f"[SDE] Rapport hebdomadaire · semaine du {week_label}",
        "html":    body,
    })
    if mark:
        mark_sent(username)
    print(f"[Weekly] Rapport envoyé à {email} (semaine {week_label}, "
          f"anti-doublon {'posé' if mark else 'NON posé — test'})", flush=True)
